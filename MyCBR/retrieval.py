from __future__ import annotations

from typing import Any, Dict, List

from MyCBR.repository import load_retained_cases
from cbr_search import (
    _build_query_embeddings,
    _cos,
    _fetch_global_synonyms,
    _jaccard,
    _sym_max_set_sim,
    _tokenize,
    find_similar_cases,
)
from embeddings import embed_paragraph, embed_short, rank_cases
import json
import numpy as np


def _json_vec_to_np(s: str) -> np.ndarray:
    try:
        v = json.loads(s or "[]")
        arr = np.array(v, dtype=float)
        if arr.ndim != 1 or arr.size == 0:
            return np.zeros((1,), dtype=float)
        return arr
    except Exception:
        return np.zeros((1,), dtype=float)


def _centroid(vectors: List[np.ndarray]) -> np.ndarray:
    vs = [v for v in vectors if isinstance(v, np.ndarray) and v.size > 0]
    if not vs:
        return np.zeros((1,), dtype=float)
    c = np.mean(np.stack(vs, axis=0), axis=0)
    n = np.linalg.norm(c)
    return c / n if n > 0 else np.zeros_like(c)


def _retained_case_matches(query: Dict[str, Any], retained_cases: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    qvecs = _build_query_embeddings(query)
    q_title = qvecs["title"]
    q_desc = qvecs["desc"]
    q_acts = qvecs["actors"]
    q_ucs = qvecs["use_cases"]

    q_tokens = _tokenize((query.get("system_name") or "") + " " + (query.get("description") or ""))
    q_tokens += [t.lower() for t in (query.get("domains") or [])]
    q_actors = [t for t in (query.get("actors") or []) if t]
    q_usecases = [t for t in (query.get("use_cases") or []) if t]
    q_tokens += [t.lower() for t in q_actors + q_usecases]

    act_syn = _fetch_global_synonyms("actor", q_actors)
    uc_syn = _fetch_global_synonyms("use_case", q_usecases)
    for syns in (act_syn or {}).values():
        q_tokens += [s.lower() for s in syns]
    for syns in (uc_syn or {}).values():
        q_tokens += [s.lower() for s in syns]

    results: List[Dict[str, Any]] = []
    for case_payload in retained_cases:
        title = case_payload.get("title") or case_payload.get("system_name") or ""
        desc = case_payload.get("description") or ""
        domains = [str(item).lower() for item in (case_payload.get("domains") or []) if item]
        case_actors = list(case_payload.get("primary_actors") or []) + list(case_payload.get("secondary_actors") or [])
        case_ucs = list(case_payload.get("use_cases") or [])

        title_v = _json_vec_to_np(embed_short(title))
        desc_v = _json_vec_to_np(embed_paragraph(desc)) if desc else np.zeros((1,), dtype=float)
        act_cent = _centroid([_json_vec_to_np(embed_short(actor)) for actor in case_actors])
        uc_cent = _centroid([_json_vec_to_np(embed_short(use_case)) for use_case in case_ucs])

        sim_title = _cos(q_title, title_v)
        sim_desc = _cos(q_desc, desc_v)
        sim_actors = max(_cos(q_acts, act_cent), _sym_max_set_sim(q_actors, case_actors))
        sim_usecases = max(_cos(q_ucs, uc_cent), _sym_max_set_sim(q_usecases, case_ucs))

        c_tokens = _tokenize(title + " " + desc)
        c_tokens += [actor.lower() for actor in case_actors]
        c_tokens += [use_case.lower() for use_case in case_ucs]
        c_tokens += domains
        sim_lexical = _jaccard(q_tokens, c_tokens)
        sim_domains = _jaccard([d.lower() for d in (query.get("domains") or [])], domains)

        results.append(
            {
                "case_id": case_payload.get("case_id"),
                "case_key": case_payload.get("case_key"),
                "title": title,
                "source": "retained",
                "sim_title": sim_title,
                "sim_desc": sim_desc,
                "sim_domains": sim_domains,
                "sim_actors": sim_actors,
                "sim_usecases": sim_usecases,
                "sim_lexical": sim_lexical,
            }
        )

    return rank_cases(results, mode=mode)


def retrieve_cases(query: Dict[str, Any], mode: str = "CBR", threshold: float = 0.5, limit: int = 20) -> List[Dict[str, Any]]:
    sql_matches = find_similar_cases(query, mode=mode, threshold=0.0, limit=max(limit * 4, 20))
    for match in sql_matches:
        match["source"] = "sql"
        match["case_key"] = f'sql-{match["case_id"]}'

    retained_matches = _retained_case_matches(query, load_retained_cases(), mode=mode)
    combined = sql_matches + retained_matches
    combined.sort(key=lambda item: float(item.get("relevance", 0.0)), reverse=True)
    return [item for item in combined if float(item.get("relevance", 0.0)) >= float(threshold)][:limit]
