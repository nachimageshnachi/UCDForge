"""Step 4: Use Cases Verification — verify use case names for the current diagram."""

import streamlit as st
import pandas as pd

from verification.element_verification import element_verification
from verification.step_manager import render_navigation, current_diagram


# ── Check helpers ─────────────────────────────────────────────────────────────

def _tick(ok):
    return "Pass" if ok else "Fail"


def _check_uc_row(name: str, meta: dict, connected_names: set) -> dict:
    """Return one dict of column values for a single use case."""
    comments = meta.get("Comments", [])
    action   = meta.get("Action", "Well Written")
    joined   = " ".join(comments).lower()

    # — General —
    has_special = any(kw in joined for kw in ["characters", "neither alphabets"])
    whitespace  = any("whitespace" in c.lower() for c in comments)
    title_ok    = not any(kw in joined for kw in ["title casing", "pascalcasing"])

    # — Uniqueness (from batch check comments) —
    unique_warn = "may be semantically" in joined
    unique_err  = "appear semantically" in joined
    if unique_err:
        unique_cell = "Fail"
    elif unique_warn:
        unique_cell = "Warn"
    else:
        unique_cell = "Pass"

    # — Verb-phrase structure —
    verb_ok = not any(kw in joined for kw in [
        "invalid use case", "expected to have combinations of base form"
    ])

    # — Spelling —
    spell_issue = "spelling" in joined

    # — Isolation: read directly from connector data (not from comments,
    #   which are only populated at Step 5/6) —
    isolated = name not in connected_names

    row = {
        "Name":           name,
        "Title Case":     "Warn" if (whitespace or not title_ok) else ("Fail" if has_special else "Pass"),
        "No Spec. Chars": _tick(not has_special),
        "Unique":         unique_cell,
        "Starts w/ Verb": _tick(verb_ok),
        "Spelling":       "Warn" if spell_issue else "Pass",
        "Not Isolated":   _tick(not isolated),
        "Action":         action,
        "Comments":       "\n".join(comments) if comments else "—",
    }
    return row


def _style_table(df):
    def color_row(row):
        action = row.get("Action", "")
        if action == "Attention Required!":
            return ["background-color: #FFCCCC"] * len(row)
        elif action == "Warning!":
            return ["background-color: #FFF5CC"] * len(row)
        return ["background-color: #E6FFCC"] * len(row)
    return df.style.apply(color_row, axis=1)


def render():
    d_info = current_diagram()
    if not d_info:
        st.warning("No diagram data available. Please go back to Step 1.")
        return

    tab_name, ucd_index, ucd_name, details = d_info

    st.write("Verify use case names: verb-phrase structure, casing, and grammar.")

    use_cases       = details.get("Use Cases", [])
    system_boundary = details.get("System Boundary", [])
    connectors      = details.get("Connectors", [])

    if not use_cases:
        st.info("No use cases found in this diagram.")
        render_navigation(next_label="Continue to UCD Semantics")
        return

    # ── Compute which names appear in at least one connector endpoint ─────────
    connected_names: set = set()
    for _, conn_meta in connectors:
        connected_names.add(conn_meta.get("Source Name", ""))
        connected_names.add(conn_meta.get("Target Name", ""))
    connected_names.discard("")

    # Skip validators if step1 already pre-computed everything
    if not st.session_state.get("ver_pre_verified"):
        element_verification.validateUsecases(use_cases)

        action_map = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
        sys_name = system_boundary[0][0] if system_boundary else ""
        for uc_name, uc_meta in use_cases:
            comments, action = element_verification.validateUsecase(uc_name, sys_name)
            uc_meta["Comments"].extend(comments)
            prev = action_map.get(uc_meta.get("Action", ""), 0)
            uc_meta["Action"] = next(k for k, v in action_map.items()
                                     if v == max(prev, action_map[action]))

    # Summary bar
    ok   = sum(1 for _, m in use_cases if m.get("Action") == "Well Written")
    warn = sum(1 for _, m in use_cases if m.get("Action") == "Warning!")
    err  = sum(1 for _, m in use_cases if m.get("Action") == "Attention Required!")
    st.markdown(f"{ok} well written &nbsp;|&nbsp; {warn} warnings &nbsp;|&nbsp; {err} issues")

    # Build check-per-column table
    data = [_check_uc_row(name, meta, connected_names) for name, meta in use_cases]
    df   = pd.DataFrame(data)

    st.dataframe(
        _style_table(df),
        use_container_width=True,
        column_config={
            "Name":           st.column_config.TextColumn("Name",           width="medium"),
            "Title Case":     st.column_config.TextColumn("Title Case",     width="small"),
            "No Spec. Chars": st.column_config.TextColumn("No Spec. Chars", width="small"),
            "Unique":         st.column_config.TextColumn("Unique",         width="small"),
            "Starts w/ Verb": st.column_config.TextColumn("Starts w/ Verb", width="small"),
            "Spelling":       st.column_config.TextColumn("Spelling",       width="small"),
            "Not Isolated":   st.column_config.TextColumn("Not Isolated",   width="small"),
            "Action":         st.column_config.TextColumn("Action",         width="medium"),
            "Comments":       st.column_config.TextColumn("Comments",       width="large"),
        },
        hide_index=True,
    )

    render_navigation(next_label="Continue to UCD Semantics")
