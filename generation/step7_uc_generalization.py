"""Step 7: Use Case Generalization (Child UC - Parent UC)."""

import streamlit as st
import pandas as pd
from generation.shared import render_uc_uc_svg, render_summary_table
from generation.step_manager import render_navigation, reset_from_step


def _use_cases():
    return st.session_state.get("ucd_use_cases") or []


def _pairs_from_relationships():
    ucs = _use_cases()
    uc_lo = {u.lower(): i for i, u in enumerate(ucs)}
    pairs = set()
    for rel in st.session_state.get("ucd_relationships") or []:
        if (rel.get("relationship_type") or "").lower() != "generalization":
            continue
        if (rel.get("source_type") or "").lower() != "usecase":
            continue
        if (rel.get("target_type") or "").lower() != "usecase":
            continue
        s = str(rel.get("source_name", "")).strip().lower()
        t = str(rel.get("target_name", "")).strip().lower()
        if s in uc_lo and t in uc_lo:
            pairs.add((uc_lo[s], uc_lo[t]))
    return sorted(pairs)


def _sync_to_relationships(pairs):
    ucs = _use_cases()
    others = []
    for r in st.session_state.get("ucd_relationships") or []:
        rt = (r.get("relationship_type") or "").lower()
        st_type = (r.get("source_type") or "").lower()
        if rt == "generalization" and st_type == "usecase":
            continue
        others.append(r)

    gen = []
    seen = set()
    for _si, _ti in pairs:
        si, ti = int(_si), int(_ti)
        if si < 0 or ti < 0 or si >= len(ucs) or ti >= len(ucs):
            continue
        s, t = ucs[si], ucs[ti]
        key = (s.lower(), t.lower())
        if key in seen:
            continue
        seen.add(key)
        gen.append({
            "relationship_type": "generalization",
            "source_name": s, "source_type": "usecase",
            "target_name": t, "target_type": "usecase",
            "extension": "", "confidence": 0.95,
        })
    st.session_state.ucd_relationships = gen + others


def render():
    st.info(
        "- **What is UC generalization?** The *child* use case is a "
        "specialized version of the *parent*. It inherits the parent's steps "
        "and adds details. Example: *Online Payment* **is a kind of** *Payment*."
    )

    ucs = _use_cases()
    if not ucs:
        st.warning("No use cases defined. Go back to Step 2.")
        render_navigation(show_next=False)
        return

    if "ucd_uc_gen_pairs" not in st.session_state:
        st.session_state.ucd_uc_gen_pairs = _pairs_from_relationships()

    # --- Summary Table ---
    rows = []
    for _si, _ti in st.session_state.ucd_uc_gen_pairs:
        si, ti = int(_si), int(_ti)
        s = ucs[si] if 0 <= si < len(ucs) else "?"
        t = ucs[ti] if 0 <= ti < len(ucs) else "?"
        rows.append({"left": s, "right": t})
    render_summary_table(
        rows, "Child UC", "is a kind of", "Parent UC",
        "UC Generalizations", icon="-", accent="#7570b3",
    )

    # --- Two tabs: Visual | Matrix --------------------------------------------
    tab_vis, tab_edit = st.tabs(["- Visual Diagram", "- Matrix Editor"])

    with tab_vis:
        render_uc_uc_svg(ucs, ucs, st.session_state.ucd_uc_gen_pairs,
                         stroke_color="#6aa9ff", key="ucg")

    with tab_edit:
        # -- Matrix ----------------------------------------------------------
        st.markdown("**- UC Generalization Matrix**")
        st.caption(
            "Rows = **Child Use Case** (the specialized version)  -  "
            "Columns = **Parent Use Case** (the general version it inherits from)  -  "
            "- = row is a kind of column"
        )
        data = {tn: [False] * len(ucs) for tn in ucs}
        for _si, _ti in st.session_state.ucd_uc_gen_pairs:
            si, ti = int(_si), int(_ti)
            if 0 <= si < len(ucs) and 0 <= ti < len(ucs):
                data[ucs[ti]][si] = True
        df = pd.DataFrame(data, index=ucs)
        df.index.name = "Child UC  -  \\ Parent UC -"

        edited = st.data_editor(df, use_container_width=True,
                                key="gen_uc_matrix")

        if st.button("- Apply Matrix Changes", key="gen_uc_matrix_apply",
                     use_container_width=True):
            new_pairs = sorted({
                (si, ti)
                for si, sn in enumerate(ucs)
                for ti, tn in enumerate(ucs)
                if bool(edited.loc[sn, tn]) and si != ti
            })
            st.session_state.ucd_uc_gen_pairs = new_pairs
            _sync_to_relationships(new_pairs)
            st.success("UC generalizations updated!")
            st.rerun()

    # -- Quick Add / Remove ----------------------------------------------------
    st.divider()
    st.markdown("**Quick Add / Remove UC Generalization**")
    c1, c2 = st.columns(2)
    with c1:
        src = st.selectbox("Child Use Case", options=ucs, key="gen_uc_src")
    with c2:
        tgt = st.selectbox("Parent Use Case", options=ucs, key="gen_uc_tgt")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("+ Add", key="gen_uc_add", use_container_width=True):
            if not src or not tgt:
                st.warning("Select both.")
            elif src == tgt:
                st.warning("Child and parent must differ.")
            else:
                si, ti = ucs.index(src), ucs.index(tgt)
                if (si, ti) not in st.session_state.ucd_uc_gen_pairs:
                    st.session_state.ucd_uc_gen_pairs.append((si, ti))
                    _sync_to_relationships(st.session_state.ucd_uc_gen_pairs)
                    st.success("UC generalization added!")
                    st.rerun()
                else:
                    st.info("Already exists.")
    with b2:
        if st.button("- Remove", key="gen_uc_rm", use_container_width=True):
            if src and tgt and src != tgt:
                si, ti = ucs.index(src), ucs.index(tgt)
                if (si, ti) in st.session_state.ucd_uc_gen_pairs:
                    st.session_state.ucd_uc_gen_pairs.remove((si, ti))
                    _sync_to_relationships(st.session_state.ucd_uc_gen_pairs)
                    st.warning("Removed.")
                    st.rerun()



    # -- SysML v2 live diagram --------------------------------------------------
    st.divider()
    from generation.sysml_ucd import render_sysml_panel
    render_sysml_panel(key='step7')

    # Navigation
    def _on_confirm():
        _sync_to_relationships(st.session_state.ucd_uc_gen_pairs)
        reset_from_step(7)
        return True

    render_navigation(
        next_label="Confirm UC Generalizations",
        on_next=_on_confirm,
    )
