# embeddings.py
import json
import numpy as np
from functools import lru_cache
from sentence_transformers import SentenceTransformer

def _cuda_available():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False

@lru_cache(maxsize=None)
def _load_model(name: str) -> SentenceTransformer:
    return SentenceTransformer(name, device="cuda" if _cuda_available() else "cpu")

# ---- Model picks (accuracy-first) ----
MODEL_LONG   = "BAAI/bge-large-en-v1.5"                    # paragraphs/titles (with retrieval instruction)
MODEL_SHORT  = "sentence-transformers/all-mpnet-base-v2"   # short labels — must match stored case base embeddings

# BGE uses a retrieval instruction; we’ll prepend it consistently
BGE_INSTRUCTION = "Represent this sentence for retrieval: "

def _encode(texts, model_name, add_instruction=False):
    if isinstance(texts, str):
        texts = [texts]
    if add_instruction:
        texts = [BGE_INSTRUCTION + t for t in texts]
    model = _load_model(model_name)
    # normalize_embeddings=True returns L2-normalized vectors
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=64, convert_to_numpy=True)
    return vecs

def embed_paragraph(text: str) -> str:
    """Paragraph/title/system description → BGE-large (with instruction), L2-normalized, JSON."""
    v = _encode(text, MODEL_LONG, add_instruction=True)[0]
    return json.dumps(v.tolist())

def embed_short(text: str) -> str:
    """Short labels (use-case names, actors, domains) → all-mpnet-base-v2, L2-normalized, JSON."""
    v = _encode(text, MODEL_SHORT, add_instruction=False)[0]
    return json.dumps(v.tolist())

def embed_many_paragraph(texts):
    vecs = _encode(texts, MODEL_LONG, add_instruction=True)
    return [json.dumps(v.tolist()) for v in vecs]

def embed_many_short(texts):
    vecs = _encode(texts, MODEL_SHORT, add_instruction=False)
    return [json.dumps(v.tolist()) for v in vecs]

# -------------------- Hybrid Ranking Profiles -------------------- #

CBR_WEIGHTS = {
    # Weights normalised so total = 1.0 (each raw value ÷ 0.85)
    # x-based formula (x = 0.10, total raw = 0.85)
    # System Name  = 0.5x   → 0.05 / 0.85
    # Description  = 1x     → 0.10 / 0.85
    # Domains      = 1.5x   → 0.15 / 0.85
    # Actors       = 2x     → 0.20 / 0.85
    # Use Cases    = 3x     → 0.30 / 0.85
    # Lexical      = 0.5x   → 0.05 / 0.85
    "sim_title":    round(0.05 / 0.85, 4),   # ≈ 0.0588 (halved)
    "sim_desc":     round(0.10 / 0.85, 4),   # ≈ 0.1176
    "sim_domains":  round(0.15 / 0.85, 4),   # ≈ 0.1765
    "sim_actors":   round(0.20 / 0.85, 4),   # ≈ 0.2353
    "sim_usecases": round(0.30 / 0.85, 4),   # ≈ 0.3529
    "sim_lexical":  round(0.05 / 0.85, 4),   # ≈ 0.0588
}

IR_WEIGHTS = {
    # Rescaled from raw (0.40, 0.30, 0.15, 0.10, 0.05, 0.20) / 1.20
    # so the dict sums to 1.0 while keeping identical effective proportions.
    "sim_title":    0.3333,   # title / system name
    "sim_desc":     0.2500,   # description
    "sim_domains":  0.1250,   # domain tags
    "sim_actors":   0.0833,   # actor set
    "sim_usecases": 0.0417,   # use-case set
    "sim_lexical":  0.1667,   # lexical overlap
}

def combine_score(sim_features: dict, weights: dict) -> float:
    """Combine pre-computed similarity features into a single score.
    sim_features keys are normalized 0..1: sim_title, sim_desc, sim_domains, sim_actors, sim_usecases, sim_lexical
    """
    return sum(sim_features.get(k, 0.0) * w for k, w in weights.items())

def rank_cases(candidates, mode: str = "CBR"):
    """Given a list of candidate dicts with per-field similarity features,
    compute a final relevance score in [0,1] and return sorted candidates.
    """
    weights = CBR_WEIGHTS if (mode or "").upper() == "CBR" else IR_WEIGHTS
    denom = max(sum(weights.values()), 1e-9)
    out = []
    for c in candidates or []:
        c = dict(c)
        # Clamp features to [0,1] for safety before weighting
        feats = {k: min(max(float(c.get(k, 0.0)), 0.0), 1.0) for k in weights.keys()}
        raw = sum(feats[k] * w for k, w in weights.items())
        c["relevance"] = float(raw) / denom
        out.append(c)
    return sorted(out, key=lambda x: x.get("relevance", 0.0), reverse=True)
