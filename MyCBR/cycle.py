from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple

from Parser import ParserOperations
from cbr_merge import merge_user_with_case
from verification.element_verification import element_verification


def _clean_list(values: List[str]) -> List[str]:
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


def _normalize_relationships(relationships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for rel in relationships or []:
        if not isinstance(rel, dict):
            continue
        normalized.append(
            {
                "relationship_type": str(rel.get("relationship_type") or rel.get("Value") or "").lower(),
                "source_name": str(rel.get("source_name") or rel.get("Source Name") or "").strip(),
                "source_type": str(rel.get("source_type") or rel.get("Source Type") or "").lower(),
                "target_name": str(rel.get("target_name") or rel.get("Target Name") or "").strip(),
                "target_type": str(rel.get("target_type") or rel.get("Target Type") or "").lower(),
                "extension": str(rel.get("extension") or rel.get("Extension") or "").strip(),
            }
        )
    return normalized


def normalize_case_payload(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    primary = _clean_list(case_payload.get("primary_actors") or [])
    secondary = [name for name in _clean_list(case_payload.get("secondary_actors") or []) if name not in primary]
    use_cases = _clean_list(case_payload.get("use_cases") or [])
    domains = _clean_list(case_payload.get("domains") or [])
    relationships = _normalize_relationships(case_payload.get("relationships") or [])

    prim_fixed, sec_fixed, ucs_fixed, rels_fixed = ParserOperations._validate_and_fix_ucd(
        primary,
        secondary,
        use_cases,
        [
            {
                "Relation Code": None,
                "Value": rel.get("relationship_type"),
                "Source Name": rel.get("source_name"),
                "Source Type": rel.get("source_type"),
                "Target Name": rel.get("target_name"),
                "Target Type": rel.get("target_type"),
                "Extension": rel.get("extension") or "",
            }
            for rel in relationships
        ],
    )

    return {
        "title": case_payload.get("title") or case_payload.get("system_name") or "",
        "description": str(case_payload.get("description") or "").strip(),
        "system_name": str(case_payload.get("system_name") or "").strip(),
        "domains": domains,
        "primary_actors": prim_fixed,
        "secondary_actors": sec_fixed,
        "use_cases": ucs_fixed,
        "relationships": [
            {
                "relationship_type": rel.get("Value"),
                "source_name": rel.get("Source Name"),
                "source_type": rel.get("Source Type"),
                "target_name": rel.get("Target Name"),
                "target_type": rel.get("Target Type"),
                "extension": rel.get("Extension") or "",
            }
            for rel in rels_fixed
        ],
    }


def _collect_action_findings(items: List[Tuple[str, Dict[str, Any]]], prefix: str) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for name, meta in items:
        action = meta.get("Action") or "Well Written"
        severity = "warning" if action == "Warning!" else ("error" if action == "Attention Required!" else "ok")
        for comment in meta.get("Comments", []):
            findings.append(
                {
                    "scope": prefix,
                    "name": name,
                    "severity": severity,
                    "message": comment,
                }
            )
    return findings


def validate_case_payload(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_case_payload(case_payload)
    findings: List[Dict[str, str]] = []

    system_name = normalized.get("system_name") or ""
    system_comments, system_action = element_verification.validateSystem(system_name)
    if system_comments:
        severity = "warning" if system_action == "Warning!" else "error"
        findings.extend(
            {
                "scope": "system",
                "name": system_name or "System",
                "severity": severity,
                "message": comment,
            }
            for comment in system_comments
        )

    actor_rows: List[Tuple[str, Dict[str, Any]]] = []
    for actor_name in normalized.get("primary_actors", []):
        actor_rows.append((actor_name, {"Element Type": "Primary Actor", "Comments": [], "Action": "Well Written"}))
    for actor_name in normalized.get("secondary_actors", []):
        actor_rows.append((actor_name, {"Element Type": "Secondary Actor", "Comments": [], "Action": "Well Written"}))

    if actor_rows:
        element_verification.validateActors(actor_rows)
        findings.extend(_collect_action_findings(actor_rows, "actor-batch"))
        for actor_name, meta in actor_rows:
            comments, action = element_verification.validateActor(actor_name, meta["Element Type"])
            if comments:
                severity = "warning" if action == "Warning!" else "error"
                findings.extend(
                    {
                        "scope": meta["Element Type"].lower(),
                        "name": actor_name,
                        "severity": severity,
                        "message": comment,
                    }
                    for comment in comments
                )

    use_case_rows: List[Tuple[str, Dict[str, Any]]] = [
        (uc_name, {"Element Type": "Use Case", "Comments": [], "Action": "Well Written"})
        for uc_name in normalized.get("use_cases", [])
    ]
    if use_case_rows:
        element_verification.validateUsecases(use_case_rows)
        findings.extend(_collect_action_findings(use_case_rows, "usecase-batch"))
        for uc_name, _meta in use_case_rows:
            comments, action = element_verification.validateUsecase(uc_name, system_name)
            if comments:
                severity = "warning" if action == "Warning!" else "error"
                findings.extend(
                    {
                        "scope": "usecase",
                        "name": uc_name,
                        "severity": severity,
                        "message": comment,
                    }
                    for comment in comments
                )

    deduped: List[Dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        key = (
            finding.get("scope", ""),
            finding.get("name", ""),
            finding.get("message", ""),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(finding)

    summary = {
        "errors": sum(1 for finding in deduped if finding["severity"] == "error"),
        "warnings": sum(1 for finding in deduped if finding["severity"] == "warning"),
        "total": len(deduped),
        "relationship_count": len(normalized.get("relationships") or []),
    }

    return {
        "normalized": normalized,
        "findings": deduped,
        "summary": summary,
    }


def _candidate_to_kb_payload(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    actors = [(name, "Primary") for name in case_payload.get("primary_actors", [])]
    actors.extend((name, "Secondary") for name in case_payload.get("secondary_actors", []))
    return {
        "system_name": case_payload.get("system_name") or "",
        "actors": actors,
        "use_cases": list(case_payload.get("use_cases") or []),
        "relationships": deepcopy(case_payload.get("relationships") or []),
    }


def reuse_case_payload(query_payload: Dict[str, Any], candidate_payload: Dict[str, Any]) -> Dict[str, Any]:
    user_payload = normalize_case_payload(query_payload)
    kb_payload = _candidate_to_kb_payload(candidate_payload)
    merged = merge_user_with_case(user_payload, kb_payload)
    revised = normalize_case_payload(
        {
            "title": user_payload.get("title") or user_payload.get("system_name"),
            "description": user_payload.get("description"),
            "system_name": user_payload.get("system_name") or candidate_payload.get("system_name"),
            "domains": user_payload.get("domains") or candidate_payload.get("domains") or [],
            "primary_actors": merged.get("primary_actors") or [],
            "secondary_actors": merged.get("secondary_actors") or [],
            "use_cases": merged.get("use_cases") or [],
            "relationships": merged.get("relationships") or [],
        }
    )
    return revised
