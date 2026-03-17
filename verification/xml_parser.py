"""
TTool XML parser — extracts UCD data from TTool XML files and runs
verification rules on the parsed model.

Renamed from ``ucd_validation_operation`` to ``UcdVerificationParser``.
"""

import xml.etree.ElementTree as ET
import html

import streamlit as st
import pandas as pd

from verification.element_verification import element_verification


class UcdVerificationParser:
    def __init__(self, file_name):
        self.file_name = file_name

    def extractData(self):
        tree = ET.parse(self.file_name)
        root = tree.getroot()
        modeling_elems = [
            m for m in root.findall('Modeling')
            if m.attrib.get('type') in ('Avatar Analysis', 'Analysis')
        ]
        if not modeling_elems:
            st.error("No Use Case Diagram Found in File!")
            return

        modeldata = []

        for modeling in modeling_elems:
            usecasediagrampanel_elems = [
                u for u in modeling.findall('UseCaseDiagramPanel')
            ]

            ucddata = []

            for usecasediagrampanel in usecasediagrampanel_elems:
                if usecasediagrampanel is None:
                    st.warning(f"No Use Case Diagram present in {modeling}")
                    continue

                name_of_ucd = usecasediagrampanel.attrib.get('name')

                stickman_actors = []
                box_actors = []
                use_cases = []
                system_boundary = []
                connectors = []


                def _meta(cdp, szp):
                    return {
                        "X": cdp.attrib.get('x', '0'),
                        "Y": cdp.attrib.get('y', '0'),
                        "W": szp.attrib.get('width', '0'),
                        "H": szp.attrib.get('height', '0'),
                        "Comments": [],
                        "Action": "Well Written"
                    }

                for component in usecasediagrampanel.findall('COMPONENT'):
                    infoparam = component.find('infoparam')
                    cdparam = component.find('cdparam')
                    sizeparam = component.find('sizeparam')
                    if infoparam is None or cdparam is None or sizeparam is None:
                        continue

                    if component.attrib.get('type') == '700':
                        stick_act = infoparam.attrib.get('value', '')
                        stickman_actors.append((stick_act, {"Element Type": "Primary Actor", **_meta(cdparam, sizeparam)}))

                    elif component.attrib.get('type') == '701':
                        uc = infoparam.attrib.get('value', '')
                        use_cases.append((uc, {"Element Type": "Use Case", **_meta(cdparam, sizeparam)}))

                    elif component.attrib.get('type') == '702':
                        sys = infoparam.attrib.get('value', '')
                        system_boundary.append((sys, {"Element Type": "System Boundary", **_meta(cdparam, sizeparam)}))

                    elif component.attrib.get('type') == '703':
                        box_act = infoparam.attrib.get('value', '')
                        box_actors.append((box_act, {"Element Type": "Secondary Actor", **_meta(cdparam, sizeparam)}))
                    else:
                        continue

                if len(system_boundary) != 1:
                    st.error(
                        f"❌ Diagram '{name_of_ucd}' must have exactly one System Boundary "
                        f"(found {len(system_boundary)}). Skipping this diagram."
                    )
                    continue

                all_actors_count = len(stickman_actors) + len(box_actors)
                if all_actors_count == 0:
                    st.error(
                        f"❌ Diagram '{name_of_ucd}' has no actors (primary or secondary). "
                        "A Use Case Diagram must have at least one actor. Skipping this diagram."
                    )
                    continue

                if len(use_cases) == 0:
                    st.error(
                        f"❌ Diagram '{name_of_ucd}' has no use cases. "
                        "A Use Case Diagram must have at least one use case. Skipping this diagram."
                    )
                    continue

                for connector in usecasediagrampanel.findall('CONNECTOR'):
                    extension = ''
                    relation_id = connector.attrib.get('id')
                    relation_code = connector.attrib.get('type')
                    if relation_code == "118":
                        continue
                    conn_infoparam = connector.find('infoparam')
                    p1 = connector.find('P1')
                    p2 = connector.find('P2')
                    if conn_infoparam is None or p1 is None or p2 is None:
                        continue
                    relation_name = conn_infoparam.attrib.get('name', '')
                    relation_value_raw = conn_infoparam.attrib.get('value', '')
                    relation_value = html.unescape(relation_value_raw).lower()
                    source = p1.attrib.get('id', '')
                    target = p2.attrib.get('id', '')

                    # BUG 1 FIX: Initialize all variables before inner loop to avoid UnboundLocalError
                    source_name = ""
                    target_name = ""
                    source_type = ""
                    target_type = ""

                    for component in usecasediagrampanel.findall('COMPONENT'):
                        comp_infoparam = component.find('infoparam')
                        if comp_infoparam is None:
                            continue
                        for connectingpoint in component.findall('TGConnectingPoint'):
                            if source == connectingpoint.attrib.get('id'):
                                source_name = comp_infoparam.attrib.get('value', '')
                                source_type = comp_infoparam.attrib.get('name', '')
                                if "extend" in relation_value:
                                    relation_value = "Extend"
                                    # BUG 2 FIX: Guard extraparam None access
                                    ep = component.find('extraparam')
                                    if ep is not None:
                                        info = ep.find('info')
                                        extension = info.attrib.get('extension', '') if info is not None else ''
                                    else:
                                        extension = ''
                                if "include" in relation_value:
                                    relation_value = "Include"
                                if relation_code == "112":
                                    relation_value = "Generalization"
                                if relation_code == "110":
                                    relation_value = "Association"

                            elif target == connectingpoint.attrib.get('id'):
                                target_name = comp_infoparam.attrib.get('value', '')
                                target_type = comp_infoparam.attrib.get('name', '')

                    connectors.append((relation_id, {"Relation Code": relation_code, "Relation Name": relation_name, "Relation Value": relation_value, "Source Type": source_type, "Target Type": target_type, "Source Name": source_name, "Target Name": target_name, "Extension": extension, "Comments": [], "Action": ""}))

                ucddata.append({name_of_ucd: {"Primary Actors": stickman_actors, "Secondary Actors": box_actors, "Use Cases": use_cases, "System Boundary": system_boundary, "Connectors": connectors, "Comments": [], "Action": ""}})

            modeldata.append({modeling.attrib.get("nameTab"): {"Ucd Data": ucddata}})

        return modeldata

    def processData(self, modeldata):
        for model in modeldata:
            for tab_name, tab_data in model.items():
                ucddata = tab_data.get('Ucd Data', [])

                for ucd_index, ucd in enumerate(ucddata):
                    for ucd_name, ucd_details in ucd.items():
                        stickman_actors = ucd_details.get("Primary Actors", [])
                        box_actors = ucd_details.get("Secondary Actors", [])
                        use_cases = ucd_details.get("Use Cases", [])
                        connectors = ucd_details.get("Connectors", [])
                        system_boundary = ucd_details.get("System Boundary", [])

                        stickman_actors_list = [stickman_actors[i][0] for i in range(len(stickman_actors))]
                        box_actors_list = [box_actors[i][0] for i in range(len(box_actors))]
                        actors_list = stickman_actors_list + box_actors_list

                        actors_with_meta = stickman_actors + box_actors

                        element_verification.validateActors(actors_with_meta)
                        element_verification.validateUsecases(use_cases)

                        action_map = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
                        for i, (stick_actor_name, stick_actor_meta) in enumerate(stickman_actors):
                            comments, action = element_verification.validateActor(stick_actor_name, "Primary Actor")
                            stick_actor_meta["Comments"].extend(comments)
                            prev_action = stick_actor_meta["Action"]
                            prev_level = action_map.get(prev_action, 0)
                            new_level = max(prev_level, action_map[action])
                            stick_actor_meta["Action"] = next(k for k, v in action_map.items() if v == new_level)

                        for i, (box_actor_name, box_actor_meta) in enumerate(box_actors):
                            comments, action = element_verification.validateActor(box_actor_name, "Secondary Actor")
                            box_actor_meta["Comments"].extend(comments)
                            prev_action = box_actor_meta["Action"]
                            prev_level = action_map.get(prev_action, 0)
                            new_level = max(prev_level, action_map[action])
                            box_actor_meta["Action"] = next(k for k, v in action_map.items() if v == new_level)

                        for i, (uc_name, uc_meta) in enumerate(use_cases):
                            comments, action = element_verification.validateUsecase(uc_name, system_boundary[0][0])
                            uc_meta["Comments"].extend(comments)
                            prev_action = uc_meta["Action"]
                            prev_level = action_map.get(prev_action, 0)
                            new_level = max(prev_level, action_map[action])
                            uc_meta["Action"] = next(k for k, v in action_map.items() if v == new_level)

                        comments, action = element_verification.validateSystem(system_boundary[0][0])

                        priority = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
                        prev = system_boundary[0][1].get("Action") or "Well Written"

                        if priority[action] > priority[prev]:
                            system_boundary[0][1]["Comments"].extend(comments)
                            system_boundary[0][1]["Action"] = action

                        element_verification.validateArrangement(stickman_actors, box_actors, use_cases, system_boundary)

                        element_verification.validateActorConnectivity(actors_with_meta, use_cases, connectors)

                        element_verification.validateUsecaseConnectivity(use_cases, actors_with_meta, connectors)

                        element_verification.validateRelations(connectors, actors_with_meta, use_cases)

    def showUcdTables(self, modeldata):
        def style_action(df):
            def highlight_row(row):
                action = row["Action"]
                if action == "Attention Required!":
                    return ['background-color: #FFCCCC'] * len(row)
                elif action == "Warning!":
                    return ['background-color: #FFF5CC'] * len(row)
                else:
                    return ['background-color: #E6FFCC'] * len(row)
            return df.style.apply(highlight_row, axis=1)

        for model_dict in modeldata:
            for modeling_tab_name, content in model_dict.items():
                st.title(f"Modeling Tab: {modeling_tab_name}")

                ucddata_list = content.get("Ucd Data", [])
                for ucd_dict in ucddata_list:
                    for ucd_name, ucd_content in ucd_dict.items():
                        st.header(f"Use Case Diagram: {ucd_name}")

                        def render_component_table(title, components):
                            data = []
                            for name, meta in components:
                                data.append({
                                    "Name": name,
                                    "Type": meta.get("Element Type", ""),
                                    "Comments": ", ".join(meta.get("Comments", [])),
                                    "Action": meta.get("Action", "")
                                })
                            df = pd.DataFrame(data)
                            st.subheader(title)
                            st.dataframe(style_action(df), use_container_width=True)

                        render_component_table("Primary Actors", ucd_content.get("Primary Actors", []))
                        render_component_table("Secondary Actors", ucd_content.get("Secondary Actors", []))
                        render_component_table("Use Cases", ucd_content.get("Use Cases", []))

                        # System Boundary
                        system_data = []
                        for name, meta in ucd_content.get("System Boundary", []):
                            system_data.append({
                                "Name": name,
                                "Type": meta.get("Element Type"),
                                "Comments": ", ".join(meta.get("Comments", [])),
                                "Action": meta.get("Action", "")
                            })
                        df_system = pd.DataFrame(system_data)
                        st.subheader("System Boundary")
                        st.dataframe(style_action(df_system), use_container_width=True)

                        # Connectors
                        connectors_data = []
                        for conn_id, meta in ucd_content.get("Connectors", []):
                            connectors_data.append({
                                "Relation Value": meta.get("Relation Value"),
                                "Source Name": meta.get("Source Name"),
                                "Source Type": meta.get("Source Type"),
                                "Target Name": meta.get("Target Name"),
                                "Target Type": meta.get("Target Type"),
                                "Extension": meta.get("Extension", ""),
                                "Comments": ", ".join(meta.get("Comments", [])) if meta.get("Comments") else "",
                                "Action": meta.get("Action", "")
                            })
                        df_connectors = pd.DataFrame(connectors_data)
                        st.subheader("Connectors")
                        st.dataframe(style_action(df_connectors), use_container_width=True)

                        st.markdown("---")
