"""Step 3 (Wizard): Edit Actors & Use Cases - add, remove, recategorize elements.

NOTE: This file is named step2_elements.py but renders WIZARD STEP 3.
A Hybrid Retrieval step was inserted between the original Steps 1 and 2,
shifting all downstream file numbers by one. The wizard step number is
authoritative; the filename is kept as-is to avoid breaking imports.
"""

import streamlit as st
from generation.shared import (
    dedupe, load_db_values, build_suggestion_lists,
)
from generation.step_manager import render_navigation, reset_from_step
from helpers_old import reverse_lookup, TextValidationTools  # type: ignore


# ---------------------------------------------------------------------------
# Unified "search or type custom" add-widget
# ---------------------------------------------------------------------------

def _render_add_widget(label, suggestions, key_prefix, on_add):
    """Single text input: shows DB matches while typing, falls back to custom."""
    counter_key = f"_cnt_{key_prefix}"
    counter = st.session_state.get(counter_key, 0)

    def _add_and_clear(name):
        st.session_state[counter_key] = counter + 1
        on_add(name)

    typed = st.text_input(
        f"Add {label}",
        key=f"{key_prefix}_input_{counter}",
        placeholder=f"Type to search knowledge base or add custom {label}-",
        label_visibility="collapsed",
    )
    typed_stripped = (typed or "").strip()

    if not typed_stripped:
        return  # nothing typed yet - show nothing

    lower = typed_stripped.lower()
    matches = [s for s in suggestions if lower in s.lower()]

    if matches:
        # Show filtered DB suggestions
        chosen = st.selectbox(
            f"Suggestions ({len(matches)})",
            options=matches,
            key=f"{key_prefix}_sel_{counter}",
            label_visibility="collapsed",
        )
        c1, c2 = st.columns([3, 2])
        with c1:
            if st.button(f"- Add \"{chosen}\"",
                         key=f"{key_prefix}_pick_{counter}",
                         use_container_width=True):
                _add_and_clear(chosen)
        with c2:
            # Only show custom button if typed text differs from chosen
            if chosen.lower() != typed_stripped.lower():
                if st.button(f"- Add \"{typed_stripped}\" (custom)",
                             key=f"{key_prefix}_cust_{counter}",
                             use_container_width=True):
                    _add_and_clear(typed_stripped)
    else:
        # Nothing in DB - auto-fall through to custom
        st.caption(f"- Not found in knowledge base - adding as custom.")
        if st.button(f"- Add \"{typed_stripped}\"",
                     key=f"{key_prefix}_cust_{counter}",
                     use_container_width=True):
            _add_and_clear(typed_stripped)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render():
    st.markdown(
        "Review and adjust the actors and use cases. "
        "**Type to search** the knowledge base or enter a custom name. "
        "**Changes here will reset any relationships set in later steps.**"
    )

    # Load DB suggestions
    db_vals = load_db_values()
    actors_expanded = (db_vals or {}).get("actors", {})
    ucs_expanded = (db_vals or {}).get("use_cases", {})
    actor_suggestions, uc_suggestions = build_suggestion_lists(db_vals)

    # -------------------------------------------------------------------
    # CBR Suggestions Panel — show KB-suggested items the user can accept
    # -------------------------------------------------------------------
    top_case = st.session_state.get("cbr_top_case")
    sug_prim = st.session_state.get("cbr_suggested_primary") or []
    sug_sec  = st.session_state.get("cbr_suggested_secondary") or []
    sug_ucs  = st.session_state.get("cbr_suggested_use_cases") or []

    has_suggestions = sug_prim or sug_sec or sug_ucs
    if top_case and has_suggestions:
        with st.expander(
            f"🔍 **KB Suggestion** — Chosen case: "
            f"*{top_case.get('title', '?')}* "
            f"(relevance {float(top_case.get('relevance', 0)):.2f})",
            expanded=True,
        ):
            st.caption(
                "The knowledge base case you selected in retrieval is shown here. "
                "You can accept these suggested elements or skip them."
            )

            # --- Suggested Actors ---
            if sug_prim or sug_sec:
                st.markdown("**Suggested Actors:**")
                all_sug_actors = (
                    [(a, "primary") for a in sug_prim] +
                    [(a, "secondary") for a in sug_sec]
                )
                for i, (a, kind) in enumerate(all_sug_actors):
                    cols = st.columns([4, 1])
                    cols[0].write(f"- {a} *({kind})*")
                    if cols[1].button("+ Add", key=f"cbr_add_act_{i}",
                                      use_container_width=True):
                        _do_add_actor(a, kind, actors_expanded)

            # --- Suggested Use Cases ---
            if sug_ucs:
                st.markdown("**Suggested Use Cases:**")
                for i, u in enumerate(sug_ucs):
                    cols = st.columns([4, 1])
                    cols[0].write(f"- {u}")
                    if cols[1].button("+ Add", key=f"cbr_add_uc_{i}",
                                      use_container_width=True):
                        _do_add_use_case(u, ucs_expanded)

            # --- Accept All ---
            if st.button("✅ Accept All Suggestions",
                         use_container_width=True, type="primary",
                         key="cbr_accept_all"):
                for a in sug_prim:
                    key_list = "ucd_primary_actors"
                    st.session_state[key_list] = dedupe(
                        (st.session_state.get(key_list) or []) + [a])
                    st.session_state.ucd_actors = dedupe(
                        (st.session_state.get("ucd_actors") or []) + [a])
                for a in sug_sec:
                    key_list = "ucd_secondary_actors"
                    st.session_state[key_list] = dedupe(
                        (st.session_state.get(key_list) or []) + [a])
                    st.session_state.ucd_actors = dedupe(
                        (st.session_state.get("ucd_actors") or []) + [a])
                for u in sug_ucs:
                    st.session_state.ucd_use_cases = dedupe(
                        (st.session_state.get("ucd_use_cases") or []) + [u])
                # Merge suggested relationships into session
                sug_rels = st.session_state.get(
                    "cbr_suggested_relationships") or []
                if sug_rels:
                    st.session_state.ucd_relationships = list(
                        st.session_state.get("ucd_relationships") or []
                    ) + sug_rels
                # Clear suggestions so they don't show again
                st.session_state.cbr_suggested_primary = []
                st.session_state.cbr_suggested_secondary = []
                st.session_state.cbr_suggested_use_cases = []
                st.session_state.cbr_suggested_relationships = []
                st.session_state["_reset_primary_multiselect"] = True
                st.session_state["_reset_secondary_multiselect"] = True
                st.session_state["_reset_usecases_multiselect"] = True
                st.rerun()

    # Handle widget resets from add actions
    for flag, widget_key in [
        ("_reset_primary_multiselect", "ucd_primary_multiselect"),
        ("_reset_secondary_multiselect", "ucd_secondary_multiselect"),
        ("_reset_usecases_multiselect", "ucd_usecases_multiselect"),
    ]:
        if st.session_state.pop(flag, False):
            st.session_state.pop(widget_key, None)

    # ---- Primary & Secondary Actors ----
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Primary Actors")
        prim_options = st.session_state.get("ucd_actors") or []
        if prim_options:
            prim_selected = st.multiselect(
                "Select primary actors",
                options=prim_options,
                default=st.session_state.get("ucd_primary_actors") or [],
                key="ucd_primary_multiselect",
                label_visibility="collapsed",
            )
        else:
            st.caption("_No actors yet - add below._")

        def _add_primary(name):
            _do_add_actor(name, "primary", actors_expanded)

        _render_add_widget("actor", actor_suggestions,
                           "prim", _add_primary)

    with c2:
        st.subheader("Secondary Actors")
        sec_options = st.session_state.get("ucd_actors") or []
        if sec_options:
            sec_selected = st.multiselect(
                "Select secondary actors",
                options=sec_options,
                default=st.session_state.get("ucd_secondary_actors") or [],
                key="ucd_secondary_multiselect",
                label_visibility="collapsed",
            )
        else:
            st.caption("_No actors yet - add below._")

        def _add_secondary(name):
            _do_add_actor(name, "secondary", actors_expanded)

        _render_add_widget("actor", actor_suggestions,
                           "sec", _add_secondary)

    # ---- Use Cases ----
    st.subheader("Use Cases")
    uc_options = st.session_state.get("ucd_use_cases") or []
    if uc_options:
        uc_selected = st.multiselect(
            "Select or keep extracted use cases",
            options=uc_options,
            default=uc_options,
            key="ucd_usecases_multiselect",
            label_visibility="collapsed",
        )
    else:
        st.caption("_No use cases yet - add below._")

    def _add_uc(name):
        _do_add_use_case(name, ucs_expanded)

    _render_add_widget("use case", uc_suggestions, "uc", _add_uc)

    # ---- Save / Confirm ----
    def _on_confirm():
        st.session_state.ucd_primary_actors = dedupe(
            st.session_state.get("ucd_primary_multiselect") or [])
        st.session_state.ucd_secondary_actors = dedupe(
            st.session_state.get("ucd_secondary_multiselect") or [])
        st.session_state.ucd_use_cases = dedupe(
            st.session_state.get("ucd_usecases_multiselect") or [])
        st.session_state.ucd_actors = dedupe(
            st.session_state.ucd_primary_actors +
            st.session_state.ucd_secondary_actors
        )
        st.session_state.ucd_elements_saved = True
        reset_from_step(3)  # This file renders Step 3; reset steps 4+ when elements change
        return True

    render_navigation(
        next_label="Save Elements & Continue",
        on_next=_on_confirm,
    )


# ---- Private helpers ----

def _do_add_actor(name, kind, actors_expanded):
    """Add an actor by name."""
    chosen = (name or "").strip()
    if not chosen:
        return
    mapped = reverse_lookup(actors_expanded, chosen)
    to_add = [mapped] if mapped else [chosen]
    if mapped and TextValidationTools.normalize(mapped) != \
       TextValidationTools.normalize(chosen):
        to_add.append(chosen)

    key_list = f"ucd_{kind}_actors"
    st.session_state[key_list] = dedupe(
        (st.session_state.get(key_list) or []) + to_add)
    st.session_state.ucd_actors = dedupe(
        (st.session_state.get("ucd_actors") or []) + to_add)
    st.session_state[f"_reset_{kind}_multiselect"] = True
    st.rerun()


def _do_add_use_case(name, ucs_expanded):
    """Add a use case by name."""
    chosen = (name or "").strip()
    if not chosen:
        return
    mapped = reverse_lookup(ucs_expanded, chosen)
    to_add = [mapped] if mapped else [chosen]
    if mapped and TextValidationTools.normalize(mapped) != \
       TextValidationTools.normalize(chosen):
        to_add.append(chosen)

    st.session_state.ucd_use_cases = dedupe(
        (st.session_state.get("ucd_use_cases") or []) + to_add)
    st.session_state._reset_usecases_multiselect = True
    st.rerun()
