from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from cbr_merge import fetch_case_data
from connection import connection


PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
OUTPUT_DIR = PACKAGE_DIR / "output"
RETAINED_STORE = DATA_DIR / "retained_cases.json"


def ensure_workspace() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not RETAINED_STORE.exists():
        RETAINED_STORE.write_text("[]", encoding="utf-8")


def discover_mycbr_exe() -> str:
    candidates = [
        os.environ.get("MYCBR_EXE", "").strip(),
        r"C:\Users\mages\Downloads\win32.win32.x86_64\win32.win32.x86_64\mycbr\myCBR.exe",
        r"C:\Program Files\myCBR\myCBR.exe",
        r"C:\Program Files (x86)\myCBR\myCBR.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def _parse_domains(raw_value: Any) -> List[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    try:
        parsed = json.loads(raw_value or "[]")
        return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        return []


def _actors_by_type(actors: List[Any]) -> tuple[List[str], List[str]]:
    primary: List[str] = []
    secondary: List[str] = []
    for name, actor_type in actors or []:
        if str(actor_type).lower().startswith("primary"):
            primary.append(name)
        else:
            secondary.append(name)
    return primary, secondary


def _canonical_case_from_sources(base_row: Dict[str, Any], details: Dict[str, Any], source: str) -> Dict[str, Any]:
    primary, secondary = _actors_by_type(details.get("actors") or [])
    return {
        "case_key": f"{source}-{base_row.get('case_id')}",
        "case_id": base_row.get("case_id"),
        "source": source,
        "title": base_row.get("title") or details.get("system_name") or "",
        "description": base_row.get("description") or "",
        "system_name": details.get("system_name") or base_row.get("title") or "",
        "domains": _parse_domains(base_row.get("domain_json")),
        "primary_actors": primary,
        "secondary_actors": secondary,
        "use_cases": list(details.get("use_cases") or []),
        "relationships": list(details.get("relationships") or []),
        "created_at": base_row.get("created_at"),
    }


def load_sql_cases() -> List[Dict[str, Any]]:
    ensure_workspace()
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute(
            """
            SELECT c.case_id, c.title, c.description, c.domain_json, c.created_at
            FROM cases c
            ORDER BY c.case_id DESC
            """
        )
        rows = cursor.fetchall() or []

    cases: List[Dict[str, Any]] = []
    for row in rows:
        details = fetch_case_data(int(row["case_id"]))
        cases.append(_canonical_case_from_sources(row, details, "sql"))
    return cases


def load_retained_cases() -> List[Dict[str, Any]]:
    ensure_workspace()
    try:
        payload = json.loads(RETAINED_STORE.read_text(encoding="utf-8"))
    except Exception:
        payload = []

    cases: List[Dict[str, Any]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        cases.append(
            {
                "case_key": item.get("case_key") or f"retained-{item.get('case_id')}",
                "case_id": item.get("case_id"),
                "source": "retained",
                "title": item.get("title") or item.get("system_name") or "",
                "description": item.get("description") or "",
                "system_name": item.get("system_name") or "",
                "domains": list(item.get("domains") or []),
                "primary_actors": list(item.get("primary_actors") or []),
                "secondary_actors": list(item.get("secondary_actors") or []),
                "use_cases": list(item.get("use_cases") or []),
                "relationships": list(item.get("relationships") or []),
                "created_at": item.get("created_at"),
            }
        )
    return cases


def load_all_cases() -> List[Dict[str, Any]]:
    return load_sql_cases() + load_retained_cases()


def save_retained_case(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    ensure_workspace()
    current = load_retained_cases()
    next_id = max([int(item.get("case_id", 0) or 0) for item in current] + [0]) + 1

    stored = {
        "case_key": f"retained-{next_id}",
        "case_id": next_id,
        "source": "retained",
        "title": case_payload.get("title") or case_payload.get("system_name") or f"Retained Case {next_id}",
        "description": case_payload.get("description") or "",
        "system_name": case_payload.get("system_name") or "",
        "domains": list(case_payload.get("domains") or []),
        "primary_actors": list(case_payload.get("primary_actors") or []),
        "secondary_actors": list(case_payload.get("secondary_actors") or []),
        "use_cases": list(case_payload.get("use_cases") or []),
        "relationships": list(case_payload.get("relationships") or []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    persisted = [
        {
            "case_key": item.get("case_key"),
            "case_id": item.get("case_id"),
            "title": item.get("title"),
            "description": item.get("description"),
            "system_name": item.get("system_name"),
            "domains": item.get("domains") or [],
            "primary_actors": item.get("primary_actors") or [],
            "secondary_actors": item.get("secondary_actors") or [],
            "use_cases": item.get("use_cases") or [],
            "relationships": item.get("relationships") or [],
            "created_at": item.get("created_at"),
        }
        for item in current
    ]
    persisted.append(stored)
    RETAINED_STORE.write_text(json.dumps(persisted, indent=2), encoding="utf-8")
    return stored


def case_label(case_payload: Dict[str, Any]) -> str:
    case_id = case_payload.get("case_id")
    title = case_payload.get("title") or case_payload.get("system_name") or "Untitled"
    source = str(case_payload.get("source") or "case").upper()
    return f"{source} {case_id}: {title}"
