import re
import spacy
import nltk
from nltk.corpus import words
from nltk.stem import WordNetLemmatizer
from typing import List, Tuple

# -------------------------------------------------
# Load NLP tools
# -------------------------------------------------
nlp = spacy.load("en_core_web_trf", disable=["ner"])
lemmatizer = WordNetLemmatizer()

LOWER_POS = {"ADP", "DET", "CCONJ", "SCONJ", "PART"}

# -------------------------------------------------
# Load English word list
# -------------------------------------------------
def load_nltk_words() -> set:
    try:
        return set(words.words())
    except LookupError:
        nltk.download("words", quiet=True)
        return set(words.words())

WORD_LIST = load_nltk_words()

def is_valid_english_word(word: str) -> bool:
    return word.lower() in WORD_LIST

# -------------------------------------------------
# Input validation
# -------------------------------------------------
VALID_TEXT_RE = re.compile(r"^[A-Za-z ]+$")

def is_valid_text(text: str) -> bool:
    return bool(VALID_TEXT_RE.fullmatch(text))

from nltk.corpus import wordnet as wn

def can_be_verb(word: str) -> bool:
    return bool(wn.synsets(word, pos=wn.VERB))

# -------------------------------------------------
# Helper: split identifiers / text into words
# -------------------------------------------------
IDENTIFIER_SPLIT_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z]+|[a-z]+|[A-Z]+$"
)

def split_identifier(text: str) -> List[str]:
    return IDENTIFIER_SPLIT_RE.findall(text)

# -------------------------------------------------
# Helper: validate a content word
# -------------------------------------------------
def validate_content_word(word: str, invalid_words: List[str]) -> str:
    """
    Capitalizes the word and records it if invalid.
    """
    candidate = word.capitalize()
    if not is_valid_english_word(candidate):
        invalid_words.append(word)
    return candidate

# -------------------------------------------------
# Grammar-aware Title Case
# -------------------------------------------------
# NOTE: This function must ALWAYS return Tuple[bool, List[str]]
# Do not return strings for error messages.

def smart_title_case(text: str) -> Tuple[str, List[str]]:
    doc_orig = nlp(text)
    doc_lower = nlp(text.lower())

    orig_tokens = [t for t in doc_orig if not t.is_space]
    low_tokens  = [t for t in doc_lower if not t.is_space]

    output = []
    invalid_words: List[str] = []

    for i, (tok_orig, tok_lower) in enumerate(zip(orig_tokens, low_tokens)):
        word = tok_orig.text

        # Acronyms
        if word.isupper():
            cased = word

        # Function words
        elif tok_lower.pos_ in LOWER_POS and i != 0:
            cased = word.lower()

        # Content words
        else:
            cased = validate_content_word(word, invalid_words)

        output.append(cased)

    return " ".join(output), invalid_words

# -------------------------------------------------
# PascalCase conversion
# -------------------------------------------------
def pascal_case(text: str) -> Tuple[str, List[str]]:
    parts = split_identifier(text)

    output = []
    invalid_words: List[str] = []

    for part in parts:
        # Acronyms
        if part.isupper():
            output.append(part)
        else:
            output.append(validate_content_word(part, invalid_words))

    return "".join(output), invalid_words

# -------------------------------------------------
# Dispatcher
# -------------------------------------------------
def process_text(text: str) -> Tuple[str, str, List[str]]:
    """
    Routes text to Title Case or PascalCase based on spaces.
    Returns:
      mode, transformed_text, invalid_words
    """
    if " " in text:
        result, invalid = smart_title_case(text)
        return "Title Case", result, invalid
    else:
        result, invalid = pascal_case(text)
        return "PascalCase", result, invalid
    
# def validate_use_case_title(
#     title: str,
#     element: str
# ) -> Tuple[bool, List[str]]:
#     """
#     Validate a SysML/UML use-case title.

#     Rules enforced:
#     ▸ starts with an imperative/base verb
#     ▸ ends with a noun (common or proper)
#     ▸ must not be named exactly as actor/system
#     ▸ may operate on a domain noun identical to actor name
#     ▸ no pronouns
#     ▸ adjectives must precede nouns
#     ▸ supports phrasal verbs
#     ▸ uses 'Please' normalization to disambiguate verbs
#     """

#     title = title.strip()
#     element = element.strip()

#     if not title:
#         return False, "use-case title must not be empty"

#     title_lc = title.lower()
#     element_lc = element.lower()

#     # -------------------------------------------------
#     # 1) Identity collision check (exact match only)
#     # -------------------------------------------------
#     if title_lc == element_lc:
#         return False, (
#             f"use-case name must not be identical to actor/system name ('{element}')"
#         )

#     if title_lc in {
#         element_lc + "s",
#         element_lc + "es",
#         element_lc + "ing",
#         element_lc + "ed",
#     }:
#         return False, (
#             f"use-case name must not be a grammatical variant of actor/system name ('{element}')"
#         )

#     # -------------------------------------------------
#     # 2) NLP parse with imperative normalization
#     # -------------------------------------------------
#     normalized = f"Please {title}"
#     doc = nlp(normalized)

#     # Drop "Please" token after parsing
#     tokens = [t for t in doc if not t.is_space and t.text.lower() != "please"]

#     # -------------------------------------------------
#     # 3) Single-word case
#     # -------------------------------------------------
#     if len(tokens) == 1:
#         return False, (
#             "use-case titles must be verb–object phrases "
#             "(e.g. 'Authenticate User', 'Submit Order')"
#         )

#     # -------------------------------------------------
#     # 4) Imperative verb enforcement
#     # -------------------------------------------------
#     root = next((t for t in doc if t.dep_ == "ROOT"), None)
#     first = tokens[0]

#     if not root or root.pos_ != "VERB":
#         return False, "use-case must contain a verbal root"

#     # Imperative heuristic: no explicit subject
#     if any(c.dep_ == "nsubj" for c in root.children):
#         return False, "use-case must be imperative but not declarative (explicit subject detected)"

#     if first.i != root.i:
#         return False, (
#             f"use-case should begin with an imperative/base verb "
#             f"(starts with '{first.text}')"
#         )

#     # -------------------------------------------------
#     # 5) Phrasal verb support (verb + particle)
#     # -------------------------------------------------
#     particles = [c for c in root.children if c.dep_ == "prt"]

#     # -------------------------------------------------
#     # 6) Final token must be a noun
#     # -------------------------------------------------
#     warnings: List[str] = []

#     last = tokens[-1]

#     # if last.pos_ not in {"NOUN", "PROPN"}:
#     if last.pos_ not in {"NOUN"}:
#         return False, [f"use-case should end with a noun (ends with '{last.text}')"]

#     if last.pos_ == "PROPN":
#         warnings.append(
#             f"warning: use-case ends with a proper noun ('{last.text}'); "
#             "consider using a generic domain concept instead"
#         )

#     # -------------------------------------------------
#     # 7) Pronoun rejection
#     # -------------------------------------------------
#     for tok in tokens:
#         if tok.pos_ == "PRON":
#             return False, (
#                 f"use-case titles must not contain pronouns "
#                 f"(found '{tok.text}')"
#             )

#     # -------------------------------------------------
#     # 8) Proper Noun rejection
#     # -------------------------------------------------
#     for tok in tokens:
#         if tok.pos_ == "PROPN":
#             return False, (
#                 f"use-case titles must not contain proper nouns "
#                 f"(found '{tok.text}')"
#             )

#     # -------------------------------------------------
#     # 9) Adjective placement
#     # -------------------------------------------------
#     for i, tok in enumerate(tokens[:-1]):
#         if tok.pos_ == "ADJ":
#             nxt = tokens[i + 1]
#             if nxt.pos_ not in {"NOUN", "PROPN"}:
#                 return False, (
#                     f"adjective '{tok.text}' must be followed by a noun"
#                 )

#     # -------------------------------------------------
#     # 10) Token sanity + dictionary fallback
#     # -------------------------------------------------
#     for tok in tokens:
#         if tok.pos_ in {"SYM", "X"}:
#             return False, f"invalid token '{tok.text}'"

#         if tok.is_alpha and tok.pos_ not in {"PROPN"}:
#             if not is_valid_english_word(tok.text):
#                 return False, (
#                     f"unknown or invalid English word '{tok.text}'"
#                 )

#     return True, ""

def validate_use_case_title(
    title: str,
    element: str
) -> Tuple[bool, List[str]]:
    """
    Validate a SysML/UML use-case title.
    """

    title = title.strip()
    element = element.strip()

    if not title:
        return False, ["use-case title must not be empty"]

    title_lc = title.lower()
    element_lc = element.lower()

    # -------------------------------------------------
    # 1) Identity collision check (exact match only)
    # -------------------------------------------------
    if title_lc == element_lc:
        return False, [
            f"use-case name must not be identical to actor/system name ('{element}')"
        ]

    if title_lc in {
        element_lc + "s",
        element_lc + "es",
        element_lc + "ing",
        element_lc + "ed",
    }:
        return False, [
            f"use-case name must not be a grammatical variant of actor/system name ('{element}')"
        ]

    # -------------------------------------------------
    # 2) NLP parse with imperative normalization
    # -------------------------------------------------
    normalized = f"User shall {title}"
    doc = nlp(normalized)

    tokens = [t for t in doc if not t.is_space]

    # Remove scaffold tokens safely
    tokens = tokens[2:]   # Remove "User shall"

    # -------------------------------------------------
    # 3) Single-word case
    # -------------------------------------------------
    if len(tokens) == 1:
        return False, [
            "use-case titles must be verb–object phrases "
            "(e.g. 'Authenticate User', 'Submit Order')"
        ]

# -------------------------------------------------
# 4) Imperative verb enforcement (robust)
# -------------------------------------------------
    root = next((t for t in doc if t.dep_ == "ROOT"), None)

    if not root:
        return False, ["use-case must contain a verbal root"]

    first = tokens[0]

    has_object_candidate = any(t.pos_ == "NOUN" for t in tokens[1:])

    is_imperative = (
        first.pos_ == "VERB"
        or (
            first.pos_ == "NOUN"
            and can_be_verb(first.text.lower())
            and has_object_candidate
        )
    )

    if not is_imperative:
        return False, [
            f"use-case must start with an imperative verb (found '{first.text}')"
        ]
    
    # 2) Reject declarative sentences
    if any(c.dep_ == "nsubj" for c in root.children):
        return False, [
            "use-case must be imperative, not declarative (explicit subject detected)"
        ]

    # 3) Must act on *some* domain concept (not necessarily dobj)
    has_complement = any(
        t.pos_ == "NOUN" and t.dep_ not in {"nsubj", "det"}
        for t in tokens[1:]
    )

    if not has_complement:
        return False, [
            "use-case must act on a domain object"
        ]

    # -------------------------------------------------
    # 5) Final token must be a noun
    # -------------------------------------------------
    errors: List[str] = []
    warnings: List[str] = []


    last = tokens[-1]

    if last.pos_ != "NOUN":
        return False, [
            f"use-case should end with a common noun (ends with '{last.text}')"
        ]

    if last.pos_ == "PROPN":
        warnings.append(
            f"use-case ends with a proper noun ('{last.text}'); "
            "consider using a generic domain concept instead"
        )

    # -------------------------------------------------
    # 6) Pronoun rejection
    # -------------------------------------------------
    for tok in tokens:
        if tok.pos_ == "PRON":
            return False, [
                f"use-case titles must not contain pronouns (found '{tok.text}')"
            ]

    # -------------------------------------------------
    # 7) Proper noun rejection
    # -------------------------------------------------
    for tok in tokens[:-1]:
        if tok.pos_ == "PROPN":
            return False, [
                f"use-case titles must not contain proper nouns (found '{tok.text}')"
            ]

    # -------------------------------------------------
    # 8) Adjective placement
    # -------------------------------------------------
    for i, tok in enumerate(tokens[:-1]):
        if tok.pos_ == "ADJ":
            nxt = tokens[i + 1]
            if nxt.pos_ not in {"NOUN", "PROPN"}:
                return False, [
                    f"adjective '{tok.text}' must be followed by a noun"
                ]

    # -------------------------------------------------
    # 9) Token sanity + dictionary fallback
    # -------------------------------------------------
    for tok in tokens:
        if tok.pos_ in {"SYM", "X"}:
            return False, [f"invalid token '{tok.text}'"]

        ACRONYM_RE = re.compile(r"^[A-Z]{2,}S?$")

        if tok.pos_ == "VERB":
            if not is_valid_english_word(tok.lemma_):
                return False, [
                    f"unknown or invalid English verb '{tok.text.capitalize()}'"
                ]

    return True, warnings

def isMeaningfulCommonSingularNounPhrase(name: str) -> Tuple[bool, List[str]]:
    """
    Validate a noun phrase that must end with a COMMON SINGULAR NOUN.

    Accuracy-first implementation using spaCy + NLTK.
    Uses 'the <NAME> role' normalization to disambiguate noun/verb ambiguity.
    """
    
    errors: List[str] = []
    warnings: List[str] = []

    name = name.strip()
    if not name:
        return False, ["System/Actor name must not be empty"]

    # ── 0) Normalize to force noun-phrase context ──────────────────────────
    normalized = f"the {name} role"

    doc_orig = nlp(normalized)
    doc_low  = nlp(normalized.lower())

    # Remove spaces
    orig_tokens = [t for t in doc_orig if not t.is_space]
    low_tokens  = [t for t in doc_low  if not t.is_space]

    # Must be at least: "the" + <name> + "role"
    if len(orig_tokens) < 3:
        return False, ["System/Actor name must contain at least one word"]

    # Strip scaffolding by POSITION
    tokens = list(zip(orig_tokens[1:-1], low_tokens[1:-1]))

    if not tokens:
        return False, ["System/Actor name must contain at least one word"]

    # ── 1) Pronoun & indefinite rejection ──────────────────────────────────
    INDEFINITE = {
        "anyone", "anybody", "someone", "somebody",
        "everyone", "everybody", "nobody", "none"
    }

    for tok_orig, tok_low in tokens:
        if tok_low.lower_ in INDEFINITE:
            errors.append(
                f"System/Actor name must not contain indefinite pronouns ('{tok_orig.text}')"
            )

        if tok_low.pos_ == "PRON":
            errors.append(
                f"System/Actor name must not contain pronouns ('{tok_orig.text}')"
            )

        if tok_low.pos_ == "PROPN":
            errors.append(
                f"System/Actor name must not contain proper nouns ('{tok_orig.text}')"
            )



    # ── 2) Noun-phrase enforcement (no verbs) ──────────────────────────────
    for tok_orig, tok_low in tokens:

        # Allow compound nouns even if spaCy is unsure
        if tok_orig.dep_ == "compound" and tok_orig.head.pos_ == "NOUN":
            continue

        # Lemma-based safeguard against verb/noun ambiguity
        noun_lemma = lemmatizer.lemmatize(tok_low.text.lower(), "n")

        if tok_low.pos_ == "VERB" and noun_lemma != tok_low.text.lower():
            errors.append(
                f"System/Actor name must be a noun phrase, not an action (found verb '{tok_orig.text}')"
            )


    # ── 3) Head noun checks (last token) ───────────────────────────────────
    head_orig, head_low = tokens[-1]

    # Must be a common noun
    if head_low.pos_ != "NOUN":
        errors.append(
            f"System/Actor name must end with a common noun (ends with '{head_orig.text}')"
        )

    # Mass-noun exceptions
    MASS_NOUNS = {
        "data", "information", "equipment", "software", "hardware",
        "staff", "personnel", "management"
    }

    # Reject plural head nouns
    if head_low.tag_ in {"NNS", "NNPS"} and head_low.text.lower() not in MASS_NOUNS:
        errors.append(
            f"System/Actor name must end with a singular noun (found plural '{head_orig.text}')"
        )

    # Lemma-based plural safeguard
    lemma = lemmatizer.lemmatize(head_low.text.lower(), "n")
    if (
        head_low.text.lower().endswith("s")
        and head_low.text.lower() != lemma
        and head_low.text.lower() not in MASS_NOUNS
    ):
        errors.append(
            f"System/Actor name must end with a singular noun (found plural '{head_orig.text}')"
        )


    # ── 4) Adjective placement ─────────────────────────────────────────────
    for i, (tok_orig, tok_low) in enumerate(tokens[:-1]):
        _, nxt_low = tokens[i + 1]
        if tok_low.pos_ == "ADJ" and nxt_low.pos_ not in {"NOUN", "PROPN"}:
            errors.append(
                f"adjective '{tok_orig.text}' must be followed by a noun"
            )


    # ── 5) POS whitelist ───────────────────────────────────────────────────
    # ALLOWED_POS = {"NOUN", "ADJ", "ADP", "PART", "PROPN"}
    ALLOWED_POS = {"NOUN", "ADJ", "ADP", "PART"}
    bad = [
        tok_orig.text
        for tok_orig, tok_low in tokens
        if tok_low.pos_ not in ALLOWED_POS
    ]
    for w in bad:
        errors.append(f"'{w}' is not allowed in a noun phrase")


    # ── 6) STYLE WARNING: prefer compound noun over prepositional role ─────
    ROLE_NOUNS = {
        "administrator", "operator", "controller", "manager",
        "owner", "maintainer", "supervisor", "coordinator",
        "provider", "consumer", "producer"
    }
    PREPOSITIONS = {"of", "for", "with"}

    if len(tokens) == 3:
        (t1o, t1l), (t2o, t2l), (t3o, t3l) = tokens
        if (
            t1l.pos_ == "NOUN"
            and t1l.lemma_.lower() in ROLE_NOUNS
            and t2l.pos_ == "ADP"
            and t2l.lower_ in PREPOSITIONS
            and t3l.pos_ == "NOUN"
        ):
            compound = f"{t3o.text.title()} {t1o.text.title()}"
            warnings.append(
                f"prefer compound noun '{compound}' over prepositional form '{name}'"
            )
    
    assert isinstance(warnings, list)
    
    if errors:
        return False, errors + warnings

    return True, warnings


# -------------------------------------------------
# Test inputs
# -------------------------------------------------
TEST_CASES = [
    "GenerateAPICOode",
    "RegisterAPIKey",
    "HeyUserBuyAPIKey",
    "Generate Electricity from Solar Panel",
    "GenerateELectricityFromSolarPanel",
    "Drive vehicle",
]

# -------------------------------------------------
# Run tests
# -------------------------------------------------
for text in TEST_CASES:
    print(f"\nInput: {text}")

    if not is_valid_text(text.replace(" ", "")):
        print("❌ Invalid characters detected")
        continue

    mode, result, invalid_words = process_text(text)

    if invalid_words:
        print("❌ NOT A VALID INPUT")
        print("Invalid words:", sorted(set(invalid_words)))
    else:
        print("✅ VALID INPUT")

    print(f"{mode} :", result)
