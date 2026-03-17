import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import MinMaxScaler
from cbr_search import (
    _fetch_all_cases, 
    _fetch_case_actors, 
    _fetch_case_use_cases,
    _sym_max_set_sim,
    _jaccard,
    _tokenize,
)

def build_fast_dataset():
    print("Fetching cases from database...")
    cases = _fetch_all_cases()
    if not cases:
        print("No cases found.")
        return [], []
        
    print(f"Found {len(cases)} cases. Building pairwise comparisons efficiently...")
    
    case_data = {}
    for c in cases:
        cid = c["case_id"]
        title = c.get("title") or ""
        desc = c.get("description") or ""
        try:
            doms = [d.strip().lower() for d in json.loads(c.get("domain_json") or "[]") if d]
        except:
            doms = []
            
        acts = _fetch_case_actors(cid)
        ucs = _fetch_case_use_cases(cid)
        
        act_names = [a.get("actor_name", "") for a in acts]
        uc_names = [u.get("name", "") for u in ucs]
        
        c_tokens = _tokenize(title + " " + desc) + doms + [a.lower() for a in act_names] + [u.lower() for u in uc_names]
        
        case_data[cid] = {
            "title": title,
            "desc": desc,
            "domains": doms,
            "act_names": act_names,
            "uc_names": uc_names,
            "tokens": c_tokens,
            # We already have title and desc embedded, but for speed we will use Jaccard/fast-overlap for the structural text 
            # instead of heavy cosine sim on 2400 pairs. 
        }
        
    X = []
    y = []
    
    cids = list(case_data.keys())
    for i in range(len(cids)):
        for j in range(i+1, len(cids)):
            c1, c2 = case_data[cids[i]], case_data[cids[j]]
            
            # Fast text approximations:
            sim_title = _jaccard(_tokenize(c1['title']), _tokenize(c2['title']))
            sim_desc = _jaccard(_tokenize(c1['desc']), _tokenize(c2['desc']))
            
            # Semantic sets take a long time to encode, we will use plain Jaccard for the fast simulation to get relative weights
            sim_actors = _jaccard(c1["act_names"], c2["act_names"])
            sim_usecases = _jaccard(c1["uc_names"], c2["uc_names"])
            
            sim_lexical = _jaccard(c1["tokens"], c2["tokens"])
            sim_domains = _jaccard(c1["domains"], c2["domains"])
            
            features = [sim_title, sim_desc, sim_domains, sim_actors, sim_usecases, sim_lexical]
            X.append(features)
            
            # Heuristic label: 
            is_relevant = 1 if (sim_domains > 0 or sim_usecases > 0.4) else 0
            y.append(is_relevant)
            
    return np.array(X), np.array(y)

def run_logistic_regression(X, y):
    print("\n--- Running Logistic Regression (Simulation) ---")
    scaler = MinMaxScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Fallback to standard logistic regression if positive constraints aren't supported
    model = LogisticRegression(fit_intercept=False, solver='lbfgs')
    model.fit(X_scaled, y)
    
    # Force weights to evaluate relative magnitude
    weights = np.abs(model.coef_[0])
    total = np.sum(weights)
    
    if total == 0:
        print("Model failed to learn positive weights.")
        return
        
    normalized = weights / total
    feature_names = ["System Name", "Description", "Domains", "Actors", "Use Cases", "Lexical"]
    
    print("\nLearned Weights (Normalized to sum to 1.0):")
    for name, w in zip(feature_names, normalized):
        print(f" - {name:<15}: {w:.4f} ({w*100:.1f}%)")
        
if __name__ == "__main__":
    X, y = build_fast_dataset()
    if len(X) > 0:
        print(f"\nGenerated {len(X)} pairwise case comparisons.")
        print(f"Positive matches (y=1): {np.sum(y)}")
        run_logistic_regression(X, y)
