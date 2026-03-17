"""Step 1: Upload XML — file upload, extraction AND full pre-verification.

All expensive validators run here once so every subsequent tab is instant.
"""

import streamlit as st

from verification.element_verification import element_verification
from verification.xml_parser import UcdVerificationParser
from verification.ttool_launcher import get_file_hash
from verification.step_manager import render_navigation


# ── helpers ──────────────────────────────────────────────────────────────────

def _run_all_validators(ucd_dataset):
    """Pre-compute every verification check and write results into ucd_dataset.

    After this function returns, every element's 'Comments' and 'Action' fields
    are populated.  Steps 2-6 only READ these values; they never re-run
    validators, so tab switching is instantaneous.
    """
    action_map = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
    rev_action  = {v: k for k, v in action_map.items()}

    def _bump(meta, action):
        prev = action_map.get(meta.get("Action", "Well Written"), 0)
        meta["Action"] = rev_action[max(prev, action_map.get(action, 0))]

    for model_dict in ucd_dataset:
        for tab_name, content in model_dict.items():
            tab_lc = (tab_name or "").lower()
            is_standard_db   = "standard database" in tab_lc
            is_verified_tab  = "verified" in tab_lc

            # Skip ALL verification for pure Standard Database tabs
            # (not the "Verified" variant — those still get partial checks).
            if is_standard_db and not is_verified_tab:
                continue

            for ucd_dict in content.get("Ucd Data", []):
                for _, details in ucd_dict.items():
                    primary    = details.get("Primary Actors", [])
                    secondary  = details.get("Secondary Actors", [])
                    use_cases  = details.get("Use Cases", [])
                    connectors = details.get("Connectors", [])
                    system_b   = details.get("System Boundary", [])
                    all_actors = primary + secondary

                    sys_name = system_b[0][0] if system_b else ""

                    # 1. Batch uniqueness / semantic-similarity checks
                    #    (these call .clear() internally, so they must run first)
                    element_verification.validateActors(all_actors)
                    element_verification.validateUsecases(use_cases)

                    # 2. Per-element NLP checks (naming, casing, grammar, …)
                    for aname, ameta in primary:
                        cmts, act = element_verification.validateActor(aname, "Primary Actor")
                        ameta["Comments"].extend(cmts)
                        _bump(ameta, act)
                    for aname, ameta in secondary:
                        cmts, act = element_verification.validateActor(aname, "Secondary Actor")
                        ameta["Comments"].extend(cmts)
                        _bump(ameta, act)
                    for ucname, ucmeta in use_cases:
                        cmts, act = element_verification.validateUsecase(ucname, sys_name)
                        ucmeta["Comments"].extend(cmts)
                        _bump(ucmeta, act)

                    # 3. System boundary checks
                    # Diagrams from a "Verified" tab are already validated —
                    # treat their system name as well-written without re-checking.
                    if not is_verified_tab:
                        for sname, smeta in system_b:
                            cmts, act = element_verification.validateSystem(sname)
                            smeta["Comments"].extend(cmts)
                            _bump(smeta, act)

                    # 4. Structural / connectivity / relationship checks
                    if system_b:
                        element_verification.validateArrangement(
                            primary, secondary, use_cases, system_b
                        )
                    element_verification.validateActorConnectivity(
                        all_actors, use_cases, connectors
                    )
                    element_verification.validateUsecaseConnectivity(
                        use_cases, all_actors, connectors
                    )
                    element_verification.validateRelations(
                        connectors, all_actors, use_cases
                    )


# ── main render ───────────────────────────────────────────────────────────────

def render():
    st.write("Upload a TTool XML file containing Use Case Diagrams for verification.")

    uploaded_file = st.file_uploader("Upload the TTool XML File", type="xml",
                                     key="ver_file_uploader")

    if uploaded_file is not None:
        file_hash = get_file_hash(uploaded_file)

        # Only re-parse and re-verify when the file actually changes
        if st.session_state.get("ver_last_file_hash") != file_hash:
            with st.spinner("Extracting and pre-verifying diagram…"):
                uploaded_file.seek(0)
                ucd_instance = UcdVerificationParser(uploaded_file)
                ucd_dataset  = ucd_instance.extractData()
                uploaded_file.seek(0)
                st.session_state["ver_uploaded_xml"] = uploaded_file.getvalue().decode(
                    "utf-8", errors="ignore"
                )

                # Run ALL validators once here so every tab is instant
                _run_all_validators(ucd_dataset)

            st.session_state["ver_last_file_hash"]  = file_hash
            st.session_state["ver_ucd_instance"]    = ucd_instance
            st.session_state["ver_ucd_dataset"]     = ucd_dataset
            st.session_state["ver_validated_ucds"]  = set()
            st.session_state["ver_finalized"]       = False
            st.session_state["ver_pre_verified"]    = True   # flag for steps

        ucd_dataset = st.session_state.get("ver_ucd_dataset")
        if ucd_dataset:
            total_ucds = total_actors = total_ucs = total_connectors = 0
            for model in ucd_dataset:
                for _, tab_data in model.items():
                    for ucd in tab_data.get("Ucd Data", []):
                        for _, details in ucd.items():
                            total_ucds       += 1
                            total_actors     += len(details.get("Primary Actors", []))
                            total_actors     += len(details.get("Secondary Actors", []))
                            total_ucs        += len(details.get("Use Cases", []))
                            total_connectors += len(details.get("Connectors", []))

            st.success(
                f"Extracted & verified **{total_ucds}** diagram(s): "
                f"**{total_actors}** actors, **{total_ucs}** use cases, "
                f"**{total_connectors}** connectors. "
                f"Tab switching is now instant."
            )
            render_navigation(show_prev=False,
                              next_label="Begin Verification",
                              next_disabled=False)
        else:
            st.warning("No diagrams could be extracted from the file.")
    else:
        st.info("Please upload a TTool XML file to begin.")

