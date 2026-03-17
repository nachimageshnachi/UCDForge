"""
POS Tag Analysis — standalone Streamlit page.

Uses spaCy (en_core_web_trf) with GPU acceleration.
Validation logic mirrors SpacyandFlair.py:
- Use cases : "User shall <UC>" prefix  (imperative verb enforcement)
- Actors/System: "the <NAME> role" suffix  (singular noun-phrase enforcement)

Usage:
    streamlit run postag.py
"""

import json
import os
import re
import time
from typing import List, Tuple

import streamlit as st
import pandas as pd
import spacy
import nltk
from nltk.corpus import words as nltk_words, wordnet as wn
from nltk.stem import WordNetLemmatizer

st.set_page_config(page_title="POS Tag Analysis", layout="wide")

# ── GPU + model ─────────────────────────────────────────────────────────────

import torch

_USE_GPU = torch.cuda.is_available()
spacy.prefer_gpu()  # hint for spaCy's own ops


@st.cache_resource
def _load_spacy():
    return spacy.load("en_core_web_trf", disable=["ner"])


@st.cache_resource
def _setup_nltk():
    for pkg in ["words", "wordnet", "omw-1.4"]:
        nltk.download(pkg, quiet=True)
    return WordNetLemmatizer(), set(nltk_words.words())


nlp = _load_spacy()
_lemmatizer, _WORD_LIST = _setup_nltk()

# Regex to detect true all-caps acronyms (e.g. GPS, ATC, UAV, DCS)
_ACRONYM_RE = re.compile(r'^[A-Z]{2,}$')


def _can_be_verb(word: str) -> bool:
    return bool(wn.synsets(word, pos=wn.VERB))


def _can_be_noun(word: str) -> bool:
    return bool(wn.synsets(word, pos=wn.NOUN))


def _is_valid_english_word(word: str) -> bool:
    return word.lower() in _WORD_LIST


# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_use_cases() -> list[tuple[str, str]]:
    """Return list of (use_case_name, system_name) from DB → session state → result.json."""
    # 1) Database (primary source)
    try:
        from connection import connection
        with connection.get_cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT uc.name, c.title AS system_name "
                "FROM use_cases uc JOIN cases c ON uc.case_id = c.case_id "
                "ORDER BY c.title, uc.name"
            )
            rows = cursor.fetchall() or []
        result = [
            ((row.get("name") or "").strip(), (row.get("system_name") or "Unknown").strip())
            for row in rows
            if (row.get("name") or "").strip()
        ]
        if result:
            return result
    except Exception:
        pass  # DB unavailable, fall through

    # 2) Session state
    extraction = st.session_state.get("extraction_results")
    if extraction and isinstance(extraction, dict):
        ucs = extraction.get("use_cases", [])
        sys_name = extraction.get("system_name", "Unknown")
        if ucs:
            return [(u.strip(), sys_name) for u in ucs if isinstance(u, str) and u.strip()]

    # 3) result.json fallback
    json_path = os.path.join(os.path.dirname(__file__), "result.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sys_name = data.get("system_name", "Unknown")
        return [(u.strip(), sys_name) for u in data.get("use_cases", []) if isinstance(u, str) and u.strip()]

    return []


def _load_actors_and_system() -> tuple[list[tuple[str, str]], list[str]]:
    """Return ([(actor_name, system_name), ...], [system_names]) from DB → session state → result.json."""
    # 1) Database (primary source)
    try:
        from connection import connection
        with connection.get_cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT a.actor_name, c.title AS system_name "
                "FROM actors a JOIN cases c ON a.case_id = c.case_id "
                "ORDER BY c.title, a.actor_name"
            )
            rows = cursor.fetchall() or []
        actors = [
            ((row.get("actor_name") or "").strip(), (row.get("system_name") or "Unknown").strip())
            for row in rows
            if (row.get("actor_name") or "").strip()
        ]
        # fetch distinct system names
        with connection.get_cursor(dictionary=True) as cursor:
            cursor.execute("SELECT title FROM cases ORDER BY title")
            sys_rows = cursor.fetchall() or []
        systems = [(r.get("title") or "").strip() for r in sys_rows if (r.get("title") or "").strip()]
        if actors:
            return actors, systems
    except Exception:
        pass  # DB unavailable, fall through

    # 2) Session state
    extraction = st.session_state.get("extraction_results")
    if extraction and isinstance(extraction, dict):
        actors_raw = extraction.get("actors", [])
        system = extraction.get("system_name", "Unknown")
        if actors_raw or system:
            return (
                [(a.strip(), system) for a in actors_raw if isinstance(a, str) and a.strip()],
                [system.strip()] if system else [],
            )

    # 3) result.json fallback
    json_path = os.path.join(os.path.dirname(__file__), "result.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        system = data.get("system_name", "Unknown").strip()
        actors = [(a.strip(), system) for a in data.get("actors", []) if isinstance(a, str) and a.strip()]
        return actors, [system] if system else []

    return [], []


# ── POS Analysis functions ──────────────────────────────────────────────────

def _clean_name(text: str) -> str:
    """Strip parenthetical expansions and non-alpha noise from a name."""
    cleaned = re.sub(r"\s*\([^)]*\)", "", text)
    cleaned = re.sub(r"[^A-Za-z ]", "", cleaned)
    return cleaned.strip()


# -------------------------------------------------------------------- #
#  USE-CASE TITLE VALIDATOR  (SysML v1/v2 naming rules)
#  Normalization prefix: "User shall <title>"
#
#  Rule 1 – Verb Phrase structure  (Verb + Object, not a noun phrase)
#  Rule 2 – Active Voice           (reject passive constructs)
#  Rule 3 – Imperative Mood        (base verb form, not 3rd person)
#  Rule 4 – Specific Direct Object (reject vague objects)
#  Rule 5 – Qualifier Placement    (adjectives must precede nouns)
#  Rule 6 – No Articles            (no "the", "a", "an")
#  Rule 7 – No Auxiliary Verbs     (no "is", "has", "will", "should"…)
# -------------------------------------------------------------------- #

# Auxiliary / modal verbs to reject
_AUXILIARIES = {
    "is", "am", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "having",
    "do", "does", "did",
    "will", "would", "shall", "should",
    "can", "could", "may", "might", "must",
}

# ── Vagueness detection via WordNet (purely structural, no hardcoded lists) ─
# A noun is "vague" if it sits near the top of the taxonomy and/or is highly polysemous.
# A verb is "vague" if it has many troponyms (sub-verbs) and/or is highly polysemous.


def _is_vague_object(word: str) -> bool:
    """
    Determine if a noun is too generic/abstract for a use-case object.
    Pure WordNet graph structure: polysemy, hypernym depth, hyponym fan-out.
    """
    w = word.lower().strip()
    if not w:
        return False

    noun_synsets = wn.synsets(w, pos=wn.NOUN)
    if not noun_synsets:
        return False  # unknown word — don't flag

    # 1) High polysemy → ambiguous/generic (≥ 6 noun senses)
    if len(noun_synsets) >= 6:
        return True

    # 2) Shallow depth + many hyponyms = broad abstract category
    #    e.g. "data" depth=3, many hyponyms; "vehicle" depth=6, few hyponyms
    primary = noun_synsets[0]
    min_depth = primary.min_depth()
    hyponym_count = len(primary.hyponyms())

    # Very shallow (near root of taxonomy) — almost certainly abstract
    if min_depth <= 2:
        return True

    # Shallow + broad (many sub-categories) = umbrella concept
    if min_depth <= 4 and hyponym_count >= 4:
        return True

    # 3) Check across top synsets for shallow+broad pattern
    for syn in noun_synsets[:3]:
        if syn.min_depth() <= 3 and len(syn.hyponyms()) >= 3:
            return True

    return False


def _is_vague_verb(word: str) -> bool:
    """
    Determine if a verb is too generic/umbrella for a use-case title.
    Pure WordNet graph structure: polysemy, troponym (hyponym) count, depth.
    """
    w = _lemmatizer.lemmatize(word.lower().strip(), "v")
    if not w:
        return False

    verb_synsets = wn.synsets(w, pos=wn.VERB)
    if not verb_synsets:
        return False

    # 1) Very high polysemy → too many meanings (≥ 8 verb senses)
    if len(verb_synsets) >= 8:
        return True

    # 2) Many troponyms on primary synset = umbrella verb
    #    "manage" → supervise, administer, direct …
    #    "authenticate" → (almost none — it's specific)
    primary = verb_synsets[0]
    troponyms = primary.hyponyms()
    if len(troponyms) >= 5:
        return True

    # 3) Very shallow verb + any troponyms = root-level action
    if primary.min_depth() <= 1 and len(troponyms) >= 1:
        return True

    # 4) Aggregate: if total troponyms across top senses are high
    total_troponyms = sum(len(s.hyponyms()) for s in verb_synsets[:3])
    if total_troponyms >= 8:
        return True

    return False


def analyse_use_case(uc_name: str, element: str = "") -> dict:
    """
    Validate a SysML use-case title against 7 grammatical rules.
    Returns dict with name, tags, errors, warnings, status.
    """
    title = _clean_name(uc_name)
    element = element.strip()
    errors: List[str] = []
    warnings: List[str] = []

    if not title:
        return _result(uc_name, [], ["use-case title must not be empty"], [])

    # ── Collision check ──────────────────────────────────────────────────
    if element:
        title_lc, elem_lc = title.lower(), element.lower()
        if title_lc == elem_lc:
            errors.append(f"use-case name must not be identical to actor/system name ('{element}')")
        elif title_lc in {elem_lc+"s", elem_lc+"es", elem_lc+"ing", elem_lc+"ed"}:
            errors.append(f"use-case name must not be a grammatical variant of actor/system name ('{element}')")

    # ── NLP parse — "User shall <title>" normalization ───────────────────
    normalized = f"User shall {title}"
    doc = nlp(normalized)
    all_tokens = [t for t in doc if not t.is_space]
    tokens = all_tokens[2:]  # strip "User shall"

    tags = [(t.text, t.pos_, t.tag_) for t in tokens]

    if not tokens:
        return _result(uc_name, tags, ["use-case title must not be empty"], [])

    first = tokens[0]
    last  = tokens[-1]

    # =====================================================================
    # RULE 0 – Spelling check  (catch typos like "Proivde")
    # =====================================================================
    for tok in tokens:
        w = tok.text
        # Skip proper nouns, acronyms (all-caps), short words, non-alpha
        if tok.pos_ == "PROPN" or _ACRONYM_RE.fullmatch(w) or len(w) <= 2 or not w.isalpha():
            continue
        w_lower = w.lower()
        # Check NLTK word list + WordNet as fallback
        if not _is_valid_english_word(w_lower) and not wn.synsets(w_lower):
            # Compound-word fallback: try splitting into two valid sub-words
            # e.g. "checkin" → "check" + "in", "substation" → "sub" + "station"
            is_compound = False
            # Scan from middle outward to prefer balanced splits
            # e.g. "logout" → "log"+"out" (i=3) not "lo"+"gout" (i=2)
            mid = len(w_lower) // 2
            split_points = sorted(range(2, len(w_lower) - 1), key=lambda x: abs(x - mid))
            for i in split_points:
                left, right = w_lower[:i], w_lower[i:]
                if ((_is_valid_english_word(left) or wn.synsets(left))
                        and (_is_valid_english_word(right) or wn.synsets(right))):
                    is_compound = True
                    break
            if not is_compound:
                # Try to suggest the correct spelling
                from difflib import get_close_matches
                suggestions = get_close_matches(w_lower, _WORD_LIST, n=1, cutoff=0.8)
                if suggestions:
                    errors.append(
                        f"[Rule 0] Possible spelling error: '{w}' — did you mean '{suggestions[0].title()}'?"
                    )
                else:
                    errors.append(
                        f"[Rule 0] Possible spelling error: '{w}' is not a recognised English word"
                    )

    # =====================================================================
    # RULE 1 – Verb Phrase structure  (Verb + Object)
    # =====================================================================
    # Must have at least 2 words (verb + object)
    if len(tokens) == 1:
        errors.append(
            "[Rule 1] Use-case must be a verb–object phrase "
            "(e.g. 'Authenticate User'), not a single word"
        )
        return _result(uc_name, tags, errors, warnings)

    # First token must be a verb
    starts_with_verb = (
        first.pos_ == "VERB"
        or _can_be_verb(first.text.lower())
    )
    if not starts_with_verb:
        errors.append(
            f"[Rule 1] Must start with a verb (found '{first.text}' → {first.pos_}). "
            f"Avoid noun-phrase names like 'Order Processing'; use 'Process Order' instead"
        )

    # Last token should be a noun (the object)
    # WordNet fallback: accept words like "Return" that can be both verb and noun
    if last.pos_ not in {"NOUN", "PROPN"}:
        if _can_be_noun(last.text.lower()):
            pass  # ambiguous word — accept it (e.g. "Return", "Report", "Process")
        else:
            errors.append(
                f"[Rule 1] Must end with a noun/object (found '{last.text}' → {last.pos_})"
            )

    # =====================================================================
    # RULE 2 – Active Voice  (reject passive constructs)
    # =====================================================================
    # Primary: dependency parser (auxpass / nsubjpass) — reliable
    # Only check UC tokens (skip scaffold "User shall")
    passive_found = False
    uc_token_set = set(id(t) for t in tokens)   # identity of UC tokens
    for tok in tokens:
        if tok.dep_ in {"auxpass", "nsubjpass"}:
            main_verb = tok.head
            # Only flag if both the passive marker and its head are UC tokens
            if id(main_verb) in uc_token_set or id(tok) in uc_token_set:
                passive_found = True
                errors.append(
                    f"[Rule 2] Passive voice detected ('{tok.text}' + '{main_verb.text}'). "
                    f"Use active voice: e.g. 'Validate Payment' not 'Payment is Validated'"
                )
                break

    # Fallback: POS heuristic (be-verb + VBN) for edge cases
    if not passive_found:
        for i, tok in enumerate(tokens[:-1]):
            if tok.lower_ in {"is", "are", "was", "were", "be", "been", "being"}:
                nxt = tokens[i + 1]
                if nxt.tag_ == "VBN":
                    errors.append(
                        f"[Rule 2] Likely passive voice ('{tok.text} {nxt.text}'). "
                        f"Use active voice: e.g. 'Validate Payment' not 'Payment is Validated'"
                    )
                    break

    # =====================================================================
    # RULE 3 – Imperative Mood  (base verb form, not 3rd person)
    # =====================================================================
    if starts_with_verb and first.tag_ == "VBZ":
        # VBZ = 3rd person singular present ("Calculates", "Processes")
        errors.append(
            f"[Rule 3] Use imperative/base verb form, not 3rd person "
            f"(found '{first.text}'). Use '{first.lemma_.title()}' instead"
        )

    # Detect noun-phrase pattern ending in "-ing"/"-tion"/"-ment" (nominalisation)
    if last.text.lower().endswith(("tion", "sion", "ment", "ance", "ence")):
        if first.pos_ != "VERB" and not _can_be_verb(first.text.lower()):
            warnings.append(
                f"[Rule 3] '{title}' looks like a noun phrase (nominalisation). "
                f"Prefer imperative verb form: e.g. 'Process Order' not 'Order Processing'"
            )

    # (Rule 4 — vague verb/object checks removed: if the use case follows
    #  Verb + Object structure, it is considered well-formed.)

    # =====================================================================
    # RULE 5 – Qualifier Placement  (adjectives must precede nouns)
    # =====================================================================
    for i, tok in enumerate(tokens[:-1]):
        if tok.pos_ == "ADJ":
            nxt = tokens[i + 1]
            if nxt.pos_ not in {"NOUN", "PROPN", "ADJ"}:
                errors.append(
                    f"[Rule 5] Adjective '{tok.text}' must be followed by a noun, "
                    f"not '{nxt.text}' ({nxt.pos_})"
                )

    # =====================================================================
    # RULE 6 – No Articles  ("the", "a", "an")
    # =====================================================================
    for tok in tokens:
        if tok.pos_ == "DET" and tok.lower_ in {"the", "a", "an"}:
            warnings.append(
                f"[Rule 6] Avoid articles in use-case names (found '{tok.text}'). "
                f"Use 'Create Account' not 'Create an Account'"
            )

    # =====================================================================
    # RULE 7 – No Auxiliary Verbs  ("is", "has", "will", "should" …)
    # =====================================================================
    for tok in tokens:
        if tok.lower_ in _AUXILIARIES:
            errors.append(
                f"[Rule 7] Avoid auxiliary verbs (found '{tok.text}'). "
                f"Use direct verbs: e.g. 'Process Payment' not 'System Will Process Payment'"
            )

    # ── Conjunction check ─────────────────────────────────────────────────
    for tok in tokens:
        if tok.pos_ == "CCONJ" and tok.lower_ == "and":
            warnings.append(
                f"Use-case contains '{tok.text}' — consider splitting into "
                f"separate use cases (e.g. 'Backup Data' and 'Restore Data')"
            )
        elif tok.pos_ == "CCONJ" and tok.lower_ == "or":
            errors.append(
                f"Use-case contains '{tok.text}' — ambiguous behaviour. "
                f"Refine into a specific action or generalize the concept "
                f"(e.g. 'Send Email or SMS' → 'Send Notification')"
            )

    # ── Additional quality checks ────────────────────────────────────────
    # Pronoun rejection
    for tok in tokens:
        if tok.pos_ == "PRON":
            errors.append(f"Use-case names must not contain pronouns (found '{tok.text}')")

    # Token sanity
    for tok in tokens:
        if tok.pos_ in {"SYM", "X"}:
            errors.append(f"Invalid token '{tok.text}'")

    return _result(uc_name, tags, errors, warnings)


# -------------------------------------------------------------------- #
#  ACTOR / SYSTEM NAME VALIDATOR  (mirrors SpacyandFlair.isMeaningfulCommonSingularNounPhrase)
#  Normalization: "the <NAME> role"
# -------------------------------------------------------------------- #

def analyse_noun_phrase(name: str) -> dict:
    """
    Validate a noun phrase that must end with a COMMON SINGULAR NOUN.
    Uses 'the <name> role' normalization to disambiguate noun/verb ambiguity.
    """
    clean = _clean_name(name)
    errors: List[str] = []
    warnings: List[str] = []

    if not clean:
        return _result(name, [], ["System/Actor name must not be empty"], [])

    # ── 0) Normalize: "the <name> role" ──────────────────────────────────
    normalized = f"the {clean} role"
    doc_orig = nlp(normalized)
    doc_low  = nlp(normalized.lower())

    orig_tokens = [t for t in doc_orig if not t.is_space]
    low_tokens  = [t for t in doc_low  if not t.is_space]

    if len(orig_tokens) < 3:
        return _result(name, [], ["System/Actor name must contain at least one word"], [])

    # Strip scaffolding: "the" … "role"
    tokens = list(zip(orig_tokens[1:-1], low_tokens[1:-1]))
    if not tokens:
        return _result(name, [], ["System/Actor name must contain at least one word"], [])

    tags = [(to.text, to.pos_, to.tag_) for to, _ in tokens]

    # ── 1) Pronoun & indefinite rejection ────────────────────────────────
    INDEFINITE = {"anyone","anybody","someone","somebody","everyone","everybody","nobody","none"}
    for tok_orig, tok_low in tokens:
        if tok_low.lower_ in INDEFINITE:
            errors.append(f"must not contain indefinite pronouns ('{tok_orig.text}')")
        if tok_low.pos_ == "PRON":
            errors.append(f"must not contain pronouns ('{tok_orig.text}')")

    # ── 2) Noun-phrase enforcement (no verbs) ────────────────────────────
    for tok_orig, tok_low in tokens:
        if tok_orig.dep_ == "compound" and tok_orig.head.pos_ == "NOUN":
            continue
        noun_lemma = _lemmatizer.lemmatize(tok_low.text.lower(), "n")
        if tok_low.pos_ == "VERB" and noun_lemma != tok_low.text.lower():
            errors.append(f"must be a noun phrase, not an action (found verb '{tok_orig.text}')")

    # ── 3) Head noun checks (last token) ─────────────────────────────────
    head_orig, head_low = tokens[-1]
    #   PROPN (proper nouns) accepted — acronyms and proper names are valid
    #   in actor/system names (e.g. "GPS", "Sentinel").
    if head_low.pos_ not in {"NOUN", "PROPN"}:
        errors.append(f"must end with a noun (ends with '{head_orig.text}')")

    MASS_NOUNS = {"data","information","equipment","software","hardware","staff","personnel","management"}

    # Skip plural checks for acronyms (GPS, DCS end in 'S' but aren't plural)
    is_head_acronym = _ACRONYM_RE.fullmatch(head_orig.text)

    # Reject plural head nouns (skip acronyms)
    if not is_head_acronym:
        if head_low.tag_ in {"NNS", "NNPS"} and head_low.text.lower() not in MASS_NOUNS:
            errors.append(f"must end with a singular noun (found plural '{head_orig.text}')")

        # Lemma-based plural safeguard
        lemma = _lemmatizer.lemmatize(head_low.text.lower(), "n")
        if (head_low.text.lower().endswith("s")
                and head_low.text.lower() != lemma
                and head_low.text.lower() not in MASS_NOUNS):
            errors.append(f"must end with a singular noun (found plural '{head_orig.text}')")

    # ── 4) Adjective placement ───────────────────────────────────────────
    for i, (tok_orig, tok_low) in enumerate(tokens[:-1]):
        _, nxt_low = tokens[i + 1]
        if tok_low.pos_ == "ADJ" and nxt_low.pos_ not in {"NOUN", "PROPN"}:
            errors.append(f"adjective '{tok_orig.text}' must be followed by a noun")

    # ── 5) POS whitelist ─────────────────────────────────────────────────
    #   PROPN allowed — proper nouns / acronyms are valid in actor/system names.
    ALLOWED_POS = {"NOUN", "ADJ", "ADP", "PART", "PROPN", "NUM"}
    for tok_orig, tok_low in tokens:
        if tok_low.pos_ not in ALLOWED_POS:
            errors.append(f"'{tok_orig.text}' is not allowed in a noun phrase")

    # ── 6) Style warning: prefer compound noun ───────────────────────────
    ROLE_NOUNS = {"administrator","operator","controller","manager","owner","maintainer","supervisor","coordinator","provider","consumer","producer"}
    PREPOSITIONS = {"of", "for", "with"}
    if len(tokens) == 3:
        (t1o, t1l), (t2o, t2l), (t3o, t3l) = tokens
        if (t1l.pos_ == "NOUN" and t1l.lemma_.lower() in ROLE_NOUNS
                and t2l.pos_ == "ADP" and t2l.lower_ in PREPOSITIONS
                and t3l.pos_ == "NOUN"):
            compound = f"{t3o.text.title()} {t1o.text.title()}"
            warnings.append(f"prefer compound noun '{compound}' over prepositional form '{name}'")

    # ── 7) Acronym-only warning ──────────────────────────────────────────
    #   A single acronym (e.g. "GPS", "ATC") is technically valid but
    #   actors should represent roles, not devices/things.
    if len(tokens) == 1 and _ACRONYM_RE.fullmatch(tokens[0][0].text):
        warnings.append(
            f"'{tokens[0][0].text}' is an abbreviation — an actor is a role played by something, "
            f"not the thing itself. Consider a more descriptive name "
            f"(e.g. 'GPS Receiver', 'ATC Controller')."
        )

    return _result(name, tags, errors, warnings)


# ── Result builder ──────────────────────────────────────────────────────────

def _result(name, tags, errors, warnings):
    """Build a standardised result dict."""
    if errors:
        status = "Attention Required!"
    elif warnings:
        status = "Warning!"
    else:
        status = "Well Written"
    return {
        "name":     name,
        "tags":     tags,
        "errors":   errors,
        "warnings": warnings,
        "status":   status,
    }


# ── Colours ─────────────────────────────────────────────────────────────────

_COLOUR = {
    "Well Written":        "#d4edda",
    "Warning!":            "#fff3cd",
    "Attention Required!": "#f8d7da",
}
_ICON = {
    "Well Written":        "✅",
    "Warning!":            "⚠️",
    "Attention Required!": "❌",
}


# ── UI ──────────────────────────────────────────────────────────────────────

st.title("🏷️ POS Tag Analysis")
st.markdown(
    "Run **spaCy POS tagging** on every use case and actor/system name. "
    "Results appear progressively as each item is processed."
)
if _USE_GPU:
    st.success(f"🚀 **GPU accelerated** — {torch.cuda.get_device_name(0)}")
else:
    st.info("🖥️ Running on **CPU** (no CUDA GPU detected)")

use_cases = _load_use_cases()        # [(name, system), ...]
actors, system_names = _load_actors_and_system()  # [(name, system), ...], [systems]

if not use_cases and not actors:
    st.warning("No use cases or actors found.\nPopulate `result.json` or run UCD Generation first.")
    st.stop()

_sys_label = ", ".join(system_names) if system_names else "—"
st.markdown(f"**{len(use_cases)}** use case(s)  ·  **{len(actors)}** actor(s)  ·  System(s): *{_sys_label}*")

# ── Run button ──────────────────────────────────────────────────────────────

if st.button("▶  Run POS Tag Analysis", type="primary", use_container_width=True):

    total = len(use_cases) + len(actors) + len(system_names)
    progress = st.progress(0, text="Starting …")
    summary_slot = st.empty()

    ok = 0
    warn = 0
    err = 0
    processed = 0

    # ── Use Cases ───────────────────────────────────────────────────────
    st.markdown("## 🔹 Use Cases")
    uc_rows = []

    for idx, (uc, uc_sys) in enumerate(use_cases):
        progress.progress(processed / total, text=f"UC {idx+1}/{len(use_cases)}: **{uc}**")

        result = analyse_use_case(uc)

        bg = _COLOUR[result["status"]]
        icon = _ICON[result["status"]]

        st.markdown(
            f'<div style="background:{bg};padding:10px 14px;border-radius:6px;margin-bottom:6px;">'
            f'<strong>{icon} {idx+1}. {uc}</strong>'
            f'<span style="float:right;font-size:0.85em;">{result["status"]}</span>'
            f'<br/><span style="font-size:0.8em;color:#555;">System: {uc_sys}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Show POS tags in a compact row
        tag_str = "  ".join(f"**{tok}**`/{pos}`" for tok, pos, _ in result["tags"])
        st.markdown(tag_str)

        if result["errors"]:
            for e in result["errors"]:
                st.markdown(f"- ❌ {e}")
        if result.get("warnings"):
            for w in result["warnings"]:
                st.markdown(f"- ⚠️ {w}")

        if result["status"] == "Well Written":
            ok += 1
        elif result["status"] == "Warning!":
            warn += 1
        else:
            err += 1
        processed += 1

        uc_rows.append({
            "System": uc_sys,
            "Name": uc,
            "POS Tags": "  ".join(f"{tok}/{pos}" for tok, pos, _ in result["tags"]),
            "Status": f"{icon} {result['status']}",
            "Issues": "; ".join(result["errors"] + result.get("warnings", [])) or "—",
        })

        summary_slot.markdown(f"### ✅ {ok}  ·  ⚠️ {warn}  ·  ❌ {err}")

    # ── Actors & System ─────────────────────────────────────────────────
    # Build combined list: actors (name, system) + system names as (name, "—")
    all_entries = [(name, sys, "Actor") for name, sys in actors]
    for sn in system_names:
        all_entries.append((sn, "—", "System"))

    if all_entries:
        st.markdown("## 🔹 Actors & System")
        name_rows = []

        for idx, (name, belongs_to, label) in enumerate(all_entries):
            progress.progress(processed / total, text=f"{label}: **{name}**")

            result = analyse_noun_phrase(name)

            bg = _COLOUR[result["status"]]
            icon = _ICON[result["status"]]

            sys_line = f'<br/><span style="font-size:0.8em;color:#555;">System: {belongs_to}</span>' if label == "Actor" else ""
            st.markdown(
                f'<div style="background:{bg};padding:10px 14px;border-radius:6px;margin-bottom:6px;">'
                f'<strong>{icon} [{label}] {name}</strong>'
                f'<span style="float:right;font-size:0.85em;">{result["status"]}</span>'
                f'{sys_line}'
                f'</div>',
                unsafe_allow_html=True,
            )

            tag_str = "  ".join(f"**{tok}**`/{pos}`" for tok, pos, _ in result["tags"])
            st.markdown(tag_str)

            if result["errors"]:
                for e in result["errors"]:
                    st.markdown(f"- ❌ {e}")
            if result.get("warnings"):
                for w in result["warnings"]:
                    st.markdown(f"- ⚠️ {w}")

            if result["status"] == "Well Written":
                ok += 1
            elif result["status"] == "Warning!":
                warn += 1
            else:
                err += 1
            processed += 1

            name_rows.append({
                "Type": label,
                "System": belongs_to,
                "Name": name,
                "POS Tags": "  ".join(f"{tok}/{pos}" for tok, pos, _ in result["tags"]),
                "Status": f"{icon} {result['status']}",
                "Issues": "; ".join(result["errors"] + result.get("warnings", [])) or "—",
            })

            summary_slot.markdown(f"### ✅ {ok}  ·  ⚠️ {warn}  ·  ❌ {err}")

    # ── Done ────────────────────────────────────────────────────────────
    progress.progress(1.0, text="Done!")

    st.markdown("---")
    st.markdown("## 📊 Summary")

    def _row_colour(row):
        if "✅" in row["Status"]:
            return ["background-color: #d4edda"] * len(row)
        elif "⚠️" in row["Status"]:
            return ["background-color: #fff3cd"] * len(row)
        return ["background-color: #f8d7da"] * len(row)

    if uc_rows:
        st.markdown("#### Use Cases")
        df_uc = pd.DataFrame(uc_rows)
        st.dataframe(df_uc.style.apply(_row_colour, axis=1), use_container_width=True)

    if all_entries and name_rows:
        st.markdown("#### Actors & System")
        df_names = pd.DataFrame(name_rows)
        st.dataframe(df_names.style.apply(_row_colour, axis=1), use_container_width=True)

    st.success(f"Analysis complete — **{ok}** passed, **{warn}** warnings, **{err}** issues.")