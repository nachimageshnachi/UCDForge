import json
import math
from typing import Any, Dict, List, Tuple

import numpy as np

from connection import connection
from embeddings import (
    embed_paragraph,
    embed_short,
    rank_cases,
)


def _json_vec_to_np(s: str) -> np.ndarray:
    try:
        v = json.loads(s or "[]")
        arr = np.array(v, dtype=float)
        if arr.ndim != 1 or arr.size == 0:
            return np.zeros((1,), dtype=float)
        # assume already L2-normalized from our encoder
        return arr
    except Exception:
        return np.zeros((1,), dtype=float)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    # inputs are already normalized; guard numeric issues
    try:
        return float(np.clip(np.dot(a, b), -1.0, 1.0))
    except Exception:
        return 0.0


def _centroid(vectors: List[np.ndarray]) -> np.ndarray:
    vs = [v for v in vectors if isinstance(v, np.ndarray) and v.size > 0]
    if not vs:
        return np.zeros((1,), dtype=float)
    c = np.mean(np.stack(vs, axis=0), axis=0)
    # L2-normalize
    n = np.linalg.norm(c)
    return c / n if n > 0 else np.zeros_like(c)


def _tokenize(s: str) -> List[str]:
    return [t.lower() for t in (s or "").split() if t and any(ch.isalnum() for ch in t)]


def _jaccard(a: List[str], b: List[str]) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 0.0
    inter = len(A & B)
    union = len(A | B) or 1
    return inter / union


def _fetch_all_cases() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT case_id, title, description, title_embedding, description_embedding, domain_json FROM cases")
        rows = cursor.fetchall() or []
    return rows


def _fetch_case_actors(case_id: int) -> List[Dict[str, Any]]:
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT actor_name, name_embedding FROM actors WHERE case_id=%s", (case_id,))
        return cursor.fetchall() or []


def _fetch_case_use_cases(case_id: int) -> List[Dict[str, Any]]:
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT name, name_embedding FROM use_cases WHERE case_id=%s", (case_id,))
        return cursor.fetchall() or []


def _fetch_case_synonyms(case_id: int) -> Dict[str, Dict[str, List[str]]]:
    """Return synonyms per case: { 'actors': {name:[syn...]}, 'use_cases': {name:[syn...]}, 'system': {system:[syn..]} }"""
    out = {"actors": {}, "use_cases": {}, "system": {}}
    with connection.get_cursor(dictionary=True) as cursor:
        try:
            cursor.execute("SELECT actor_name, synonym FROM actor_synonyms WHERE case_id=%s", (case_id,))
            for r in cursor.fetchall() or []:
                n = (r.get("actor_name") or "").strip()
                s = (r.get("synonym") or "").strip()
                if n and s:
                    out["actors"].setdefault(n, []).append(s)
        except Exception:
            pass
        try:
            cursor.execute("SELECT use_case_name, synonym FROM use_case_synonyms WHERE case_id=%s", (case_id,))
            for r in cursor.fetchall() or []:
                n = (r.get("use_case_name") or "").strip()
                s = (r.get("synonym") or "").strip()
                if n and s:
                    out["use_cases"].setdefault(n, []).append(s)
        except Exception:
            pass
        try:
            cursor.execute("SELECT system_name, synonym FROM system_synonyms WHERE case_id=%s", (case_id,))
            for r in cursor.fetchall() or []:
                n = (r.get("system_name") or "").strip()
                s = (r.get("synonym") or "").strip()
                if n and s:
                    out["system"].setdefault(n, []).append(s)
        except Exception:
            pass
    return out


def _fetch_global_synonyms(kind: str, terms: List[str]) -> Dict[str, List[str]]:
    """Fetch synonyms across all cases for the given terms. kind in {'actor','use_case','system'}"""
    terms = [t for t in (terms or []) if t]
    if not terms:
        return {}
    placeholders = ",".join(["%s"] * len(terms))
    table = "actor_synonyms" if kind == 'actor' else ("use_case_synonyms" if kind == 'use_case' else "system_synonyms")
    name_col = "actor_name" if kind == 'actor' else ("use_case_name" if kind == 'use_case' else "system_name")
    out: Dict[str, List[str]] = {t: [] for t in terms}
    with connection.get_cursor(dictionary=True) as cursor:
        try:
            cursor.execute(f"SELECT {name_col} AS name, synonym FROM {table} WHERE {name_col} IN ({placeholders})", tuple(terms))
            for r in cursor.fetchall() or []:
                n = (r.get("name") or "").strip()
                s = (r.get("synonym") or "").strip()
                if n and s:
                    out.setdefault(n, []).append(s)
        except Exception:
            pass
    return out


def _build_query_embeddings(query: Dict[str, Any]) -> Dict[str, np.ndarray]:
    q = {}
    if query.get("system_name"):
        q["title"] = _json_vec_to_np(embed_short(query["system_name"]))
    else:
        q["title"] = np.zeros((1,), dtype=float)
    if query.get("description"):
        q["desc"] = _json_vec_to_np(embed_paragraph(query["description"]))
    else:
        q["desc"] = np.zeros((1,), dtype=float)
    # actor and uc centroids
    act_vecs = [_json_vec_to_np(embed_short(a)) for a in (query.get("actors") or [])]
    uc_vecs = [_json_vec_to_np(embed_short(u)) for u in (query.get("use_cases") or [])]
    q["actors"] = _centroid(act_vecs)
    q["use_cases"] = _centroid(uc_vecs)
    return q


def _greedy_one_to_one(
    a_vecs: List[Tuple[str, np.ndarray]],
    b_vecs: List[Tuple[str, np.ndarray]],
) -> List[Tuple[int, int, float]]:
    """Greedy 1-to-1 bipartite matching.

    Scores all (a_i, b_j) cosine pairs, then assigns them greedily from
    highest to lowest score — once a_i or b_j is assigned it cannot be
    re-used.  Returns a list of (a_index, b_index, score) tuples.
    """
    if not a_vecs or not b_vecs:
        return []
    all_pairs = sorted(
        [
            (i, j, _cos(av, bv))
            for i, (_, av) in enumerate(a_vecs)
            for j, (_, bv) in enumerate(b_vecs)
        ],
        key=lambda x: x[2],
        reverse=True,
    )
    used_a: set = set()
    used_b: set = set()
    matches: List[Tuple[int, int, float]] = []
    for i, j, score in all_pairs:
        if i not in used_a and j not in used_b:
            matches.append((i, j, score))
            used_a.add(i)
            used_b.add(j)
    return matches


def _sym_max_set_sim(query_terms: List[str], case_terms: List[str]) -> float:
    """Symmetric 1-to-1 matching between two label sets.

    Uses greedy bipartite assignment (best score first) so each term on
    either side is matched at most once.  Unmatched terms contribute 0.
    Final score = 0.5 * (forward_avg + backward_avg).
    Returns 0.0 when either set is empty.
    """
    qa = [(t, _json_vec_to_np(embed_short(t))) for t in (query_terms or []) if t]
    cb = [(t, _json_vec_to_np(embed_short(t))) for t in (case_terms or []) if t]
    if not qa or not cb:
        return 0.0
    # forward: unmatched query terms contribute 0
    fwd_matches = _greedy_one_to_one(qa, cb)
    fwd = sum(s for _, _, s in fwd_matches) / len(qa)
    # backward: unmatched case terms contribute 0
    bwd_matches = _greedy_one_to_one(cb, qa)
    bwd = sum(s for _, _, s in bwd_matches) / len(cb)
    return 0.5 * (fwd + bwd)


def _sym_max_set_sim_with_detail(
    query_terms: List[str], case_terms: List[str]
) -> Tuple[float, List[Dict[str, Any]]]:
    """Like _sym_max_set_sim but also returns a 1-to-1 per-query-term breakdown.

    Each query term is matched to at most one case term and each case term
    is matched to at most one query term (greedy highest-score-first).

    Returns
    -------
    score : float
        Symmetric 1-to-1 average.
    breakdown : list of dict
        One entry per query term: {"query", "best_match", "score"}.
        Query terms that cannot be matched (e.g. |case| < |query|) get
        best_match="—" and score=0.0.
    """
    qa = [(t, _json_vec_to_np(embed_short(t))) for t in (query_terms or []) if t]
    cb = [(t, _json_vec_to_np(embed_short(t))) for t in (case_terms or []) if t]
    if not qa or not cb:
        return 0.0, []

    # forward 1-to-1: query → case
    fwd_matches = _greedy_one_to_one(qa, cb)
    fwd_by_qi = {i: (cb[j][0], s) for i, j, s in fwd_matches}

    breakdown: List[Dict[str, Any]] = []
    fwd_total = 0.0
    for qi, (qt, _) in enumerate(qa):
        if qi in fwd_by_qi:
            best_term, score = fwd_by_qi[qi]
        else:
            best_term, score = "—", 0.0   # unmatched (|case| < |query|)
        fwd_total += score
        breakdown.append({"query": qt, "best_match": best_term, "score": round(score, 6)})
    fwd = fwd_total / len(qa)

    # backward 1-to-1: case → query (for the symmetric score only)
    bwd_matches = _greedy_one_to_one(cb, qa)
    bwd = sum(s for _, _, s in bwd_matches) / len(cb)

    return 0.5 * (fwd + bwd), breakdown


def _build_case_centroids(case_id: int, acts: List[Dict[str, Any]], ucs: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
    act_vecs = [_json_vec_to_np(a.get("name_embedding") or "") for a in acts]
    uc_vecs = [_json_vec_to_np(u.get("name_embedding") or "") for u in ucs]
    return _centroid(act_vecs), _centroid(uc_vecs)


def find_similar_cases(query: Dict[str, Any], mode: str = "CBR", threshold: float = 0.5, limit: int = 20) -> List[Dict[str, Any]]:
    """Hybrid retrieval: basic lexical feature + multi-field embedding re-rank.
    Returns sorted matches with relevance >= threshold.
    query keys: system_name, description, domains (list[str]), actors (list[str]), use_cases (list[str])
    """
    # Query embeddings
    qvecs = _build_query_embeddings(query)
    q_title = qvecs["title"]
    q_desc = qvecs["desc"]
    q_acts = qvecs["actors"]
    q_ucs = qvecs["use_cases"]

    q_tokens = _tokenize((query.get("system_name") or "") + " " + (query.get("description") or ""))
    q_tokens += [t.lower() for t in (query.get("domains") or [])]
    # add synonyms for query actors/use_cases to aid lexical overlap
    q_actors = [t for t in (query.get("actors") or []) if t]
    q_usecases = [t for t in (query.get("use_cases") or []) if t]
    q_tokens += [t.lower() for t in q_actors + q_usecases]
    # global synonyms expansion
    act_syn = _fetch_global_synonyms('actor', q_actors)
    uc_syn = _fetch_global_synonyms('use_case', q_usecases)
    for t, syns in (act_syn or {}).items():
        q_tokens += [s.lower() for s in syns]
    for t, syns in (uc_syn or {}).items():
        q_tokens += [s.lower() for s in syns]

    # Fetch candidates (simple recall-first; could be restricted if needed)
    cases = _fetch_all_cases()
    results: List[Dict[str, Any]] = []
    for c in cases:
        cid = c["case_id"]
        title = c.get("title") or ""
        desc = c.get("description") or ""
        title_v = _json_vec_to_np(c.get("title_embedding") or "")
        desc_v = _json_vec_to_np(c.get("description_embedding") or "")
        try:
            domains = [d.strip().lower() for d in json.loads(c.get("domain_json") or "[]") if d]
        except Exception:
            domains = []

        acts = _fetch_case_actors(cid)
        ucs = _fetch_case_use_cases(cid)
        syn = _fetch_case_synonyms(cid)
        act_cent, uc_cent = _build_case_centroids(cid, acts, ucs)

        # per-field similarities (0..1)
        sim_title = _cos(q_title, title_v)
        sim_desc = _cos(q_desc, desc_v)
        # set-to-set similarity (symmetric max) is more robust than centroid-only
        # --- Actor similarity: per-actor best-match average (both directions) ---
        case_actor_labels = [a.get("actor_name", "") for a in acts]
        sim_actors, actor_breakdown = _sym_max_set_sim_with_detail(q_actors, case_actor_labels)

        # --- Use-case similarity: per-UC best-match average (both directions) ---
        case_uc_labels = [u.get("name", "") for u in ucs]
        sim_usecases, uc_breakdown = _sym_max_set_sim_with_detail(q_usecases, case_uc_labels)

        # lexical tokens for quick tie-breaking
        c_tokens = _tokenize(title + " " + desc)
        # include KB synonyms for this case
        c_tokens += [a.get("actor_name", "").lower() for a in acts]
        for name, syns in (syn.get("actors") or {}).items():
            c_tokens += [s.lower() for s in syns]
        c_tokens += [u.get("name", "").lower() for u in ucs]
        for name, syns in (syn.get("use_cases") or {}).items():
            c_tokens += [s.lower() for s in syns]
        c_tokens += domains
        sim_lexical = _jaccard(q_tokens, c_tokens)

        # --- Domain similarity: semantic per-domain best-match average + exact Jaccard ---
        q_domains = [d for d in (query.get("domains") or []) if d]
        sim_domains = max(
            _jaccard([d.lower() for d in q_domains], domains),   # exact token overlap
            _sym_max_set_sim(q_domains, domains),                 # semantic per-domain avg
        ) if (q_domains and domains) else _jaccard([d.lower() for d in q_domains], domains)

        results.append({
            "case_id": cid,
            "title": title,
            "sim_title": sim_title,
            "sim_desc": sim_desc,
            "sim_domains": sim_domains,
            "sim_actors": sim_actors,
            "sim_usecases": sim_usecases,
            "sim_lexical": sim_lexical,
            # per-term breakdowns for Excel detail sheet
            "uc_breakdown": uc_breakdown,
            "actor_breakdown": actor_breakdown,
        })

    ranked = rank_cases(results, mode=mode)
    return [r for r in ranked if r.get("relevance", 0.0) >= float(threshold)][:limit]


def find_all_uc_similarities(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return every use case from every case in the database scored against
    the query use cases.

    Each row: {case_title, uc_name, best_query_uc, similarity}
    Sorted by similarity descending so the most relevant UCs appear first.
    Uses stored name_embedding where available to avoid re-encoding.
    """
    q_usecases = [t for t in (query.get("use_cases") or []) if t]
    if not q_usecases:
        return []

    # embed query UCs once
    q_vecs = [(t, _json_vec_to_np(embed_short(t))) for t in q_usecases]

    cases = _fetch_all_cases()
    rows: List[Dict[str, Any]] = []

    for c in cases:
        cid   = c["case_id"]
        title = c.get("title") or ""
        ucs   = _fetch_case_use_cases(cid)

        for uc in ucs:
            uc_name = (uc.get("name") or "").strip()
            if not uc_name:
                continue
            # prefer stored embedding, fall back to live encoding
            stored = uc.get("name_embedding")
            uc_vec = _json_vec_to_np(stored) if stored else _json_vec_to_np(embed_short(uc_name))

            best_score = 0.0
            best_query = ""
            for qt, qv in q_vecs:
                s = _cos(qv, uc_vec)
                if s > best_score:
                    best_score = s
                    best_query = qt

            rows.append({
                "case_title":    title,
                "uc_name":       uc_name,
                "best_query_uc": best_query,
                "similarity":    round(best_score, 6),
            })

    return sorted(rows, key=lambda x: x["similarity"], reverse=True)
