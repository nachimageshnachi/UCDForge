"""Step 5: UCD Semantics — structural and connectivity checks for the current diagram."""

import streamlit as st
import pandas as pd

from verification.element_verification import element_verification
from verification.step_manager import (
    render_navigation, current_diagram,
)


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
    d_info = current_diagram()
    if not d_info:
        st.warning("No diagram data available. Please go back to Step 1.")
        return

    tab_name, ucd_index, ucd_name, details = d_info

    st.write(
        "Verify spatial arrangement (actors outside, use cases inside the "
        "system boundary) and element connectivity (no isolated elements)."
    )

    stickman_actors = details.get("Primary Actors", [])
    box_actors = details.get("Secondary Actors", [])
    use_cases = details.get("Use Cases", [])
    connectors = details.get("Connectors", [])
    system_boundary = details.get("System Boundary", [])
    actors_with_meta = stickman_actors + box_actors

    # ── Run structural checks ────────────────────────────────────────────
    if system_boundary:
        element_verification.validateArrangement(
            stickman_actors, box_actors, use_cases, system_boundary
        )

    element_verification.validateActorConnectivity(
        actors_with_meta, use_cases, connectors
    )
    element_verification.validateUsecaseConnectivity(
        use_cases, actors_with_meta, connectors
    )

    # ── Collect all elements into one table ──────────────────────────────
    all_elements = []
    for name, meta in actors_with_meta:
        sem_comments = [c for c in meta.get("Comments", [])
                        if "isolated" in c.lower() or "boundary" in c.lower()]
        action = "Attention Required!" if sem_comments else "Well Written"
        all_elements.append((name, meta.get("Element Type", "Actor"),
                             sem_comments, action))

    for name, meta in use_cases:
        sem_comments = [c for c in meta.get("Comments", [])
                        if "isolated" in c.lower() or "boundary" in c.lower()]
        action = "Attention Required!" if sem_comments else "Well Written"
        all_elements.append((name, "Use Case", sem_comments, action))

    ok   = sum(1 for *_, a in all_elements if a == "Well Written")
    err  = sum(1 for *_, a in all_elements if a == "Attention Required!")

    # ── Summary line (matches step 3/4 style) ────────────────────────────
    st.markdown(f"✅ {ok} passed &nbsp;|&nbsp; ❌ {err} issues")

    # ── Metrics row ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Primary Actors", len(stickman_actors))
    c2.metric("Secondary Actors", len(box_actors))
    c3.metric("Use Cases", len(use_cases))
    c4.metric("Connectors", len(connectors))

    # ── Results table ────────────────────────────────────────────────────
    data = []
    for name, elem_type, comments, action in all_elements:
        data.append({
            "Name": name,
            "Type": elem_type,
            "Comments": "\n".join(comments) if comments else "—",
            "Action": action,
        })

    df = pd.DataFrame(data)
    st.dataframe(_style_action(df), use_container_width=True, hide_index=True)

    if err > 0:
        st.markdown(
            "> **Tip:** Fix these issues in TTool and re-upload, or "
            "acknowledge them and continue to the next step."
        )

    render_navigation(next_label="Continue to Relationships")
