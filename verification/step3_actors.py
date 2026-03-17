"""Step 3: Actors Verification — verify actor names and types for the current diagram."""

import streamlit as st
import pandas as pd

from verification.element_verification import element_verification
from verification.step_manager import render_navigation, current_diagram


# ── Check helpers ─────────────────────────────────────────────────────────────

def _tick(ok):
    return "Pass" if ok else "Fail"

def _warn_tick(ok, warned):
    """Three-state: Pass / Warn / Fail."""
    if ok and not warned:
        return "Pass"
    if warned:
        return "Warn"
    return "Fail"


def _check_actor_row(name: str, meta: dict, connected_names: set) -> dict:
    """Return one dict of column values for a single actor."""
    comments = meta.get("Comments", [])
    action    = meta.get("Action", "Well Written")
    joined    = " ".join(comments).lower()

    # — General —
    has_special = any(kw in joined for kw in ["characters", "neither alphabets"])
    title_ok    = not any(kw in joined for kw in ["title casing", "pascalcasing"])
    whitespace  = any("whitespace" in c.lower() for c in comments)

    # — Uniqueness —
    unique_ok   = not any(kw in joined for kw in ["similar", "duplicate", "unique"])

    # — Grammar (common noun) —
    noun_ok     = not any(kw in joined for kw in [
        "invalid actor", "verb", "expected to have common singular"
    ])

    # — Isolation: read from connector data, not comments —
    isolated = name not in connected_names

    # — Role classification —
    role_mismatch = any(kw in joined for kw in ["secondary actor", "primary actor", "artefact"])

    row = {
        "Name":           name,
        "Type":           meta.get("Element Type", ""),
        "Title Case":     "Warn" if (whitespace or not title_ok) else ("Fail" if has_special else "Pass"),
        "No Spec. Chars": _tick(not has_special),
        "Unique":         "Warn" if "may be semantically" in joined else ("Fail" if (not unique_ok and "appear semantically" in joined) else "Pass"),
        "Common Noun":    _tick(noun_ok),
        "Not Isolated":   _tick(not isolated),
        "Correct Role":   "Warn" if role_mismatch else "Pass",
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

    st.write("Verify actor names, casing, and primary/secondary classification.")

    stickman_actors  = details.get("Primary Actors", [])
    box_actors       = details.get("Secondary Actors", [])
    actors_with_meta = stickman_actors + box_actors
    connectors       = details.get("Connectors", [])

    if not actors_with_meta:
        st.info("No actors found in this diagram.")
        render_navigation(next_label="Continue to Use Cases Verification")
        return

    # Compute which names appear in at least one connector endpoint
    connected_names: set = set()
    for _, conn_meta in connectors:
        connected_names.add(conn_meta.get("Source Name", ""))
        connected_names.add(conn_meta.get("Target Name", ""))
    connected_names.discard("")

    # Skip validators if step1 already pre-computed everything
    if not st.session_state.get("ver_pre_verified"):
        element_verification.validateActors(actors_with_meta)

        action_map = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
        for actor_name, actor_meta in stickman_actors:
            comments, action = element_verification.validateActor(actor_name, "Primary Actor")
            actor_meta["Comments"].extend(comments)
            prev = action_map.get(actor_meta.get("Action", ""), 0)
            actor_meta["Action"] = next(k for k, v in action_map.items()
                                        if v == max(prev, action_map[action]))

        for actor_name, actor_meta in box_actors:
            comments, action = element_verification.validateActor(actor_name, "Secondary Actor")
            actor_meta["Comments"].extend(comments)
            prev = action_map.get(actor_meta.get("Action", ""), 0)
            actor_meta["Action"] = next(k for k, v in action_map.items()
                                        if v == max(prev, action_map[action]))

    # Summary bar
    ok   = sum(1 for _, m in actors_with_meta if m.get("Action") == "Well Written")
    warn = sum(1 for _, m in actors_with_meta if m.get("Action") == "Warning!")
    err  = sum(1 for _, m in actors_with_meta if m.get("Action") == "Attention Required!")
    st.markdown(f"{ok} well written &nbsp;|&nbsp; {warn} warnings &nbsp;|&nbsp; {err} issues")

    # Build check-per-column table
    data = [_check_actor_row(name, meta, connected_names)
            for name, meta in actors_with_meta]
    df = pd.DataFrame(data)

    # Column width hints via custom CSS on the dataframe
    st.dataframe(
        _style_table(df),
        use_container_width=True,
        column_config={
            "Name":          st.column_config.TextColumn("Name",          width="medium"),
            "Type":          st.column_config.TextColumn("Type",          width="small"),
            "Title Case":    st.column_config.TextColumn("Title Case",    width="small"),
            "No Spec. Chars":st.column_config.TextColumn("No Spec. Chars",width="small"),
            "Unique":        st.column_config.TextColumn("Unique",        width="small"),
            "Common Noun":   st.column_config.TextColumn("Common Noun",   width="small"),
            "Not Isolated":  st.column_config.TextColumn("Not Isolated",  width="small"),
            "Correct Role":  st.column_config.TextColumn("Correct Role",  width="small"),
            "Action":        st.column_config.TextColumn("Action",        width="medium"),
            "Comments":      st.column_config.TextColumn("Comments",      width="large"),
        },
        hide_index=True,
    )

    render_navigation(next_label="Continue to Use Cases Verification")
