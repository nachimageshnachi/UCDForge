"""Step 5: Include Relationships (UC - UC)."""

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
        if (rel.get("relationship_type") or "").lower() != "include":
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
    others = [r for r in (st.session_state.get("ucd_relationships") or [])
              if (r.get("relationship_type") or "").lower() != "include"]
    inc = []
    seen = set()
    extend_set = set(st.session_state.get("ucd_extend_pairs") or [])
    for _si, _ti in pairs:
        si, ti = int(_si), int(_ti)
        if si < 0 or ti < 0 or si >= len(ucs) or ti >= len(ucs):
            continue
        s, t = ucs[si], ucs[ti]
        key = (s.lower(), t.lower())
        if key in seen or (si, ti) in extend_set:
            continue
        seen.add(key)
        inc.append({
            "relationship_type": "include",
            "source_name": s, "source_type": "usecase",
            "target_name": t, "target_type": "usecase",
            "extension": "", "confidence": 0.95,
        })
    st.session_state.ucd_relationships = inc + others


def render():
    st.info(
        "- **What is an include?** An include means the *base use case* "
        "always invokes the *included use case* as a mandatory sub-step. "
        "Example: *Checkout* **includes** *Calculate Total*."
    )

    ucs = _use_cases()
    if not ucs:
        st.warning("No use cases defined. Go back to Step 2.")
        render_navigation(show_next=False)
        return

    recomputed = set(_pairs_from_relationships())
    existing = set(st.session_state.get("ucd_include_pairs") or [])
    st.session_state.ucd_include_pairs = sorted(recomputed | existing)

    # --- Summary Table ---
    rows = []
    for _si, _ti in st.session_state.ucd_include_pairs:
        si, ti = int(_si), int(_ti)
        s = ucs[si] if 0 <= si < len(ucs) else "?"
        t = ucs[ti] if 0 <= ti < len(ucs) else "?"
        rows.append({"left": s, "right": t})
    render_summary_table(
        rows, "Base Use Case", "-includes-", "Included Use Case",
        "Include Relationships", icon="-", accent="#1f78b4",
    )

    # --- Two tabs: Visual | Matrix --------------------------------------------
    labels = {f"{int(_si)}|{int(_ti)}": "includes"
              for _si, _ti in st.session_state.ucd_include_pairs}
    tab_vis, tab_edit = st.tabs(["- Visual Diagram", "- Matrix Editor"])

    with tab_vis:
        render_uc_uc_svg(ucs, ucs, st.session_state.ucd_include_pairs,
                         stroke_color="#6aa9ff", labels=labels, key="inc")

    with tab_edit:
        # -- Matrix ----------------------------------------------------------
        st.markdown("**- Include Matrix**")
        st.caption(
            "Rows = **Base Use Case** (the one that always calls the other)  -  "
            "Columns = **Included Use Case** (the mandatory sub-step)  -  "
            "- = base row -includes- column"
        )
        data = {right: [False] * len(ucs) for right in ucs}
        for _si, _ti in st.session_state.ucd_include_pairs:
            si, ti = int(_si), int(_ti)
            if 0 <= si < len(ucs) and 0 <= ti < len(ucs):
                data[ucs[ti]][si] = True
        df = pd.DataFrame(data, index=ucs)
        df.index.name = "Base UC  -  \ Included UC -"

        edited = st.data_editor(df, use_container_width=True, key="inc_matrix")

        if st.button("- Apply Matrix Changes", key="inc_matrix_apply",
                     use_container_width=True):
            new_pairs = sorted({
                (si, ti)
                for si, sn in enumerate(ucs)
                for ti, tn in enumerate(ucs)
                if bool(edited.loc[sn, tn])
            })
            extend_set = set(st.session_state.get("ucd_extend_pairs") or [])
            conflicted = [p for p in new_pairs if p in extend_set]
            if conflicted:
                st.warning(f"Skipped {len(conflicted)} include(s) conflicting "
                           f"with existing extend(s).")
            new_pairs = [p for p in new_pairs if p not in extend_set]
            st.session_state.ucd_include_pairs = new_pairs
            _sync_to_relationships(new_pairs)
            st.success("Includes updated!")
            st.rerun()

    # -- Quick Add / Remove ----------------------------------------------------
    st.divider()
    st.markdown("**Quick Add / Remove Include**")
    c1, c2 = st.columns(2)
    with c1:
        inc_src = st.selectbox("Base Use Case", options=ucs, key="inc_src")
    with c2:
        inc_tgt = st.selectbox("Included Use Case", options=ucs, key="inc_tgt")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("+ Add Include", key="inc_add", use_container_width=True):
            if not inc_src or not inc_tgt:
                st.warning("Select both.")
            elif inc_src == inc_tgt:
                st.warning("Base and included UC must differ.")
            else:
                si, ti = ucs.index(inc_src), ucs.index(inc_tgt)
                extend_set = set(st.session_state.get("ucd_extend_pairs") or [])
                if (si, ti) in extend_set:
                    st.error("Conflict: already an extend.")
                elif (si, ti) in st.session_state.ucd_include_pairs:
                    st.info("Already exists.")
                else:
                    st.session_state.ucd_include_pairs.append((si, ti))
                    _sync_to_relationships(st.session_state.ucd_include_pairs)
                    st.success("Include added!")
                    st.rerun()
    with b2:
        if st.button("- Remove Include", key="inc_rm", use_container_width=True):
            if inc_src and inc_tgt and inc_src != inc_tgt:
                si, ti = ucs.index(inc_src), ucs.index(inc_tgt)
                if (si, ti) in st.session_state.ucd_include_pairs:
                    st.session_state.ucd_include_pairs.remove((si, ti))
                    _sync_to_relationships(st.session_state.ucd_include_pairs)
                    st.warning("Removed.")
                    st.rerun()


    # -- SysML v2 live diagram --------------------------------------------------
    st.divider()
    from generation.sysml_ucd import render_sysml_panel
    render_sysml_panel(key='step5')

    # Navigation
    def _on_confirm():
        _sync_to_relationships(st.session_state.ucd_include_pairs)
        reset_from_step(5)
        return True

    render_navigation(
        next_label="Confirm Includes",
        on_next=_on_confirm,
    )
