"""
Text verification tools — NLP-based name / phrase analysis.

Uses spaCy ``en_core_web_trf`` (same transformer model as postag.py).
Flair is no longer used.

Verb phrases  : spelling, verb-phrase structure, active voice, imperative mood,
                qualifier placement, no articles, no auxiliaries, conjunctions,
                pronouns, invalid tokens.
Noun phrases  : spelling, pronoun rejection, noun-phrase enforcement,
                head-noun checks, adjective placement, compound-noun style
                warning, acronym-only warning.
"""

import re
from difflib import get_close_matches
from functools import lru_cache

import spacy
import streamlit as st
from nltk.corpus import words, wordnet
from nltk.stem import WordNetLemmatizer

from verification.nlp_setup import (
    getLemmatizer,
    getSimilarityEncoder,
)


# ── Module-level resources ──────────────────────────────────────────────────

_lemmatizer = getLemmatizer()

@st.cache_resource
def _load_spacy_trf():
    """Load the transformer spaCy model (same as postag.py)."""
    try:
        return spacy.load("en_core_web_trf", disable=["ner"])
    except OSError:
        spacy.cli.download("en_core_web_trf")
        return spacy.load("en_core_web_trf", disable=["ner"])


# ── Helpers (mirror postag.py exactly) ──────────────────────────────────────

def _is_valid_english_word(word: str, word_list: set) -> bool:
    return word.lower() in word_list


_NOMINAL_SUFFIXES = (
    "ment", "tion", "sion", "ness", "ity", "ance", "ence",
    "ure", "age", "ism", "ist", "ery", "ary",
)

_DOMAIN_WORD_ALLOWLIST = {
    "backend", "frontend", "middleware", "telemetry", "geospatial",
    "geolocation", "geofence", "geofencing", "georeference",
    "georeferencing", "uav", "sysml", "plantuml",
    # Telecom / mobile domain
    "sim", "gsm", "voip", "wifi", "bluetooth", "cellular", "roaming",
    "hotspot", "imei", "sms", "mms",
}

_LEXICAL_CANONICAL_FORMS = {
    # "admin" is a common actor-role shorthand that is absent from NLTK words/WordNet.
    "admin": "administrator",
}

_PREFIX_WORD_PARTS = {
    "geo", "bio", "cyber", "tele", "multi", "inter", "intra",
    "micro", "macro", "auto", "meta", "pre", "post",
}


def _is_known_wordpiece(piece: str, word_list: set) -> bool:
    p = _LEXICAL_CANONICAL_FORMS.get(piece.lower(), piece.lower())
    return p in _PREFIX_WORD_PARTS or p in word_list or bool(wordnet.synsets(p))


def _is_valid_hyphenated_word(word: str, word_list: set) -> bool:
    parts = [part for part in word.lower().split("-") if part]
    if len(parts) < 2:
        return False
    if "".join(parts) in _DOMAIN_WORD_ALLOWLIST:
        return True
    return all(len(part) >= 2 and _is_known_wordpiece(part, word_list) for part in parts)


def _looks_like_valid_compound_word(word: str, word_list: set) -> bool:
    w = word.lower()
    if w in _DOMAIN_WORD_ALLOWLIST:
        return True
    if "-" in w:
        return _is_valid_hyphenated_word(w, word_list)
    for prefix in sorted(_PREFIX_WORD_PARTS, key=len, reverse=True):
        if not w.startswith(prefix):
            continue
        right = w[len(prefix):]
        if len(right) >= 3 and _is_known_wordpiece(right, word_list):
            return True
    return False


def _is_spelling_valid(word: str, word_list: set) -> bool:
    w = word.lower()
    canonical = _LEXICAL_CANONICAL_FORMS.get(w, w)
    return (
        _is_valid_english_word(canonical, word_list)
        or bool(wordnet.synsets(canonical))
        or _looks_like_valid_compound_word(w, word_list)
    )


def _iter_hyphen_aware_tokens(tokens):
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.text == "-":
            i += 1
            continue

        parts = [tok.text]
        j = i
        while (
            j + 2 < len(tokens)
            and tokens[j + 1].text == "-"
            and tokens[j + 2].text.isalpha()
        ):
            parts.append(tokens[j + 2].text)
            j += 2

        yield "-".join(parts), tok
        i = j + 1


def _is_hyphen_compound_member(tokens, index: int) -> bool:
    if index < 0 or index >= len(tokens):
        return False
    prev_is_hyphen = index > 0 and tokens[index - 1][0].text == "-"
    next_is_hyphen = index + 1 < len(tokens) and tokens[index + 1][0].text == "-"
    return prev_is_hyphen or next_is_hyphen


def _is_likely_nominalization(word: str) -> bool:
    w = word.lower()
    if not any(w.endswith(s) for s in _NOMINAL_SUFFIXES):
        return False
    verb_count = len(wordnet.synsets(w, pos=wordnet.VERB))
    noun_count = len(wordnet.synsets(w, pos=wordnet.NOUN))
    return verb_count == 0 or noun_count > verb_count

def _can_be_verb(word: str) -> bool:
    w = word.lower()
    # Reject likely nominalised forms but keep genuine verbs like "manage".
    if _is_likely_nominalization(w):
        return False
    return bool(wordnet.synsets(w, pos=wordnet.VERB))


def _can_be_noun(word: str) -> bool:
    canonical = _LEXICAL_CANONICAL_FORMS.get(word.lower(), word.lower())
    return bool(wordnet.synsets(canonical, pos=wordnet.NOUN))


# Regex to detect true all-caps acronyms (e.g. GPS, ATC, UAV, DCS)
_ACRONYM_RE = re.compile(r'^[A-Z]{2,}$')

# Auxiliary / modal verbs to reject in use-case titles  (Rule 7)
_AUXILIARIES = {
    "is", "am", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "having",
    "do", "does", "did",
    "will", "would", "shall", "should",
    "can", "could", "may", "might", "must",
}


def _clean_name(text: str) -> str:
    """Strip parenthetical expansions and non-alpha noise from a name."""
    cleaned = re.sub(r"\s*\([^)]*\)", "", text)
    cleaned = re.sub(r"[^A-Za-z -]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


class TextVerificationTools:

    # ------------------------------------------------------------------ #
    #  one-time resources
    # ------------------------------------------------------------------ #
    WORD_LIST   = set(words.words())
    _lemmatizer = getLemmatizer()
    _nlp        = _load_spacy_trf()

    # ================================================================== #
    #  1.  ACTOR / SYSTEM  NAME  VALIDATOR
    #      Mirrors postag.py  analyse_noun_phrase()
    #      Normalisation: "the <NAME> role"
    # ================================================================== #
    @staticmethod
    def isMeaningfulCommonSingularNounPhrase(name: str) -> tuple[bool, str | list, list[str]]:
        """
        Validate a noun-phrase that should end with a **singular noun**.

        Uses ``the <name> role`` normalisation (same as postag.py) to
        disambiguate noun / verb ambiguity via dependency parsing.

        Returns
        -------
        (True,  "", [warnings])       on success
        (False, reason, [warnings])   on failure
        """
        warnings: list[str] = []
        nlp = TextVerificationTools._nlp

        clean = _clean_name(name)
        if not clean:
            return False, "actor/system name must not be empty", warnings

        # ── 0) Normalise: Padding "<name> is creating an account" ────────────────
        normalized = f"{clean} is creating an account"
        doc_orig = nlp(normalized)
        doc_low  = nlp(normalized.lower())

        orig_tokens = [t for t in doc_orig if not t.is_space]
        low_tokens  = [t for t in doc_low  if not t.is_space]

        # "is", "creating", "an", "account" is exactly 4 tokens.
        # Strip this scaffolding to leave only the actor name's tokens.
        if len(orig_tokens) <= 4:
            return False, "actor/system name must contain at least one word", warnings

        tokens = list(zip(orig_tokens[:-4], low_tokens[:-4]))
        if not tokens:
            return False, "actor/system name must contain at least one word", warnings

        # ── RULE 0: Spelling check ──────────────────────────────────────────
        for w, tok_orig in _iter_hyphen_aware_tokens([tok_orig for tok_orig, _ in tokens]):
            w_alpha = w.replace("-", "")
            # Skip proper nouns, acronyms, short words, non-alpha
            if (
                tok_orig.pos_ == "PROPN"
                or _ACRONYM_RE.fullmatch(w_alpha)
                or len(w_alpha) <= 2
                or not w_alpha.isalpha()
            ):
                continue
            w_lower = w.lower()
            if not _is_spelling_valid(w_lower, TextVerificationTools.WORD_LIST):
                suggestions = get_close_matches(
                    w_lower.replace("-", ""),
                    TextVerificationTools.WORD_LIST,
                    n=1,
                    cutoff=0.8,
                )
                if suggestions:
                    return False, (
                        f"possible spelling error: '{w}' — did you mean '{suggestions[0].title()}'?"
                    ), warnings
                else:
                    return False, (
                        f"possible spelling error: '{w}' is not a recognised English word"
                    ), warnings

        # ── 1) Pronoun & indefinite rejection ───────────────────────────────
        INDEFINITE = {"anyone","anybody","someone","somebody","everyone","everybody","nobody","none"}
        for tok_orig, tok_low in tokens:
            if tok_low.lower_ in INDEFINITE:
                return False, f"must not contain indefinite pronouns ('{tok_orig.text}')", warnings
            if tok_low.pos_ == "PRON":
                return False, f"must not contain pronouns ('{tok_orig.text}')", warnings

        # ── 2) Noun-phrase enforcement (no verbs) ──────────────────────────
        for i, (tok_orig, tok_low) in enumerate(tokens):
            if tok_orig.text == "-" or _is_hyphen_compound_member(tokens, i):
                continue
            if tok_orig.dep_ == "compound" and tok_orig.head.pos_ in {"NOUN", "PROPN"}:
                continue
            
            w_lower = tok_low.text.lower()
            noun_lemma = _lemmatizer.lemmatize(w_lower, "n")
            spacy_says_verb = (tok_low.pos_ == "VERB" and noun_lemma != w_lower)
            
            # Additional robustness (inspired by usecase validation):
            # If spaCy doesn't catch it, fallback to WordNet count for single words.
            verb_count = len(wordnet.synsets(w_lower, pos=wordnet.VERB))
            noun_count = len(wordnet.synsets(w_lower, pos=wordnet.NOUN))
            is_primarily_verb = verb_count > 0 and verb_count > noun_count
            
            if spacy_says_verb or is_primarily_verb:
                return False, f"must be a noun phrase, not an action (found verb '{tok_orig.text}')", warnings

        # ── 3) Head noun checks (last token) ───────────────────────────────
        head_orig, head_low = tokens[-1]
        #   PROPN accepted — acronyms and proper names are valid
        if head_low.pos_ not in {"NOUN", "PROPN"}:
            if _can_be_noun(head_low.text.lower()):
                pass  # ambiguous word — accept (e.g. fallback like in usecases)
            else:
                return False, f"must end with a noun (ends with '{head_orig.text}')", warnings

        MASS_NOUNS = {"data","information","equipment","software","hardware","staff","personnel","management"}
        is_head_acronym = _ACRONYM_RE.fullmatch(head_orig.text)

        # Reject plural head nouns (skip acronyms)
        if not is_head_acronym:
            if head_low.tag_ in {"NNS", "NNPS"} and head_low.text.lower() not in MASS_NOUNS:
                return False, f"must end with a singular noun (found plural '{head_orig.text}')", warnings

            # Lemma-based plural safeguard
            lemma = _lemmatizer.lemmatize(head_low.text.lower(), "n")
            if (head_low.text.lower().endswith("s")
                    and head_low.text.lower() != lemma
                    and head_low.text.lower() not in MASS_NOUNS):
                return False, f"must end with a singular noun (found plural '{head_orig.text}')", warnings

        # ── 4) Adjective placement ─────────────────────────────────────────
        for i, (tok_orig, tok_low) in enumerate(tokens[:-1]):
            if tok_orig.text == "-" or _is_hyphen_compound_member(tokens, i):
                continue
            _, nxt_low = tokens[i + 1]
            if tok_low.pos_ == "ADJ" and nxt_low.pos_ not in {"NOUN", "PROPN"} and not _can_be_noun(nxt_low.text.lower()):
                return False, f"adjective '{tok_orig.text}' must be followed by a noun", warnings

        # ── 5) Reject disallowed POS ───────────────────────────────────────
        for i, (tok_orig, tok_low) in enumerate(tokens):
            if tok_orig.text == "-" or _is_hyphen_compound_member(tokens, i):
                continue
            if tok_low.pos_ in {"VERB", "AUX", "CCONJ", "SCONJ", "INTJ", "SYM", "X"}:
                if not _can_be_noun(tok_low.text.lower()):
                    return False, f"'{tok_orig.text}' ({tok_low.pos_}) is not allowed in a noun phrase", warnings

        # ── 6) Style warning: prefer compound noun ─────────────────────────
        ROLE_NOUNS = {
            "administrator","operator","controller","manager","owner",
            "maintainer","supervisor","coordinator","provider","consumer","producer"
        }
        PREPOSITIONS = {"of", "for", "with"}
        if len(tokens) == 3:
            (t1o, t1l), (t2o, t2l), (t3o, t3l) = tokens
            if (t1l.pos_ == "NOUN" and t1l.lemma_.lower() in ROLE_NOUNS
                    and t2l.pos_ == "ADP" and t2l.lower_ in PREPOSITIONS
                    and t3l.pos_ == "NOUN"):
                compound = f"{t3o.text.title()} {t1o.text.title()}"
                warnings.append(
                    f"prefer compound noun '{compound}' over prepositional form '{name}'"
                )

        # ── 7) Acronym-only warning ────────────────────────────────────────
        if len(tokens) == 1 and _ACRONYM_RE.fullmatch(tokens[0][0].text):
            warnings.append(
                f"'{tokens[0][0].text}' is an abbreviation — an actor is a role played by something, "
                f"not the thing itself. Consider a more descriptive name "
                f"(e.g. 'GPS Receiver', 'ATC Controller')."
            )

        return True, "", warnings        # ✔ all good

    # ================================================================== #
    #  2.  USE-CASE  TITLE  VALIDATOR
    #      Mirrors postag.py  analyse_use_case()
    #      Normalisation: "User shall <title>"
    # ================================================================== #
    @staticmethod
    def isMeaningfulBaseVerbPhrase(title: str, element: str) -> tuple[bool, str, list[str]]:
        """
        Validate a use-case title against postag.py rules 0-7 + extras.

        Uses ``User shall <title>`` normalisation (same as postag.py) so
        spaCy reliably parses the title in imperative context.

        Returns
        -------
        (True,  "", [warnings])     on success
        (False, reason, [warnings]) on failure
        """
        errors: list[str] = []
        warnings: list[str] = []
        nlp = TextVerificationTools._nlp

        clean = _clean_name(title)
        if not clean:
            return False, "use-case title must not be empty", warnings

        # ── Collision check ──────────────────────────────────────────────
        if element:
            title_lc, elem_lc = clean.lower(), _clean_name(element).lower()
            if title_lc == elem_lc:
                errors.append(f"use-case name must not be identical to actor/system name ('{element}')")
            elif title_lc in {elem_lc+"s", elem_lc+"es", elem_lc+"ing", elem_lc+"ed"}:
                errors.append(f"use-case name must not be a grammatical variant of actor/system name ('{element}')")

        # ── NLP parse — "User shall <title>" normalisation ──────────────
        normalized = f"User shall {clean}"
        doc = nlp(normalized)
        all_tokens = [t for t in doc if not t.is_space]
        tokens = all_tokens[2:]  # strip "User shall"

        if not tokens:
            return False, "use-case title must not be empty", warnings

        first = tokens[0]
        last  = tokens[-1]

        # ==================================================================
        # RULE 0 – Spelling check  (catch typos like "Proivde")
        # ==================================================================
        for w, tok in _iter_hyphen_aware_tokens(tokens):
            w_alpha = w.replace("-", "")
            # Skip proper nouns, acronyms, short words, non-alpha
            if (
                tok.pos_ == "PROPN"
                or _ACRONYM_RE.fullmatch(w_alpha)
                or len(w_alpha) <= 2
                or not w_alpha.isalpha()
            ):
                continue
            w_lower = w.lower()
            if not _is_spelling_valid(w_lower, TextVerificationTools.WORD_LIST):
                suggestions = get_close_matches(
                    w_lower.replace("-", ""),
                    TextVerificationTools.WORD_LIST,
                    n=1,
                    cutoff=0.8,
                )
                if suggestions:
                    errors.append(
                        f"[Rule 0] Possible spelling error: '{w}' — did you mean '{suggestions[0].title()}'?"
                    )
                else:
                    errors.append(
                        f"[Rule 0] Possible spelling error: '{w}' is not a recognised English word"
                    )

        # ==================================================================
        # RULE 1 – Verb Phrase structure  (Verb + Object)
        # ==================================================================
        # Must have at least 2 words (verb + object) — matches postag.py
        if len(tokens) == 1:
            errors.append(
                "[Rule 1] Use-case must be a verb–object phrase "
                "(e.g. 'Authenticate User'), not a single word"
            )
            return False, "; ".join(errors), warnings

        # First token must be a verb
        # Guard: reject nominalised forms even if spaCy tags them VERB
        first_is_nominal = _is_likely_nominalization(first.text.lower())
        starts_with_verb = (
            not first_is_nominal
            and (first.pos_ == "VERB" or _can_be_verb(first.text.lower()))
        )
        if not starts_with_verb:
            errors.append(
                f"[Rule 1] Must start with a verb (found '{first.text}' → {first.pos_}). "
                f"Avoid noun-phrase names like 'Order Processing'; use 'Process Order' instead"
            )

        # Last token should be a noun (the object)
        if last.pos_ not in {"NOUN", "PROPN"}:
            if _can_be_noun(last.text.lower()):
                pass  # ambiguous word — accept (e.g. "Return", "Report")
            else:
                errors.append(
                    f"[Rule 1] Must end with a noun/object (found '{last.text}' → {last.pos_})"
                )

        # ==================================================================
        # RULE 2 – Active Voice  (reject passive constructs)
        # ==================================================================
        passive_found = False
        uc_token_set = set(id(t) for t in tokens)
        for tok in tokens:
            if tok.dep_ in {"auxpass", "nsubjpass"}:
                main_verb = tok.head
                if id(main_verb) in uc_token_set or id(tok) in uc_token_set:
                    passive_found = True
                    errors.append(
                        f"[Rule 2] Passive voice detected ('{tok.text}' + '{main_verb.text}'). "
                        f"Use active voice: e.g. 'Validate Payment' not 'Payment is Validated'"
                    )
                    break

        # Fallback: POS heuristic (be-verb + VBN)
        if not passive_found:
            for i_tok, tok in enumerate(tokens[:-1]):
                if tok.lower_ in {"is", "are", "was", "were", "be", "been", "being"}:
                    nxt = tokens[i_tok + 1]
                    if nxt.tag_ == "VBN":
                        errors.append(
                            f"[Rule 2] Likely passive voice ('{tok.text} {nxt.text}'). "
                            f"Use active voice: e.g. 'Validate Payment' not 'Payment is Validated'"
                        )
                        break

        # ==================================================================
        # RULE 3 – Imperative Mood  (base verb form, not 3rd person)
        # ==================================================================
        if starts_with_verb and first.tag_ == "VBZ":
            errors.append(
                f"[Rule 3] Use imperative/base verb form, not 3rd person "
                f"(found '{first.text}'). Use '{first.lemma_.title()}' instead"
            )

        # Detect nominalisation pattern
        if last.text.lower().endswith(("tion", "sion", "ment", "ance", "ence")):
            if first.pos_ != "VERB" and not _can_be_verb(first.text.lower()):
                warnings.append(
                    f"[Rule 3] '{clean}' looks like a noun phrase (nominalisation). "
                    f"Prefer imperative verb form: e.g. 'Process Order' not 'Order Processing'"
                )

        # ==================================================================
        # RULE 5 – Qualifier Placement  (adjectives must precede nouns)
        # ==================================================================
        for i_tok, tok in enumerate(tokens[:-1]):
            if tok.pos_ == "ADJ":
                nxt = tokens[i_tok + 1]
                if nxt.pos_ not in {"NOUN", "PROPN", "ADJ"}:
                    errors.append(
                        f"[Rule 5] Adjective '{tok.text}' must be followed by a noun, "
                        f"not '{nxt.text}' ({nxt.pos_})"
                    )

        # ==================================================================
        # RULE 6 – No Articles  ("the", "a", "an")
        # ==================================================================
        for tok in tokens:
            if tok.pos_ == "DET" and tok.lower_ in {"the", "a", "an"}:
                warnings.append(
                    f"[Rule 6] Avoid articles in use-case names (found '{tok.text}'). "
                    f"Use 'Create Account' not 'Create an Account'"
                )

        # ==================================================================
        # RULE 7 – No Auxiliary Verbs  ("is", "has", "will", "should" …)
        # ==================================================================
        for tok in tokens:
            if tok.lower_ in _AUXILIARIES:
                errors.append(
                    f"[Rule 7] Avoid auxiliary verbs (found '{tok.text}'). "
                    f"Use direct verbs: e.g. 'Process Payment' not 'System Will Process Payment'"
                )

        # ── Conjunction check ─────────────────────────────────────────────
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

        # ── Pronoun rejection ─────────────────────────────────────────────
        for tok in tokens:
            if tok.pos_ == "PRON":
                errors.append(f"Use-case names must not contain pronouns (found '{tok.text}')")

        # ── Token sanity ──────────────────────────────────────────────────
        for tok in tokens:
            if tok.pos_ in {"SYM", "X"}:
                errors.append(f"Invalid token '{tok.text}'")

        # ── Final verdict ─────────────────────────────────────────────────
        if errors:
            combined = "; ".join(errors)
            return False, combined, warnings

        return True, "", warnings  # ✔ OK


    # ================================================================== #
    #  3.  PRIMARY ACTOR DETECTION
    # ================================================================== #
    @staticmethod
    def isPrimaryActor(name: str) -> tuple[bool, str]:
        """
        Decide whether *name* looks like a 'primary' actor (= human / external role).

        Returns
        -------
        (True,  "person")   → human / role — should be Primary Actor (stickman)
        (False, "artifact") → physical / software artefact — Secondary Actor (box)
        (False, "other")    → cannot be determined reliably
        """
        lemmatizer = getLemmatizer()
        nlp = TextVerificationTools._nlp

        doc = nlp(name)
        tokens = [t for t in doc if not t.is_space and t.is_alpha]
        if not tokens:
            return False, "other"

        # Lemmatised head word (last content word)
        head_raw = tokens[-1].text.lower()
        head = lemmatizer.lemmatize(head_raw, pos="n")

        # ── Layer 1: Human-role suffixes ──────────────────────────────────────
        # Words ending in these suffixes are almost always human roles
        HUMAN_SUFFIXES = (
            "er", "or", "ist", "ian", "ant", "ent", "ee",
            "man", "woman", "person", "staff", "crew",
        )
        # But exclude hardware/software false positives for -or/-er
        SUFFIX_EXCEPTIONS = {
            "sensor", "actuator", "processor", "reactor", "inductor",
            "resistor", "rotor", "motor", "transistor", "connector",
            "filter", "router", "server", "layer", "buffer", "timer",
            "adapter", "encoder", "decoder", "receiver", "transmitter",
            "computer", "container", "controller",  # controller dealt with below
        }
        if head not in SUFFIX_EXCEPTIONS:
            for suf in HUMAN_SUFFIXES:
                if head.endswith(suf) and len(head) > len(suf) + 1:
                    # Extra guard: not an obvious artefact word
                    return True, "person"

        # ── Layer 2: Explicit human role keywords ─────────────────────────────
        CLEAR_HUMAN = {
            # Generic roles
            "user", "admin", "administrator", "manager", "supervisor",
            "director", "coordinator", "officer", "agent", "advisor",
            "analyst", "engineer", "technician", "mechanic", "specialist",
            "consultant", "auditor", "inspector", "reviewer", "examiner",
            "instructor", "trainer", "teacher", "student", "learner",
            "researcher", "scientist", "developer", "designer", "architect",
            # Domain-specific human roles
            "pilot", "driver", "navigator", "dispatcher", "commander",
            "operator", "controller",  # treated as human when used alone
            "attendant", "assistant", "clerk", "receptionist", "secretary",
            "guard", "officer", "authority", "regulator", "auditor",
            "customer", "client", "passenger", "patient", "citizen",
            "buyer", "seller", "vendor", "supplier", "partner", "member",
            "stakeholder", "owner", "shareholder", "investor",
            "viewer", "visitor", "guest", "subscriber",
            # Medical / safety
            "doctor", "nurse", "paramedic", "caregiver", "therapist",
            "pharmacist", "surgeon", "radiologist",
        }
        if head in CLEAR_HUMAN:
            return True, "person"

        # ── Layer 3: Explicit artefact keywords ───────────────────────────────
        CLEAR_ARTIFACT = {
            # Software/systems
            "system", "subsystem", "application", "app", "software",
            "platform", "framework", "module", "component", "service",
            "interface", "api", "database", "server", "client",
            "network", "protocol", "algorithm", "tool", "utility",
            # Hardware/physical
            "device", "hardware", "sensor", "actuator", "motor",
            "machine", "robot", "drone", "vehicle", "aircraft", "satellite",
            "equipment", "apparatus", "instrument", "terminal",
            "router", "switch", "node", "gateway", "antenna",
            # Data
            "data", "log", "record", "file", "cache",
            "repository", "storage", "backup",
            # Infra
            "infrastructure", "cloud", "cluster", "container", "pod",
        }
        # Re-add controller/processor explicitly as artifact only when head IS controller
        CLEAR_ARTIFACT_EXACT = {
            "processor", "router", "switch", "node", "gateway", "antenna",
            "sensor", "actuator", "motor", "robot", "drone", "satellite",
        }
        if head in CLEAR_ARTIFACT or head in CLEAR_ARTIFACT_EXACT:
            return False, "artifact"

        # ── Layer 4: WordNet — vote across all synsets ────────────────────────
        person_root   = wordnet.synset("person.n.01")
        artifact_root = wordnet.synset("artifact.n.01")

        synsets = wordnet.synsets(head, pos=wordnet.NOUN)
        person_votes   = 0
        artifact_votes = 0

        PERSON_LEXNAMES   = {"noun.person", "noun.group"}
        ARTIFACT_LEXNAMES = {"noun.artifact", "noun.object", "noun.possession",
                              "noun.communication", "noun.cognition"}

        for syn in synsets:
            lx = syn.lexname()
            if lx in PERSON_LEXNAMES:
                person_votes   += 2          # strong signal
            elif lx in ARTIFACT_LEXNAMES:
                artifact_votes += 1
            for path in syn.hypernym_paths():
                if person_root in path:
                    person_votes   += 1
                if artifact_root in path:
                    artifact_votes += 1

        if person_votes > artifact_votes and person_votes > 0:
            return True, "person"
        if artifact_votes > person_votes and artifact_votes > 0:
            return False, "artifact"

        # ── Layer 5: spaCy NER on the full original name ──────────────────────
        for ent in doc.ents:
            if ent.label_ in {"PERSON", "ORG"}:
                return True, "person"
            if ent.label_ in {"PRODUCT", "FAC", "LOC"}:
                return False, "artifact"

        # ── Layer 6: spaCy token morphology on the full name ─────────────────
        # If any token is tagged as PROPN it could be an org/system name
        prop_count  = sum(1 for t in tokens if t.pos_ == "PROPN")
        noun_count  = sum(1 for t in tokens if t.pos_ == "NOUN")
        if noun_count > 0 and prop_count == 0:
            # Plain common nouns with no WordNet signal — lean "other"
            pass

        return False, "other"



    # ------------------------------------------------------------------ #
    #  Utility methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def split_words(text):
        words_out = []
        for word in text.split():
            parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+', word)
            if parts:
                words_out.extend(parts)
            else:
                words_out.append(word)
        return words_out

    @staticmethod
    def toPascalCase(text):
        words_list = TextVerificationTools.split_words(text)
        return ''.join(w if w.isupper() else w.capitalize() for w in words_list)

    @staticmethod
    def toTitleCase(text):
        words_list = TextVerificationTools.split_words(text)
        return ' '.join(w if w.isupper() else w.capitalize() for w in words_list)

    @staticmethod
    @lru_cache(maxsize=512)
    def toTitleCaseSmart(text):
        SMALL_WORDS = {
            "a", "an", "the",          # articles
            "and", "but", "or", "nor",  # conjunctions
            "in", "on", "at", "to", "by", "of", "for", "from",
            "with", "as", "into", "via",  # prepositions
        }
        words_list = TextVerificationTools.split_words(text)
        nlp = TextVerificationTools._nlp
        doc = nlp(' '.join(words_list))

        result = []
        for i, token in enumerate(doc):
            if i > 0 and (token.pos_ == "ADP" or token.text.lower() in SMALL_WORDS):
                result.append(token.text.lower())
            else:
                result.append(token.text if token.text.isupper() else token.text.capitalize())
        return ' '.join(result)

    @staticmethod
    def isTruePreposition(word, sentence):
        nlp = TextVerificationTools._nlp
        doc = nlp(sentence)
        for token in doc:
            if token.text.lower() == word.lower():
                if token.dep_ == "prep" and token.head.pos_ != "VERB":
                    return True
                elif token.dep_ in {"mark", "advmod", "complm"}:
                    return False
        return False

    @staticmethod
    def phraseSimilarity(phrase1, phrase2):
        """Return cosine similarity [0, 1] between two short phrases.

        Uses ``all-MiniLM-L6-v2`` sentence embeddings — designed for
        symmetric semantic similarity, unlike the old CrossEncoder which
        was a passage-retrieval model and gave nonsensical scores for
        short actor / use-case name pairs.
        """
        model = getSimilarityEncoder()
        emb = model.encode([phrase1, phrase2], convert_to_tensor=False)
        # Cosine similarity via dot product on unit-normalised vectors
        import numpy as np
        a = emb[0] / (np.linalg.norm(emb[0]) + 1e-10)
        b = emb[1] / (np.linalg.norm(emb[1]) + 1e-10)
        return float(np.dot(a, b))
