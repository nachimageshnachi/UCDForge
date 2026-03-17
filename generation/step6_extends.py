"""Step 6: Extend Relationships (UC - Base UC) with extension points."""

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
    meta = {}
    for rel in st.session_state.get("ucd_relationships") or []:
        if (rel.get("relationship_type") or "").lower() != "extend":
            continue
        if (rel.get("source_type") or "").lower() != "usecase":
            continue
        if (rel.get("target_type") or "").lower() != "usecase":
            continue
        s = str(rel.get("source_name", "")).strip().lower()
        t = str(rel.get("target_name", "")).strip().lower()
        if s in uc_lo and t in uc_lo:
            si, ti = uc_lo[s], uc_lo[t]
            pairs.add((si, ti))
            meta[f"{si}|{ti}"] = rel.get("extension", "")
    return sorted(pairs), meta


def _sync_to_relationships(pairs, meta):
    ucs = _use_cases()
    others = [r for r in (st.session_state.get("ucd_relationships") or [])
              if (r.get("relationship_type") or "").lower() != "extend"]
    ext = []
    seen = set()
    include_set = set(st.session_state.get("ucd_include_pairs") or [])
    for _si, _ti in pairs:
        si, ti = int(_si), int(_ti)
        if si < 0 or ti < 0 or si >= len(ucs) or ti >= len(ucs):
            continue
        s, t = ucs[si], ucs[ti]
        key = (s.lower(), t.lower())
        if key in seen or (si, ti) in include_set:
            continue
        seen.add(key)
        ext.append({
            "relationship_type": "extend",
            "source_name": s, "source_type": "usecase",
            "target_name": t, "target_type": "usecase",
            "extension": meta.get(f"{si}|{ti}", ""),
            "confidence": 0.95,
        })
    st.session_state.ucd_relationships = ext + others


def render():
    st.info(
        "- **What is an extend?** An extend is an *optional* add-on to a "
        "base use case that runs only under certain conditions (extension "
        "point). Example: *Forgot Password* **extends** *Login* - happens when "
        "the user cannot remember credentials."
    )

    ucs = _use_cases()
    if not ucs:
        st.warning("No use cases defined. Go back to Step 2.")
        render_navigation(show_next=False)
        return

    if "ucd_extend_pairs" not in st.session_state \
       or "ucd_extend_meta" not in st.session_state:
        pairs, meta = _pairs_from_relationships()
        st.session_state.ucd_extend_pairs = pairs
        st.session_state.ucd_extend_meta = meta

    # --- Summary Table ---
    rows = []
    for _si, _ti in st.session_state.ucd_extend_pairs:
        si, ti = int(_si), int(_ti)
        s = ucs[si] if 0 <= si < len(ucs) else "?"
        t = ucs[ti] if 0 <= ti < len(ucs) else "?"
        ep = st.session_state.ucd_extend_meta.get(f"{si}|{ti}", "")
        rows.append({"left": s, "right": t, "extra": ep})
    render_summary_table(
        rows, "Extension UC", "-extends-", "Base UC",
        "Extend Relationships", icon="-", accent="#ff7f0e",
        extra_col_label="Condition (extension point)",
    )

    # --- Two tabs: Visual | Matrix --------------------------------------------
    tab_vis, tab_edit = st.tabs(["- Visual Diagram", "- Matrix Editor"])

    with tab_vis:
        render_uc_uc_svg(
            ucs, ucs, st.session_state.ucd_extend_pairs,
            stroke_color="#ff7f0e",
            labels=st.session_state.ucd_extend_meta,
            key="ext",
        )

    with tab_edit:
        # -- Extend Matrix ------------------------------------------------
        st.markdown("**- Extend Matrix**")
        st.caption(
            "Rows = **Extension Use Case** (the optional add-on)  -  "
            "Columns = **Base Use Case** (the one being extended)  -  "
            "- = row UC -extends- column UC"
        )
        data = {right: [False] * len(ucs) for right in ucs}
        meta_data = {right: [""] * len(ucs) for right in ucs}
        for _si, _ti in st.session_state.ucd_extend_pairs:
            si, ti = int(_si), int(_ti)
            if 0 <= si < len(ucs) and 0 <= ti < len(ucs):
                data[ucs[ti]][si] = True
                meta_data[ucs[ti]][si] = st.session_state.ucd_extend_meta.get(
                    f"{si}|{ti}", "")
        df_ext = pd.DataFrame(data, index=ucs)
        df_ext.index.name = "Extension UC  -  \\ Base UC -"
        df_meta = pd.DataFrame(meta_data, index=ucs)
        df_meta.index.name = "Extension UC  -  \\ Base UC -"

        c_m1, c_m2 = st.columns(2)
        with c_m1:
            st.caption("Tick to add extend:")
            edited_ext = st.data_editor(df_ext, use_container_width=True,
                                        key="ext_matrix")
        with c_m2:
            st.caption("Extension point condition (when it triggers):")
            edited_meta = st.data_editor(df_meta, use_container_width=True,
                                         key="ext_meta_matrix")

        if st.button("- Apply Matrix Changes", key="ext_matrix_apply",
                     use_container_width=True):
            new_pairs = []
            new_meta = {}
            for si, sn in enumerate(ucs):
                for ti, tn in enumerate(ucs):
                    if bool(edited_ext.loc[sn, tn]):
                        new_pairs.append((si, ti))
                        val = str(edited_meta.loc[sn, tn] or "").strip()
                        if val:
                            new_meta[f"{si}|{ti}"] = val
            new_pairs = sorted(set(new_pairs))
            include_set = set(st.session_state.get("ucd_include_pairs") or [])
            conflicted = [p for p in new_pairs if p in include_set]
            if conflicted:
                st.warning(f"Skipped {len(conflicted)} extend(s) conflicting "
                           f"with existing include(s).")
            new_pairs = [p for p in new_pairs if p not in include_set]
            st.session_state.ucd_extend_pairs = new_pairs
            st.session_state.ucd_extend_meta = new_meta
            _sync_to_relationships(new_pairs, new_meta)
            st.success("Extends updated!")
            st.rerun()

    # -- Quick Add / Remove ----------------------------------------------------
    st.divider()
    st.markdown("**Quick Add / Remove Extend**")
    c1, c2, c3 = st.columns([3, 3, 3])
    with c1:
        ext_src = st.selectbox("Extension Use Case", options=ucs, key="ext_src")
    with c2:
        ext_tgt = st.selectbox("Base Use Case", options=ucs, key="ext_tgt")
    with c3:
        ext_point = st.text_input("Extension point -- happens when...",
                                   key="ext_point_new",
                                   placeholder="e.g., User is idle for 5 min")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("+ Add Extend", key="ext_add", use_container_width=True):
            if not ext_src or not ext_tgt:
                st.warning("Select both.")
            elif ext_src == ext_tgt:
                st.warning("Extension and base UC must differ.")
            else:
                si, ti = ucs.index(ext_src), ucs.index(ext_tgt)
                include_set = set(st.session_state.get("ucd_include_pairs") or [])
                if (si, ti) in include_set:
                    st.error("Conflict: already an include.")
                elif (si, ti) in st.session_state.ucd_extend_pairs:
                    key = f"{si}|{ti}"
                    st.session_state.ucd_extend_meta[key] = (ext_point or "").strip()
                    _sync_to_relationships(st.session_state.ucd_extend_pairs, st.session_state.ucd_extend_meta)
                    st.success("Extension point updated!")
                    st.rerun()
                else:
                    key = f"{si}|{ti}"
                    st.session_state.ucd_extend_pairs.append((si, ti))
                    st.session_state.ucd_extend_meta[key] = (ext_point or "").strip()
                    _sync_to_relationships(st.session_state.ucd_extend_pairs, st.session_state.ucd_extend_meta)
                    st.success("Extend added!")
                    st.rerun()
    with b2:
        if st.button("- Remove Extend", key="ext_rm", use_container_width=True):
            if ext_src and ext_tgt and ext_src != ext_tgt:
                si, ti = ucs.index(ext_src), ucs.index(ext_tgt)
                key = f"{si}|{ti}"
                if (si, ti) in st.session_state.ucd_extend_pairs:
                    st.session_state.ucd_extend_pairs.remove((si, ti))
                    st.session_state.ucd_extend_meta.pop(key, None)
                    _sync_to_relationships(st.session_state.ucd_extend_pairs, st.session_state.ucd_extend_meta)
                    st.warning("Removed.")
                    st.rerun()


    # -- SysML v2 live diagram --------------------------------------------------
    st.divider()
    from generation.sysml_ucd import render_sysml_panel
    render_sysml_panel(key='step6')

    # Navigation
    def _on_confirm():
        _sync_to_relationships(st.session_state.ucd_extend_pairs,
                               st.session_state.ucd_extend_meta)
        reset_from_step(6)
        return True

    render_navigation(
        next_label="Confirm Extends",
        on_next=_on_confirm,
    )
