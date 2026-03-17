"""Step 6 (Wizard): Relationship verification.

NOTE: This file is named step5_relationships.py but renders WIZARD STEP 6.
A UCD Semantics step was inserted between the original Steps 4 and 5,
shifting all downstream file numbers by one. The wizard step number is
authoritative; the filename is kept as-is to avoid breaking imports.
"""

import streamlit as st

from verification.element_verification import element_verification
from verification.step_manager import (
    render_navigation, current_diagram, current_diagram_index,
    total_diagrams, advance_diagram, complete_step, go_to_step,
    current_step,
)


def render():
    d_info = current_diagram()
    if not d_info:
        st.warning("No diagram data available. Please go back to Step 1.")
        return

    tab_name, ucd_index, ucd_name, details = d_info

    st.write(
        "Review and confirm the auto-detected relationship types. "
        "Also runs arrangement, connectivity, and relation-semantics checks."
    )

    connectors = details.get('Connectors', [])
    stickman_actors = details.get("Primary Actors", [])
    box_actors = details.get("Secondary Actors", [])
    use_cases = details.get("Use Cases", [])
    system_boundary = details.get("System Boundary", [])
    actors_with_meta = stickman_actors + box_actors

    # Run structural checks
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
    element_verification.validateRelations(
        connectors, actors_with_meta, use_cases
    )

    # Filter to classifiable relations only
    classifiable = [
        (idx, conn) for idx, conn in enumerate(connectors)
        if conn[1].get("Relation Value", "") in ["Include", "Extend", "Generalization"]
    ]

    if not classifiable:
        st.info("No Include/Extend/Generalization connectors in this diagram — auto-confirmed.")
        _render_advance_button()
        return

    # Show classification UI
    st.markdown("""
    - **Include** → Target use case is always part of the source.
    - **Extend** → Target use case happens optionally under certain conditions.
    - **Generalization** → Target is a specialized version of the source.
    - **None of the Above** → You are unsure or believe none of the above apply.
    """)

    user_choices = {}
    relation_keys = ["Include", "Extend", "Generalization", "None of the Above"]

    i = 1
    for idx, conn in classifiable:
        conn_id, conn_data = conn
        rel_val = conn_data.get("Relation Value", "")

        A = conn_data['Source Name']
        B = conn_data['Target Name']
        src = f"{conn_data['Source Name']} ({conn_data['Source Type']})"
        tgt = f"{conn_data['Target Name']} ({conn_data['Target Type']})"

        radio_options = [
            f"Include - if {B} should always occur if {A} occurs",
            f"Extend - if {B} should optionally occur after {A} occurs",
            f"Generalization - if {A} can be subcategorized into {B}",
            f"None of the Above - Does none of these apply"
        ]

        option_to_type = {
            radio_options[0]: "Include",
            radio_options[1]: "Extend",
            radio_options[2]: "Generalization",
            radio_options[3]: "None of the Above"
        }

        default_index = relation_keys.index(rel_val) if rel_val in relation_keys else 3

        st.markdown(f"#### {i}. {rel_val} Relationship Verification")
        i += 1
        st.markdown(f"`{src}` → `{tgt}`")
        st.markdown(f"**Auto-detected:** `{rel_val}`")

        selected_label = st.radio(
            label="Select Appropriate Relationship Type:",
            options=radio_options,
            index=default_index,
            key=f"ver_reltype_{tab_name}_{ucd_name}_{conn_id}_{idx}"
        )

        selected_type = option_to_type[selected_label]
        disable_reverse = selected_type == "None of the Above"

        reverse_key = f"ver_reverse_{tab_name}_{ucd_name}_{conn_id}_{idx}"
        if disable_reverse:
            st.session_state[reverse_key] = False

        reverse = st.checkbox(
            label=f"Should the relationship direction be reversed from {B} → {A} ?",
            key=reverse_key,
            disabled=disable_reverse
        )

        user_choices[conn_id] = {
            "type": selected_type,
            "reverse": reverse
        }

        st.markdown("---")

    if user_choices:
        if st.button(f"Confirm Classifications", key=f"ver_confirm_{tab_name}_{ucd_name}_{ucd_index}",
                      type="primary", use_container_width=True):
            action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
            for conn in connectors:
                conn_id = conn[0]
                if conn_id in user_choices:
                    choice = user_choices[conn_id]
                    new_val = choice["type"]
                    reverse = choice["reverse"]
                    old_val = conn[1]["Relation Value"]

                    comment = []
                    action_level = 0

                    source = f"{conn[1]['Source Name']} ({conn[1]['Source Type']})"
                    target = f"{conn[1]['Target Name']} ({conn[1]['Target Type']})"
                    A = conn[1]['Source Name']

                    if new_val == "None of the Above":
                        comment.append(f"'{source}' → {target} are expected to be independent elements. Remove the '{old_val}' relationship between them.")
                        action_level = max(action_level, 2)
                    else:
                        if reverse:
                            comment.append(f"'{source}' → '{target}' should be reversed to '{target}' → '{source}'.")
                            action_level = max(action_level, 2)
                            if old_val != new_val:
                                comment.append(f"Replace '{old_val}' with '{new_val}' relationship (reversed direction).")
                                action_level = max(action_level, 2)
                        else:
                            if old_val != new_val:
                                comment.append(f"Replace '{old_val}' with '{new_val}' relationship.")
                                action_level = max(action_level, 2)

                        if new_val == "Extend":
                            comment.append(f"Don't forget to add 'Extension Point' in the use case {A}.")
                        if new_val == "Include" and old_val == "Extend":
                            comment.append(f"Don't forget to remove 'Extension Point' from the use case {A}.")

                    action = action_map[action_level]
                    conn[1]["Comments"].extend(comment)
                    conn[1]["Action"] = action

            # Advance to next diagram or results
            advance_diagram()


def _render_advance_button():
    """Show a button to advance to the next diagram or to results."""
    d_idx = current_diagram_index()
    d_total = total_diagrams()

    st.divider()
    col_prev, col_space, col_next = st.columns([1, 2, 1])
    with col_prev:
        cur = current_step()
        if cur > 1:
            if st.button("Previous", key=f"ver_nav_prev_{cur}",
                         use_container_width=True):
                go_to_step(cur - 1)
    with col_next:
        if d_idx + 1 < d_total:
            label = f"Next Diagram ({d_idx + 2}/{d_total})"
        else:
            label = "View Results & Download"
        if st.button(label, key="ver_advance_diagram",
                     use_container_width=True, type="primary"):
            advance_diagram()
