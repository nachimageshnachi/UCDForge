"""Session save/load helpers - serialize UCD wizard state to/from XML."""

import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import streamlit as st


# Keys that belong to the UCD session (ordered: step 1 - 9)
_SESSION_KEYS = {
    "ucd_system_name": "str",
    "ucd_paragraph": "str",
    "_saved_paragraph": "str",
    "ucd_primary_actors": "list",
    "ucd_secondary_actors": "list",
    "ucd_actors": "list",
    "ucd_use_cases": "list",
    "ucd_domains": "list",
    "ucd_relationships": "list_dict",
    "ucd_match_pairs": "list_dict",
    "ucd_visible_actors": "list",
    "ucd_actor_colors": "dict",
    "ucd_include_pairs": "list_dict",
    "ucd_extend_pairs": "list_dict",
    "ucd_extend_meta": "dict",
    "ucd_uc_gen_pairs": "list_dict",
    "ucd_uc_colors": "dict",
    "ucd_actor_gen_pairs": "list_dict",
    "ucd_current_step": "int",
    "ucd_completed_steps": "set_int",
    "ucd_ready": "bool",
    "ucd_elements_saved": "bool",
    # Step 9 outputs - included automatically once CBR matching runs
    "ucd_ttool_xml": "str",
    "ucd_ttool_xml_base": "str",   # base XML (before activity panels) — saves a rebuild on reload
    "cbr_matches": "list_dict",
    # CBR retrieval results (populated in Step 1 after extraction)
    "cbr_top_case": "dict",
    "cbr_suggested_primary": "list",
    "cbr_suggested_secondary": "list",
    "cbr_suggested_use_cases": "list",
    "cbr_suggested_relationships": "list_dict",
}


# ---------------------------------------------------------------------------
# Save: session state - XML string
# ---------------------------------------------------------------------------

def session_to_xml(step_name: str = "") -> str:
    root = ET.Element("UCDSession")

    # -- Metadata block: what step was active and when it was saved ----------
    from datetime import datetime, timezone
    meta = ET.SubElement(root, "Metadata")
    ET.SubElement(meta, "SavedAt").text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur_step = st.session_state.get("ucd_current_step", 1)
    ET.SubElement(meta, "CurrentStep").text = str(cur_step)
    ET.SubElement(meta, "CurrentStepName").text = step_name or f"Step {cur_step}"
    done = sorted(st.session_state.get("ucd_completed_steps") or [])
    ET.SubElement(meta, "CompletedSteps").text = ",".join(str(s) for s in done)
    ET.SubElement(meta, "PopulatedUpToStep").text = str(max(done, default=cur_step))

    for key, dtype in _SESSION_KEYS.items():
        val = st.session_state.get(key)
        if val is None:
            continue
        node = ET.SubElement(root, key)

        if dtype == "str":
            node.text = str(val)

        elif dtype == "int":
            node.text = str(val)

        elif dtype == "bool":
            node.text = "true" if val else "false"

        elif dtype == "list":
            for item in (val or []):
                ET.SubElement(node, "item").text = str(item)

        elif dtype == "set_int":
            for item in sorted(val or set()):
                ET.SubElement(node, "item").text = str(item)

        elif dtype == "dict":
            for k, v in (val or {}).items():
                e = ET.SubElement(node, "entry")
                e.set("key", str(k))
                e.text = str(v)

        elif dtype == "list_dict":
            for d in (val or []):
                e = ET.SubElement(node, "record")
                if isinstance(d, dict):
                    for k, v in d.items():
                        e.set(str(k), str(v) if v is not None else "")
                elif isinstance(d, (list, tuple)):
                    # Pair stored as tuple/list, e.g. (actor, usecase)
                    for i, v in enumerate(d):
                        e.set(f"item_{i}", str(v) if v is not None else "")

        elif dtype == "dict_of_dict":
            for outer_k, inner in (val or {}).items():
                outer = ET.SubElement(node, "entry")
                outer.set("key", str(outer_k))
                for k, v in (inner or {}).items():
                    outer.set(str(k), str(v) if v is not None else "")

    raw = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ")


# ---------------------------------------------------------------------------
# Load: XML string - session state
# ---------------------------------------------------------------------------

def xml_to_session(xml_bytes: bytes) -> bool:
    """Parse XML bytes and restore session state. Returns True on success."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        st.error(f"Invalid XML file: {e}")
        return False

    for key, dtype in _SESSION_KEYS.items():
        node = root.find(key)
        if node is None:
            continue

        if dtype == "str":
            st.session_state[key] = node.text or ""

        elif dtype == "int":
            try:
                st.session_state[key] = int(node.text)
            except (TypeError, ValueError):
                pass

        elif dtype == "bool":
            st.session_state[key] = (node.text or "").lower() == "true"

        elif dtype == "list":
            st.session_state[key] = [e.text or "" for e in node.findall("item")]

        elif dtype == "set_int":
            st.session_state[key] = {
                int(e.text) for e in node.findall("item") if e.text
            }

        elif dtype == "dict":
            st.session_state[key] = {
                e.get("key"): e.text or "" for e in node.findall("entry")
            }

        elif dtype == "list_dict":
            result = []
            for e in node.findall("record"):
                attrib = dict(e.attrib)
                # If every key is item_N, it was stored as a tuple — restore as (int, int)
                item_keys = [k for k in attrib if k.startswith("item_")]
                non_item  = [k for k in attrib if not k.startswith("item_")]
                if item_keys and not non_item:
                    try:
                        ordered = sorted(item_keys, key=lambda k: int(k.split("_")[1]))
                        result.append(tuple(int(attrib[k]) for k in ordered))
                        continue
                    except (ValueError, IndexError):
                        pass
                result.append(attrib)
            st.session_state[key] = result


        elif dtype == "dict_of_dict":
            result = {}
            for e in node.findall("entry"):
                outer_k = e.get("key")
                inner = {k: v for k, v in e.attrib.items() if k != "key"}
                result[outer_k] = inner
            st.session_state[key] = result

    return True
