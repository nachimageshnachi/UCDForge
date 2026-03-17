import re
import json
from nltk.corpus import wordnet
from connection import connection


# ------------------ TEXT NORMALIZATION UTILITIES ------------------ #

class TextValidationTools:
    @staticmethod
    def split_words(text):
        words = []
        for word in text.split():
            parts = re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+', word)
            if parts:
                words.extend(parts)
            else:
                words.append(word)
        return words

    @staticmethod
    def to_pascal_case(text):
        words = TextValidationTools.split_words(text)
        return ''.join(w if w.isupper() else w.capitalize() for w in words)

    @staticmethod
    def to_title_case(text):
        words = TextValidationTools.split_words(text)
        return ' '.join(w if w.isupper() else w.capitalize() for w in words)

    @staticmethod
    def normalize(text):
        """ Normalize any string to Title Case for consistent comparison/display """
        if not text:
            return ""
        return TextValidationTools.to_title_case(text.strip())


# ------------------ SYNONYM HANDLING ------------------ #

def get_synonyms(word):
    syns = set()
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            syns.add(lemma.name().replace('_', ' '))
    return syns


def _fetch_db_synonyms(kind: str):
    """Return mapping canonical->set(synonyms) aggregated from synonym tables."""
    mapping = {}
    with connection.get_cursor() as cursor:
        if kind == 'actor':
            cursor.execute("SELECT actor_name, synonym FROM actor_synonyms")
            rows = cursor.fetchall()
            for r in rows:
                canon = TextValidationTools.normalize(r["actor_name"]) if isinstance(r, dict) else TextValidationTools.normalize(r[0])
                syn = TextValidationTools.normalize(r["synonym"]) if isinstance(r, dict) else TextValidationTools.normalize(r[1])
                if not canon or not syn:
                    continue
                mapping.setdefault(canon, set()).add(syn)
        elif kind == 'use_case':
            cursor.execute("SELECT use_case_name, synonym FROM use_case_synonyms")
            rows = cursor.fetchall()
            for r in rows:
                canon = TextValidationTools.normalize(r["use_case_name"]) if isinstance(r, dict) else TextValidationTools.normalize(r[0])
                syn = TextValidationTools.normalize(r["synonym"]) if isinstance(r, dict) else TextValidationTools.normalize(r[1])
                if not canon or not syn:
                    continue
                mapping.setdefault(canon, set()).add(syn)
        elif kind == 'system':
            cursor.execute("SELECT system_name, synonym FROM system_synonyms")
            rows = cursor.fetchall()
            for r in rows:
                canon = TextValidationTools.normalize(r["system_name"]) if isinstance(r, dict) else TextValidationTools.normalize(r[0])
                syn = TextValidationTools.normalize(r["synonym"]) if isinstance(r, dict) else TextValidationTools.normalize(r[1])
                if not canon or not syn:
                    continue
                mapping.setdefault(canon, set()).add(syn)
    return mapping


def expand_terms(terms, kind: str = 'actor'):
    """
    Build expanded dict using ONLY DB-backed synonyms. No WordNet fallback.
    The result shape matches previous callers: { normalized: { original, synonyms: [...] } }.
    """
    expanded = {}
    db_syns = _fetch_db_synonyms(kind)
    for term in terms:
        normalized = TextValidationTools.normalize(term)
        syns = db_syns.get(normalized, set())
        expanded[normalized] = {
            "original": term,
            "synonyms": list(sorted(set(TextValidationTools.normalize(s) for s in syns if s)))
        }
    return expanded


# ------------------ FETCH & EXPAND DB VALUES ------------------ #

def get_db_values():
    with connection.get_cursor() as cursor:
        cursor.execute("SELECT domain_json FROM cases WHERE domain_json IS NOT NULL")
        all_domains = []
        for row in cursor.fetchall():
            try:
                all_domains.extend(json.loads(row["domain_json"]))
            except Exception:
                continue
        domains = sorted(set(TextValidationTools.normalize(d) for d in all_domains))

        cursor.execute("SELECT DISTINCT actor_name FROM actors")
        actors_raw = [row["actor_name"] for row in cursor.fetchall() if row["actor_name"]]

        cursor.execute("SELECT DISTINCT name FROM use_cases")
        usecases_raw = [row["name"] for row in cursor.fetchall() if row["name"]]

    connection.close_connection()

    return {
        "domains": domains,
        "actors": expand_terms(actors_raw, kind='actor'),
        "use_cases": expand_terms(usecases_raw, kind='use_case')
    }


# ------------------ LOOKUP UTILITY ------------------ #

def reverse_lookup(expanded_dict, user_entry):
    normalized = TextValidationTools.normalize(user_entry)
    for readable, data in expanded_dict.items():
        if normalized in [readable] + [TextValidationTools.normalize(s) for s in data["synonyms"]]:
            return data["original"]
    return user_entry


# ------------------ CASE MATCHING ------------------ #

def match_case(user_input):
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM cases")
        all_cases = cursor.fetchall()

        ranked = []

        for case in all_cases:
            case_id = case["case_id"]
            domain_score = 0.0
            actor_score = 0.0
            use_case_score = 0.0

            # Domains
            try:
                db_domains = json.loads(case.get("domain_json") or "[]")
                db_domains = [TextValidationTools.normalize(d) for d in db_domains]
            except Exception:
                db_domains = []

            input_domains = [TextValidationTools.normalize(d) for d in user_input.get("domains", [])]
            if db_domains and input_domains:
                domain_score = len(set(db_domains) & set(input_domains)) / len(set(db_domains) | set(input_domains))

            # Actors
            cursor.execute("SELECT actor_name FROM actors WHERE case_id = %s", (case_id,))
            db_actors = [TextValidationTools.normalize(a["actor_name"]) for a in cursor.fetchall()]
            input_actors = [TextValidationTools.normalize(a) for a in user_input.get("actors", [])]
            if db_actors or input_actors:
                actor_score = len(set(db_actors) & set(input_actors)) / len(set(db_actors) | set(input_actors))

            # Use Cases
            cursor.execute("SELECT name FROM use_cases WHERE case_id = %s", (case_id,))
            db_use_cases = [TextValidationTools.normalize(u["name"]) for u in cursor.fetchall()]
            input_use_cases = [TextValidationTools.normalize(u) for u in user_input.get("use_cases", [])]
            if db_use_cases or input_use_cases:
                use_case_score = len(set(db_use_cases) & set(input_use_cases)) / len(set(db_use_cases) | set(input_use_cases))

            # Weighted total
            total_score = 0.3 * domain_score + 0.35 * actor_score + 0.35 * use_case_score

            ranked.append({
                "case_id": case_id,
                "title": case["title"],
                "domain_score": domain_score,
                "actor_score": actor_score,
                "use_case_score": use_case_score,
                "total_score": round(total_score, 3),
            })

        ranked.sort(key=lambda x: x["total_score"], reverse=True)
        return ranked[0] if ranked else None
