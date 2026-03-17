from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

st.set_page_config(page_title="MyCBR SDK Bridge", layout="wide")

from MyCBR_Integration.python.bridge import (
    DEFAULT_BASE_URL,
    case_label,
    discover_mycbr_exe,
    list_service_cases,
    load_all_cases,
    load_retained_cases,
    load_sql_cases,
    query_service,
    reset_service,
    retain_and_push,
    reuse_case_payload,
    service_health,
    sync_service_cases,
    validate_case_payload,
    write_project_bundle,
)


def _split_items(text: str) -> List[str]:
    items: List[str] = []
    seen: set[str] = set()
    for raw in str(text or "").replace(",", "\n").splitlines():
        item = raw.strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            items.append(item)
    return items


def _relationship_lines_to_dicts(text: str) -> List[Dict[str, Any]]:
    rels: List[Dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 5:
            continue
        rels.append(
            {
                "relationship_type": parts[0].lower(),
                "source_name": parts[1],
                "source_type": parts[2].lower(),
                "target_name": parts[3],
                "target_type": parts[4].lower(),
                "extension": parts[5] if len(parts) > 5 else "",
            }
        )
    return rels


def _relationship_dicts_to_text(relationships: List[Dict[str, Any]]) -> str:
    lines = []
    for rel in relationships or []:
        lines.append(
            " | ".join(
                [
                    str(rel.get("relationship_type") or ""),
                    str(rel.get("source_name") or ""),
                    str(rel.get("source_type") or ""),
                    str(rel.get("target_name") or ""),
                    str(rel.get("target_type") or ""),
                    str(rel.get("extension") or ""),
                ]
            )
        )
    return "\n".join(lines)


def _current_case_from_editor() -> Dict[str, Any]:
    return {
        "title": st.session_state.get("mycbr_bridge_title", "").strip(),
        "description": st.session_state.get("mycbr_bridge_description", "").strip(),
        "system_name": st.session_state.get("mycbr_bridge_system_name", "").strip(),
        "domains": _split_items(st.session_state.get("mycbr_bridge_domains", "")),
        "primary_actors": _split_items(st.session_state.get("mycbr_bridge_primary_actors", "")),
        "secondary_actors": _split_items(st.session_state.get("mycbr_bridge_secondary_actors", "")),
        "use_cases": _split_items(st.session_state.get("mycbr_bridge_use_cases", "")),
        "relationships": _relationship_lines_to_dicts(st.session_state.get("mycbr_bridge_relationships", "")),
    }


def _queue_case_into_editor(case_payload: Dict[str, Any]) -> None:
    st.session_state["_mycbr_bridge_pending_case"] = {
        "title": case_payload.get("title") or case_payload.get("system_name") or "",
        "description": case_payload.get("description") or "",
        "system_name": case_payload.get("system_name") or "",
        "domains": "\n".join(case_payload.get("domains") or []),
        "primary_actors": "\n".join(case_payload.get("primary_actors") or []),
        "secondary_actors": "\n".join(case_payload.get("secondary_actors") or []),
        "use_cases": "\n".join(case_payload.get("use_cases") or []),
        "relationships": _relationship_dicts_to_text(case_payload.get("relationships") or []),
    }


def _apply_pending_editor_case() -> None:
    pending = st.session_state.pop("_mycbr_bridge_pending_case", None)
    if not pending:
        return
    st.session_state["mycbr_bridge_title"] = pending.get("title", "")
    st.session_state["mycbr_bridge_description"] = pending.get("description", "")
    st.session_state["mycbr_bridge_system_name"] = pending.get("system_name", "")
    st.session_state["mycbr_bridge_domains"] = pending.get("domains", "")
    st.session_state["mycbr_bridge_primary_actors"] = pending.get("primary_actors", "")
    st.session_state["mycbr_bridge_secondary_actors"] = pending.get("secondary_actors", "")
    st.session_state["mycbr_bridge_use_cases"] = pending.get("use_cases", "")
    st.session_state["mycbr_bridge_relationships"] = pending.get("relationships", "")


def _find_case_by_key(case_key: str, cases: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for case_payload in cases:
        if case_payload.get("case_key") == case_key:
            return case_payload
    return None


def _findings_df(findings: List[Dict[str, str]]) -> pd.DataFrame:
    if not findings:
        return pd.DataFrame(columns=["Scope", "Name", "Severity", "Message"])
    return pd.DataFrame(
        [{"Scope": item.get("scope"), "Name": item.get("name"), "Severity": item.get("severity"), "Message": item.get("message")} for item in findings]
    )


def _results_df(results: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for item in results or []:
        rows.append(
            {
                "Similarity": item.get("similarity"),
                "Case Key": item.get("case_key"),
                "Source": item.get("source"),
                "Title": item.get("title") or item.get("system_name"),
                "System": item.get("system_name"),
                "Domains": ", ".join(item.get("domains") or []),
                "Use Cases": len(item.get("use_cases") or []),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    sql_cases = load_sql_cases()
    retained_cases = load_retained_cases()
    all_cases = sql_cases + retained_cases
    mycbr_exe = discover_mycbr_exe()

    for key in [
        "mycbr_bridge_title",
        "mycbr_bridge_description",
        "mycbr_bridge_system_name",
        "mycbr_bridge_domains",
        "mycbr_bridge_primary_actors",
        "mycbr_bridge_secondary_actors",
        "mycbr_bridge_use_cases",
        "mycbr_bridge_relationships",
    ]:
        st.session_state.setdefault(key, "")
    _apply_pending_editor_case()

    st.title("MyCBR SDK Bridge")
    st.caption("Separate project: Python reuses your existing case, validation, and export logic, while a standalone Java service uses the local myCBR SDK for storage and retrieval.")

    top1, top2, top3 = st.columns(3)
    top1.metric("SQL Cases", len(sql_cases))
    top2.metric("Retained Local Cases", len(retained_cases))
    top3.metric("Total Local Cases", len(all_cases))
    if mycbr_exe:
        st.success(f"Detected myCBR Workbench: {mycbr_exe}")
    else:
        st.warning("myCBR Workbench executable was not auto-detected.")

    base_url = st.text_input("Service URL", value=st.session_state.get("mycbr_bridge_base_url", DEFAULT_BASE_URL))
    st.session_state["mycbr_bridge_base_url"] = base_url.strip() or DEFAULT_BASE_URL

    tabs = st.tabs(["Service", "Build", "Check", "Retrieve", "Reuse & Revise", "Retain & Export"])

    with tabs[0]:
        st.subheader("Service Control")
        st.code(
            "powershell -ExecutionPolicy Bypass -File MyCBR_Integration/scripts/build_server.ps1\n"
            "powershell -ExecutionPolicy Bypass -File MyCBR_Integration/scripts/run_server.ps1",
            language="powershell",
        )

        col1, col2, col3 = st.columns(3)
        if col1.button("Check Service", use_container_width=True):
            try:
                st.session_state["mycbr_bridge_health"] = service_health(base_url)
                st.session_state.pop("mycbr_bridge_health_error", None)
            except Exception as exc:
                st.session_state["mycbr_bridge_health_error"] = str(exc)
        if col2.button("Sync Local Cases To Service", type="primary", use_container_width=True):
            try:
                st.session_state["mycbr_bridge_sync"] = sync_service_cases(base_url)
                st.session_state.pop("mycbr_bridge_sync_error", None)
            except Exception as exc:
                st.session_state["mycbr_bridge_sync_error"] = str(exc)
        if col3.button("Reset Service Store", use_container_width=True):
            try:
                st.session_state["mycbr_bridge_reset"] = reset_service(base_url)
                st.session_state.pop("mycbr_bridge_reset_error", None)
            except Exception as exc:
                st.session_state["mycbr_bridge_reset_error"] = str(exc)

        if st.session_state.get("mycbr_bridge_health"):
            st.json(st.session_state["mycbr_bridge_health"])
        if st.session_state.get("mycbr_bridge_health_error"):
            st.error(st.session_state["mycbr_bridge_health_error"])
        if st.session_state.get("mycbr_bridge_sync"):
            st.success(f"Service synchronized. Cases in service: {st.session_state['mycbr_bridge_sync'].get('case_count')}")
        if st.session_state.get("mycbr_bridge_sync_error"):
            st.error(st.session_state["mycbr_bridge_sync_error"])
        if st.session_state.get("mycbr_bridge_reset"):
            st.warning("Service case store reset.")
        if st.session_state.get("mycbr_bridge_reset_error"):
            st.error(st.session_state["mycbr_bridge_reset_error"])

        if st.button("Refresh Service Case Catalog", use_container_width=True):
            try:
                st.session_state["mycbr_bridge_cases"] = list_service_cases(base_url)
                st.session_state.pop("mycbr_bridge_cases_error", None)
            except Exception as exc:
                st.session_state["mycbr_bridge_cases_error"] = str(exc)

        service_cases = (st.session_state.get("mycbr_bridge_cases") or {}).get("cases") or []
        if service_cases:
            st.dataframe(pd.DataFrame(service_cases), use_container_width=True, hide_index=True)
        elif st.session_state.get("mycbr_bridge_cases_error"):
            st.error(st.session_state["mycbr_bridge_cases_error"])

    with tabs[1]:
        st.subheader("Build Working Case")
        case_options = [""] + [f'{case_payload["case_key"]} | {case_label(case_payload)}' for case_payload in all_cases]
        selected_case = st.selectbox("Load Existing Local Case", options=case_options, index=0)
        if st.button("Load Selected Local Case", use_container_width=True):
            if selected_case:
                case_key = selected_case.split(" | ", 1)[0]
                found = _find_case_by_key(case_key, all_cases)
                if found:
                    _queue_case_into_editor(found)
                    st.rerun()

        left, right = st.columns(2)
        with left:
            st.text_input("Case Title", key="mycbr_bridge_title")
            st.text_input("System Name", key="mycbr_bridge_system_name")
            st.text_area("Description", key="mycbr_bridge_description", height=180)
            st.text_area("Domains", key="mycbr_bridge_domains", height=100, help="One item per line or comma-separated.")
        with right:
            st.text_area("Primary Actors", key="mycbr_bridge_primary_actors", height=120, help="One item per line or comma-separated.")
            st.text_area("Secondary Actors", key="mycbr_bridge_secondary_actors", height=120, help="One item per line or comma-separated.")
            st.text_area("Use Cases", key="mycbr_bridge_use_cases", height=120, help="One item per line or comma-separated.")
            st.text_area(
                "Relationships",
                key="mycbr_bridge_relationships",
                height=120,
                help="One relationship per line: relationship_type | source_name | source_type | target_name | target_type | extension(optional)",
            )

    with tabs[2]:
        st.subheader("Check")
        if st.button("Validate Working Case", type="primary", use_container_width=True):
            st.session_state["mycbr_bridge_validation"] = validate_case_payload(_current_case_from_editor())

        report = st.session_state.get("mycbr_bridge_validation")
        if report:
            summary = report["summary"]
            s1, s2, s3 = st.columns(3)
            s1.metric("Errors", summary["errors"])
            s2.metric("Warnings", summary["warnings"])
            s3.metric("Relationships", summary["relationship_count"])
            findings_df = _findings_df(report["findings"])
            if findings_df.empty:
                st.success("No validation findings.")
            else:
                st.dataframe(findings_df, use_container_width=True, hide_index=True)
            with st.expander("Normalized Payload", expanded=False):
                st.json(report["normalized"])
        else:
            st.info("Run validation to inspect the working case.")

    with tabs[3]:
        st.subheader("Retrieve Through Java + myCBR SDK")
        profile = st.radio("Similarity Profile", ["balanced", "structure", "text"], horizontal=True)
        limit = st.slider("Max Results", 1, 15, 5, 1, key="mycbr_bridge_limit")
        threshold = st.slider("Minimum Similarity", 0.0, 1.0, 0.2, 0.01, key="mycbr_bridge_threshold")

        if st.button("Query Service", type="primary", use_container_width=True):
            try:
                st.session_state["mycbr_bridge_query"] = query_service(
                    _current_case_from_editor(),
                    base_url,
                    profile=profile,
                    limit=limit,
                    min_similarity=threshold,
                )
                st.session_state.pop("mycbr_bridge_query_error", None)
            except Exception as exc:
                st.session_state["mycbr_bridge_query_error"] = str(exc)

        if st.session_state.get("mycbr_bridge_query_error"):
            st.error(st.session_state["mycbr_bridge_query_error"])

        query_payload = st.session_state.get("mycbr_bridge_query") or {}
        results = query_payload.get("results") or []
        if results:
            st.dataframe(_results_df(results), use_container_width=True, hide_index=True)
            st.session_state["mycbr_bridge_result_map"] = {item["case_key"]: item for item in results if item.get("case_key")}
        elif query_payload:
            st.info("The service returned no matches above the current threshold.")

    with tabs[4]:
        st.subheader("Reuse & Revise")
        result_map = st.session_state.get("mycbr_bridge_result_map") or {}
        options = [""] + [f"{key} | {(value.get('title') or value.get('system_name') or key)}" for key, value in result_map.items()]
        selected = st.selectbox("Select Retrieved Case", options=options, index=0)
        if st.button("Reuse Selected Case", type="primary", use_container_width=True):
            if selected:
                case_key = selected.split(" | ", 1)[0]
                candidate = result_map.get(case_key)
                if candidate:
                    revised = reuse_case_payload(_current_case_from_editor(), candidate)
                    st.session_state["mycbr_bridge_revised"] = revised
                    st.session_state["mycbr_bridge_revised_validation"] = validate_case_payload(revised)

        revised = st.session_state.get("mycbr_bridge_revised")
        revised_validation = st.session_state.get("mycbr_bridge_revised_validation")
        if revised:
            st.json(revised)
            if revised_validation:
                st.dataframe(_findings_df(revised_validation.get("findings") or []), use_container_width=True, hide_index=True)
            if st.button("Load Revised Case Into Editor", use_container_width=True):
                _queue_case_into_editor(revised)
                st.rerun()
        else:
            st.info("Retrieve cases first, then reuse one here.")

    with tabs[5]:
        st.subheader("Retain & Export")
        col1, col2 = st.columns(2)
        if col1.button("Retain Locally And Push To Service", type="primary", use_container_width=True):
            try:
                st.session_state["mycbr_bridge_retained"] = retain_and_push(_current_case_from_editor(), base_url)
                st.session_state.pop("mycbr_bridge_retained_error", None)
            except Exception as exc:
                st.session_state["mycbr_bridge_retained_error"] = str(exc)
        if col2.button("Export Local Cases As Workbench Bundle", use_container_width=True):
            project_name = (_current_case_from_editor().get("system_name") or "MyCBRIntegrationProject").strip() or "MyCBRIntegrationProject"
            st.session_state["mycbr_bridge_export"] = write_project_bundle(project_name, load_all_cases())

        if st.session_state.get("mycbr_bridge_retained"):
            st.success("Case retained locally and pushed to the Java service.")
            st.json(st.session_state["mycbr_bridge_retained"])
        if st.session_state.get("mycbr_bridge_retained_error"):
            st.error(st.session_state["mycbr_bridge_retained_error"])
        if st.session_state.get("mycbr_bridge_export"):
            export_rows = [{"Asset": path.name, "Path": str(path)} for path in st.session_state["mycbr_bridge_export"].values()]
            st.dataframe(pd.DataFrame(export_rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
