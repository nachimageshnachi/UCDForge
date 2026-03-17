from typing import List, Optional, Dict, Any

from connection import connection
from SpacyandFlair import validate_use_case_title


def fetch_use_cases(case_id: Optional[int] = None) -> List[str]:
    """
    Return a list of use case names from the database.
    If case_id is provided, results are filtered to that case.
    """
    query = "SELECT name FROM use_cases"
    params = ()
    if case_id is not None:
        query += " WHERE case_id = %s"
        params = (case_id,)

    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall() or []

    return [
        (row.get("name") or "").strip()
        for row in rows
        if (row.get("name") or "").strip()
    ]


def fetch_actors(case_id: Optional[int] = None) -> List[str]:
    """
    Return a list of actor names from the database.
    If case_id is provided, results are filtered to that case.
    """
    query = "SELECT actor_name FROM actors"
    params = ()
    if case_id is not None:
        query += " WHERE case_id = %s"
        params = (case_id,)

    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall() or []

    return [
        (row.get("actor_name") or "").strip()
        for row in rows
        if (row.get("actor_name") or "").strip()
    ]


def validate_use_cases_with_nlp(case_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Validate use-case names fetched from the DB using the Spacy/Flair rules.

    Returns a list of dicts:
      { "name": <use case>,
        "valid": <bool>,
        "messages": [list of issues] }
    """
    use_cases = fetch_use_cases(case_id)
    actors = fetch_actors(case_id)

    results: List[Dict[str, Any]] = []
    for uc in use_cases:
        messages: List[str] = []

        # Primary grammar/structure check (no specific element)
        ok, msg = validate_use_case_title(uc, "")
        if not ok:
            messages.extend(msg)

        # Collision check against actors (identical / variant)
        for actor in actors:
            coll_ok, coll_msg = validate_use_case_title(uc, actor)
            if not coll_ok:
                messages.extend(coll_msg)

        # de-duplicate messages while preserving order
        seen = set()
        deduped = []
        for m in messages:
            if m not in seen:
                deduped.append(m)
                seen.add(m)

        results.append({
            "name": uc,
            "valid": len(deduped) == 0,
            "messages": deduped
        })

    return results


def validate_use_case_name(name: str, actors: List[str]) -> Dict[str, Any]:
    """
    Validate a single use-case name against grammar rules and actor collisions.
    """
    messages: List[str] = []

    ok, msg = validate_use_case_title(name, "")
    if not ok:
        messages.extend(msg)

    for actor in actors:
        coll_ok, coll_msg = validate_use_case_title(name, actor)
        if not coll_ok:
            messages.extend(coll_msg)

    seen = set()
    deduped = []
    for m in messages:
        if m not in seen:
            deduped.append(m)
            seen.add(m)

    return {
        "name": name,
        "valid": len(deduped) == 0,
        "messages": deduped,
    }
