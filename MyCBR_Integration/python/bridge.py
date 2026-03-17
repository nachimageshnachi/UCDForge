from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MyCBR.cycle import normalize_case_payload, reuse_case_payload, validate_case_payload
from MyCBR.project_export import build_project_bundle, write_project_bundle
from MyCBR.repository import (
    case_label,
    discover_mycbr_exe,
    load_all_cases,
    load_retained_cases,
    load_sql_cases,
    save_retained_case,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8099"


def _case_key(case_payload: Dict[str, Any]) -> str:
    value = str(case_payload.get("case_key") or "").strip()
    if value:
        return value
    source = str(case_payload.get("source") or "case").strip() or "case"
    raw_id = str(case_payload.get("case_id") or case_payload.get("title") or case_payload.get("system_name") or "local")
    token = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw_id).strip("_") or "local"
    return f"{source}-{token}"


def _string_list(values: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = str(value).strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _relationship_types(case_payload: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for rel in case_payload.get("relationships") or []:
        rel_type = str(rel.get("relationship_type") or rel.get("Value") or "").strip().lower()
        if rel_type:
            values.append(rel_type)
    return _string_list(values)


def service_case_payload(case_payload: Dict[str, Any], *, source: str | None = None) -> Dict[str, Any]:
    normalized = normalize_case_payload(case_payload)
    return {
        "case_key": _case_key(case_payload),
        "case_id": case_payload.get("case_id"),
        "source": source or case_payload.get("source") or "ad_hoc",
        "title": normalized.get("title") or normalized.get("system_name") or "",
        "description": normalized.get("description") or "",
        "system_name": normalized.get("system_name") or "",
        "domains": list(normalized.get("domains") or []),
        "primary_actors": list(normalized.get("primary_actors") or []),
        "secondary_actors": list(normalized.get("secondary_actors") or []),
        "use_cases": list(normalized.get("use_cases") or []),
        "relationship_types": _relationship_types(normalized),
    }


def _request(method: str, url: str, *, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    response = requests.request(method, url, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected response from service: {data!r}")
    return data


def service_health(base_url: str = DEFAULT_BASE_URL) -> Dict[str, Any]:
    return _request("GET", f"{base_url.rstrip('/')}/health")


def list_service_cases(base_url: str = DEFAULT_BASE_URL) -> Dict[str, Any]:
    return _request("GET", f"{base_url.rstrip('/')}/cases")


def reset_service(base_url: str = DEFAULT_BASE_URL) -> Dict[str, Any]:
    return _request("POST", f"{base_url.rstrip('/')}/cases/reset", payload={})


def sync_service_cases(base_url: str = DEFAULT_BASE_URL, cases: List[Dict[str, Any]] | None = None, *, replace: bool = True) -> Dict[str, Any]:
    source_cases = cases if cases is not None else load_all_cases()
    payload = {
        "replace": replace,
        "cases": [service_case_payload(case_payload) for case_payload in source_cases],
    }
    return _request("POST", f"{base_url.rstrip('/')}/cases/import", payload=payload)


def add_case_to_service(case_payload: Dict[str, Any], base_url: str = DEFAULT_BASE_URL, *, source: str | None = None) -> Dict[str, Any]:
    payload = {"case": service_case_payload(case_payload, source=source)}
    return _request("POST", f"{base_url.rstrip('/')}/cases/add", payload=payload)


def query_service(
    query_payload: Dict[str, Any],
    base_url: str = DEFAULT_BASE_URL,
    *,
    profile: str = "balanced",
    limit: int = 5,
    min_similarity: float = 0.0,
) -> Dict[str, Any]:
    payload = {
        "profile": profile,
        "k": int(limit),
        "min_similarity": float(min_similarity),
        "query": service_case_payload(query_payload, source="query"),
    }
    return _request("POST", f"{base_url.rstrip('/')}/query", payload=payload)


def retain_and_push(case_payload: Dict[str, Any], base_url: str = DEFAULT_BASE_URL) -> Dict[str, Any]:
    normalized = normalize_case_payload(case_payload)
    stored = save_retained_case(normalized)
    service_response = add_case_to_service(stored, base_url=base_url, source="retained")
    return {"stored": stored, "service": service_response}


__all__ = [
    "DEFAULT_BASE_URL",
    "add_case_to_service",
    "build_project_bundle",
    "case_label",
    "discover_mycbr_exe",
    "list_service_cases",
    "load_all_cases",
    "load_retained_cases",
    "load_sql_cases",
    "query_service",
    "reset_service",
    "retain_and_push",
    "reuse_case_payload",
    "service_health",
    "service_case_payload",
    "sync_service_cases",
    "validate_case_payload",
    "write_project_bundle",
]
