"""Step 2: System Verification — verify system boundary name for the current diagram."""

import streamlit as st
import pandas as pd

from verification.element_verification import element_verification
from verification.step_manager import render_navigation, current_diagram


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

    st.write("Verify the System Boundary name for this Use Case Diagram.")

    system_boundary = details.get("System Boundary", [])
    if not system_boundary:
        st.info("No system boundary found in this diagram.")
        render_navigation(next_label="Continue to Actors Verification")
        return

    sys_name = system_boundary[0][0]
    sys_meta = system_boundary[0][1]

    # Run verification
    comments, action = element_verification.validateSystem(sys_name)
    priority = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
    prev = sys_meta.get("Action") or "Well Written"
    if priority.get(action, 0) > priority.get(prev, 0):
        sys_meta["Comments"] = comments
        sys_meta["Action"] = action
    elif not sys_meta.get("Action"):
        sys_meta["Comments"] = comments
        sys_meta["Action"] = action

    # Summary line (matches step 3/4 style)
    if action == "Well Written":
        st.markdown("1 well written &nbsp;|&nbsp; 0 warnings &nbsp;|&nbsp; 0 issues")
    elif action == "Warning!":
        st.markdown("0 well written &nbsp;|&nbsp; 1 warning &nbsp;|&nbsp; 0 issues")
    else:
        st.markdown("0 well written &nbsp;|&nbsp; 0 warnings &nbsp;|&nbsp; 1 issue")

    # Results table
    data = [{
        "Name": sys_name,
        "Type": "System Boundary",
        "Comments": "\n".join(comments) if comments else "—",
        "Action": action,
    }]

    df = pd.DataFrame(data)
    st.dataframe(_style_action(df), use_container_width=True, hide_index=True)

    render_navigation(next_label="Continue to Actors Verification")
