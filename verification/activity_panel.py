"""TTool activity-panel builder for verification notes inside activity panels."""

import copy
import os
import textwrap
import uuid
import xml.etree.ElementTree as ET


def _max_id_in_xml(root: ET.Element) -> int:
    m = 0
    for e in root.iter():
        v = e.get("id", "")
        if v.isdigit():
            m = max(m, int(v))
    return m


class _IdGen:
    def __init__(self, start):
        self._n = start

    def next(self):
        v = self._n
        self._n += 1
        return v


def _remap_panel_ids(panel: ET.Element, id_gen: _IdGen) -> ET.Element:
    """Clone a panel subtree and remap all internal ids to fresh values.

    Requirement panels loaded from ``ucd_rules.xml`` ship with static ids.
    Reusing them verbatim creates collisions with the generated diagram and
    verification tabs, which can make TTool ignore or misrender appended tabs.
    """
    cloned = copy.deepcopy(panel)
    id_map: dict[str, str] = {}
    definers = {"COMPONENT", "CONNECTOR", "SUBCOMPONENT", "TGConnectingPoint"}

    for elem in cloned.iter():
        if elem.tag not in definers:
            continue
        old_id = elem.get("id")
        if old_id and old_id.isdigit() and old_id not in id_map:
            id_map[old_id] = str(id_gen.next())

    for elem in cloned.iter():
        old_id = elem.get("id")
        if old_id in id_map:
            elem.set("id", id_map[old_id])

    return cloned


def _normalize_line(text: str) -> str:
    """Collapse tabs/spaces inside a single line while preserving line breaks."""
    return " ".join(text.replace("\t", " ").split())


# Layout constants
PADDING_PCT = 0.10
SWIM_X, SWIM_Y = 60, 60
SWIM_W = 1000
PANEL_W = 1100
ROW_SPACING = 44
STANDARD_NOTE_W = 620
NOTE_LINE_H = 18
NOTE_V_PAD = 14
NOTE_MIN_H = 24
NOTE_CP_COUNT = 16
NOTE_ENTRY_CP_NUM = 1
NOTE_EXIT_CP_NUM = 6
PIXELS_PER_CHAR = 7.2
N_CPS = 40
X_C = SWIM_X + int(SWIM_W * 0.5)


def _wrap_note_lines(text: str, max_chars: int) -> list[str]:
    """Wrap a note to the available width while preserving paragraph breaks."""
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    wrapped = []
    for raw_line in raw_lines:
        line = _normalize_line(raw_line)
        if not line:
            if wrapped and wrapped[-1] != "":
                wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                line,
                width=max_chars,
                break_long_words=True,
                break_on_hyphens=False,
            )
        )
    return wrapped or ["No issues detected."]


def _note_height(lines: list[str]) -> int:
    """Return note height from rendered line count."""
    line_count = max(1, len(lines))
    return max(NOTE_MIN_H, line_count * NOTE_LINE_H + 2 * NOTE_V_PAD)


def _make_note_connector(panel: ET.Element, conn_id: int, index: int,
                         p1_id: int, p1x: int, p1y: int,
                         p2_id: int, p2x: int, p2y: int) -> None:
    conn = ET.SubElement(panel, "CONNECTOR", attrib={
        "type": "118", "id": str(conn_id),
        "index": str(index), "uid": str(uuid.uuid4())})
    ET.SubElement(conn, "cdparam", attrib={"x": str(p2x), "y": str(p2y)})
    ET.SubElement(conn, "sizeparam", attrib={
        "width": "0", "height": "0", "minWidth": "0", "minHeight": "0",
        "maxWidth": "2000", "maxHeight": "2000",
        "minDesiredWidth": "0", "minDesiredHeight": "0"})
    ET.SubElement(conn, "infoparam", attrib={"name": "connector", "value": "null"})
    ET.SubElement(conn, "P1", attrib={"x": str(p1x), "y": str(p1y), "id": str(p1_id)})
    ET.SubElement(conn, "P2", attrib={"x": str(p2x), "y": str(p2y), "id": str(p2_id)})
    ET.SubElement(conn, "AutomaticDrawing", attrib={"data": "false"})
    ET.SubElement(conn, "new", attrib={"d": "false"})


def _make_note_component(panel: ET.Element, id_gen: _IdGen,
                         note_id: int, index: int,
                         x: int, y: int, w: int, h: int,
                         lines: list[str], panel_h: int) -> tuple[int, int]:
    """Create a UML note component and return (entry_cp_id, exit_cp_id)."""
    note = ET.SubElement(panel, "COMPONENT", attrib={
        "type": "301", "id": str(note_id),
        "index": str(index), "uid": str(uuid.uuid4())})
    ET.SubElement(note, "cdparam", attrib={"x": str(x), "y": str(y)})
    ET.SubElement(note, "sizeparam", attrib={
        "width": str(w), "height": str(h),
        "minWidth": str(w), "minHeight": "10",
        "maxWidth": str(w), "maxHeight": "2000",
        "minDesiredWidth": "0", "minDesiredHeight": "0"})
    ET.SubElement(note, "hidden", attrib={"value": "false"})
    ET.SubElement(note, "cdrectangleparam", attrib={
        "minX": "10", "maxX": str(PANEL_W), "minY": "10", "maxY": str(panel_h)})
    note_lines = ["UML note:", "Double-click to edit", *lines]
    ET.SubElement(note, "infoparam", attrib={
        "name": "UML Note",
        "value": "\n".join(note_lines) + "\n",
    })
    ET.SubElement(note, "new", attrib={"d": "false"})

    cp_ids = []
    for cp_num in range(NOTE_CP_COUNT):
        cp_id = id_gen.next()
        cp_ids.append(cp_id)
        ET.SubElement(note, "TGConnectingPoint", attrib={"num": str(cp_num), "id": str(cp_id)})

    extra = ET.SubElement(note, "extraparam")
    for line in note_lines:
        ET.SubElement(extra, "Line", attrib={"value": line})

    return cp_ids[NOTE_ENTRY_CP_NUM], cp_ids[NOTE_EXIT_CP_NUM]


def build_activity_panel(name: str, steps: list, id_gen: _IdGen) -> ET.Element:
    steps = [s for s in steps if s and s.strip()]
    if not steps:
        steps = ["No issues detected."]

    content_left = int(SWIM_X + SWIM_W * PADDING_PCT)
    content_w = int(SWIM_W * (1 - 2 * PADDING_PCT))
    note_w = min(STANDARD_NOTE_W, content_w)
    note_x = content_left + (content_w - note_w) // 2
    max_chars = max(20, int(note_w / PIXELS_PER_CHAR))
    wrapped_steps = [_wrap_note_lines(step, max_chars) for step in steps]
    step_heights = [_note_height(lines) for lines in wrapped_steps]

    n = len(wrapped_steps)
    content_height = sum(step_heights) + (n - 1) * ROW_SPACING + 100
    swim_h = int(content_height / (1 - 2 * PADDING_PCT))
    swim_h = max(swim_h, 200)

    content_top = int(SWIM_Y + swim_h * PADDING_PCT)
    step_y0 = content_top + 24
    step_ys = []
    y_acc = step_y0
    for h in step_heights:
        step_ys.append(y_acc)
        y_acc += h + ROW_SPACING

    panel_h = y_acc + 40

    panel = ET.Element("AvatarADPanel", attrib={
        "name": name,
        "minX": "10", "maxX": str(PANEL_W),
        "minY": "10", "maxY": str(panel_h), "zoom": "1.0"
    })

    connector_index = 0
    previous = None

    for idx, note_lines in enumerate(wrapped_steps):
        note_y = step_ys[idx]
        note_h = step_heights[idx]
        note_id = id_gen.next()
        entry_cp, exit_cp = _make_note_component(
            panel, id_gen, note_id, 2 + idx, note_x, note_y, note_w, note_h, note_lines, panel_h
        )

        note_center_x = note_x + note_w // 2
        note_top_y = note_y
        note_bottom_y = note_y + note_h

        if previous is not None:
            _make_note_connector(
                panel, id_gen.next(), connector_index,
                previous["exit_cp"], previous["x"], previous["bottom_y"],
                entry_cp, note_center_x, note_top_y,
            )
            connector_index += 1

        previous = {
            "exit_cp": exit_cp,
            "x": note_center_x,
            "bottom_y": note_bottom_y,
        }

    # Keep the activity block last in the XML so it renders behind the notes in TTool.
    swim_id = id_gen.next()
    swim_cps = [id_gen.next() for _ in range(N_CPS)]
    swimlane = ET.SubElement(panel, "COMPONENT", attrib={
        "type": "5507", "id": str(swim_id), "index": str(1 + n + connector_index), "uid": str(uuid.uuid4())})
    ET.SubElement(swimlane, "cdparam", attrib={"x": str(SWIM_X), "y": str(SWIM_Y)})
    ET.SubElement(swimlane, "sizeparam", attrib={
        "width": str(SWIM_W), "height": str(swim_h),
        "minWidth": "40", "minHeight": "30",
        "maxWidth": "2000", "maxHeight": "2000",
        "minDesiredWidth": "0", "minDesiredHeight": "0"})
    ET.SubElement(swimlane, "hidden", attrib={"value": "false"})
    ET.SubElement(swimlane, "enabled", attrib={"value": "true"})
    ET.SubElement(swimlane, "cdrectangleparam", attrib={
        "minX": "10", "maxX": str(PANEL_W), "minY": "10", "maxY": str(panel_h)})
    ET.SubElement(swimlane, "infoparam", attrib={"name": "activity", "value": name})
    ET.SubElement(swimlane, "new", attrib={"d": "false"})
    for i, cp in enumerate(swim_cps):
        ET.SubElement(swimlane, "TGConnectingPoint", attrib={"num": str(i), "id": str(cp)})

    return panel


# Fixed order for all verification tabs to keep exported TTool tabs stable.
VERIFICATION_GROUPS = [
    "System",
    "Primary Actors",
    "Secondary Actors",
    "Use Cases",
    "Connectors",
]

TAB_LABELS = {
    "System": "VER_System_Issues",
    "Primary Actors": "VER_Primary_Actor_Issues",
    "Secondary Actors": "VER_Secondary_Actor_Issues",
    "Use Cases": "VER_Use_Case_Issues",
    "Connectors": "VER_Connector_Issues",
}


def append_grouped_activity_panels(xml_content: str, groups: dict) -> str:
    import re as _re

    # ET cannot round-trip CDATA sections, so extract SysML blocks before parsing
    # and re-inject them verbatim after serialisation.
    _sysml_pattern = _re.compile(r"<(SysMLv[12])>.*?</\1>", _re.DOTALL)
    sysml_full_blocks = [m.group(0) for m in _sysml_pattern.finditer(xml_content)]
    clean_xml = _sysml_pattern.sub("", xml_content)


    root = ET.fromstring(clean_xml)
    id_gen = _IdGen(_max_id_in_xml(root) + 1)

    ver = ET.SubElement(root, "Modeling", attrib={
        "type": "Avatar Analysis", "nameTab": "Verification"})
    for gname in VERIFICATION_GROUPS:
        steps = groups.get(gname, []) if groups else []
        pname = TAB_LABELS.get(gname, "VER_{}_Issues".format(gname.replace(" ", "_")))
        ver.append(build_activity_panel(pname, steps, id_gen))

    req = ET.SubElement(root, "Modeling", attrib={
        "type": "Avatar Requirement", "nameTab": "Requirements"})
    rules_path = os.path.join(os.path.dirname(__file__), "ucd_rules.xml")
    if os.path.exists(rules_path):
        try:
            for rm in ET.parse(rules_path).getroot().findall("Modeling"):
                for p in rm.findall("AvatarRDPanel"):
                    remapped_panel = _remap_panel_ids(p, id_gen)
                    remapped_panel.set("name", rm.get("nameTab", "Rules"))
                    req.append(remapped_panel)
        except ET.ParseError as e:
            req.append(ET.Comment(f" ucd_rules.xml error: {e} "))

    serialized = ET.tostring(root, encoding="utf-8").decode("utf-8")

    # Re-inject SysML CDATA blocks just before the closing root tag
    if sysml_full_blocks:
        injection = "\n".join(sysml_full_blocks) + "\n"
        serialized = serialized.replace("</TURTLEGMODELING>",
                                        injection + "</TURTLEGMODELING>")

    return serialized



def append_activity_panel(xml_content: str, steps: list) -> str:
    """Legacy single-panel API."""
    root = ET.fromstring(xml_content)
    id_gen = _IdGen(_max_id_in_xml(root) + 1)
    modeling = root.find(".//Modeling[@type='Avatar Analysis']") or root.find("Modeling")
    if modeling is not None:
        modeling.append(build_activity_panel("Verification Steps", steps, id_gen))
    rules_path = os.path.join(os.path.dirname(__file__), "ucd_rules.xml")
    if os.path.exists(rules_path):
        try:
            for me in ET.parse(rules_path).getroot().findall("Modeling"):
                for p in me.findall("AvatarRDPanel"):
                    remapped = _remap_panel_ids(p, id_gen)
                    remapped.set("name", me.get("nameTab", "Rules"))
                    req = ET.SubElement(root, "Modeling", attrib={
                        "type": "Avatar Requirement",
                        "nameTab": me.get("nameTab", "Rules"),
                    })
                    req.append(remapped)
        except ET.ParseError:
            pass
    return ET.tostring(root, encoding="utf-8").decode("utf-8")
