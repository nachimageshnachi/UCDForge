"""Step 3: Review Extracted Elements - read-only summary of what the LLM found
plus any relationships the user has added in subsequent steps."""

import streamlit as st
from generation.step_manager import render_navigation, go_to_step

# Map relationship type - display label and icon
_REL_META = {
    "association":    ("-", "Associations",          "Actor - Use Case"),
    "include":        ("-", "Includes",               "Base UC --includes-- Included UC"),
    "extend":         ("-", "Extends",                "Extension UC --extends-- Base UC  -  (condition)"),
    "generalization": ("-", "Generalizations",        "Child - Parent  (is a kind of)"),
}


def render():
    st.markdown(
        "Review the elements extracted from your description. "
        "Relationships shown here include both LLM-inferred and any you've "
        "added manually in later steps."
    )

    if not st.session_state.get("ucd_ready"):
        st.warning("No extraction data found. Please go back to Step 1.")
        render_navigation(show_next=False)
        return

    # -- Actors & Use Cases --------------------------------------------------
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("System Name")
        st.info(st.session_state.get("ucd_system_name") or "-")

        st.subheader("Primary Actors")
        prim = st.session_state.get("ucd_primary_actors") or []
        for a in prim:
            st.write(f"- {a}")
        if not prim:
            st.write("-")

        st.subheader("Secondary Actors")
        sec = st.session_state.get("ucd_secondary_actors") or []
        for a in sec:
            st.write(f"- {a}")
        if not sec:
            st.write("-")

    with col2:
        st.subheader("Use Cases")
        ucs = st.session_state.get("ucd_use_cases") or []
        for u in ucs:
            st.write(f"- {u}")
        if not ucs:
            st.write("-")

        st.subheader("Domains")
        doms = st.session_state.get("ucd_domains") or []
        for d in doms:
            st.write(f"- {d}")
        if not doms:
            st.write("-")

    # -- Relationships (grouped by type) ------------------------------------
    st.subheader("Relationships")
    rels = st.session_state.get("ucd_relationships") or []

    # Deduplicate before display (source, target, type) - LLM can return dupes
    seen_keys: set = set()
    deduped_rels = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        key = (
            str(r.get("source_name") or "").lower().strip(),
            str(r.get("target_name") or "").lower().strip(),
            str(r.get("relationship_type") or "").lower().strip(),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_rels.append(r)
    rels = deduped_rels

    # Group by relationship_type
    grouped: dict[str, list] = {k: [] for k in _REL_META}
    for r in rels:
        rt = (r.get("relationship_type") or "").lower()
        if rt in grouped:
            grouped[rt].append(r)

    total = len(rels)
    st.write(f"**{total}** relationship{'s' if total != 1 else ''} total")

    for rt, (icon, label, hint) in _REL_META.items():
        bucket = grouped[rt]
        if not bucket:
            continue
        with st.expander(f"{icon} {label}  ({len(bucket)})  -  *{hint}*",
                         expanded=False):
            for i, r in enumerate(bucket, 1):
                src = r.get("source_name", "?")
                tgt = r.get("target_name", "?")
                ext = (r.get("extension") or "").strip()
                label_str = f"{i}. **{src}** - {tgt}"
                if ext:
                    label_str += f"  *(when {ext})*"
                st.write(label_str)

    st.divider()
    from generation.sysml_ucd import render_sysml_panel
    render_sysml_panel(key="step3")

    render_navigation(next_label="Looks Good, Continue")

