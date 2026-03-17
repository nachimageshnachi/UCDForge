"""Step 8: Actor Generalization (Child Actor - Parent Actor)."""

import streamlit as st
import pandas as pd
from generation.shared import (
    ensure_actor_colors, render_uc_uc_svg, render_summary_table,
)
from generation.step_manager import render_navigation, reset_from_step


def _actors():
    return st.session_state.get("ucd_actors") or []


def _pairs_from_relationships():
    actors = _actors()
    act_lo = {a.lower(): i for i, a in enumerate(actors)}
    pairs = set()
    for rel in st.session_state.get("ucd_relationships") or []:
        if (rel.get("relationship_type") or "").lower() != "generalization":
            continue
        if (rel.get("source_type") or "").lower() != "actor":
            continue
        if (rel.get("target_type") or "").lower() != "actor":
            continue
        s = str(rel.get("source_name", "")).strip().lower()
        t = str(rel.get("target_name", "")).strip().lower()
        if s in act_lo and t in act_lo:
            pairs.add((act_lo[s], act_lo[t]))
    return sorted(pairs)


def _sync_to_relationships(pairs):
    actors = _actors()
    others = []
    for r in st.session_state.get("ucd_relationships") or []:
        rt = (r.get("relationship_type") or "").lower()
        st_type = (r.get("source_type") or "").lower()
        if rt == "generalization" and st_type == "actor":
            continue
        others.append(r)

    gen = []
    seen = set()
    for _si, _ti in pairs:
        si, ti = int(_si), int(_ti)
        if si < 0 or ti < 0 or si >= len(actors) or ti >= len(actors):
            continue
        s, t = actors[si], actors[ti]
        key = (s.lower(), t.lower())
        if key in seen:
            continue
        seen.add(key)
        gen.append({
            "relationship_type": "generalization",
            "source_name": s, "source_type": "actor",
            "target_name": t, "target_type": "actor",
            "extension": "", "confidence": 0.95,
        })
    st.session_state.ucd_relationships = gen + others


def render():
    st.info(
        "- **What is actor generalization?** The *child* actor is a kind of "
        "the *parent* actor. It can do everything the parent does, plus more. "
        "Example: *Premium Customer* **is a kind of** *Customer*."
    )

    actors = _actors()
    if not actors:
        st.warning("No actors defined. Go back to Step 2.")
        render_navigation(show_next=False)
        return

    if "ucd_actor_gen_pairs" not in st.session_state:
        st.session_state.ucd_actor_gen_pairs = _pairs_from_relationships()

    actor_colors = ensure_actor_colors(actors)

    # --- Summary Table ---
    rows = []
    for _si, _ti in st.session_state.ucd_actor_gen_pairs:
        si, ti = int(_si), int(_ti)
        s = actors[si] if 0 <= si < len(actors) else "?"
        t = actors[ti] if 0 <= ti < len(actors) else "?"
        rows.append({"left": s, "right": t})
    render_summary_table(
        rows, "Child Actor", "is a kind of", "Parent Actor",
        "Actor Generalizations", icon="-", accent="#e7298a",
    )

    # --- Two tabs: Visual | Matrix --------------------------------------------
    tab_vis, tab_edit = st.tabs(["- Visual Diagram", "- Matrix Editor"])

    with tab_vis:
        render_uc_uc_svg(
            actors, actors, st.session_state.ucd_actor_gen_pairs,
            stroke_color="#6aa9ff", key="actg",
            color_map=actor_colors,
        )

    with tab_edit:
        # -- Matrix (NEW - was missing from step 8 previously) ------------
        st.markdown("**- Actor Generalization Matrix**")
        st.caption(
            "Rows = **Child Actor** (the specialized role)  -  "
            "Columns = **Parent Actor** (the general role it inherits from)  -  "
            "- = row is a kind of column"
        )
        data = {tn: [False] * len(actors) for tn in actors}
        for _si, _ti in st.session_state.ucd_actor_gen_pairs:
            si, ti = int(_si), int(_ti)
            if 0 <= si < len(actors) and 0 <= ti < len(actors):
                data[actors[ti]][si] = True
        df = pd.DataFrame(data, index=actors)
        df.index.name = "Child Actor  -  \\ Parent Actor -"

        edited = st.data_editor(df, use_container_width=True,
                                key="gen_actor_matrix")

        if st.button("- Apply Matrix Changes", key="gen_actor_matrix_apply",
                     use_container_width=True):
            new_pairs = sorted({
                (si, ti)
                for si, sn in enumerate(actors)
                for ti, tn in enumerate(actors)
                if bool(edited.loc[sn, tn]) and si != ti
            })
            st.session_state.ucd_actor_gen_pairs = new_pairs
            _sync_to_relationships(new_pairs)
            st.success("Actor generalizations updated!")
            st.rerun()

    # -- Quick Add / Remove ----------------------------------------------------
    st.divider()
    st.markdown("**Quick Add / Remove Actor Generalization**")
    c1, c2 = st.columns(2)
    with c1:
        src = st.selectbox("Child Actor", options=actors, key="gen_act_src")
    with c2:
        tgt = st.selectbox("Parent Actor", options=actors, key="gen_act_tgt")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("+ Add", key="gen_actor_add", use_container_width=True):
            if not src or not tgt:
                st.warning("Select both.")
            elif src == tgt:
                st.warning("Child and parent must differ.")
            else:
                si, ti = actors.index(src), actors.index(tgt)
                if (si, ti) not in st.session_state.ucd_actor_gen_pairs:
                    st.session_state.ucd_actor_gen_pairs.append((si, ti))
                    _sync_to_relationships(st.session_state.ucd_actor_gen_pairs)
                    st.success("Actor generalization added!")
                    st.rerun()
                else:
                    st.info("Already exists.")
    with b2:
        if st.button("- Remove", key="gen_actor_rm", use_container_width=True):
            if src and tgt and src != tgt:
                si, ti = actors.index(src), actors.index(tgt)
                if (si, ti) in st.session_state.ucd_actor_gen_pairs:
                    st.session_state.ucd_actor_gen_pairs.remove((si, ti))
                    _sync_to_relationships(st.session_state.ucd_actor_gen_pairs)
                    st.warning("Removed.")
                    st.rerun()



    # -- SysML v2 live diagram --------------------------------------------------
    st.divider()
    from generation.sysml_ucd import render_sysml_panel
    render_sysml_panel(key='step8')

    # Navigation
    def _on_confirm():
        _sync_to_relationships(st.session_state.ucd_actor_gen_pairs)
        reset_from_step(8)
        return True

    render_navigation(
        next_label="Confirm Actor Generalizations",
        on_next=_on_confirm,
    )
