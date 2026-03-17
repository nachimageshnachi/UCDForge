import json
import re
import requests
from typing import Any, Dict, List, Tuple
import streamlit as st
from openai import OpenAI

REL_CODE = {"association": 110, "include": 111, "generalization": 112, "extend": 113}


def _get_llm_provider() -> str:
    """Return the active extraction provider for generation flows."""
    choice = st.session_state.get("llm_provider")
    if choice:
        return choice.lower()
    return (st.secrets.get("llm", {}).get("provider") or "google").lower()


def _call_google_llm_text(user_text: str, *, temperature: float = 0.0,
                          max_tokens: int = 8192) -> str:
    cfg = st.secrets.get("gemini", {})
    api_key = cfg.get("api_key") or ""
    model = cfg.get("model") or "gemini-2.5-flash"

    if not api_key:
        raise RuntimeError(
            "Google Gemini API key not configured. "
            "Add [gemini] api_key = \"...\" to .streamlit/secrets.toml"
        )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_text}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    resp = requests.post(url, json=body)
    resp.raise_for_status()
    result = resp.json()
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise ValueError(
            f"Unexpected Gemini response structure:\n{json.dumps(result, indent=2)}"
        )


def _call_openai_llm_text(user_text: str, *, temperature: float = 0.0,
                          max_tokens: int = 8192) -> str:
    cfg = (st.secrets or {}).get("llm", {})
    base_url = cfg.get("base_url") or "https://api.openai.com/v1"
    api_key = cfg.get("api_key") or ""
    model = cfg.get("model") or "gpt-4o-mini"

    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_text}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""

# --- Normalization helpers ----------------------------------------------------

def _norm_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _norm_role_type(s: str) -> str:
    """
    Normalize role types the LLM may produce into {'actor', 'usecase'}.
    Accepts variants like 'Actor', 'Use Case', 'use-case', 'UseCase', etc.
    """
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = re.sub(r"[\s_-]+", "", s)
    if s in {"actor", "actors"}:
        return "actor"
    if s in {"usecase", "usecases"}:
        return "usecase"
    return s

def _norm_rel_type(s: str) -> str:
    """
    Normalize relationship types to keys in REL_CODE:
    {'association', 'include', 'extend', 'generalization'}.
    Handles variants like 'associations', '<<include>>', 'extends', 'generalisation'.
    """
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = re.sub(r"[<>\s]", "", s)
    s = re.sub(r"[^a-z]", "", s)
    if s in {"association", "associations", "assoc"}:
        return "association"
    if s in {"include", "includes"}:
        return "include"
    if s in {"extend", "extends"}:
        return "extend"
    if s in {"generalization", "generalisation", "generalize", "generalise"}:
        return "generalization"
    # Unknown type — fall back to association (most common UCD relationship)
    return "association"


def _to_text(v: Any) -> str:
    """Coerce arbitrary LLM value to a plain string for normalization/dedup.
    - Lists: join simple scalar items with spaces
    - Dicts: try common text-bearing keys
    - Numbers/bool: cast to str
    - None: empty string
    """
    if isinstance(v, list):
        parts: List[str] = []
        for x in v:
            if isinstance(x, (str, int, float)):
                parts.append(str(x))
        return " ".join(parts)
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        for k in ("name", "title", "text", "value", "description", "domain_name", "label"):
            if k in v and isinstance(v[k], (str, int, float)):
                return str(v[k])
        return ""
    return str(v or "")

def _safe_dedupe_strings(items: list, cap: int) -> List[str]:
    """
    Safely de-duplicates a list that is *supposed* to contain strings
    but might contain other unhashable types (like dicts) from the LLM.
    """
    seen = set()
    cleaned: List[str] = []
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _to_text(item).strip()
        elif isinstance(item, (int, float)):
            text = str(item).strip()
        else:
            continue
        if text and text.lower() not in seen:
            seen.add(text.lower())
            cleaned.append(text)
        if len(cleaned) >= cap:
            break
    return cleaned

def _infer_system_name(data: dict, paragraph: str) -> str:
    """
    Infer a reasonable system_name if the LLM omits it.
    """
    name = (data.get("system_name") or "").strip()
    if name:
        return name
    m = re.search(r"\b([A-Z][A-Za-z0-9 ]{2,}?)\s+(System|Platform|Application)\b", paragraph)
    if m:
        return f"{m.group(1).strip()} {m.group(2)}"
    doms = data.get("domains") or []
    if isinstance(doms, list) and doms:
        dom0 = str(doms[0]).strip()
        if dom0:
            return f"{dom0} System"
    return "System"

# --- Lightweight "Verb-Objectify" heuristics ---------------------------------

_PREP_STARTS = re.compile(r"\b(from|in|into|within|with|using|via|through|to|on|at|by)\b", re.IGNORECASE)

def _verb_objectify(title: str) -> str:
    """
    Keep the leading verb phrase; drop trailing prepositional phrases to get closer to Verb-Object.
    """
    if not isinstance(title, str):
        return ""
    t = _norm_whitespace(title)

    m = _PREP_STARTS.search(t)
    if m:
        head = _norm_whitespace(t[:m.start()])
        if head and len(head.split()) >= 2:
            t = head

    words = t.split()
    if len(words) > 5:
        t = " ".join(words[:4])

    t = " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in t.split())
    return t

# --- Title Case with acronym preservation ------------------------------------

def _is_acronym(token: str) -> bool:
    if not isinstance(token, str):
        return False
    letters = re.sub(r"[^A-Za-z]", "", token)
    return len(letters) > 1 and letters.isupper()

def _title_preserve_acronyms(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip()
    if not s:
        return ""
    tokens = re.split(r"\s+", s)
    out = []
    for tok in tokens:
        if "-" in tok:
            parts = tok.split("-")
            parts_t = [p if _is_acronym(p) else (p.capitalize() if p else p) for p in parts]
            out.append("-".join(parts_t))
        else:
            out.append(tok if _is_acronym(tok) else tok.capitalize())
    return " ".join(out)

def _title_list_preserve_acronyms(items: List[str]) -> List[str]:
    if not isinstance(items, list):
        return []
    return [_title_preserve_acronyms(str(x)) for x in items if isinstance(x, str)]

# --- Singularization helpers --------------------------------------------------

def _singularize_token(tok: str) -> str:
    if not isinstance(tok, str):
        return tok
    t = tok.strip()
    if not t:
        return t
    if _is_acronym(t) or len(t) <= 3:
        return t
    low = t.lower()
    _NON_PLURAL = ("us", "is", "ous", "sis", "ics", "tics", "ais", "eas")
    if any(low.endswith(e) for e in _NON_PLURAL):
        return t
    if low.endswith("ies") and len(t) > 3:
        return t[:-3] + ("Y" if t[-3:].istitle() else "y")
    for suf in ("xes", "zes", "ches", "shes", "ses"):
        if low.endswith(suf) and len(t) > len(suf):
            return t[:-2]
    if low.endswith("s") and not low.endswith("ss") and len(t) > 4:
        return t[:-1]
    return t

def _force_singular(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if not s:
        return s
    parts = s.split(" ")
    last = parts[-1]
    if "-" in last:
        hparts = last.split("-")
        hparts[-1] = _singularize_token(hparts[-1])
        parts[-1] = "-".join(hparts)
    else:
        parts[-1] = _singularize_token(parts[-1])
    return " ".join(parts)

# --- Coercion for alternate schema --------------------------------------------

def _coerce_alt_schema(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "system_name": "",
        "primary_actors": [],
        "secondary_actors": [],
        "actors": [],
        "use_cases": [],
        "domains": [],
        "relationships": [],
    }

    if not isinstance(raw, dict):
        return out

    diagram = raw.get("UseCaseDiagram") or raw.get("useCaseDiagram") or {}
    if not isinstance(diagram, dict):
        return out

    actors_raw = diagram.get("Actors", [])
    usecases_raw = diagram.get("UseCases", [])

    actors: List[str] = []
    if isinstance(actors_raw, list):
        for a in actors_raw:
            if isinstance(a, dict):
                nm = _norm_whitespace(a.get("ActorName") or a.get("name") or "")
                if nm:
                    actors.append(nm)
            elif isinstance(a, str):
                nm = _norm_whitespace(a)
                if nm:
                    actors.append(nm)

    use_cases: List[str] = []
    relationships: List[Dict[str, Any]] = []
    if isinstance(usecases_raw, list):
        for uc in usecases_raw:
            if not isinstance(uc, dict):
                continue
            title = _verb_objectify(uc.get("Title") or uc.get("name") or "")
            if not title:
                continue
            use_cases.append(title)

            involved = uc.get("ActorsInvolved") or uc.get("actors") or []
            if isinstance(involved, list):
                for actor_name in involved:
                    an = _norm_whitespace(actor_name) if isinstance(actor_name, str) else ""
                    if not an:
                        continue
                    if an and an.lower() not in {x.lower() for x in actors}:
                        actors.append(an)
                    relationships.append({
                        "relationship_type": "association",
                        "relation_code": REL_CODE["association"],
                        "source_name": an,
                        "source_type": "actor",
                        "target_name": title,
                        "target_type": "usecase",
                        "extension": "",
                        "confidence": 0.9,
                    })

    out["actors"] = _safe_dedupe_strings(actors, 8)
    out["use_cases"] = _safe_dedupe_strings(use_cases, 12)
    out["domains"] = []
    out["relationships"] = relationships
    return out

# --- Merge helper -------------------------------------------------------------

def _merge_canonical(base: Dict[str, Any], alt: Dict[str, Any]) -> Dict[str, Any]:
    base = dict(base or {})
    for k in ["primary_actors", "secondary_actors", "actors", "use_cases", "domains"]:
        merged = (base.get(k) or []) + (alt.get(k) or [])
        if k == "use_cases":
            cap = 12
        elif k in ("actors", "primary_actors", "secondary_actors"):
            cap = 16 if k == "actors" else 8
        else:
            cap = 5
        base[k] = _safe_dedupe_strings(merged, cap)

    seen = set()
    for r in base.get("relationships") or []:
        try:
            sn = _to_text(r.get("source_name", "")).strip().lower()
            tn = _to_text(r.get("target_name", "")).strip().lower()
            rt = _to_text(r.get("relationship_type", "")).strip().lower()
            seen.add((sn, tn, rt))
        except Exception:
            continue
    rels = base.get("relationships") or []
    for r in alt.get("relationships") or []:
        try:
            sn = _to_text(r.get("source_name", "")).strip().lower()
            tn = _to_text(r.get("target_name", "")).strip().lower()
            rt = _to_text(r.get("relationship_type", "")).strip().lower()
            key = (sn, tn, rt)
            if key in seen:
                continue
            seen.add(key)
            rels.append(r)
        except Exception:
            continue
    base["relationships"] = rels[:40]
    return base

# --- Main LLM extraction ------------------------------------------------------

# ── Semantic RAG utilities ─────────────────────────────────────────────────

def _chunk_text(text: str, chunk_words: int = 350, overlap_words: int = 80) -> list:
    """Split text into overlapping word windows. Returns list of (start_idx, chunk_str)."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_words])
        chunks.append((i, chunk))
        if i + chunk_words >= len(words):
            break
        i += chunk_words - overlap_words
    return chunks


def _cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag = (sum(x * x for x in a) ** 0.5) * (sum(x * x for x in b) ** 0.5)
    return dot / (mag + 1e-9)


def _embed_local(texts: list) -> list:
    from embeddings import _encode, MODEL_LONG, BGE_INSTRUCTION
    vecs = _encode(texts, MODEL_LONG, add_instruction=True)
    return vecs.tolist()


def _semantic_rag_condense(text: str, base_url: str = "", api_key: str = "",
                            char_budget: int = 8000) -> str:
    if len(text) <= char_budget:
        return text

    chunks = _chunk_text(text)
    if not chunks:
        return text[:char_budget]

    QUERIES = [
        "actors roles users administrators managers operators stakeholders patients doctors",
        "use cases system functions tasks operations activities services capabilities",
        "actor performs interacts uses does handles manages submits requests accesses",
        "system name title platform application service called known as named",
    ]

    try:
        all_texts      = QUERIES + [c for _, c in chunks]
        all_embeddings = _embed_local(all_texts)
        q_embs         = all_embeddings[: len(QUERIES)]
        c_embs         = all_embeddings[len(QUERIES) :]

        scored = sorted(
            ((max(_cosine_sim(ce, qe) for qe in q_embs), idx, txt)
             for (idx, txt), ce in zip(chunks, c_embs)),
            reverse=True,
        )
    except Exception:
        return _rag_condense(text, char_budget)

    selected: dict = {}
    used = 0
    for score, idx, txt in scored:
        if used + len(txt) + 1 <= char_budget:
            selected[idx] = txt
            used += len(txt) + 1
        if used >= char_budget * 0.92:
            break

    return " ".join(selected[i] for i in sorted(selected)) or text[:char_budget]


def _keyword_rag_condense(text: str, char_budget: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    ACTOR   = re.compile(r"\b(user|admin|manager|operator|customer|client|staff|technician|"
                          r"engineer|officer|director|analyst|developer|department|"
                          r"organization|authority|stakeholder|doctor|patient|employee|"
                          r"supervisor|nurse|receptionist|technician|pharmacist)\b", re.I)
    ACTION  = re.compile(r"\b(manage|create|update|delete|view|register|schedule|monitor|"
                          r"approve|submit|process|generate|notify|access|control|track|"
                          r"report|configure|authenticate|authorize|search|login|pay|upload|"
                          r"download|request|assign|review|evaluate|validate|verify|"
                          r"maintain|operate|develop|design|implement|plan|analyse|analyze|"
                          r"dispense|prescribe|diagnose|refer|audit|reconcile)\b", re.I)
    scored = sorted(
        enumerate(sentences),
        key=lambda x: len(ACTOR.findall(x[1])) * 2 + len(ACTION.findall(x[1])),
        reverse=True,
    )
    selected_idx, used = set(), 0
    for idx, sent in scored:
        if used + len(sent) + 1 <= char_budget:
            selected_idx.add(idx)
            used += len(sent) + 1
        if used >= char_budget * 0.92:
            break
    return " ".join(sentences[i] for i in sorted(selected_idx)) or text[:char_budget]


def _rag_condense(text: str, char_budget: int = 8000) -> str:
    return _keyword_rag_condense(text, char_budget)


def _merge_extractions(results: list) -> dict:
    merged = {
        "system_name": "",
        "primary_actors": [], "secondary_actors": [], "actors": [],
        "use_cases": [], "domains": [], "relationships": [],
    }
    for r in results:
        if not merged["system_name"] and r.get("system_name"):
            merged["system_name"] = r["system_name"]
        for k in ("primary_actors", "secondary_actors", "actors", "use_cases", "domains"):
            merged[k].extend(r.get(k) or [])
        merged["relationships"].extend(r.get("relationships") or [])

    for k in ("primary_actors", "secondary_actors", "actors", "use_cases", "domains"):
        seen_lo: set = set()
        deduped = []
        for item in merged[k]:
            if isinstance(item, str) and item.strip().lower() not in seen_lo:
                seen_lo.add(item.strip().lower())
                deduped.append(item.strip())
        merged[k] = deduped

    seen_rels: set = set()
    deduped_rels = []
    for rel in merged["relationships"]:
        if not isinstance(rel, dict):
            continue
        key = (rel.get("source_name", "").lower(), rel.get("target_name", "").lower(),
               rel.get("relationship_type", ""))
        if key not in seen_rels:
            seen_rels.add(key)
            deduped_rels.append(rel)
    merged["relationships"] = deduped_rels
    return merged


def ask_llm_extract(paragraph: str) -> Dict[str, Any]:
    """
    Accurate UCD extraction pipeline with semantic RAG.

    Strategy:
      Short  (<8 000 chars):  direct extraction — full text sent to LLM
      Medium (8-30 000 chars): semantic RAG condense → single LLM call
      Long   (>30 000 chars): semantic RAG chunk-and-merge → 3-4 LLM calls
                               then merge results
    """
    text = paragraph.strip()
    SHORT_LIMIT  =  8_000
    MEDIUM_LIMIT = 30_000

    provider = _get_llm_provider()

    def _call_llm(user_text: str, condensed: bool = False, previous_state: str = "") -> str:
        sys_msg = (
            "You are a SysML / UML Use Case Diagram (UCD) extraction expert.\n"
            "Read the system description and extract ALL UCD elements. "
            "Return ONLY a single valid JSON object — no prose, no markdown fences, no explanation.\n\n"

            "OUTPUT SCHEMA (return exactly these top-level keys):\n"
            "{\n"
            '  "system_name":      "Exact system name from the text (2-5 words) but polished and singular",\n'
            '  "primary_actors":   ["Entities that INITIATE use cases and directly benefit from the system. Use singular names only."],\n'
            '  "secondary_actors": ["External supporting entities OUTSIDE the system boundary: third-party gateways, external servers, external sensors. NEVER internal subsystems. Use singular names only."],\n'
            '  "actors":           ["Combined list of ALL primary + secondary actors — no omissions"],\n'
            '  "use_cases":        ["Verb-Object, 2-4 words, Title Case, e.g. Withdraw Cash, Validate PIN"],\n'
            '  "domains":          ["2-4 high-level domain tags, e.g. Banking, Healthcare"],\n'
            '  "relationships":    [ ... see RELATIONSHIP TYPES below ... ]\n'
            "}\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "RELATIONSHIP TYPES — definitions, constraints, and examples\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            '1. "association"  ——  An actor participates in / interacts with a use case.\n'
            "   • Who can use it: ANY actor (primary or secondary) → ANY use case.\n"
            "   • source_type must be \"actor\", target_type must be \"usecase\".\n"
            "   • This is the MOST COMMON relationship. Only add when the text supports it.\n"
            "   • Multiple actors CAN associate to the same use case if the text implies they both interact with it.\n"
            "     e.g. both Driver and Vehicle Occupant may participate in 'Open/close Door'.\n"
            "   • Example: Driver interacts with the system to control braking.\n"
            '     → {"relationship_type":"association","source_name":"Driver","source_type":"actor",'
            '"target_name":"Control Braking","target_type":"usecase","extension":""}\n\n'

            '2. "include"  ——  A base use case ALWAYS and unconditionally executes another use case\n'
            "   as a mandatory sub-step (the included use case is never optional).\n"
            "   • ONLY between two use cases. NEVER between an actor and a use case.\n"
            "   • source_type must be \"usecase\", target_type must be \"usecase\".\n"
            "   • Ask yourself: does the base use case ALWAYS trigger the target? If yes → include.\n"
            "   • Example: Booking a ticket always requires payment processing.\n"
            '     → {"relationship_type":"include","source_name":"Book Ticket","source_type":"usecase",'
            '"target_name":"Process Payment","target_type":"usecase","extension":""}\n\n'

            '3. "extend"  ——  An extending use case OPTIONALLY augments a base use case under a\n'
            "   specific condition. The base use case is complete without it.\n"
            "   • ONLY between two use cases. NEVER between an actor and a use case.\n"
            "   • source_type must be \"usecase\", target_type must be \"usecase\".\n"
            "   • Set \"extension\" to a short description of the condition (e.g. \"if discount applies\").\n"
            "   • Ask yourself: is the target use case still complete without the source? If yes → extend.\n"
            "   • Example: Apply Discount optionally extends Checkout when a coupon is used.\n"
            '     → {"relationship_type":"extend","source_name":"Apply Discount","source_type":"usecase",'
            '"target_name":"Checkout","target_type":"usecase","extension":"when coupon is provided"}\n\n'

            '4. "generalization"  ——  One actor or use case is a specialised kind of another\n'
            "   (inheritance / is-a relationship).\n"
            "   • actor→actor OR usecase→usecase ONLY. NEVER actor→usecase or usecase→actor.\n"
            "   • source_type and target_type must both be \"actor\" or both be \"usecase\".\n"
            "   • Example (actor): Premium Customer is a specialised kind of Customer.\n"
            '     → {"relationship_type":"generalization","source_name":"Premium Customer","source_type":"actor",'
            '"target_name":"Customer","target_type":"actor","extension":""}\n'
            "   • Example (use case): Emergency Withdraw is a specialised kind of Withdraw Cash.\n"
            '     → {"relationship_type":"generalization","source_name":"Emergency Withdraw","source_type":"usecase",'
            '"target_name":"Withdraw Cash","target_type":"usecase","extension":""}\n\n'

            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "STRICT RULES\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1.  system_name: exact name from the text. Do NOT invent one. Use a singular system/artifact noun phrase, not a plural name.\n"
            "2.  primary_actors: human users or EXTERNAL entities that INITIATE use cases (e.g. Doctor, Customer, Admin).\n"
            "    Use singular names only; never plural actor names.\n"
            "    These exist OUTSIDE the system boundary.\n"
            "3.  secondary_actors: EXTERNAL systems/devices the system communicates with (e.g. Payment Gateway,\n"
            "    SMS Service, External Bank Server). MUST exist independently OUTSIDE the system boundary.\n"
            "    Use singular names only; never plural actor names.\n"
            "    LITMUS TEST: Can this entity exist before the system is built and interact with a different system?\n"
            "    If NO -> it is an INTERNAL component, NOT an actor.\n"
            "    NEVER list these as actors (they are INTERNAL elements):\n"
            "      - System name components (ATM in ATM System, Library in Library System, Hospital in Hospital System)\n"
            "      - Managers / Controllers (Session Manager, Login Controller, Registration Manager, System Controller)\n"
            "      - Modules / Engines      (Billing Module, Recommendation Engine, Processing Engine, Auth Module)\n"
            "      - Validators / Checkers  (PIN Validator, Auth Checker, Price Calculator, Form Validator)\n"
            "      - Internal databases or logs owned by the system (Local DB, Audit Log, Event Log)\n"
            "      - Hardware the system itself runs on (internal server, device, controller board)\n"
            "    VALID secondary actors: exist outside the system, are independent of it, e.g.:\n"
            "      - External Payment Gateway, External Bank Server, External SMS Service\n"
            "      - Third-party APIs, External Sensors or Cameras not part of this system\n"
            "4.  actors: combined list of ALL primary + secondary actors.\n"
            "    Every actor name in this combined list must also be singular.\n"
            "5.  use_cases: Verb-Object format, 2-4 words, Title Case, singular object nouns.\n"
            "    Split conjunctions: 'Choose Seat and Train' → 'Choose Seat', 'Choose Train'.\n"
            "6.  Infer relationships only from what the text explicitly states or clearly implies.\n"
            "    Do NOT force a link just because an actor or use case exists.\n"
            "7.  association: actor → usecase ONLY. Never usecase → actor.\n"
            "8.  include: usecase → usecase ONLY. The included UC is always executed, never optional.\n"
            "9.  extend: usecase → usecase ONLY. The extending UC fires only under a specific condition.\n"
            "10. generalization: (actor → actor) OR (usecase → usecase) ONLY. Never cross-type.\n"
            "11. source_name and target_name must EXACTLY match a name already in your actors or use_cases lists.\n"
            "12. NO HALLUCINATION: only extract relationships that are explicitly stated or strongly implied\n"
            "    by the text. Fewer accurate relationships are better than many fabricated ones.\n\n"

            "FULL EXAMPLE (banking ATM):\n"
            "Input: \"A bank customer uses an ATM to withdraw cash. "
            "Withdrawing cash requires validating the customer PIN with the Bank Server. "
            "A Premium Customer is a kind of Bank Customer who can also request a credit limit increase.\"\n"
            "NOTE: The system IS the ATM — so 'ATM' must NOT appear as an actor. "
            "'Bank Server' is an external system outside the ATM, so it IS a secondary actor.\n"
            "Output:\n"
            '{"system_name":"ATM System",'
            '"primary_actors":["Bank Customer","Premium Customer"],'
            '"secondary_actors":["Bank Server"],'
            '"actors":["Bank Customer","Premium Customer","Bank Server"],'
            '"use_cases":["Withdraw Cash","Validate PIN","Request Credit Limit Increase"],'
            '"domains":["Banking","Authentication"],'
            '"relationships":['
            '{"relationship_type":"association","source_name":"Bank Customer","source_type":"actor","target_name":"Withdraw Cash","target_type":"usecase","extension":"","confidence":1.0},'
            '{"relationship_type":"association","source_name":"Premium Customer","source_type":"actor","target_name":"Request Credit Limit Increase","target_type":"usecase","extension":"","confidence":1.0},'
            '{"relationship_type":"association","source_name":"Bank Server","source_type":"actor","target_name":"Validate PIN","target_type":"usecase","extension":"","confidence":1.0},'
            '{"relationship_type":"include","source_name":"Withdraw Cash","source_type":"usecase","target_name":"Validate PIN","target_type":"usecase","extension":"","confidence":1.0},'
            '{"relationship_type":"generalization","source_name":"Premium Customer","source_type":"actor","target_name":"Bank Customer","target_type":"actor","extension":"","confidence":1.0}'
            "]}"
        )

        note = (
            "\n[Partial text — extract ALL actors, use cases, and relationships visible here.]\n"
            if condensed else ""
        )

        try:
            if previous_state:
                combined_content = (
                    f"{sys_msg}\n\n"
                    f"--- PREVIOUS EXTRACTED JSON ---\n"
                    f"Update and expand this JSON with any new actors/use cases/relationships found in the chunk below.\n"
                    f"{previous_state}\n\n"
                    f"--- NEW SYSTEM DESCRIPTION CHUNK ---\n{note}\n{user_text}\n/no_think"
                )
            else:
                # Combined into single user message for local model compatibility
                # (models that don't support the 'system' role in their jinja template).
                combined_content = f"{sys_msg}\n\nSystem description:{note}\n{user_text}\n/no_think"

            if provider == "google":
                return _call_google_llm_text(
                    combined_content,
                    temperature=0,
                    max_tokens=8192,
                )

            return _call_openai_llm_text(
                combined_content,
                temperature=0,
                max_tokens=8192,
            )
        except Exception as e:
            raise e

    def _parse(raw_output: str) -> dict:
        """Full think-block strip + JSON extraction + bracket repair + parse."""
        t = re.sub(r"<think>.*?</think>",                "", raw_output, flags=re.DOTALL)
        t = re.sub(r"<\|thinking\|>.*?<\|/thinking\|>", "", t,          flags=re.DOTALL)
        t = re.sub(r"```[a-zA-Z0-9]*\r?\n", "", t)
        t = re.sub(r"\r?\n```", "", t)
        start = t.find("{")
        if start == -1:
            raise ValueError("No JSON in model output")
        depth, end = 0, -1
        for i, ch in enumerate(t[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        candidate = t[start : end + 1] if end != -1 else t[start:]

        def _repair(s: str) -> str:
            s = re.sub(r"//[^\n]*", "", s)
            s = re.sub(r",(\s*[}\]])", r"\1", s)
            try:
                json.loads(s)
                return s
            except json.JSONDecodeError:
                pass
            chars, stack, in_str, esc = list(s), [], False, False
            for i, ch in enumerate(chars):
                if esc:
                    esc = False
                    continue
                if ch == "\\" and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    stack.append("}")
                elif ch == "[":
                    stack.append("]")
                elif ch in "]}":
                    if stack:
                        if ch != stack[-1]:
                            chars[i] = stack[-1]
                        stack.pop()
            if in_str:
                chars.append('"')
            fixed = "".join(chars)
            fixed = re.sub(r',\s*"[^"]*"\s*:\s*"[^"]*"\s*$', '', fixed)
            fixed = re.sub(r'{\s*"[^"]*"\s*:\s*"[^"]*"\s*$', '{', fixed)
            fixed = re.sub(r',\s*"[^"]*"\s*:\s*$', '', fixed)
            fixed = re.sub(r'{\s*"[^"]*"\s*:\s*$', '{', fixed)
            fixed = re.sub(r',\s*"[^"]*"\s*$', '', fixed)
            fixed = re.sub(r'{\s*"[^"]*"\s*$', '{', fixed)
            chars = list(fixed)
            while stack:
                chars.append(stack.pop())
            return re.sub(r",(\s*[}\]])", r"\1", "".join(chars))

        return json.loads(_repair(candidate))

    # ── TIER 1: short doc — direct extraction (single call, no QA needed) ─────────────────
    if len(text) <= SHORT_LIMIT:
        raw = _parse(_call_llm(text))
        partial_results = [raw]
        _run_qa = False  # single-call extraction is already complete — skip QA

    # ── TIER 2: medium doc — sequential Recursive Refine ──────────────────────────
    elif len(text) <= MEDIUM_LIMIT:
        _run_qa = True
        chunks = _chunk_text(text, chunk_words=800, overlap_words=100)
        selected = [c for _, c in chunks]

        partial_results = []
        current_state_json = ""
        for chunk_text_item in selected:
            try:
                raw_resp = _call_llm(chunk_text_item, condensed=True, previous_state=current_state_json)
                parsed = _parse(raw_resp)
                if isinstance(parsed, dict) and any(parsed.values()):
                    import json as _json
                    current_state_json = _json.dumps(parsed, indent=2)
                    partial_results = [parsed]
            except Exception:
                continue

        if not partial_results:
            raise RuntimeError("Medium Tier chunk extractions failed.")

    # ── TIER 3: long doc — chunk → per-chunk extraction → merge ────────────────────
    else:
        _run_qa = True
        CHUNK_BUDGET = 6_000
        try:
            chunks = _chunk_text(text, chunk_words=1200, overlap_words=250)
            QUERIES = [
                "actors roles users administrators managers operators patients doctors",
                "use cases system functions tasks operations activities services capabilities",
                "actor performs interacts uses does handles manages submits requests accesses",
                "system name title platform application service called known as named",
            ]
            all_embs  = _embed_local(QUERIES + [c for _, c in chunks])
            nq        = len(QUERIES)
            q_embs    = all_embs[:nq]
            c_embs    = all_embs[nq:]
            scored    = sorted(
                ((max(_cosine_sim(ce, qe) for qe in q_embs), idx, txt)
                 for (idx, txt), ce in zip(chunks, c_embs)),
                reverse=True,
            )
            selected, used_idx = [], set()
            for _, idx, txt in scored:
                if len(selected) >= 4:
                    break
                if not any(abs(idx - u) < 3 for u in used_idx):
                    selected.append(txt)
                    used_idx.add(idx)
        except Exception:
            big_condensed = _keyword_rag_condense(text, CHUNK_BUDGET * 3)
            selected = [big_condensed]

        partial_results = []
        current_state_json = ""
        for chunk_text_item in selected:
            try:
                raw_resp = _call_llm(chunk_text_item, condensed=True, previous_state=current_state_json)
                parsed = _parse(raw_resp)
                if isinstance(parsed, dict) and any(parsed.values()):
                    import json as _json
                    current_state_json = _json.dumps(parsed, indent=2)
                    partial_results = [parsed]
            except Exception:
                continue

        if not partial_results:
            raise RuntimeError("All chunk extractions failed. Check your LLM connection.")

    # ── Merge partial results → final normalised data ─────────────────────────
    raw = _merge_extractions(partial_results)

    data = {
        "system_name": "",
        "primary_actors": [],
        "secondary_actors": [],
        "actors": [],
        "use_cases": [],
        "domains": [],
        "relationships": [],
    }

    if isinstance(raw, dict):
        for k in ["system_name", "primary_actors", "secondary_actors", "actors", "use_cases", "domains", "relationships"]:
            if k in raw:
                data[k] = raw[k]

    coerced = _coerce_alt_schema(raw)
    data = _merge_canonical(data, coerced)

    for k in ["primary_actors", "secondary_actors", "actors", "use_cases", "domains", "relationships"]:
        if k not in data:
            data[k] = []
    for k in ["primary_actors", "secondary_actors", "actors", "use_cases", "domains"]:
        v = data.get(k)
        data[k] = v if isinstance(v, list) else []

    data["primary_actors"]   = _safe_dedupe_strings(data.get("primary_actors"), 8)
    data["secondary_actors"] = _safe_dedupe_strings(data.get("secondary_actors"), 8)
    combined = (data.get("primary_actors") or []) + (data.get("secondary_actors") or []) + (data.get("actors") or [])
    data["actors"]    = _safe_dedupe_strings(combined, 16)
    data["use_cases"] = _safe_dedupe_strings(data.get("use_cases"), 30)
    data["domains"]   = _safe_dedupe_strings(data.get("domains"), 5)

    data["system_name"] = _infer_system_name(data, paragraph)

    data["actors"]    = [_force_singular(a) for a in _title_list_preserve_acronyms(data.get("actors") or [])]
    data["use_cases"] = [
        _force_singular(_title_preserve_acronyms(_verb_objectify(u))) for u in (data.get("use_cases") or [])
    ]
    data["domains"]     = _title_list_preserve_acronyms(data.get("domains") or [])
    data["system_name"] = _title_preserve_acronyms(data.get("system_name") or "")

    actors_l = {a.lower() for a in data["actors"]}
    ucs_l    = {u.lower() for u in data["use_cases"]}

    def _norm_name(s: str) -> str:
        return _force_singular(_title_preserve_acronyms(_verb_objectify(s))).lower()

    uc_norm_map  = {_norm_name(u): u.lower() for u in data["use_cases"]}
    act_norm_map = {_force_singular(a).lower(): a.lower() for a in data["actors"]}

    def _resolve_uc(raw_name: str) -> str:
        r = raw_name.strip().lower()
        if r in ucs_l:
            return r
        n = _norm_name(raw_name)
        if n in ucs_l:
            return n
        if n in uc_norm_map:
            return uc_norm_map[n]
        return r

    def _resolve_act(raw_name: str) -> str:
        r = raw_name.strip().lower()
        if r in actors_l:
            return r
        fs = _force_singular(raw_name.strip()).lower()
        if fs in actors_l:
            return fs
        return r

    cleaned: List[Dict[str, Any]] = []
    seen: set = set()

    rels = data.get("relationships") or []
    if not isinstance(rels, list):
        rels = []

    def _as_text(v) -> str:
        if isinstance(v, list):
            parts = []
            for x in v:
                if isinstance(x, (str, int, float)):
                    parts.append(str(x))
            return " ".join(parts)
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, dict):
            for k in ("name", "title", "text", "value"):
                if k in v and isinstance(v[k], (str, int, float)):
                    return str(v[k])
            return ""
        return str(v or "")

    def _expand_rels(rels_raw: list) -> list:
        """Expand comma-separated source/target names into individual relationship dicts."""
        expanded = []
        for rel in rels_raw:
            if not isinstance(rel, dict):
                continue
            rt_raw = _as_text(rel.get("relationship_type") or "association")
            st_raw = _as_text(rel.get("source_type") or "actor")
            tt_raw = _as_text(rel.get("target_type") or "usecase")
            sn_raw = _as_text(rel.get("source_name") or "")
            tn_raw = _as_text(rel.get("target_name") or "")
            sources = [s.strip() for s in sn_raw.split(",") if s.strip()]
            targets = [t.strip() for t in tn_raw.split(",") if t.strip()]
            for sn in sources:
                for tn in targets:
                    expanded.append({
                        "relationship_type": rt_raw,
                        "source_name": sn,
                        "source_type": st_raw,
                        "target_name": tn,
                        "target_type": tt_raw,
                        "extension": rel.get("extension", ""),
                        "confidence": rel.get("confidence", 0.9),
                    })
        return expanded

    for rel in _expand_rels(rels):
        rt = _norm_rel_type(_as_text(rel.get("relationship_type") or "association"))
        sn = _force_singular(_norm_whitespace(_as_text(rel.get("source_name") or "")))
        tn = _force_singular(_norm_whitespace(_as_text(rel.get("target_name") or "")))
        raw_st = _norm_role_type(_as_text(rel.get("source_type") or ""))
        raw_tt = _norm_role_type(_as_text(rel.get("target_type") or ""))

        sn_l = _resolve_act(sn) if raw_st == "actor" else _resolve_uc(sn)
        tn_l = _resolve_act(tn) if raw_tt == "actor" else _resolve_uc(tn)

        # Infer source_type from known sets when LLM omits or mislabels it
        if raw_st in {"actor", "usecase"}:
            st = raw_st
        elif sn_l in actors_l:
            st = "actor"
        elif sn_l in ucs_l:
            st = "usecase"
        else:
            st = "actor"

        # Infer target_type the same way
        if raw_tt in {"actor", "usecase"}:
            tt = raw_tt
        elif tn_l in ucs_l:
            tt = "usecase"
        elif tn_l in actors_l:
            tt = "actor"
        else:
            tt = "usecase"

        # ── UCD semantic type constraints ──────────────────────────────────────
        # association: actor → usecase ONLY
        if rt == "association":
            if not (st == "actor" and tt == "usecase"):
                continue
        # include / extend: usecase → usecase ONLY
        if rt in {"include", "extend"}:
            if not (st == "usecase" and tt == "usecase"):
                continue
        # generalization: actor→actor OR usecase→usecase ONLY
        if rt == "generalization":
            if not ((st == "actor" and tt == "actor") or (st == "usecase" and tt == "usecase")):
                continue

        valid_source = (sn_l in actors_l) if st == "actor" else (sn_l in ucs_l)
        valid_target = (tn_l in actors_l) if tt == "actor" else (tn_l in ucs_l)
        if not (sn and tn and valid_source and valid_target):
            continue

        key = (sn_l, tn_l, rt)
        if key in seen:
            continue
        seen.add(key)

        # Restore canonical Title Case names for display
        found_sn = next((a for a in data["actors"]    if a.lower() == sn_l), None)
        if not found_sn:
            found_sn = next((u for u in data["use_cases"] if u.lower() == sn_l), sn)
        sn = found_sn

        found_tn = next((a for a in data["actors"]    if a.lower() == tn_l), None)
        if not found_tn:
            found_tn = next((u for u in data["use_cases"] if u.lower() == tn_l), tn)
        tn = found_tn

        conf = rel.get("confidence", 0.9)
        try:
            conf = float(conf)
        except Exception:
            conf = 0.9

        cleaned.append({
            "relationship_type": rt,
            "relation_code": REL_CODE[rt],
            "source_name": sn,
            "source_type": st,
            "target_name": tn,
            "target_type": tt,
            "extension": (_as_text(rel.get("extension", "")) if rt == "extend" else ""),
            "confidence": conf,
        })


    data["relationships"] = cleaned

    # ── Consistency QA Pass (Tier 2/3 only) ─────────────────────────────────────────────
    # Only runs when multiple chunks were merged — verifies consistency of
    # existing relationships, not completeness. It is fine for actors or use
    # cases to have no relationships; we never invent links not in the text.
    if _run_qa:
        try:
            import json as _json
            draft_json = _json.dumps(data, indent=2)
            qa_prompt = (
                "You are a SysML QA Reviewer. Check the following Use Case Diagram JSON for "
                "CONSISTENCY errors only. Do NOT add relationships that are absent. "
                "Do NOT remove relationships just because an actor or use case has none — "
                "it is perfectly valid for elements to have no relationships.\n\n"
                "CHECK ONLY:\n"
                "1. relationship_type is one of: association, include, extend, generalization.\n"
                "2. association → source_type must be 'actor', target_type must be 'usecase'.\n"
                "3. include / extend → both source_type and target_type must be 'usecase'.\n"
                "4. generalization → both sides must be the same type (actor→actor or usecase→usecase).\n"
                "5. source_name and target_name must exactly match a name in the actors or use_cases lists.\n"
                "6. No hallucinated relationships — every relationship must be supported by the text.\n\n"
                "For each relationship that fails any check, REMOVE it. Otherwise keep everything as-is.\n"
                "Output ONLY the corrected valid JSON with the same schema. No markdown, no prose."
                f"\n\n--- ORIGINAL SYSTEM DESCRIPTION ---\n{paragraph}\n\n"
                f"--- DRAFT JSON ---\n{draft_json}"
            )
            raw_qa = _call_llm(f"{qa_prompt}\n\n/no_think", condensed=True)
            final_parsed = _parse(raw_qa)
            if isinstance(final_parsed, dict) and "relationships" in final_parsed:
                for k in ["primary_actors", "secondary_actors", "actors", "use_cases", "domains", "relationships"]:
                    if k not in final_parsed:
                        final_parsed[k] = data[k]
                return final_parsed
        except Exception as e:
            print(f"QA pass failed: {e}")

    return data
