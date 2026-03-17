"""Step 4: Associations - Actor - Use Case matching."""

import streamlit as st
import pandas as pd
from generation.shared import (
    dedupe, ensure_actor_colors, render_match_svg,
)
from generation.step_manager import render_navigation, reset_from_step


def _actors():
    return st.session_state.get("ucd_actors") or []

def _use_cases():
    return st.session_state.get("ucd_use_cases") or []


def _pairs_from_relationships():
    """Build actor-use-case pairs from the LLM-extracted relationships.
    No Python fallback guessing - pairs come exclusively from the LLM output.
    The ID-based second pass in helpers.py ensures every actor and use case
    has at least one association before we reach this step.
    """
    actors    = _actors()
    use_cases = _use_cases()
    if not actors or not use_cases:
        return []

    # Case-insensitive lookup maps so minor casing differences don't break pairing
    act_lo = {a.lower(): i for i, a in enumerate(actors)}
    uc_lo  = {u.lower(): i for i, u in enumerate(use_cases)}
    pairs  = set()

    def _fuzzy_lookup(name: str, lookup: dict) -> int | None:
        """Look up a name in the dict, trying exact - strip-s - add-s."""
        if name in lookup:
            return lookup[name]
        # strip trailing 's' (Operations - Operation)
        if name.endswith("s") and name[:-1] in lookup:
            return lookup[name[:-1]]
        # add trailing 's' (Operation - Operations)
        if name + "s" in lookup:
            return lookup[name + "s"]
        return None

    for rel in st.session_state.get("ucd_relationships") or []:
        rt    = (rel.get("relationship_type") or "").lower()
        stype = (rel.get("source_type") or "").lower()
        ttype = (rel.get("target_type") or "").lower()
        sname = str(rel.get("source_name") or "").strip().lower()
        tname = str(rel.get("target_name") or "").strip().lower()
        if rt != "association":
            continue
        if stype == "actor" and ttype == "usecase":
            ai = _fuzzy_lookup(sname, act_lo)
            ui = _fuzzy_lookup(tname, uc_lo)
            if ai is not None and ui is not None:
                pairs.add((ai, ui))
        elif stype == "usecase" and ttype == "actor":
            ai = _fuzzy_lookup(tname, act_lo)
            ui = _fuzzy_lookup(sname, uc_lo)
            if ai is not None and ui is not None:
                pairs.add((ai, ui))

    return sorted(pairs)






def _sync_pairs_to_relationships(pairs):
    actors = _actors()
    use_cases = _use_cases()
    others = [r for r in (st.session_state.get("ucd_relationships") or [])
              if (r.get("relationship_type") or "").lower() != "association"]
    assoc = []
    seen = set()
    for ai, ui in pairs:
        if ai < 0 or ai >= len(actors) or ui < 0 or ui >= len(use_cases):
            continue
        a, u = actors[ai], use_cases[ui]
        key = (a.lower(), u.lower())
        if key in seen:
            continue
        seen.add(key)
        assoc.append({
            "relationship_type": "association",
            "source_name": a, "source_type": "actor",
            "target_name": u, "target_type": "usecase",
            "extension": "", "confidence": 0.95,
        })
    st.session_state.ucd_relationships = assoc + others


# ---------------------------------------------------------------------------
# Match-the-Following table renderer
# ---------------------------------------------------------------------------

def _render_match_table(actors, use_cases, pairs, actor_colors):
    actor_ucs = {a: [] for a in actors}
    for ai, ui in pairs:
        if 0 <= ai < len(actors) and 0 <= ui < len(use_cases):
            actor_ucs[actors[ai]].append(use_cases[ui])

    rows = []
    for a in actors:
        ucs_here = actor_ucs.get(a, [])
        if ucs_here:
            for uc in ucs_here:
                rows.append({"Actor -": a, "Use Case -": uc})
        else:
            rows.append({"Actor -": a, "Use Case -": "- (none yet)"})

    matched_ucs = {use_cases[ui] for _, ui in pairs if 0 <= ui < len(use_cases)}
    for uc in use_cases:
        if uc not in matched_ucs:
            rows.append({"Actor -": "-- No actor", "Use Case -": uc})

    n = len(pairs)
    st.markdown(
        f"**- Match the Following - Who performs what?**  "
        f"&nbsp;&nbsp;*{n} association{'s' if n != 1 else ''}*"
    )
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render():
    st.info(
        "- **What is an association?** An association links an actor to a "
        "use case they interact with. Example: *Customer* performs *Place Order*."
    )

    actors = _actors()
    use_cases = _use_cases()

    if not actors or not use_cases:
        st.warning("No actors or use cases defined. Go back to Step 2.")
        render_navigation(show_next=False)
        return

    actor_colors = ensure_actor_colors(actors)

    if "ucd_match_pairs" not in st.session_state:
        st.session_state.ucd_match_pairs = _pairs_from_relationships()
    else:
        # Normalise: old session files stored dicts; convert to (int, int) tuples
        _raw = st.session_state.ucd_match_pairs or []
        _normalised = []
        for p in _raw:
            if isinstance(p, (list, tuple)) and len(p) == 2:
                try:
                    _normalised.append((int(p[0]), int(p[1])))
                except (ValueError, TypeError):
                    pass
            elif isinstance(p, dict):
                # session_io XML loader produces dicts: {"item_0": "0", "item_1": "1"}
                try:
                    _normalised.append((int(p.get("item_0", p.get(0, -1))),
                                        int(p.get("item_1", p.get(1, -1)))))
                except (ValueError, TypeError):
                    pass  # bad entry - will trigger regeneration
        if len(_normalised) != len(_raw) or any(a < 0 or b < 0 for a, b in _normalised):
            # Had bad entries - regenerate cleanly from relationships
            st.session_state.ucd_match_pairs = _pairs_from_relationships()
        else:
            st.session_state.ucd_match_pairs = _normalised
            # Auto-fix: regenerate if any use case or actor is uncovered
            _pairs_set = set(_normalised)
            _matched_ucs  = {ui for _, ui in _pairs_set}
            _matched_acts = {ai for ai, _ in _pairs_set}
            if len(_matched_ucs) < len(use_cases) or len(_matched_acts) < len(actors):
                st.session_state.ucd_match_pairs = _pairs_from_relationships()


    # --- Match-the-Following summary table ---
    _render_match_table(actors, use_cases,
                        st.session_state.ucd_match_pairs, actor_colors)

    # --- Two tabs: Visual | Matrix --------------------------------------------
    tab_vis, tab_edit = st.tabs(["- Visual Diagram", "- Matrix Editor"])

    with tab_vis:
        if "ucd_visible_actors" not in st.session_state:
            st.session_state.ucd_visible_actors = list(actors)
        else:
            st.session_state.ucd_visible_actors = [
                a for a in (st.session_state.ucd_visible_actors or [])
                if a in actors
            ]

        visible_actors = st.multiselect(
            "Filter actors",
            options=actors,
            key="ucd_visible_actors",
            help="Show only selected actors' connections",
        )

        filtered_pairs = [
            p for p in st.session_state.ucd_match_pairs
            if not visible_actors or (actors[p[0]] in visible_actors)
        ]
        render_match_svg(actors, use_cases, filtered_pairs,
                         visible_actors, actor_colors)

    with tab_edit:
        # -- Matrix ----------------------------------------------------------
        st.markdown("**- Association Matrix**")
        st.caption(
            "Rows = **Actors** (who performs)  -  "
            "Columns = **Use Cases** (what is performed)  -  "
            "- = associated"
        )
        data = {uc: [False] * len(actors) for uc in use_cases}
        for ai, ui in st.session_state.ucd_match_pairs or []:
            if 0 <= ai < len(actors) and 0 <= ui < len(use_cases):
                data[use_cases[ui]][ai] = True
        df = pd.DataFrame(data, index=actors)
        df.index.name = "Actor  -  \ Use Case -"

        edited = st.data_editor(df, use_container_width=True,
                                key="assoc_matrix_editor")

        c_l, c_r = st.columns(2)
        with c_l:
            if st.button("- Select All", key="assoc_sel_all"):
                for c in edited.columns:
                    edited[c] = True
                st.session_state.assoc_matrix_editor = edited
                st.rerun()
        with c_r:
            if st.button("-- Clear All", key="assoc_clear_all"):
                for c in edited.columns:
                    edited[c] = False
                st.session_state.assoc_matrix_editor = edited
                st.rerun()

        if st.button("- Apply Matrix Changes", key="assoc_matrix_apply",
                     use_container_width=True):
            new_pairs = sorted({
                (ai, ui)
                for ai, aname in enumerate(actors)
                for ui, uname in enumerate(use_cases)
                if bool(edited.loc[aname, uname])
            })
            st.session_state.ucd_match_pairs = new_pairs
            _sync_pairs_to_relationships(new_pairs)
            st.success("Associations updated from matrix!")
            st.rerun()

    # -- Quick Add / Remove ----------------------------------------------------
    st.divider()
    st.markdown("**- Quick Add / Remove Association**")
    c1, c2 = st.columns(2)
    with c1:
        sel_actor = st.selectbox("Actor", options=actors,
                                 key="match_add_actor")
    with c2:
        sel_uc = st.selectbox("Use Case", options=use_cases,
                              key="match_add_uc")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("- Add", key="match_add_btn", use_container_width=True):
            if sel_actor and sel_uc:
                ai, ui = actors.index(sel_actor), use_cases.index(sel_uc)
                if (ai, ui) not in st.session_state.ucd_match_pairs:
                    st.session_state.ucd_match_pairs.append((ai, ui))
                    _sync_pairs_to_relationships(st.session_state.ucd_match_pairs)
                    st.success(f"- Linked {sel_actor} - {sel_uc}")
                    st.rerun()
                else:
                    st.info("Already linked.")
    with b2:
        if st.button("- Remove", key="match_rm_btn", use_container_width=True):
            if sel_actor and sel_uc:
                ai, ui = actors.index(sel_actor), use_cases.index(sel_uc)
                if (ai, ui) in st.session_state.ucd_match_pairs:
                    st.session_state.ucd_match_pairs.remove((ai, ui))
                    _sync_pairs_to_relationships(st.session_state.ucd_match_pairs)
                    st.warning("Removed.")
                    st.rerun()


    # -- SysML v2 live diagram --------------------------------------------------
    st.divider()
    from generation.sysml_ucd import render_sysml_panel
    render_sysml_panel(key='step4')

    # Navigation
    def _on_confirm():
        _sync_pairs_to_relationships(st.session_state.ucd_match_pairs)
        reset_from_step(4)
        return True

    render_navigation(
        next_label="Confirm Associations",
        on_next=_on_confirm,
    )
