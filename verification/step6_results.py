"""Step 7 (Wizard): Results & Download — final verification summary and corrected XML.

NOTE: This file is named step6_results.py but renders WIZARD STEP 7.
A UCD Semantics step was inserted between the original Steps 4 and 5,
shifting all downstream file numbers by one. The wizard step number is
authoritative; the filename is kept as-is to avoid breaking imports.
"""

import os
import tempfile
import subprocess

import streamlit as st
import pandas as pd

from verification.element_verification import element_verification
from verification.activity_panel import append_grouped_activity_panels
from verification.ttool_launcher import launch_ttool_app
from verification.step_manager import render_navigation


def _style_action(df):
    def highlight_row(row):
        action = row.get("Action", "")
        if action == "Attention Required!":
            return ['background-color: #FFCCCC'] * len(row)
        elif action == "Warning!":
            return ['background-color: #FFF5CC'] * len(row)
        else:
            return ['background-color: #E6FFCC'] * len(row)
    return df.style.apply(highlight_row, axis=1)


def render():
    ucd_dataset  = st.session_state.get("ver_ucd_dataset")
    ucd_instance = st.session_state.get("ver_ucd_instance")
    if not ucd_dataset or not ucd_instance:
        st.warning("No data available. Please go back to Step 1.")
        return

    st.write("Complete verification results with colour-coded tables and "
             "a downloadable corrected TTool XML file.")

    # ── IMPORTANT: do NOT call ucd_instance.processData() here.
    #
    # processData() calls validateActors() and validateUsecases() which do a
    # hard meta["Comments"].clear() — this would wipe:
    #   • NLP comments written in steps 3 & 4
    #   • Questionnaire answers written in step 5 (relationships)
    #
    # Instead, re-run only the structural validators (arrangement, connectivity,
    # validateRelations). These now use selective-clear so they preserve all
    # previously written comments while refreshing their own findings.
    # -------------------------------------------------------------------------
    for model_dict in ucd_dataset:
        for _, content in model_dict.items():
            for ucd_dict in content.get("Ucd Data", []):
                for _, details in ucd_dict.items():
                    primary    = details.get("Primary Actors", [])
                    secondary  = details.get("Secondary Actors", [])
                    use_cases  = details.get("Use Cases", [])
                    connectors = details.get("Connectors", [])
                    system_b   = details.get("System Boundary", [])
                    all_actors = primary + secondary

                    if system_b:
                        # BUG 7 FIX: Clear prior arrangement comments before re-running to stop accumulation
                        _ARRANGEMENT_KEYWORDS = ("inside the system boundary", "outside the system boundary", "intersecting with the system boundary")
                        for _, meta in primary + secondary + use_cases:
                            meta["Comments"] = [c for c in meta.get("Comments", []) if not any(kw in c.lower() for kw in _ARRANGEMENT_KEYWORDS)]
                        element_verification.validateArrangement(
                            primary, secondary, use_cases, system_b)

                    element_verification.validateActorConnectivity(
                        all_actors, use_cases, connectors)

                    element_verification.validateUsecaseConnectivity(
                        use_cases, all_actors, connectors)

                    # validateRelations selective-clears only its own structural
                    # markers — questionnaire comments are left untouched.
                    element_verification.validateRelations(
                        connectors, all_actors, use_cases)

    # ── Collect issue steps ───────────────────────────────────────────────
    steps = element_verification.collect_issue_steps(ucd_dataset)

    # ── Summary metrics ───────────────────────────────────────────────────
    errors       = sum(1 for s in steps if "[ERR]"  in s)
    warnings     = sum(1 for s in steps if "[WARN]" in s)
    total_issues = errors + warnings

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Issues", total_issues)
    col2.metric("Errors",       errors)
    col3.metric("Warnings",     warnings)

    if total_issues == 0:
        st.success("No verification issues detected. The diagram looks good.")
    else:
        st.warning(f"Found **{total_issues}** issue(s). Review the details below.")

    # ── Issue list ────────────────────────────────────────────────────────
    with st.expander("Verification Instructions (ordered by severity)", expanded=True):
        for i, step in enumerate(steps, 1):
            if "[ERR]" in step:
                st.markdown(f"**{i}.** :red[{step}]")
            elif "[WARN]" in step:
                st.markdown(f"**{i}.** :orange[{step}]")
            else:
                st.markdown(f"**{i}.** {step}")

    # ── Detailed tables per diagram ───────────────────────────────────────
    st.markdown("---")
    st.markdown("### Detailed Results by Diagram")

    for model_dict in ucd_dataset:
        for modeling_tab_name, content in model_dict.items():
            st.subheader(f"Modeling Tab: {modeling_tab_name}")

            for ucd_dict in content.get("Ucd Data", []):
                for ucd_name, ucd_content in ucd_dict.items():
                    with st.expander(f"{ucd_name}", expanded=False):

                        def render_table(title, components):
                            data = [
                                {
                                    "Name":     name,
                                    "Type":     meta.get("Element Type", ""),
                                    "Comments": "\n".join(meta.get("Comments", [])),
                                    "Action":   meta.get("Action", ""),
                                }
                                for name, meta in components
                            ]
                            if data:
                                df = pd.DataFrame(data)
                                st.markdown(f"**{title}**")
                                st.dataframe(_style_action(df), use_container_width=True)

                        render_table("Primary Actors",   ucd_content.get("Primary Actors",   []))
                        render_table("Secondary Actors", ucd_content.get("Secondary Actors", []))
                        render_table("Use Cases",        ucd_content.get("Use Cases",        []))

                        sys_data = [
                            {
                                "Name":     name,
                                "Type":     meta.get("Element Type"),
                                "Comments": "\n".join(meta.get("Comments", [])),
                                "Action":   meta.get("Action", ""),
                            }
                            for name, meta in ucd_content.get("System Boundary", [])
                        ]
                        if sys_data:
                            st.markdown("**System Boundary**")
                            st.dataframe(_style_action(pd.DataFrame(sys_data)),
                                         use_container_width=True)

                        conn_data = [
                            {
                                "Relation": meta.get("Relation Value"),
                                "Source":   meta.get("Source Name"),
                                "Target":   meta.get("Target Name"),
                                "Comments": "\n".join(meta.get("Comments", [])) if meta.get("Comments") else "",
                                "Action":   meta.get("Action", ""),
                            }
                            for conn_id, meta in ucd_content.get("Connectors", [])
                        ]
                        if conn_data:
                            st.markdown("**Connectors**")
                            st.dataframe(_style_action(pd.DataFrame(conn_data)),
                                         use_container_width=True)

    # ── Download corrected XML ─────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Download Corrected TTool XML")
    st.write("The file includes one activity diagram tab per element type, "
             "plus the UCD rule reference tabs.")

    raw_xml = st.session_state.get("ver_uploaded_xml", "")
    if raw_xml:
        grouped          = element_verification.collect_grouped_steps(ucd_dataset)
        xml_with_steps   = append_grouped_activity_panels(raw_xml, grouped)

        download_clicked = st.download_button(
            "Download verification_with_activity.xml",
            data=xml_with_steps,
            file_name="verification_with_activity.xml",
            mime="application/xml",
            use_container_width=True,
        )

        if download_clicked:
            default_ttool = "C:\\Users\\mages\\Downloads\\releaseTTool_2_0\\TTool\\ttool_windows.bat"
            ttool_path    = st.session_state.get("ttool_path", default_ttool)
            st.session_state["ttool_path"] = ttool_path
            ok, msg = launch_ttool_app(ttool_path)
            if ok:
                st.info("File downloaded. TTool opened separately; load the XML manually if needed.")
            else:
                st.warning(f"Download saved. TTool not opened: {msg}")
    else:
        st.warning("No uploaded XML found in session.")

    render_navigation(show_next=False)