from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

st.set_page_config(page_title="MyCBR CBR Cycle", layout="wide")

from MyCBR.cycle import normalize_case_payload, reuse_case_payload, validate_case_payload
from MyCBR.project_export import build_project_bundle, write_project_bundle
from MyCBR.retrieval import retrieve_cases
from MyCBR.repository import (
    case_label,
    discover_mycbr_exe,
    load_all_cases,
    load_retained_cases,
    load_sql_cases,
    save_retained_case,
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
        "title": st.session_state.get("mycbr_cycle_title", "").strip(),
        "description": st.session_state.get("mycbr_cycle_description", "").strip(),
        "system_name": st.session_state.get("mycbr_cycle_system_name", "").strip(),
        "domains": _split_items(st.session_state.get("mycbr_cycle_domains", "")),
        "primary_actors": _split_items(st.session_state.get("mycbr_cycle_primary_actors", "")),
        "secondary_actors": _split_items(st.session_state.get("mycbr_cycle_secondary_actors", "")),
        "use_cases": _split_items(st.session_state.get("mycbr_cycle_use_cases", "")),
        "relationships": _relationship_lines_to_dicts(st.session_state.get("mycbr_cycle_relationships", "")),
    }


def _queue_case_into_editor(case_payload: Dict[str, Any]) -> None:
    st.session_state["_mycbr_pending_editor_case"] = {
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
    pending = st.session_state.pop("_mycbr_pending_editor_case", None)
    if not pending:
        return
    st.session_state["mycbr_cycle_title"] = pending.get("title", "")
    st.session_state["mycbr_cycle_description"] = pending.get("description", "")
    st.session_state["mycbr_cycle_system_name"] = pending.get("system_name", "")
    st.session_state["mycbr_cycle_domains"] = pending.get("domains", "")
    st.session_state["mycbr_cycle_primary_actors"] = pending.get("primary_actors", "")
    st.session_state["mycbr_cycle_secondary_actors"] = pending.get("secondary_actors", "")
    st.session_state["mycbr_cycle_use_cases"] = pending.get("use_cases", "")
    st.session_state["mycbr_cycle_relationships"] = pending.get("relationships", "")


def _find_case_by_key(case_key: str, cases: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for case_payload in cases:
        if case_payload.get("case_key") == case_key:
            return case_payload
    return None


def _query_for_retrieval(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    actors = list(case_payload.get("primary_actors") or []) + list(case_payload.get("secondary_actors") or [])
    return {
        "system_name": case_payload.get("system_name") or "",
        "description": case_payload.get("description") or "",
        "domains": list(case_payload.get("domains") or []),
        "actors": actors,
        "use_cases": list(case_payload.get("use_cases") or []),
    }


def _findings_df(findings: List[Dict[str, str]]) -> pd.DataFrame:
    if not findings:
        return pd.DataFrame(columns=["Scope", "Name", "Severity", "Message"])
    return pd.DataFrame(
        [
            {
                "Scope": item.get("scope"),
                "Name": item.get("name"),
                "Severity": item.get("severity"),
                "Message": item.get("message"),
            }
            for item in findings
        ]
    )


def _build_full_mysql_csvs(all_cases: list) -> bytes:
    """Query all 9 MySQL tables and return ONE flat CSV (one row per case, UTF-8, semicolon-delimited).

    Design decisions
    ----------------
    * Canonical Normalization: All actors, use cases, and system names are mapped to their 
      canonical base names (the keys in the synonym tables) before insertion into the CSV.
      Example: "User" -> "Customer" if "User" is listed as a synonym for "Customer".
    * CaseId formatted as UCD_0000 ... UCD_0048 so myCBR sorts correctly.
    * SystemName used as the primary identity; Title removed.
    * All synonyms deduplicated, sorted, and self-synonyms stripped.
    """
    import csv, io
    from connection import connection

    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT case_id, description, created_at FROM cases ORDER BY case_id"
        )
        db_cases = cursor.fetchall()

        cursor.execute("SELECT case_id, system_name FROM diagrams")
        diagrams_map = {r["case_id"]: r["system_name"] for r in cursor.fetchall()}

        cursor.execute(
            "SELECT system_name, synonym FROM system_synonyms ORDER BY system_name, synonym"
        )
        sys_syns: dict = {}
        # Reverse map: synonym -> canonical system name
        sys_canon_map: dict = {}
        for r in cursor.fetchall():
            sys_name = r["system_name"]
            sys_syns.setdefault(sys_name, set()).add(r["synonym"])
            sys_canon_map[r["synonym"].lower()] = sys_name

        cursor.execute(
            "SELECT case_id, actor_name, actor_type FROM actors ORDER BY case_id, actor_name"
        )
        all_db_actors = cursor.fetchall()

        # actor_synonyms schema: (id, case_id, actor_name, synonym)
        cursor.execute(
            "SELECT case_id, actor_name, synonym FROM actor_synonyms ORDER BY case_id, actor_name, synonym"
        )
        actor_syns_by_case_name: dict = {}
        # Reverse map per case: synonym -> canonical actor name
        actor_canon_map: dict = {}
        for r in cursor.fetchall():
            key = (r["case_id"], r["actor_name"])
            actor_syns_by_case_name.setdefault(key, set()).add(r["synonym"])
            actor_canon_map[(r["case_id"], r["synonym"].lower())] = r["actor_name"]

        cursor.execute(
            "SELECT case_id, name FROM use_cases ORDER BY case_id, name"
        )
        all_db_ucs = cursor.fetchall()

        # use_case_synonyms schema: (id, case_id, use_case_name, synonym)
        cursor.execute(
            "SELECT case_id, use_case_name, synonym FROM use_case_synonyms ORDER BY case_id, use_case_name, synonym"
        )
        uc_syns_by_case_name: dict = {}
        # Reverse map per case: synonym -> canonical use case name
        uc_canon_map: dict = {}
        for r in cursor.fetchall():
            key = (r["case_id"], r["use_case_name"])
            uc_syns_by_case_name.setdefault(key, set()).add(r["synonym"])
            uc_canon_map[(r["case_id"], r["synonym"].lower())] = r["use_case_name"]

        cursor.execute(
            "SELECT case_id, relationship_type, source_name, source_type, "
            "       target_name, target_type, extension "
            "FROM relationships ORDER BY case_id, relationship_type, source_name"
        )
        all_db_rels = cursor.fetchall()

        cursor.execute(
            "SELECT case_id, domain_name FROM case_domains ORDER BY case_id, domain_name"
        )
        all_db_domains = cursor.fetchall()

    actors_by_case: dict = {}
    for r in all_db_actors:
        actors_by_case.setdefault(r["case_id"], []).append(r)

    uc_by_case: dict = {}
    for r in all_db_ucs:
        uc_by_case.setdefault(r["case_id"], []).append(r)

    rels_by_case: dict = {}
    for r in all_db_rels:
        rels_by_case.setdefault(r["case_id"], []).append(r)

    domains_by_case: dict = {}
    for r in all_db_domains:
        domains_by_case.setdefault(r["case_id"], []).append(r["domain_name"])

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")

    w.writerow([
        "CaseLabel",
        "SystemName",
        "SystemSynonyms",
        "PrimaryDomain",
        "AllDomains",
        "PrimaryActors",
        "SecondaryActors",
        "AllActors",
        "ActorSynonyms",
        "UseCases",
        "UseCaseSynonyms",
        "Relationships",
        "RelationshipTypes",
        "HasInclude",
        "HasExtend",
        "HasGeneralization",
    ])

    for seq, case in enumerate(db_cases, start=1):
        cid         = case["case_id"]
        case_id_str = f"UCD_{seq:04d}"

        # 1. Map System Name
        raw_sys     = diagrams_map.get(cid, "")
        sys_name    = sys_canon_map.get(raw_sys.lower(), raw_sys)
        domains     = domains_by_case.get(cid, [])

        # 2. Map Actors
        def norm_actor(name):
            return actor_canon_map.get((cid, name.lower()), name)

        actors    = actors_by_case.get(cid, [])
        primary   = sorted({norm_actor(a["actor_name"]) for a in actors
                            if "primary"   in str(a["actor_type"]).lower()})
        secondary = sorted({norm_actor(a["actor_name"]) for a in actors
                            if "secondary" in str(a["actor_type"]).lower()})
        all_actor_names = sorted({norm_actor(a["actor_name"]) for a in actors})

        # Keep synonyms mapped to the CANONICAL name
        actor_syn_parts = []
        for name in all_actor_names:
            raw = set()
            # gather synonyms for any variant that mapped to this canonical name
            for (syn_cid, a_name), syns in actor_syns_by_case_name.items():
                if syn_cid == cid and norm_actor(a_name) == name:
                    raw.update(syns)
            
            syns_clean = sorted(s for s in raw if s.strip() and s.lower() != name.lower())
            if syns_clean:
                actor_syn_parts.append(f"{name}: {' | '.join(syns_clean)}")
        a_syns_str = " || ".join(actor_syn_parts)

        # 3. Map Use Cases
        def norm_uc(name):
            return uc_canon_map.get((cid, name.lower()), name)

        ucs = sorted({norm_uc(u["name"]) for u in uc_by_case.get(cid, [])})

        uc_syn_parts = []
        for uc_name in ucs:
            raw = set()
            for (syn_cid, u_name), syns in uc_syns_by_case_name.items():
                if syn_cid == cid and norm_uc(u_name) == uc_name:
                    raw.update(syns)
            
            syns_clean = sorted(s for s in raw if s.strip() and s.lower() != uc_name.lower())
            if syns_clean:
                uc_syn_parts.append(f"{uc_name}: {' | '.join(syns_clean)}")
        uc_syns_str = " || ".join(uc_syn_parts)

        # 4. Map Relationships
        rels      = rels_by_case.get(cid, [])
        rel_types = sorted(set(r["relationship_type"].lower() for r in rels))
        
        rel_strs  = []
        for r in rels:
            stype = r["source_type"].lower()
            ttype = r["target_type"].lower()
            
            sname = norm_actor(r["source_name"]) if stype == "actor" else norm_uc(r["source_name"])
            tname = norm_actor(r["target_name"]) if ttype == "actor" else norm_uc(r["target_name"])
            
            ext = f" [{r['extension']}]" if r.get("extension") else ""
            rel_strs.append(
                f"{r['relationship_type']}: {sname}({stype}) -> {tname}({ttype}){ext}"
            )
        rel_strs.sort()

        sys_syn_list = sorted(sys_syns.get(sys_name, set()))

        w.writerow([
            case_id_str,
            sys_name,
            " | ".join(sys_syn_list),
            domains[0] if domains else "",
            " | ".join(domains),
            " | ".join(primary),
            " | ".join(secondary),
            " | ".join(all_actor_names),
            a_syns_str,
            " | ".join(ucs),
            uc_syns_str,
            " | ".join(rel_strs),
            " | ".join(rel_types),
            "Yes" if "include"        in rel_types else "No",
            "Yes" if "extend"         in rel_types else "No",
            "Yes" if "generalization" in rel_types else "No",
        ])

    return buf.getvalue().encode("utf-8")

def main() -> None:

    sql_cases = load_sql_cases()
    retained_cases = load_retained_cases()
    all_cases = sql_cases + retained_cases
    mycbr_exe = discover_mycbr_exe()

    for key in [
        "mycbr_cycle_title",
        "mycbr_cycle_description",
        "mycbr_cycle_system_name",
        "mycbr_cycle_domains",
        "mycbr_cycle_primary_actors",
        "mycbr_cycle_secondary_actors",
        "mycbr_cycle_use_cases",
        "mycbr_cycle_relationships",
    ]:
        st.session_state.setdefault(key, "")
    _apply_pending_editor_case()

    st.title("MyCBR CBR Cycle")
    st.caption("Standalone subproject for storing, checking, retrieving, revising, retaining, and exporting UCD cases for myCBR Workbench.")

    top1, top2, top3 = st.columns(3)
    top1.metric("SQL Cases", len(sql_cases))
    top2.metric("Retained Local Cases", len(retained_cases))
    top3.metric("Total Cases Available", len(all_cases))
    if mycbr_exe:
        st.success(f"Detected myCBR Workbench: {mycbr_exe}")
    else:
        st.warning("myCBR Workbench executable was not auto-detected. You can still generate project files and open them manually.")

    tabs = st.tabs(["Build", "Check", "Retrieve", "Reuse & Revise", "Retain", "Export"])

    with tabs[0]:
        st.subheader("Build Working Case")
        case_options = [""] + [f'{case_payload["case_key"]} | {case_label(case_payload)}' for case_payload in all_cases]
        selected_case = st.selectbox("Load Existing Case", options=case_options, index=0)
        if st.button("Load Selected Case", use_container_width=True):
            if selected_case:
                case_key = selected_case.split(" | ", 1)[0]
                found = _find_case_by_key(case_key, all_cases)
                if found:
                    _queue_case_into_editor(found)
                    st.rerun()

        left, right = st.columns(2)
        with left:
            st.text_input("Case Title", key="mycbr_cycle_title")
            st.text_input("System Name", key="mycbr_cycle_system_name")
            st.text_area("Description", key="mycbr_cycle_description", height=180)
            st.text_area("Domains", key="mycbr_cycle_domains", height=100, help="One item per line or comma-separated.")
        with right:
            st.text_area("Primary Actors", key="mycbr_cycle_primary_actors", height=120, help="One item per line or comma-separated.")
            st.text_area("Secondary Actors", key="mycbr_cycle_secondary_actors", height=120, help="One item per line or comma-separated.")
            st.text_area("Use Cases", key="mycbr_cycle_use_cases", height=120, help="One item per line or comma-separated.")
            st.text_area(
                "Relationships",
                key="mycbr_cycle_relationships",
                height=120,
                help="One relationship per line: relationship_type | source_name | source_type | target_name | target_type | extension(optional)",
            )

        st.code(
            "association | Customer | actor | Withdraw Cash | usecase |\n"
            "include | Withdraw Cash | usecase | Validate PIN | usecase |",
            language="text",
        )

    with tabs[1]:
        st.subheader("Check")
        if st.button("Validate Working Case", type="primary", use_container_width=True):
            report = validate_case_payload(_current_case_from_editor())
            st.session_state["mycbr_cycle_validation"] = report

        report = st.session_state.get("mycbr_cycle_validation")
        if report:
            summary = report["summary"]
            s1, s2, s3 = st.columns(3)
            s1.metric("Errors", summary["errors"])
            s2.metric("Warnings", summary["warnings"])
            s3.metric("Relationships After Normalization", summary["relationship_count"])

            findings_df = _findings_df(report["findings"])
            if findings_df.empty:
                st.success("No validation findings for the current working case.")
            else:
                st.dataframe(findings_df, use_container_width=True, hide_index=True)

            with st.expander("Normalized Payload", expanded=False):
                st.json(report["normalized"])
        else:
            st.info("Run validation to inspect the current working case.")

    with tabs[2]:
        st.subheader("Retrieve")
        mode = st.radio("Retrieval Mode", ["CBR", "IR"], horizontal=True)
        threshold = st.slider("Minimum Relevance", 0.0, 1.0, 0.35, 0.01, key="mycbr_cycle_threshold")
        limit = st.slider("Max Results", 1, 15, 5, 1, key="mycbr_cycle_limit")

        if st.button("Retrieve Similar Cases", type="primary", use_container_width=True):
            query = _query_for_retrieval(_current_case_from_editor())
            matches = retrieve_cases(query, mode=mode, threshold=threshold, limit=limit)
            st.session_state["mycbr_cycle_matches"] = matches

        matches = st.session_state.get("mycbr_cycle_matches") or []
        if matches:
            rows = []
            for match in matches:
                rows.append(
                    {
                        "Case ID": match["case_id"],
                        "Source": str(match.get("source") or ""),
                        "Title": match.get("title") or "",
                        "Relevance": round(float(match.get("relevance", 0.0)), 4),
                        "Title Sim": round(float(match.get("sim_title", 0.0)), 4),
                        "Desc Sim": round(float(match.get("sim_desc", 0.0)), 4),
                        "Actor Sim": round(float(match.get("sim_actors", 0.0)), 4),
                        "UC Sim": round(float(match.get("sim_usecases", 0.0)), 4),
                        "Domain Sim": round(float(match.get("sim_domains", 0.0)), 4),
                        "Lexical": round(float(match.get("sim_lexical", 0.0)), 4),
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            selected_case_key = st.selectbox(
                "Select a retrieved case for reuse",
                options=[match["case_key"] for match in matches],
                format_func=lambda key: next((f'{m.get("source") or ""} | {m["case_id"]} - {m.get("title") or ""}' for m in matches if m["case_key"] == key), str(key)),
            )
            if st.button("Use Selected Retrieval Result", use_container_width=True):
                st.session_state["mycbr_cycle_selected_case_key"] = selected_case_key
                st.success(f"Selected case {selected_case_key} for reuse.")
        else:
            st.info("Run retrieval to see ranked matches.")

    with tabs[3]:
        st.subheader("Reuse & Revise")
        selected_case_key = st.session_state.get("mycbr_cycle_selected_case_key")
        if selected_case_key is None:
            st.info("Select a retrieved case in the Retrieve tab first.")
        else:
            selected_case = _find_case_by_key(selected_case_key, all_cases)
            if selected_case:
                st.markdown(f"**Selected Base Case:** {case_label(selected_case)}")
                if st.button("Build Revised Case", type="primary", use_container_width=True):
                    revised = reuse_case_payload(_current_case_from_editor(), selected_case)
                    st.session_state["mycbr_cycle_revised"] = revised
                    st.session_state["mycbr_cycle_revised_report"] = validate_case_payload(revised)

                revised = st.session_state.get("mycbr_cycle_revised")
                revised_report = st.session_state.get("mycbr_cycle_revised_report")
                if revised:
                    st.json(revised)
                    if revised_report:
                        findings_df = _findings_df(revised_report["findings"])
                        if findings_df.empty:
                            st.success("The revised case has no validation findings.")
                        else:
                            st.dataframe(findings_df, use_container_width=True, hide_index=True)

                    if st.button("Load Revised Case Into Editor", use_container_width=True):
                        _queue_case_into_editor(revised)
                        st.rerun()

    with tabs[4]:
        st.subheader("Retain")
        st.markdown("Retaining here writes only to the standalone `MyCBR/data/retained_cases.json` store. It does not modify your main SQL case base.")
        if st.button("Retain Current Working Case", type="primary", use_container_width=True):
            normalized = normalize_case_payload(_current_case_from_editor())
            retained = save_retained_case(normalized)
            st.success(f'Retained new local case: {retained["case_key"]}')

        retained_now = load_retained_cases()
        if retained_now:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Case Key": item.get("case_key"),
                            "Title": item.get("title"),
                            "System Name": item.get("system_name"),
                            "Created At": item.get("created_at"),
                        }
                        for item in retained_now
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No retained local cases yet.")

    with tabs[5]:
        st.subheader("Export")

        # ── Section 1: myCBR Workbench project files ──────────────────────────
        st.markdown("#### myCBR Workbench Project")
        project_name = st.text_input("myCBR Project Name", value="UCD_CBR_Cycle_Project")
        include_working = st.checkbox("Include current working case in the export bundle", value=True)

        export_cases = load_all_cases()
        if include_working:
            export_cases = export_cases + [normalize_case_payload(_current_case_from_editor()) | {"case_key": "working-case", "case_id": "working", "source": "working"}]

        st.caption(
            "The export bundle includes `.myCBR`, `.myCB`, `.myExp`, `.config`, a packaged `.prj`, "
            "and a CSV case base. The generated myCBR model includes multiple similarity profiles "
            "and per-attribute strict/loose numeric similarity functions."
        )

        if st.button("Generate myCBR Project Files", type="primary", use_container_width=True):
            bundle = build_project_bundle(project_name, export_cases)
            st.session_state["mycbr_cycle_export_bundle"] = bundle
            st.session_state["mycbr_cycle_export_paths"] = write_project_bundle(project_name, export_cases)

        bundle = st.session_state.get("mycbr_cycle_export_bundle")
        paths = st.session_state.get("mycbr_cycle_export_paths")
        if bundle:
            if paths:
                st.success("Exported project files to disk:")
                st.write("\n".join(str(path) for path in paths.values()))

            for file_name, content in bundle.items():
                st.download_button(
                    label=f"Download {file_name}",
                    data=content,
                    file_name=file_name,
                    use_container_width=True,
                    mime="application/octet-stream",
                    key=f"download_{file_name}",
                )

            with st.expander("How to open in myCBR Workbench", expanded=False):
                st.markdown(
                    "1. Open your local myCBR Workbench.\n"
                    "2. Open the generated `.prj` file or unzip the workspace bundle.\n"
                    "3. Inspect the concept model, case base, and similarity profiles.\n"
                    "4. Switch between the prebuilt amalgams to compare retrieval behavior."
                )

        st.divider()

        # ── Section 2: Full MySQL export ───────────────────────────────────────
        st.markdown("#### Full MySQL Case Base Export")
        st.caption(
            "Exports all 9 MySQL tables into a single semicolon-delimited CSV "
            "(UTF-8 with BOM, one row per case). Saved directly to disk so the "
            "filename is always correct — no browser download required."
        )

        if st.button("Generate & Save Full MySQL CSV", type="secondary", use_container_width=True):
            with st.spinner("Querying MySQL and writing file…"):
                csv_bytes = _build_full_mysql_csvs(all_cases)
                from MyCBR.repository import OUTPUT_DIR
                out_dir = OUTPUT_DIR / "full_export"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / "casebase_mysql_full.csv"
                out_path.write_bytes(csv_bytes)
            st.session_state["mycbr_full_csv_bytes"] = csv_bytes
            st.session_state["mycbr_full_csv_path"]  = str(out_path)

        csv_bytes = st.session_state.get("mycbr_full_csv_bytes")
        csv_path  = st.session_state.get("mycbr_full_csv_path")
        if csv_bytes and csv_path:
            line_count = csv_bytes.count(b"\n")
            st.success(f"✅ {line_count - 1} cases saved  ({len(csv_bytes):,} bytes)")
            st.markdown("**File saved to:**")
            st.code(csv_path, language=None)
            st.caption("Open File Explorer, navigate to the path above, and double-click the CSV to open it in Excel.")

            with st.expander("Column reference (24 columns — semicolon delimited)", expanded=False):
                st.markdown(
                    "| Column | Description |\n|---|---|\n"
                    "| CaseId | MySQL case ID |\n"
                    "| Title | Case title |\n"
                    "| SystemName | UCD system boundary label |\n"
                    "| SystemSynonyms | Alternative system names (pipe-separated) |\n"
                    "| Description | Full problem description |\n"
                    "| PrimaryDomain | First/main domain |\n"
                    "| AllDomains | All domains (pipe-separated) |\n"
                    "| PrimaryActors | Primary actor names (pipe-separated) |\n"
                    "| SecondaryActors | Secondary actor names (pipe-separated) |\n"
                    "| AllActors | All actors combined |\n"
                    "| PrimaryActorCount / SecondaryActorCount / TotalActorCount | Counts |\n"
                    "| ActorSynonyms | Actor: syn1, syn2 (pipe-separated) |\n"
                    "| UseCases | Use case names (pipe-separated) |\n"
                    "| UseCaseCount | Numeric count |\n"
                    "| UseCaseSynonyms | UC: syn1, syn2 (pipe-separated) |\n"
                    "| Relationships | type: Source(type) -> Target(type) (pipe-separated) |\n"
                    "| RelationshipCount | Numeric count |\n"
                    "| RelationshipTypes | Unique types (pipe-separated) |\n"
                    "| HasInclude / HasExtend / HasGeneralization | Yes/No |\n"
                    "| CreatedAt | Timestamp |"
                )




if __name__ == "__main__":
    main()

