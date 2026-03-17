"""
generation/sysml_ucd.py
=======================
SysML v1 & v2 Use Case Diagram support for the UCD Generation wizard.

Public entry-points:
  generate_sysml_v1_text(ss)   -> str   SysML v1 (PlantUML) textual notation
  generate_sysml_v2_text(ss)   -> str   Authentic SysML v2 textual notation
  render_sysml_panel(key)               Streamlit: SVG diagram + two code expanders
"""

import html
import streamlit as st


# ---------------------------------------------------------------------------
# 1.  SysML v1 textual notation generator (PlantUML Syntax)
# ---------------------------------------------------------------------------

def generate_sysml_v1_text(ss=None) -> str:
    """
    Build a SysML v1 (PlantUML) textual model for the current Use Case Diagram.
    """
    if ss is None:
        ss = st.session_state

    system   = (ss.get("ucd_system_name") or "System").strip()
    prim     = ss.get("ucd_primary_actors")   or []
    sec      = ss.get("ucd_secondary_actors")  or []
    ucs      = ss.get("ucd_use_cases")         or []
    rels     = ss.get("ucd_relationships")     or []

    lines = ["@startuml", ""]

    # Outer Use Case diagram frame
    lines.append(f"rectangle \"uc {system} Use Case\" {{")
    lines.append("")

    # Primary Actors (inside frame, OUTSIDE the system boundary)
    if prim:
        lines.append("    ' Primary Actors")
        for a in prim:
            lines.append(f"    actor \"{a}\" as A_{_safe_id(a)}")
        lines.append("")

    # Inner system boundary package (only use cases inside)
    lines.append(f"    package \"{system}\" {{")
    lines.append("")

    if ucs:
        lines.append("        ' Use Cases")
        for uc in ucs:
            lines.append(f"        usecase \"{uc}\" as UC_{_safe_id(uc)}")
        lines.append("")

    lines.append("    }")
    lines.append("")

    # Secondary Actors (inside frame, OUTSIDE the system boundary)
    if sec:
        lines.append("    ' Secondary Actors")
        for a in sec:
            lines.append(f"    actor \"{a}\" as A_{_safe_id(a)}")
        lines.append("")

    lines.append("}")
    lines.append("")

    for r in rels:
        rt  = (r.get("relationship_type") or "association").lower()
        src = r.get("source_name") or ""
        tgt = r.get("target_name") or ""
        ext = (r.get("extension") or "").strip()
        
        # Determine correct ID strings
        if src in prim or src in sec:
            s_id = f"A_{_safe_id(src)}"
        else:
            s_id = f"UC_{_safe_id(src)}"
            
        if tgt in prim or tgt in sec:
            t_id = f"A_{_safe_id(tgt)}"
        else:
            t_id = f"UC_{_safe_id(tgt)}"

        if rt == "association":
            lines.append(f"{s_id} -- {t_id}")
        elif rt == "include":
            lines.append(f"{s_id} ..> {t_id} : <<include>>")
        elif rt == "extend":
            cond = f"\\nCondition: {ext}" if ext else ""
            # Notice the reversal for extend semantics in diagramming (Source extends Target)
            lines.append(f"{s_id} .up.> {t_id} : <<extend>>{cond}")
        elif rt == "generalization":
            lines.append(f"{s_id} --|> {t_id}")

    lines.append("")
    lines.append("@enduml")
    return "\n".join(lines)

def _safe_id(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


# ---------------------------------------------------------------------------
# 2. Authentic SysML v2 textual notation generator
# ---------------------------------------------------------------------------

def generate_sysml_v2_text(ss=None) -> str:
    """
    Build an authentic SysML v2 textual model for the Use Case Diagram.
    Follows official UseCaseUsage/UseCaseDefinition patterns.
    """
    if ss is None:
        ss = st.session_state

    system   = (ss.get("ucd_system_name") or "System").strip()
    prim     = ss.get("ucd_primary_actors")   or []
    sec      = ss.get("ucd_secondary_actors")  or []
    ucs      = ss.get("ucd_use_cases")         or []
    rels     = ss.get("ucd_relationships")     or []

    lines = [f"package '{system} Use Case' {{", ""]
    
    # 1. Actors as parts (in the outer UC frame, OUTSIDE the system boundary)
    all_actors = prim + sec
    if all_actors:
        lines.append("    // Actor Definitions")
        for a in all_actors:
            parents = [r.get("target_name") for r in rels 
                       if (r.get("relationship_type") or "").lower() == "generalization" 
                       and (r.get("source_type") or "").lower() == "actor" 
                       and r.get("source_name") == a]
            
            if parents:
                parent_str = " specializes " + ", ".join([f"'{p}'" for p in parents])
                lines.append(f"    part def '{a}'{parent_str};")
            else:
                lines.append(f"    part def '{a}';")
        lines.append("")

    # 2. System Boundary (Inner Package — use cases go inside here)
    lines.append(f"    package '{system}' {{")
    lines.append(f"        part def '{system}';")
    lines.append("")

    # 3. Use Case Definitions (Inside System)
    if ucs:
        lines.append("        // Use Case Definitions")
        for uc in ucs:
            # Check for generalizations where this UC is the child
            parents = [r.get("target_name") for r in rels 
                       if (r.get("relationship_type") or "").lower() == "generalization" 
                       and (r.get("source_type") or "").lower() == "usecase" 
                       and r.get("source_name") == uc]
                       
            specializes = f" specializes {', '.join([repr(p) for p in parents])}" if parents else ""
            
            lines.append(f"        use case def '{uc}'{specializes} {{")
            lines.append(f"            subject system : '{system}';")
            
            # Re-adding the actor usages: This is authentic SysML v2 syntax
            # and is the ONLY way PlantUML knows to draw relationship associations
            # in SysML v2 mode, even if it forces the visual layout inside the box.
            uc_actors = []
            for r in rels:
                rt = (r.get("relationship_type") or "").lower()
                if rt == "association":
                    src, tgt = r.get("source_name"), r.get("target_name")
                    if tgt == uc and src in all_actors:
                        uc_actors.append(src)
                        
            for a in uc_actors:
                safe_name = "".join([c if c.isalnum() else "_" for c in a]).lower()
                lines.append(f"            actor {safe_name} : '{a}';")
            
            includes = [r.get("target_name") for r in rels 
                        if (r.get("relationship_type") or "").lower() == "include" 
                        and r.get("source_name") == uc]
            
            if includes:
                for inc in includes:
                    lines.append(f"            include use case '{inc}';")

            extends = [r for r in rels 
                      if (r.get("relationship_type") or "").lower() == "extend" 
                      and r.get("source_name") == uc]
                      
            if extends:
                for ext_rel in extends:
                    tgt = ext_rel.get("target_name")
                    cond = ext_rel.get("extension")
                    if cond:
                        lines.append(f"            // Condition: {cond}")
                    lines.append(f"            extend use case '{tgt}';")
                    
            lines.append("        }")
            lines.append("")

    lines.append("    }")  # Close inner System boundary package
    lines.append("}")      # Close outer Use Case frame package
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Inline SVG renderer  (Fixed spacing)
# ---------------------------------------------------------------------------

_ACTOR_W  = 40
_ACTOR_H  = 70
_UC_W     = 180      # Increased for spaciousness
_UC_H     = 50       # Increased
_PAD      = 20
_ROW_H    = 90       # Increased vertical spacing to prevent overlapping

_REL_STYLE = {
    "association":    ("#4a90d9", "",      ""),
    "include":        ("#2ca02c", "6,3",   "<<include>>"),
    "extend":         ("#ff7f0e", "6,3",   "<<extend>>"),
    "generalization": ("#9467bd", "",      ""),
}

def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=True)

def _actor_svg(cx: int, cy: int, name: str, color: str = "#4a90d9") -> str:
    r = 10
    return (
        f'<circle cx="{cx}" cy="{cy - 25}" r="{r}" stroke="{color}" stroke-width="1.5" fill="white"/>'
        f'<line x1="{cx}" y1="{cy-15}" x2="{cx}" y2="{cy+10}" stroke="{color}" stroke-width="1.5"/>'
        f'<line x1="{cx-14}" y1="{cy-5}" x2="{cx+14}" y2="{cy-5}" stroke="{color}" stroke-width="1.5"/>'
        f'<line x1="{cx}" y1="{cy+10}" x2="{cx-12}" y2="{cy+26}" stroke="{color}" stroke-width="1.5"/>'
        f'<line x1="{cx}" y1="{cy+10}" x2="{cx+12}" y2="{cy+26}" stroke="{color}" stroke-width="1.5"/>'
        f'<text x="{cx}" y="{cy+44}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="{color}">{_esc(name)}</text>'
    )

def _uc_svg(x: int, y: int, name: str) -> str:
    cx = x + _UC_W // 2
    cy = y + _UC_H // 2
    rx = _UC_W // 2
    ry = _UC_H // 2
    label = name if len(name) <= 26 else name[:24] + "..."
    return (
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
        f'stroke="#555" stroke-width="1.2" fill="#f0f4ff"/>'
        f'<text x="{cx}" y="{cy+4}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="12" fill="#222">{_esc(label)}</text>'
    )

def _connector_svg(x1: int, y1: int, x2: int, y2: int,
                   stroke: str, dash: str, label: str, arrow: bool = True) -> str:
    mid_x = (x1 + x2) // 2
    mid_y = (y1 + y2) // 2
    dash_attr = f'stroke-dasharray="{dash}"' if dash else ""
    marker = 'marker-end="url(#arrowhead)"' if arrow else ""
    lbl = ""
    if label:
        lbl = (f'<text x="{mid_x}" y="{mid_y - 8}" text-anchor="middle" '
               f'font-family="sans-serif" font-size="11" fill="{stroke}">{_esc(label)}</text>')
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{stroke}" stroke-width="1.5" {dash_attr} {marker}/>'
        + lbl
    )

def render_ucd_svg(ss=None) -> str:
    if ss is None:
        ss = st.session_state

    system   = (ss.get("ucd_system_name") or "System").strip()
    prim     = list(ss.get("ucd_primary_actors")   or [])
    sec      = list(ss.get("ucd_secondary_actors")  or [])
    ucs      = list(ss.get("ucd_use_cases")         or [])
    rels     = list(ss.get("ucd_relationships")     or [])

    # Wider layout parameters
    left_x    = _PAD + 70                 # center x for primary actors
    uc_col_x  = 300                       # left edge of UC column
    right_x_base = 850                    # center x for secondary actors
    uc_col_cx = uc_col_x + _UC_W // 2

    n_rows = max(len(prim), len(sec), len(ucs), 1)
    svg_h  = n_rows * _ROW_H + 160
    svg_w  = 1000                         # Wider total canvas

    pos: dict[str, tuple[int, int]] = {}
    svg_parts = []

    svg_parts.append(
        '<defs>'
        '<marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">'
        '<polygon points="0 0, 8 3, 0 6" fill="#555"/>'
        '</marker>'
        '</defs>'
    )

    box_x = uc_col_x - 30
    box_y = 30
    box_w = _UC_W + 60
    box_h = max(len(ucs), 1) * _ROW_H + 40
    svg_parts.append(
        f'<rect x="{box_x}" y="{box_y}" width="{box_w}" height="{box_h}" '
        f'rx="8" ry="8" stroke="#aaa" stroke-width="1.5" fill="#fafbff"/>'
        f'<text x="{box_x + box_w // 2}" y="{box_y - 10}" text-anchor="middle" '
        f'font-family="sans-serif" font-size="14" font-weight="bold" fill="#333">{_esc(system)}</text>'
    )

    for i, uc in enumerate(ucs):
        y = box_y + 20 + i * _ROW_H
        svg_parts.append(_uc_svg(uc_col_x, y, uc))
        pos[uc] = (uc_col_cx, y + _UC_H // 2)

    for i, a in enumerate(prim):
        cy = 80 + i * _ROW_H
        svg_parts.append(_actor_svg(left_x, cy, a, "#1f78b4"))
        pos[a] = (left_x, cy)

    for i, a in enumerate(sec):
        cy = 80 + i * _ROW_H
        svg_parts.append(_actor_svg(right_x_base, cy, a, "#e7298a"))
        pos[a] = (right_x_base, cy)

    for r in rels:
        rt  = (r.get("relationship_type") or "association").lower()
        src = r.get("source_name") or ""
        tgt = r.get("target_name") or ""
        ext = (r.get("extension") or "").strip()
        style = _REL_STYLE.get(rt, _REL_STYLE["association"])
        stroke, dash, label = style
        if ext and rt == "extend":
            label = f"<<extend>> [{ext[:18]}]"

        if src in pos and tgt in pos:
            x1, y1 = pos[src]
            x2, y2 = pos[tgt]
            arrow = rt != "association"
            svg_parts.append(_connector_svg(x1, y1, x2, y2, stroke, dash, label, arrow))

    svg_inner = "\n".join(svg_parts)

    html_out = f"""
    <div style="background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px;overflow-x:auto;">
      <svg width="{svg_w}" height="{svg_h}" xmlns="http://www.w3.org/2000/svg"
           style="font-family:sans-serif;display:block;max-width:100%;">
        {svg_inner}
      </svg>
    </div>
    """
    return html_out


# ---------------------------------------------------------------------------
# 4. Streamlit panel  (image + two collapsible codes)
# ---------------------------------------------------------------------------

def render_sysml_panel(key: str = "sysml") -> None:
    ucs   = st.session_state.get("ucd_use_cases") or []
    prim  = st.session_state.get("ucd_primary_actors") or []
    sec   = st.session_state.get("ucd_secondary_actors") or []

    if not ucs and not prim and not sec:
        st.caption("Diagram will appear once elements are defined.")
        return

    st.markdown("**Use Case Diagram**")

    svg_html = render_ucd_svg()
    st.markdown(svg_html, unsafe_allow_html=True)

    with st.expander("SysML v1 (PlantUML) Code", expanded=False):
        v1_code = generate_sysml_v1_text()
        st.code(v1_code, language="text")
        st.download_button(
            "Download SysML v1",
            data=v1_code,
            file_name=f"{(st.session_state.get('ucd_system_name') or 'diagram').replace(' ','_')}_v1.txt",
            mime="text/plain",
            key=f"dl_sysml_v1_{key}",
        )

    with st.expander("SysML v2 Code", expanded=False):
        v2_code = generate_sysml_v2_text()
        st.code(v2_code, language="text")
        st.download_button(
            "Download SysML v2",
            data=v2_code,
            file_name=f"{(st.session_state.get('ucd_system_name') or 'diagram').replace(' ','_')}_v2.sysml",
            mime="text/plain",
            key=f"dl_sysml_v2_{key}",
        )
