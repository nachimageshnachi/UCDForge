import copy
import json
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

import numpy as np

from connection import connection
from embeddings import embed_short
from Parser import ParserOperations  # reuse validation/repair
from ucd_validation_operation import element_validation


def _vec(text: str) -> np.ndarray:
    try:
        v = json.loads(embed_short(text) or "[]")
        arr = np.array(v, dtype=float)
        return arr if arr.size else np.zeros((1,), dtype=float)
    except Exception:
        return np.zeros((1,), dtype=float)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    try:
        return float(np.clip(np.dot(a, b), -1.0, 1.0))
    except Exception:
        return 0.0


def fetch_case_data(case_id: int) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "system_name": "",
        "xml_content": "",
        "actors": [],  # list of (name, type) where type in {'Primary','Secondary'}
        "use_cases": [],
        "relationships": [],  # normalized dicts
    }
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute("SELECT system_name, xml_content FROM diagrams WHERE case_id=%s", (case_id,))
        row = cursor.fetchone()
        data["system_name"] = (row or {}).get("system_name") or ""
        data["xml_content"] = (row or {}).get("xml_content") or ""

        cursor.execute("SELECT actor_name, actor_type FROM actors WHERE case_id=%s", (case_id,))
        for r in cursor.fetchall() or []:
            data["actors"].append((r.get("actor_name") or "", r.get("actor_type") or "Primary"))

        cursor.execute("SELECT name FROM use_cases WHERE case_id=%s", (case_id,))
        data["use_cases"] = [r.get("name") or "" for r in cursor.fetchall() or []]

        cursor.execute(
            """
            SELECT relationship_type, source_name, source_type, target_name, target_type, extension
            FROM relationships WHERE case_id=%s
            """,
            (case_id,),
        )
        for r in cursor.fetchall() or []:
            rt = (r.get("relationship_type") or "").lower()
            st = (r.get("source_type") or "").strip().lower()
            tt = (r.get("target_type") or "").strip().lower()
            data["relationships"].append(
                {
                    "relationship_type": rt,
                    "source_name": r.get("source_name") or "",
                    "source_type": "usecase" if st in {"use case", "usecase"} else "actor",
                    "target_name": r.get("target_name") or "",
                    "target_type": "usecase" if tt in {"use case", "usecase"} else "actor",
                    "extension": r.get("extension") or "",
                }
            )
    return data


def _map_with_priority(user_items: List[str], kb_items: List[str], threshold: float = 0.86) -> Tuple[Dict[str, str], List[str]]:
    """Return (mapping: user->final, merged_list). If similar, prefer the KB name."""
    kb_vecs = {k: _vec(k) for k in kb_items}
    mapping = {}
    merged = list(kb_items)
    for u in user_items:
        v = _vec(u)
        best = None
        best_sim = 0.0
        for k, kv in kb_vecs.items():
            s = _cos(v, kv)
            if s > best_sim:
                best_sim = s
                best = k
        if best and best_sim >= threshold:
            mapping[u] = best
        else:
            mapping[u] = u
            if u not in merged:
                merged.append(u)
    return mapping, merged


def merge_user_with_case(user: Dict[str, Any], kb: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user diagram with KB case data. Prefer KB names on near-duplicates.
    Returns dict: system_name, primary_actors, secondary_actors, use_cases, relationships (normalized).
    """
    # KB actors split
    kb_primary = [a for a, t in kb.get("actors", []) if (t or "").lower().startswith("primary")]
    kb_secondary = [a for a, t in kb.get("actors", []) if (t or "").lower().startswith("secondary")]
    user_primary = user.get("primary_actors") or []
    user_secondary = user.get("secondary_actors") or []

    # Build mapping for actors/use-cases (pref KB on similarity)
    act_map_p, merged_primary = _map_with_priority(user_primary, kb_primary)
    act_map_s, merged_secondary = _map_with_priority(user_secondary, kb_secondary)
    # ensure global actor set and avoid duplicates across primary/secondary
    merged_sec_only = [a for a in merged_secondary if a not in merged_primary]
    primary_actors = merged_primary
    secondary_actors = merged_sec_only

    uc_map, merged_use_cases = _map_with_priority(user.get("use_cases") or [], kb.get("use_cases") or [])

    # Remap relationships (user + kb)
    relationships: List[Dict[str, Any]] = []
    # from KB (already normalized)
    for r in kb.get("relationships") or []:
        relationships.append(dict(r))
    # from user
    for r in user.get("relationships") or []:
        rt = (r.get("relationship_type") or "").lower()
        st = (r.get("source_type") or "").lower()
        tt = (r.get("target_type") or "").lower()
        sn = r.get("source_name") or ""
        tn = r.get("target_name") or ""
        if st == 'actor':
            sn = act_map_p.get(sn, act_map_s.get(sn, sn))
        else:
            sn = uc_map.get(sn, sn)
        if tt == 'actor':
            tn = act_map_p.get(tn, act_map_s.get(tn, tn))
        else:
            tn = uc_map.get(tn, tn)
        relationships.append(
            {
                "relationship_type": rt,
                "source_name": sn,
                "source_type": st,
                "target_name": tn,
                "target_type": tt,
                "extension": r.get("extension") or "",
            }
        )

    # Final validation & repair via ParserOperations
    prim_fixed, sec_fixed, ucs_fixed, rels_fixed = ParserOperations._validate_and_fix_ucd(
        primary_actors, secondary_actors, merged_use_cases, [
            {
                "Relation Code": None,
                "Value": r.get("relationship_type"),
                "Source Name": r.get("source_name"),
                "Source Type": r.get("source_type"),
                "Target Name": r.get("target_name"),
                "Target Type": r.get("target_type"),
                "Extension": r.get("extension") or "",
            }
            for r in relationships
        ],
    )

    return {
        "system_name": user.get("system_name") or kb.get("system_name") or "System",
        "primary_actors": prim_fixed,
        "secondary_actors": sec_fixed,
        "use_cases": ucs_fixed,
        "relationships": [
            {
                "relationship_type": r.get("Value"),
                "source_name": r.get("Source Name"),
                "source_type": r.get("Source Type"),
                "target_name": r.get("Target Name"),
                "target_type": r.get("Target Type"),
                "extension": r.get("Extension") or "",
            }
            for r in rels_fixed
        ],
    }


def _tg_points_block(start_id: int = 1) -> Tuple[str, int]:
    parts = []
    for i in range(32):
        parts.append(f'<TGConnectingPoint num="{i}" id="{start_id+i}"/>')
    return "\n".join(parts), start_id + 32


def _xml_escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _normalize_ucd_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return canonical fields for a UCD payload (system_name, prim/sec actors, use_cases, relationships)."""
    # System name and actors may come in different shapes (actors list with type vs split lists)
    system_name = payload.get("system_name") or "System"
    if payload.get("actors"):
        prim = [a for a, t in payload.get("actors", []) if (t or "").lower().startswith("primary")]
        sec = [a for a, t in payload.get("actors", []) if (t or "").lower().startswith("secondary")]
    else:
        prim = payload.get("primary_actors") or []
        sec = payload.get("secondary_actors") or []
    use_cases = payload.get("use_cases") or []

    rels_raw = payload.get("relationships") or []
    rels_norm = []
    for r in rels_raw:
        rels_norm.append(
            {
                "relationship_type": (r.get("relationship_type") or r.get("Value") or "").lower(),
                "source_name": r.get("source_name") or r.get("Source Name") or "",
                "source_type": (r.get("source_type") or r.get("Source Type") or "").lower(),
                "target_name": r.get("target_name") or r.get("Target Name") or "",
                "target_type": (r.get("target_type") or r.get("Target Type") or "").lower(),
                "extension": r.get("extension") or r.get("Extension") or "",
            }
        )

    # Validate / repair via ParserOperations to keep consistency with other exports
    prim_fixed, sec_fixed, ucs_fixed, rels_fixed = ParserOperations._validate_and_fix_ucd(
        prim,
        sec,
        use_cases,
        [
            {
                "Relation Code": None,
                "Value": r.get("relationship_type"),
                "Source Name": r.get("source_name"),
                "Source Type": r.get("source_type"),
                "Target Name": r.get("target_name"),
                "Target Type": r.get("target_type"),
                "Extension": r.get("extension") or "",
            }
            for r in rels_norm
        ],
    )

    relationships = [
        {
            "relationship_type": r.get("Value"),
            "source_name": r.get("Source Name"),
            "source_type": r.get("Source Type"),
            "target_name": r.get("Target Name"),
            "target_type": r.get("Target Type"),
            "extension": r.get("Extension") or "",
        }
        for r in rels_fixed
    ]

    return {
        "system_name": system_name,
        "primary_actors": prim_fixed,
        "secondary_actors": sec_fixed,
        "use_cases": ucs_fixed,
        "relationships": relationships,
    }


def _build_ucd_panel(
    panel_name: str,
    system_name: str,
    primary_actors: List[str],
    secondary_actors: List[str],
    use_cases: List[str],
    relationships: List[Dict[str, Any]],
) -> str:
    """Render a single <UseCaseDiagramPanel> block with stable ids/layout."""
    comp_id = 1
    xml_parts: List[str] = [
        f'<UseCaseDiagramPanel name="{_xml_escape(panel_name)}" minX="10" maxX="2500" minY="10" maxY="1500" zoom="1.0">'
    ]

    components: Dict[str, Dict[str, Any]] = {}
    next_point_id = 1

    # -- Layout constants -------------------------------------------------
    MARGIN_TOP = 80
    MARGIN_LEFT = 60
    ACTOR_W, ACTOR_H = 30, 70
    UC_W, UC_H = 150, 40
    ACTOR_SPACING_Y = 100
    UC_SPACING_X = 180          # horizontal gap between UC columns
    UC_SPACING_Y = 70           # vertical gap between UCs
    UC_COLS = 2                 # arrange UCs in a grid of this many columns
    GAP_ACTOR_SYS = 120         # gap between left actors and system boundary
    GAP_SYS_ACTOR = 120         # gap between system boundary and right actors
    SYS_PAD_X = 40              # padding inside system boundary (left/right)
    SYS_PAD_TOP = 50            # padding inside system boundary (top)
    SYS_PAD_BOT = 40            # padding inside system boundary (bottom)

    # -- Compute UC grid dimensions ---------------------------------------
    n_ucs = max(len(use_cases), 1)
    uc_rows = (n_ucs + UC_COLS - 1) // UC_COLS
    uc_grid_w = UC_COLS * UC_W + (UC_COLS - 1) * UC_SPACING_X
    uc_grid_h = uc_rows * UC_H + (uc_rows - 1) * UC_SPACING_Y

    # -- System boundary dimensions ---------------------------------------
    sys_w = uc_grid_w + 2 * SYS_PAD_X
    sys_h = uc_grid_h + SYS_PAD_TOP + SYS_PAD_BOT

    # -- Compute positions ------------------------------------------------
    # Primary actors: left column
    prim_x = MARGIN_LEFT
    max_actors = max(len(primary_actors), len(secondary_actors), 1)
    actor_block_h = max_actors * ACTOR_H + (max_actors - 1) * (ACTOR_SPACING_Y - ACTOR_H)
    total_h = max(sys_h, actor_block_h)

    # System boundary position
    sys_x = prim_x + ACTOR_W + GAP_ACTOR_SYS
    sys_y = MARGIN_TOP

    # Secondary actors: right column
    sec_x = sys_x + sys_w + GAP_SYS_ACTOR

    # -- Helper to add actor -----------------------------------------------
    def add_actor(name: str, kind: str, x: int, y: int):
        nonlocal comp_id, next_point_id
        type_code = "700" if kind == "Primary" else "703"
        tg, next_point_id = _tg_points_block(next_point_id)
        xml_parts.extend(
            [
                f'<COMPONENT type="{type_code}" id="{comp_id}" index="{comp_id}" uid="{uuid.uuid4()}">',
                f'<cdparam x="{x}" y="{y}"/>',
                f'<sizeparam width="{ACTOR_W}" height="{ACTOR_H}" minWidth="10" minHeight="1" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
                '<hidden value="false"/>',
                '<cdrectangleparam minX="10" maxX="2500" minY="10" maxY="1500"/>',
                f'<infoparam name="actor" value="{_xml_escape(name)}"/>',
                '<new d="false"/>',
                tg,
                '</COMPONENT>',
            ]
        )
        cy = y + ACTOR_H // 2
        components[name] = {
            "id": comp_id, "first_cp": next_point_id - 32,
            "x": x, "y": y,
            "lx": x, "ly": cy,              # left-center edge
            "rx": x + ACTOR_W, "ry": cy,     # right-center edge
            "cx": x + ACTOR_W // 2, "cy": cy,
        }
        comp_id += 1

    # -- Helper to add use case --------------------------------------------
    def add_uc(name: str, x: int, y: int, ext_text: str = ""):
        nonlocal comp_id, next_point_id
        tg, next_point_id = _tg_points_block(next_point_id)
        ext_xml = (
            f'<extraparam>\n<info extension="{_xml_escape(ext_text)}"/>\n</extraparam>'
            if ext_text
            else '<extraparam>\n<info extension=""/>\n</extraparam>'
        )
        xml_parts.extend(
            [
                f'<COMPONENT type="701" id="{comp_id}" index="{comp_id}" uid="{uuid.uuid4()}">',
                f'<cdparam x="{x}" y="{y}"/>',
                f'<sizeparam width="{UC_W}" height="{UC_H}" minWidth="1" minHeight="1" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
                '<hidden value="false"/>',
                '<cdrectangleparam minX="10" maxX="2500" minY="10" maxY="1500"/>',
                f'<infoparam name="Use case" value="{_xml_escape(name)}"/>',
                '<new d="false"/>',
                tg,
                ext_xml,
                '</COMPONENT>',
            ]
        )
        cy = y + UC_H // 2
        components[name] = {
            "id": comp_id, "first_cp": next_point_id - 32,
            "x": x, "y": y,
            "lx": x, "ly": cy,              # left-center edge
            "rx": x + UC_W, "ry": cy,       # right-center edge
            "cx": x + UC_W // 2, "cy": cy,
        }
        comp_id += 1

    # -- Place primary actors (left, vertically centered) ------------------
    prim_total = len(primary_actors) * ACTOR_H + max(0, len(primary_actors) - 1) * (ACTOR_SPACING_Y - ACTOR_H)
    prim_start_y = sys_y + max(0, (total_h - prim_total) // 2)
    for i, a in enumerate(primary_actors):
        ay = prim_start_y + i * ACTOR_SPACING_Y
        add_actor(a, "Primary", prim_x, ay)

    # -- Place secondary actors (right, vertically centered) ---------------
    sec_total = len(secondary_actors) * ACTOR_H + max(0, len(secondary_actors) - 1) * (ACTOR_SPACING_Y - ACTOR_H)
    sec_start_y = sys_y + max(0, (total_h - sec_total) // 2)
    for i, a in enumerate(secondary_actors):
        ay = sec_start_y + i * ACTOR_SPACING_Y
        add_actor(a, "Secondary", sec_x, ay)

    # -- Build extension text map ------------------------------------------
    ext_map: Dict[str, str] = {}
    for r in relationships or []:
        if (r.get("relationship_type") or "").lower() == "extend":
            t = r.get("target_name") or ""
            if t and t not in ext_map:
                ext_map[t] = r.get("extension") or ""

    # -- Place use cases (grid inside system boundary) ---------------------
    uc_origin_x = sys_x + SYS_PAD_X
    uc_origin_y = sys_y + SYS_PAD_TOP
    for idx, u in enumerate(use_cases):
        col = idx % UC_COLS
        row = idx // UC_COLS
        ux = uc_origin_x + col * (UC_W + UC_SPACING_X)
        uy = uc_origin_y + row * (UC_H + UC_SPACING_Y)
        add_uc(u, ux, uy, ext_text=ext_map.get(u, ""))

    # -- System boundary ---------------------------------------------------
    tg_sys, next_point_id = _tg_points_block(next_point_id)
    xml_parts.extend(
        [
            f'<COMPONENT type="702" id="{comp_id}" index="{comp_id}" uid="{uuid.uuid4()}">',
            f'<cdparam x="{sys_x}" y="{sys_y}"/>',
            f'<sizeparam width="{sys_w}" height="{max(sys_h, total_h)}" minWidth="100" minHeight="100" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
            '<hidden value="false"/>',
            '<cdrectangleparam minX="10" maxX="2500" minY="10" maxY="1500"/>',
            f'<infoparam name="border" value="{_xml_escape(system_name)}"/>',
            '<new d="false"/>',
            tg_sys,
            '</COMPONENT>',
        ]
    )
    comp_id += 1

    # -- Connectors --------------------------------------------------------
    rel_index = 0
    base_conn_id = comp_id
    for r in relationships or []:
        rt = (r.get("relationship_type") or "association").lower()
        if rt == "association":
            tcode = "110"
            label = "null"
        elif rt == "include":
            tcode = "111"
            label = "<<include>>"
        elif rt == "extend":
            tcode = "113"
            label = "<<extend>>"
        elif rt == "generalization":
            tcode = "112"
            label = "null"
        else:
            tcode = "110"
            label = "null"
        s_comp = components.get(r.get("source_name"), {})
        t_comp = components.get(r.get("target_name"), {})
        sid = s_comp.get("first_cp", 1)
        tid = t_comp.get("first_cp", 1)
        # Pick nearest edge: if source is LEFT of target, use source's
        # right edge → target's left edge, and vice versa.
        s_cx = s_comp.get("cx", 0)
        t_cx = t_comp.get("cx", 0)
        if s_cx <= t_cx:
            sx = s_comp.get("rx", s_cx);  sy = s_comp.get("ry", s_comp.get("cy", 0))
            tx = t_comp.get("lx", t_cx);  ty = t_comp.get("ly", t_comp.get("cy", 0))
        else:
            sx = s_comp.get("lx", s_cx);  sy = s_comp.get("ly", s_comp.get("cy", 0))
            tx = t_comp.get("rx", t_cx);  ty = t_comp.get("ry", t_comp.get("cy", 0))
        xml_parts.extend(
            [
                f'<CONNECTOR type="{tcode}" id="{base_conn_id + rel_index}" index="{rel_index}" uid="{uuid.uuid4()}">',
                f'<cdparam x="{(sx + tx) // 2}" y="{(sy + ty) // 2}"/>',
                '<sizeparam width="0" height="0" minWidth="0" minHeight="0" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
                f'<infoparam name="connector" value="{_xml_escape(label)}"/>',
                f'<P1 x="{sx}" y="{sy}" id="{sid}"/>',
                f'<P2 x="{tx}" y="{ty}" id="{tid}"/>',
                '<AutomaticDrawing data="true"/>',
                '<new d="false"/>',
                '</CONNECTOR>',
            ]
        )
        rel_index += 1

    xml_parts.append("</UseCaseDiagramPanel>")
    return "\n".join(xml_parts)


def _build_activity_panel(panel_name: str, steps: List[str]) -> str:
    """Minimal Avatar Activity Diagram guiding ordered edits."""
    # Component and connector ids
    comp_id = 1
    cp_id = 1
    xml = [f'<AvatarADPanel name="{_xml_escape(panel_name)}" minX="10" maxX="2500" minY="10" maxY="1500" zoom="1.0">']

    def tg_point():
        nonlocal cp_id
        val = cp_id
        cp_id += 1
        return val

    # Start state (5501)
    start_cp = tg_point()
    xml.extend([
        f'<COMPONENT type="5501" id="{comp_id}" index="0" uid="{uuid.uuid4()}">',
        '<cdparam x="140" y="100"/>',
        '<sizeparam width="15" height="15" minWidth="0" minHeight="0" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
        '<hidden value="false"/>',
        '<cdrectangleparam minX="10" maxX="2500" minY="10" maxY="1500"/>',
        '<infoparam name="start state" value="null"/>',
        '<new d="false"/>',
        f'<TGConnectingPoint num="0" id="{start_cp}"/>',
        '</COMPONENT>',
    ])
    comp_id += 1

    # Activity container (5507)
    act_cp = [tg_point() for _ in range(40)]
    xml.extend([
        f'<COMPONENT type="5507" id="{comp_id}" index="1" uid="{uuid.uuid4()}">',
        '<cdparam x="120" y="80"/>',
        '<sizeparam width="420" height="280" minWidth="40" minHeight="30" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
        '<hidden value="false"/>',
        '<enabled value="true"/>',
        '<cdrectangleparam minX="10" maxX="2500" minY="10" maxY="1500"/>',
        '<infoparam name="activity" value="Guided Alignment"/>',
        '<new d="false"/>',
    ])
    for i, cp in enumerate(act_cp):
        xml.append(f'<TGConnectingPoint num="{i}" id="{cp}"/>')
    xml.append('</COMPONENT>')
    comp_id += 1

    # Action states (5506) placed vertically
    action_cp_pairs = []
    y = 140
    sub_index = 0
    for step in steps:
        entry = tg_point()
        exitp = tg_point()
        action_cp_pairs.append((entry, exitp))
        xml.extend([
            f'<SUBCOMPONENT type="5506" id="{comp_id}" index="{2 + sub_index}" uid="{uuid.uuid4()}">',
            f'<father id="2" num="{sub_index}"/>',
            f'<cdparam x="200" y="{y}"/>',
            '<sizeparam width="250" height="24" minWidth="30" minHeight="0" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
            '<hidden value="false"/>',
            '<enabled value="true"/>',
            '<cdrectangleparam minX="0" maxX="420" minY="0" maxY="280"/>',
            f'<infoparam name="action state" value="{_xml_escape(step)}"/>',
            '<new d="false"/>',
            f'<TGConnectingPoint num="0" id="{entry}"/>',
            f'<TGConnectingPoint num="1" id="{exitp}"/>',
            '</SUBCOMPONENT>',
        ])
        comp_id += 1
        sub_index += 1
        y += 40

    # Stop state (5502)
    stop_cp = tg_point()
    xml.extend([
        f'<COMPONENT type="5502" id="{comp_id}" index="{2 + sub_index}" uid="{uuid.uuid4()}">',
        '<cdparam x="140" y="300"/>',
        '<sizeparam width="20" height="20" minWidth="0" minHeight="0" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
        '<hidden value="false"/>',
        '<cdrectangleparam minX="10" maxX="2500" minY="10" maxY="1500"/>',
        '<infoparam name="stop state" value="null"/>',
        '<new d="false"/>',
        f'<TGConnectingPoint num="0" id="{stop_cp}"/>',
        '</COMPONENT>',
    ])
    comp_id += 1

    # Connectors (5500) start -> actions -> stop
    conn_id = 1
    src = start_cp
    for entry, exitp in action_cp_pairs:
        xml.extend([
            f'<CONNECTOR type="5500" id="{100 + conn_id}" index="{conn_id - 1}" uid="{uuid.uuid4()}">',
            f'<cdparam x="150" y="{(entry + exitp)//2}"/>',
            '<sizeparam width="0" height="0" minWidth="0" minHeight="0" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
            '<infoparam name="connector" value="null"/>',
            f'<P1 x="150" y="150" id="{src}"/>',
            f'<P2 x="200" y="150" id="{entry}"/>',
            '<AutomaticDrawing data="true"/>',
            '<new d="false"/>',
            '</CONNECTOR>',
        ])
        src = exitp
        conn_id += 1
    xml.extend([
        f'<CONNECTOR type="5500" id="{100 + conn_id}" index="{conn_id - 1}" uid="{uuid.uuid4()}">',
        '<cdparam x="150" y="320"/>',
        '<sizeparam width="0" height="0" minWidth="0" minHeight="0" maxWidth="2000" maxHeight="2000" minDesiredWidth="0" minDesiredHeight="0"/>',
        '<infoparam name="connector" value="null"/>',
        f'<P1 x="200" y="320" id="{src}"/>',
        f'<P2 x="140" y="300" id="{stop_cp}"/>',
        '<AutomaticDrawing data="true"/>',
        '<new d="false"/>',
        '</CONNECTOR>',
    ])

    xml.append("</AvatarADPanel>")
    return "\n".join(xml)


def _max_numeric_id(root: ET.Element) -> int:
    max_id = 0
    for elem in root.iter():
        value = elem.attrib.get("id", "")
        if value.isdigit():
            max_id = max(max_id, int(value))
    return max_id


def _remap_panel_ids(panel: ET.Element, start_id: int) -> ET.Element:
    cloned = copy.deepcopy(panel)
    id_map: Dict[str, str] = {}
    next_id = start_id

    for elem in cloned.iter():
        old_id = elem.attrib.get("id")
        if old_id and old_id.isdigit() and old_id not in id_map:
            id_map[old_id] = str(next_id)
            next_id += 1

    for elem in cloned.iter():
        old_id = elem.attrib.get("id")
        if old_id in id_map:
            elem.set("id", id_map[old_id])

    return cloned


def _extract_reference_panel(xml_content: str, panel_name: str) -> ET.Element | None:
    if not (xml_content or "").strip():
        return None

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    fallback_panel = None
    for modeling in root.findall("Modeling"):
        if modeling.attrib.get("type") not in {"Avatar Analysis", "Analysis"}:
            continue
        for panel in modeling.findall("UseCaseDiagramPanel"):
            cloned = copy.deepcopy(panel)
            cloned.set("name", panel_name)
            if panel.find("COMPONENT") is not None or panel.find("CONNECTOR") is not None:
                return cloned
            if fallback_panel is None:
                fallback_panel = cloned

    return fallback_panel


def _build_reference_panel(reference_payload: Dict[str, Any], panel_name: str) -> ET.Element | None:
    # Preserve the reference case layout from the database XML exactly as stored.
    return _extract_reference_panel(reference_payload.get("xml_content") or "", panel_name)


def build_ttool_xml(
    system_name: str,
    primary_actors: List[str],
    secondary_actors: List[str],
    use_cases: List[str],
    relationships: List[Dict[str, Any]],
    generated_panel_name: str = "Use Case Diagram Generated by UCD Master",
    reference_payload: Dict[str, Any] | None = None,
    reference_panel_name: str = "Reference Base Case Diagram",
) -> str:
    """Produce a minimal TTool-compatible UCD XML with simple layout and stable ids.
    Includes an embedded <SysMLv2> CDATA block with the SysML v2 textual notation.
    """
    panel_xml = _build_ucd_panel(
        generated_panel_name, system_name, primary_actors, secondary_actors, use_cases, relationships
    )

    # Generate SysML v1 & v2 textual notations using the true generators
    from generation.sysml_ucd import generate_sysml_v1_text, generate_sysml_v2_text
    ss_mock = {
        "ucd_system_name": system_name,
        "ucd_primary_actors": primary_actors,
        "ucd_secondary_actors": secondary_actors,
        "ucd_use_cases": use_cases,
        "ucd_relationships": relationships
    }
    sysml_v1_text = generate_sysml_v1_text(ss_mock)
    sysml_v2_text = generate_sysml_v2_text(ss_mock)

    last_selected_sub_tab = "0"

    root = ET.Element(
        "TURTLEGMODELING",
        attrib={
            "version": "2.0",
            "ANIMATE_INTERACTIVE_SIMULATION": "true",
            "ACTIVATE_PENALTIES": "true",
            "UPDATE_INFORMATION_DIPLO_SIM": "true",
            "ANIMATE_WITH_INFO_DIPLO_SIM": "true",
            "OPEN_DIAG_DIPLO_SIM": "false",
            "LAST_SELECTED_MAIN_TAB": "0",
            "LAST_SELECTED_SUB_TAB": last_selected_sub_tab,
        },
    )
    analysis = ET.SubElement(root, "Modeling", attrib={"type": "Avatar Analysis", "nameTab": "Analysis"})
    analysis.append(ET.fromstring(panel_xml))

    if reference_payload:
        reference_panel = _build_reference_panel(reference_payload, reference_panel_name)
        if reference_panel is not None:
            remapped_panel = _remap_panel_ids(reference_panel, _max_numeric_id(root) + 1)
            analysis.append(remapped_panel)
            root.set("LAST_SELECTED_SUB_TAB", "1")

    return ET.tostring(root, encoding="utf-8").decode("utf-8")



def build_parallel_ttool_xml(user_payload: Dict[str, Any], reference_payload: Dict[str, Any]) -> str:
    """Emit a TTool XML containing two UCD panels plus a guided activity and empty requirements panel."""
    ref_norm = _normalize_ucd_payload(reference_payload)
    user_norm = _normalize_ucd_payload(user_payload)

    def _collect_validation_steps(data: Dict[str, Any]) -> List[str]:
        steps: List[str] = []
        actors = (data.get("primary_actors") or []) + (data.get("secondary_actors") or [])
        use_cases = data.get("use_cases") or []

        # Actor name validation
        for a in actors:
            try:
                comments, action = element_validation.validateActor(a, "actor")
                if comments:
                    steps.append(f"Actor '{a}': {comments[0]}")
            except Exception:
                continue

        # Use case name validation
        for uc in use_cases:
            try:
                comments, action = element_validation.validateUsecase(uc, "usecase")
                if comments:
                    steps.append(f"Use case '{uc}': {comments[0]}")
            except Exception:
                continue

        # Relationship sanity: include/extend self or duplicates
        rels = data.get("relationships") or []
        uc_set = set(use_cases)  # O(1) membership check against the merged UC list
        seen = set()
        for r in rels:
            rt = (r.get("relationship_type") or "").lower()
            s = r.get("source_name") or ""
            t = r.get("target_name") or ""
            key = (s.lower(), t.lower(), rt)
            if key in seen:
                steps.append(f"Duplicate {rt} link between '{s}' and '{t}' — remove one copy.")
            seen.add(key)
            if s == t:
                steps.append(f"{rt.title()} uses same source/target '{s}' — choose different elements.")
            if rt in {"include", "extend"} and (s not in uc_set or t not in uc_set):
                steps.append(f"{rt.title()} must link use cases only — adjust '{s}' -> '{t}'.")
        if not steps:
            steps.append("Review diagram — no validation issues detected.")
        return steps[:10]

    steps = _collect_validation_steps(user_norm)

    xml_parts = [
        '<TURTLEGMODELING version="2.0" ANIMATE_INTERACTIVE_SIMULATION="true" ACTIVATE_PENALTIES="true" UPDATE_INFORMATION_DIPLO_SIM="false" ANIMATE_WITH_INFO_DIPLO_SIM="true" OPEN_DIAG_DIPLO_SIM="false" LAST_SELECTED_MAIN_TAB="0" LAST_SELECTED_SUB_TAB="2">',
        '<Modeling type="Avatar Analysis" nameTab="Analysis">',
        _build_ucd_panel("ValidatedSimilarUCDFromDB", ref_norm["system_name"], ref_norm["primary_actors"], ref_norm["secondary_actors"], ref_norm["use_cases"], ref_norm["relationships"]),
        _build_ucd_panel("YourRequestedModelOutline", user_norm["system_name"], user_norm["primary_actors"], user_norm["secondary_actors"], user_norm["use_cases"], user_norm["relationships"]),
        _build_activity_panel("ActivityDiagram 0", steps),
        '</Modeling>',
        '<Modeling type="Avatar Requirement" nameTab="Requirements">',
        '<AvatarRDPanel name="AVATARRD" minX="10" maxX="2500" minY="10" maxY="1500" zoom="1.0"> </AvatarRDPanel>',
        '</Modeling>',
        '</TURTLEGMODELING>',
    ]
    return "\n".join(xml_parts)
