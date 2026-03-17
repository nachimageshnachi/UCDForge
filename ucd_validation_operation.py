import math
import os
import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import nltk
from nltk.corpus import words, wordnet
from nltk import pos_tag, word_tokenize
from nltk.stem import WordNetLemmatizer
import re
import spacy
import html
from sentence_transformers import CrossEncoder, SentenceTransformer, util
from flair.data import Sentence
from flair.models import SequenceTagger
import uuid

@st.cache_resource
def setup_nltk():
    nltk.download('words')
    nltk_data_dir = os.path.join(os.path.expanduser('~'), 'nltk_data')
    if not os.path.exists(nltk_data_dir):
        os.makedirs(nltk_data_dir)

    nltk.download('punkt', download_dir=nltk_data_dir)
    nltk.download('averaged_perceptron_tagger', download_dir=nltk_data_dir)
    nltk.download('wordnet', download_dir=nltk_data_dir)
    nltk.download('omw-1.4', download_dir=nltk_data_dir)    

    return nltk_data_dir

@st.cache_resource
def getSpacyModel():
    try:
        return spacy.load("en_core_web_md")
    except OSError:
        spacy.cli.download("en_core_web_md")
        return spacy.load("en_core_web_md")

@st.cache_resource
def getSimilarityEncoder():
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L12-v2")

@st.cache_resource
def getLemmatizer():
    return WordNetLemmatizer()

@st.cache_resource
def getFlairPosTagger():
    return SequenceTagger.load("flair/pos-english")
    
setup_nltk()

lemmatizer = getLemmatizer()

class ucd_validation_operation:
    def __init__(self,file_name):
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
        
        modeldata=[]
        
        for modeling in modeling_elems:
            usecasediagrampanel_elems = [
                u for u in modeling.findall('UseCaseDiagramPanel')
            ]
            
            ucddata=[]
            
            for usecasediagrampanel in usecasediagrampanel_elems:    
                if usecasediagrampanel is None:
                    st.warning(f"No Use Case Diagram present in {modeling}")
                    continue
                
                name_of_ucd = usecasediagrampanel.attrib.get('name')
                
                stickman_actors=[]
                box_actors=[]
                use_cases=[]
                system_boundary=[]
                connectors=[]
                
                print(f"The Name of the Use Case Diagram is : {name_of_ucd}")

                for component in usecasediagrampanel.findall('COMPONENT'):
                    if component.attrib.get('type') == '700':
                        stick_act=component.find('infoparam').attrib.get('value')
                        stickman_actors.append((stick_act,{"Element Type":"Primary Actor","X":component.find('cdparam').attrib.get('x'),"Y":component.find('cdparam').attrib.get('y'),"W":component.find('sizeparam').attrib.get('width'),"H":component.find('sizeparam').attrib.get('height'),"Comments":[],"Action":""}))
                    
                    elif component.attrib.get('type') == '701':
                        uc=component.find('infoparam').attrib.get('value')
                        use_cases.append((uc,{"Element Type":"Use Case","X":component.find('cdparam').attrib.get('x'),"Y":component.find('cdparam').attrib.get('y'),"W":component.find('sizeparam').attrib.get('width'),"H":component.find('sizeparam').attrib.get('height'),"Comments":[],"Action":""}))
                    
                    elif component.attrib.get('type') == '702':
                        sys=component.find('infoparam').attrib.get('value')
                        system_boundary.append((sys,{"Element Type":"System Boundary","X":component.find('cdparam').attrib.get('x'),"Y":component.find('cdparam').attrib.get('y'),"W":component.find('sizeparam').attrib.get('width'),"H":component.find('sizeparam').attrib.get('height'),"Comments":[],"Action":""}))
                        
                    elif component.attrib.get('type') == '703':
                        box_act=component.find('infoparam').attrib.get('value')
                        box_actors.append((box_act,{"Element Type":"Secondary Actor","X":component.find('cdparam').attrib.get('x'),"Y":component.find('cdparam').attrib.get('y'),"W":component.find('sizeparam').attrib.get('width'),"H":component.find('sizeparam').attrib.get('height'),"Comments":[],"Action":""}))        
                    else:
                        continue
                        
                if len(system_boundary) != 1:
                        st.error(f"It is advisable to have exactly one System Boundary in an Use Case Diagram,\nTherefore I am skipping evaluating the Use Case Diagram present in {modeling} Tab of the file {self.file_name}")
                        stickman_actors=[]
                        box_actors=[]
                        use_cases=[]
                        system_boundary=[]
                        connectors=[]
                        continue

                for connector in usecasediagrampanel.findall('CONNECTOR'):
                    extension=''
                    relation_id = connector.attrib.get('id')
                    relation_code = connector.attrib.get('type')
                    if relation_code=="118":
                        continue
                    relation_name = connector.find('infoparam').attrib.get('name')
                    relation_value_raw = connector.find('infoparam').attrib.get('value')
                    relation_value = html.unescape(relation_value_raw).lower()
                    source = connector.find('P1').attrib.get('id')
                    target = connector.find('P2').attrib.get('id')
                    
                    for component in usecasediagrampanel.findall('COMPONENT'):
                        for connectingpoint in component.findall('TGConnectingPoint'):
                            if source == connectingpoint.attrib.get('id'):
                                source_name = component.find('infoparam').attrib.get('value')
                                source_type = component.find('infoparam').attrib.get('name')
                                if "extend" in relation_value:
                                    relation_value="Extend"
                                    extension = component.find('extraparam').find('info').attrib.get('extension')
                                if "include" in relation_value:
                                    relation_value="Include"
                                if relation_code=="112":
                                    relation_value="Generalization"
                                if relation_code=="110":
                                    relation_value="Assosciation"
                                
                            elif target == connectingpoint.attrib.get('id'):
                                target_name = component.find('infoparam').attrib.get('value')
                                target_type = component.find('infoparam').attrib.get('name')
                    
                    connectors.append((relation_id,{"Relation Code":relation_code,"Relation Name":relation_name,"Relation Value":relation_value,"Source Type":source_type,"Target Type":target_type,"Source Name":source_name,"Target Name":target_name,"Extension":extension,"Comments":[],"Action":""}))

                ucddata.append({name_of_ucd:{"Primary Actors":stickman_actors,"Secondary Actors":box_actors,"Use Cases":use_cases,"System Boundary":system_boundary,"Connectors":connectors,"Comments":[],"Action":""}})
                    
            modeldata.append({modeling.attrib.get("nameTab"):{"Ucd Data":ucddata}})

        return modeldata
    
    def processData(self,modeldata):
        for model in modeldata:
            for tab_name, tab_data in model.items():
                ucddata=tab_data.get('Ucd Data', [])

                for ucd_index, ucd in enumerate(ucddata):
                    for ucd_name, ucd_details in ucd.items():
                        stickman_actors = ucd_details.get("Primary Actors", [])
                        box_actors = ucd_details.get("Secondary Actors", [])
                        use_cases = ucd_details.get("Use Cases", [])
                        connectors = ucd_details.get("Connectors", [])
                        system_boundary = ucd_details.get("System Boundary", [])
                        
                        stickman_actors_list=[stickman_actors[i][0] for i in range(len(stickman_actors))]
                        box_actors_list=[box_actors[i][0] for i in range(len(box_actors))]
                        actors_list=stickman_actors_list+box_actors_list
                        
                        actors_with_meta = stickman_actors + box_actors
                        
                        element_validation.validateActors(actors_with_meta)
                        element_validation.validateUsecases(use_cases)

                        action_map = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
                        for i, (stick_actor_name, stick_actor_meta) in enumerate(stickman_actors):
                            comments, action = element_validation.validateActor(stick_actor_name, "Primary Actor")
                            stick_actor_meta["Comments"].extend(comments)
                            prev_action=stick_actor_meta["Action"]
                            prev_level=action_map.get(prev_action, 0)
                            new_level=max(prev_level, action_map[action])
                            stick_actor_meta["Action"]=next(k for k, v in action_map.items() if v == new_level)

                        for i, (box_actor_name, box_actor_meta) in enumerate(box_actors):
                            comments, action = element_validation.validateActor(box_actor_name, "Secondary Actor")
                            box_actor_meta["Comments"].extend(comments)
                            prev_action=box_actor_meta["Action"]
                            prev_level=action_map.get(prev_action, 0)
                            new_level=max(prev_level, action_map[action])
                            box_actor_meta["Action"]=next(k for k, v in action_map.items() if v == new_level)
                        
                        for i, (uc_name, uc_meta) in enumerate(use_cases):
                            comments, action = element_validation.validateUsecase(uc_name, system_boundary[0][0])
                            uc_meta["Comments"].extend(comments)
                            prev_action=uc_meta["Action"]
                            prev_level=action_map.get(prev_action, 0)
                            new_level=max(prev_level, action_map[action])
                            uc_meta["Action"]=next(k for k, v in action_map.items() if v == new_level)

                        comments, action = element_validation.validateSystem(system_boundary[0][0])

                        priority = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}
                        prev     = system_boundary[0][1].get("Action") or "Well Written"

                        if priority[action] > priority[prev]:
                            system_boundary[0][1]["Comments"].extend(comments)
                            system_boundary[0][1]["Action"] = action
                        
                                
                        element_validation.validateArrangement(stickman_actors,box_actors,use_cases,system_boundary)
                        
                        element_validation.validateActorConnectivity(actors_with_meta,use_cases,connectors)
                        
                        element_validation.validateUsecaseConnectivity(use_cases,actors_with_meta,connectors)

                        element_validation.validateRelations(connectors, actors_with_meta, use_cases)
                        
    def showUcdTables(self,modeldata):
        def style_action(df):
            def highlight_row(row):
                action = row["Action"]
                if action == "Attention Required!":
                    return ['background-color: #FFCCCC'] * len(row)
                elif action == "Warning!":
                    return ['background-color: #FFF5CC'] * len(row)
                else:
                    return ['background-color: #E6FFCC'] * len(row)  # Well Written
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
                                "Extension": meta.get("Extension",""),
                                "Comments": ", ".join(meta.get("Comments", [])) if meta.get("Comments") else "",
                                "Action": meta.get("Action", "")
                            })
                        df_connectors = pd.DataFrame(connectors_data)
                        st.subheader("Connectors")
                        st.dataframe(style_action(df_connectors), use_container_width=True)

                        st.markdown("---")

class element_validation:

    @staticmethod
    def _set_action(meta, level, msg):
        """Update Comments/Action with severity level (0 ok, 1 warning, 2 attention)."""
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
        if msg:
            meta.setdefault("Comments", []).append(msg)
        prev_level = {v: k for k, v in action_map.items()}.get(meta.get("Action", "Well Written"), 0)
        meta["Action"] = action_map[max(prev_level, level)]
    
    @staticmethod  
    def validateActors(actors_arr):
        # reset
        for _, meta in actors_arr:
            meta["Comments"].clear()
            meta["Action"] = "Well Written"
            
        for i in range(len(actors_arr)):
            name_i, meta_i = actors_arr[i]
            for j in range(i+1,len(actors_arr)):
                name_j, meta_j = actors_arr[j]
                #Name Equality
                if name_i == name_j:
                    msg = (f"Two {meta_i['Element Type']}s have the same name "
                        f"('{name_i}'). Please DELETE or MODIFY one of them.")
                    for meta in (meta_i, meta_j):
                        meta["Comments"].append(msg)
                        meta["Action"] = "Attention Required!"
                    continue
                #Name similarity check skipped to avoid false positives

        # Individual actor quality checks
        for name, meta in actors_arr:
            nm = name.strip()
            tokens = nm.split()
            if len(nm) < 3:
                element_validation._set_action(meta, 1, f"Actor '{nm}' looks too short to be meaningful.")
            if len(tokens) > 5:
                element_validation._set_action(meta, 1, f"Actor '{nm}' is very long; keep role names concise.")
            if re.search(r"\b(system|application|software)\b", nm, re.IGNORECASE):
                element_validation._set_action(meta, 2, f"'{nm}' sounds like the system, not an external actor.")
            if tokens and re.match(r"(?i)(add|create|book|update|manage|cancel|view)", tokens[0]):
                element_validation._set_action(meta, 1, f"Actor '{nm}' starts with a verb; actors should be roles, not actions.")

    @staticmethod  
    def validateUsecases(usecases_arr):
        for _, meta in usecases_arr:
            meta["Comments"].clear()
            meta["Action"] = "Well Written"     
               
        for i in range(len(usecases_arr)):
            name_i, meta_i = usecases_arr[i]
            for j in range(i+1,len(usecases_arr)):
                name_j, meta_j = usecases_arr[j]
                
                #Name Equality
                if name_i == name_j:
                    msg = (f"Two use cases have the same name ('{name_i}'). "
                           "Please rename or delete one of them.")
                    for meta in (meta_i, meta_j):
                        meta["Comments"].append(msg)
                        meta["Action"] = "Attention Required!"
                    continue
                #Name similarity check skipped to reduce false positives

        # Individual use case heuristics (Verb + Object, concise, user-goal focused)
        allowed_verbs = {"add","book","cancel","create","delete","display","generate","handle","list","login","manage","mark","pay","process","register","remove","reset","schedule","search","select","submit","update","validate","view"}
        for name, meta in usecases_arr:
            nm = name.strip()
            tokens = nm.split()
            if len(tokens) == 0:
                element_validation._set_action(meta, 2, "Use case name is empty.")
                continue
            first = tokens[0].lower()
            if first not in allowed_verbs:
                element_validation._set_action(meta, 1, f"Use case '{nm}' should start with a base verb (e.g., 'View', 'Update').")
            if len(tokens) < 2:
                element_validation._set_action(meta, 1, f"Use case '{nm}' should include a clear object after the verb.")
            if len(tokens) > 8:
                element_validation._set_action(meta, 1, f"Use case '{nm}' is long; keep it concise.")
            if re.search(r"\b(system|application)\b", nm, re.IGNORECASE):
                element_validation._set_action(meta, 1, f"Use case '{nm}' references the system; focus on a user goal instead.")
    
    @staticmethod
    def validateArrangement(stickman_actors_arr,box_actors_arr,use_cases_arr,system_boundary_arr):
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
        temp=system_boundary_arr[0][1]
        sys_bound=element_validation.getBoundaryBox(float(temp["X"]),float(temp["Y"]),float(temp["W"]),float(temp["H"]))
        for actor_list in [stickman_actors_arr,box_actors_arr]:
            for i, (name, meta) in enumerate(actor_list):
                elem_bound = element_validation.getBoundaryBox(
                    float(meta["X"]), float(meta["Y"]), float(meta["W"]), float(meta["H"])
                )
                action_level = 0
                comments = []

                if not element_validation.isOutside(sys_bound,elem_bound):
                    if element_validation.isInside(sys_bound,elem_bound):
                        comments.append(f"'{meta['Element Type']}' : '{name}' is present inside the system boundary but should be outside the system boundary.")
                        action_level=max(action_level, 2)
                    else:
                        comments.append(f"'{meta['Element Type']}' : '{name}' is intersecting with the system boundary but should be completely outside the system boundary.")
                        action_level=max(action_level, 2)
                
                if comments:
                    meta["Comments"].extend(comments)
                    prev_level={"Well Written": 0, "Warning!": 1, "Attention Required!": 2}.get(meta.get("Action", ""), 0)
                    meta["Action"]=action_map[max(prev_level, action_level)]
                    
        for i, (name, meta) in enumerate(use_cases_arr):
            elem_bound = element_validation.getBoundaryBox(
                float(meta["X"]), float(meta["Y"]), float(meta["W"]), float(meta["H"])
            )
            action_level = 0
            comments = []
            
            if not element_validation.isInside(sys_bound,elem_bound):
                if element_validation.isOutside(sys_bound,elem_bound):
                    comments.append(f"'{meta['Element Type']}' : '{name}' is present outside the system boundary but should be inside the system boundary.")
                    action_level=max(action_level, 2)

                else:
                    comments.append(f"'{meta['Element Type']}' : '{name}' is intersecting with the system boundary but should be completely inside the system boundary.")
                    action_level=max(action_level, 2)
                
        if comments:
            meta["Comments"].extend(comments)
            prev_level={"Well Written": 0, "Warning!": 1, "Attention Required!": 2}.get(meta.get("Action", ""), 0)
            meta["Action"]=action_map[max(prev_level, action_level)]         
            
    @staticmethod      
    def getBoundaryBox(cx, cy, width, height):
        return {
            'left': cx,
            'right': cx + width,
            'top': cy,
            'bottom': cy + height
        }

    @staticmethod  
    def isInside(sys_boundary, element_boundary):
        return (
            element_boundary['left'] >= sys_boundary['left'] and
            element_boundary['right'] <= sys_boundary['right'] and
            element_boundary['top'] >= sys_boundary['top'] and
            element_boundary['bottom'] <= sys_boundary['bottom']
        )

    @staticmethod  
    def isOutside(sys_boundary, element_boundary):
        return (
            element_boundary['right'] < sys_boundary['left'] or
            element_boundary['left'] > sys_boundary['right'] or
            element_boundary['bottom'] < sys_boundary['top'] or
            element_boundary['top'] > sys_boundary['bottom']
        )
    
    @staticmethod  
    def validateActor(actors_name,actors_type):
        comments=[]
        action=""
        action_level = 0
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
        
        chars=re.findall(r"[^A-Za-z ]", actors_name)
        if chars:
            comments.append(f"Difficult to read and comprehend because it contains characters {', '.join(sorted(set(chars)))} that are neither alphabets nor whitespaces.")
            action_level = max(action_level, 2)
            action = action_map[action_level]
            return comments, action
            
        else:
            if not(actors_name==TextValidationTools.toTitleCase(actors_name) or actors_name==TextValidationTools.toTitleCaseSmart(actors_name) or actors_name==TextValidationTools.toPascalCase(actors_name)):
                comments.append(f"Difficult to read and comprehend because it lacks 'Title Casing' or 'PascalCasing'.")
                action_level = max(action_level, 2)
                action = action_map[action_level]
                return comments, action
            
            else:
                processed_actors_name=TextValidationTools.toTitleCase(actors_name)
                
                cond,comment=TextValidationTools.isMeaningfulCommonSingularNounPhrase(processed_actors_name)

                if cond:
                    check, stmt= TextValidationTools.isPrimaryActor(processed_actors_name)
                    if actors_type=="Primary Actor":
                        if not (check):
                            action_level = max(action_level, 1)
                            if "artifact" in stmt:
                                comments.append(f"Marked as a Primary Actor, but it appears more appropriate as a Secondary Actor. Consider using the representation with Primary Actor(Box Figure with <<Stereotype>>).")
                            elif "other" in stmt:
                                action_level = max(action_level, 1)          # ← force yellow
                                comments.append(
                                    "Cannot determine whether this is a person or an artefact – "
                                    "please clarify the name (e.g. end with 'System', 'Controller', etc.)."
                                )
                            else:
                                comments.append(f"'{actors_type}' : '{actors_name}' {stmt}")
                                action_level = max(action_level, 2)
                    else:
                        if check:
                            comments.append(f"Marked as a Secondary Actor, but it appears more appropriate as a Primary Actor. Consider using the representation with Primary Actor(Stickman Figure).")
                            action_level = max(action_level, 1)
                else:
                    action_level = max(action_level, 2)
                    if isinstance(comment, str):
                        comments.append(f"Invalid actor name because {comment}")
                    else:
                        comments.append(f"Invalid actor name because it is expected to have common singular nouns or combinations of adjectives and common singular nouns.")
                        comments.extend(comment)
                    
        action = action_map[action_level]
        return comments,action
    
    @staticmethod  
    def validateUsecase(uc_text,element):
        comments=[]
        action=""
        action_level = 0
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
        
        chars=re.findall(r"[^A-Za-z ]", uc_text)
        if chars:
            comments.append(f"Difficult to read and comprehend because it contains characters {', '.join(sorted(set(chars)))} that are neither alphabets nor whitespaces.")
            action_level = max(action_level, 2)
            action = action_map[action_level]
            return comments, action
            
        else:
            if not(uc_text==TextValidationTools.toTitleCase(uc_text) or uc_text==TextValidationTools.toTitleCaseSmart(uc_text) or uc_text==TextValidationTools.toPascalCase(uc_text)):
                comments.append(f"Difficult to read and comprehend because it lacks 'Title Casing' or 'PascalCasing'.")
                action_level = max(action_level, 2)
                action = action_map[action_level]
                return comments, action
            
            else:
                processed_uc_name=TextValidationTools.toTitleCase(uc_text)
                
                cond,comment=TextValidationTools.isMeaningfulBaseVerbPhrase(processed_uc_name,element)

                if not(cond):
                    action_level = max(action_level, 2)
                    if isinstance(comment, str):
                        comments.append(f"Invalid use case name because {comment}")
                    else:
                        comments.append(f"Invalid use case name because it is expected to have combinations of base form verb, preposition (optional) adjective (optional) and common singular noun(s).")
                        comments.extend(comment)
                    
        action = action_map[action_level]
        return comments,action
    
    @staticmethod
    def validateSystem(systems_name):
        """
        Green  – clear artefact (Payment System)
        Yellow – valid noun-phrase but abstract head (Online Shopping)
        Red    – not a noun-phrase / looks like a person, etc.
        """
        comments     = []
        action_level = 0                          # 0 ✔  1 ⚠  2 ❌
        action_map   = {0: "Well Written",
                        1: "Warning!",
                        2: "Attention Required!"}

        # ── 1) illegal characters ─────────────────────────────────────────────
        bad_chars = re.findall(r"[^A-Za-z ]", systems_name)
        if bad_chars:
            comments.append(
                "Contains illegal characters: "
                + ", ".join(sorted(set(bad_chars)))
            )
            return comments, action_map[2]

        # ── 2) casing check (Title / Pascal) ──────────────────────────────────
        if not (
            systems_name == TextValidationTools.toTitleCase(systems_name)
            or systems_name == TextValidationTools.toPascalCase(systems_name)
            or systems_name == TextValidationTools.toTitleCaseSmart(systems_name)
        ):
            comments.append("Must use Title-Case or Pascal-Case.")
            return comments, action_map[2]

        # ── 3) noun-phrase sanity (must end in NN) ────────────────────────────
        processed = TextValidationTools.toTitleCase(systems_name)
        ok, reason = TextValidationTools.isMeaningfulCommonSingularNounPhrase(processed)
        if not ok:
            if isinstance(reason, list):
                comments.extend(reason)
            else:
                comments.append(reason)
            return comments, action_map[2]
        
        # ── 4) concrete artefact head word? (yellow if not) ───────────────────────
        # NEW  ➜ skip check for all-caps acronyms like “EMS”
        orig_head = systems_name.split()[-1]
        if re.fullmatch(r'[A-Z]{2,}', orig_head):
            return comments, action_map[action_level]   # ✔ keep current colour

        # ── 4) concrete artefact head word?  (yellow if not) ──────────────────
        SYSTEM_HEADS = {
            "system", "subsystem", "controller", "server", "device", "machine",
            "station", "module", "engine", "gateway", "platform", "unit",
            "equipment", "terminal", "robot", "appliance", "data"
        }
        head = processed.split()[-1].lower()
        if head not in SYSTEM_HEADS:
            action_level = max(action_level, 1)      # promote to Warning ⚠
            comments.append(
                f"Ends with “{head.title()}”. "
                "A system boundary should end with a concrete artefact noun "
                "(e.g. *System*, *Module*, *Device* …)."
            )

        # ── 5) reject names that look like people / roles (red) ───────────────
        is_person, _ = TextValidationTools.isPrimaryActor(processed)
        if is_person:
            action_level = 2
            comments.append(
                "Looks like a person/role – a system boundary must be an artefact."
            )

        # ── 6) final verdict ──────────────────────────────────────────────────
        return comments, action_map[action_level]

    @staticmethod
    def validateActorConnectivity(actors, use_cases, connectors):
        connected_actors=set()
        graph={}

        for conn_id, conn in connectors:
            src=conn["Source Name"]
            tgt=conn["Target Name"]

            graph.setdefault(src, set()).add(tgt)
            graph.setdefault(tgt, set()).add(src)

        use_case_names={uc[0] for uc in use_cases}

        def bfsFromActor(actor_name):
            visited=set()
            queue=[actor_name]

            while queue:
                node=queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)

                if node in use_case_names:
                    return True

                for neighbor in graph.get(node, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            return False

        comments_map={}
        for actor_name, _ in actors:
            if not bfsFromActor(actor_name):
                comments_map.setdefault(actor_name, []).append(
                    f"Actor is isolated - not connected to any use case directly or through generalization. Please either remove '{actor_name}' or establish valid associations with use cases or other related elements."
                )

        for i, (actor_name, meta) in enumerate(actors):
            if actor_name in comments_map:
                actors[i][1]["Comments"].extend(comments_map[actor_name])
                actors[i][1]["Action"]="Attention Required!"

        return actors

    @staticmethod
    def validateUsecaseConnectivity(use_cases, actors, connectors):
        graph = {}

        for conn_id, conn in connectors:
            src=conn["Source Name"]
            tgt=conn["Target Name"]

            graph.setdefault(src, set()).add(tgt)
            graph.setdefault(tgt, set()).add(src)

        actor_names = {actor[0] for actor in actors}

        def isConnectedToActor(uc_name):
            visited=set()
            queue=[uc_name]

            while queue:
                node=queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)

                if node in actor_names:
                    return True

                for neighbor in graph.get(node, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            return False

        for i, (uc_name, meta) in enumerate(use_cases):
            if not isConnectedToActor(uc_name):
                use_cases[i][1]["Comments"].append(
                    f"Use case is isolated — it is not connected to any actor directly or via generalization. Please either remove '{uc_name}' or establish valid associations with actors or other related elements."
                )
                use_cases[i][1]["Action"] = "Attention Required!"

        return use_cases

    @staticmethod
    def validateRelations(connectors, actors, use_cases):
        actor_set = {a[0] for a in actors}
        uc_set = {u[0] for u in use_cases}
        seen = set()
        for conn_id, meta in connectors:
            meta.setdefault("Comments", [])
            meta.setdefault("Action", "Well Written")
            rt = (meta.get("Relation Value") or "").lower()
            s = meta.get("Source Name") or ""
            t = meta.get("Target Name") or ""
            stype = (meta.get("Source Type") or "").lower()
            ttype = (meta.get("Target Type") or "").lower()

            if (s, t, rt) in seen:
                element_validation._set_action(meta, 1, f"Duplicate relationship '{s}' -> '{t}' ({rt}).")
            seen.add((s, t, rt))

            if s == t and rt in {"include","extend","generalization"}:
                element_validation._set_action(meta, 2, f"Relationship '{rt}' cannot link '{s}' to itself.")

            if rt in {"include","extend"}:
                if stype != "usecase" or ttype != "usecase" or s not in uc_set or t not in uc_set:
                    element_validation._set_action(meta, 2, f"{rt.title()} must connect use case to use case; found '{s}' ({stype}) -> '{t}' ({ttype}).")

            if rt == "generalization":
                same_domain = (stype == ttype)
                if not same_domain:
                    element_validation._set_action(meta, 2, f"Generalization should stay within actors or within use cases; '{s}' ({stype}) -> '{t}' ({ttype}).")
                if stype == "actor" and (s not in actor_set or t not in actor_set):
                    element_validation._set_action(meta, 2, "Generalization connects unknown actors.")
                if stype == "usecase" and (s not in uc_set or t not in uc_set):
                    element_validation._set_action(meta, 2, "Generalization connects unknown use cases.")

    # ------------------------------------------------------------------ #
    #  ACTIVITY PANEL BUILDER (TTool) FOR VERIFICATION STEPS
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_activity_panel(panel_name: str, steps: list[str]) -> ET.Element:
        """Create an AvatarADPanel element with ordered steps."""
        comp_id = 1
        cp_id = 1

        def next_cp():
            nonlocal cp_id
            cid = cp_id
            cp_id += 1
            return cid

        panel = ET.Element("AvatarADPanel", attrib={
            "name": panel_name,
            "minX": "10", "maxX": "2500", "minY": "10", "maxY": "1500", "zoom": "1.0"
        })

        # start state
        start_cp = next_cp()
        comp = ET.SubElement(panel, "COMPONENT", attrib={"type": "5501", "id": str(comp_id), "index": "0", "uid": str(uuid.uuid4())})
        comp_id += 1
        ET.SubElement(comp, "cdparam", attrib={"x": "140", "y": "100"})
        ET.SubElement(comp, "sizeparam", attrib={"width": "15", "height": "15", "minWidth": "0", "minHeight": "0", "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"})
        ET.SubElement(comp, "hidden", attrib={"value": "false"})
        ET.SubElement(comp, "cdrectangleparam", attrib={"minX": "10", "maxX": "2500", "minY": "10", "maxY": "1500"})
        ET.SubElement(comp, "infoparam", attrib={"name": "start state", "value": "null"})
        ET.SubElement(comp, "new", attrib={"d": "false"})
        ET.SubElement(comp, "TGConnectingPoint", attrib={"num": "0", "id": str(start_cp)})

        # activity container
        act_cp = [next_cp() for _ in range(40)]
        comp = ET.SubElement(panel, "COMPONENT", attrib={"type": "5507", "id": str(comp_id), "index": "1", "uid": str(uuid.uuid4())})
        comp_id += 1
        ET.SubElement(comp, "cdparam", attrib={"x": "120", "y": "80"})
        height_val = 140 + max(len(steps), 1) * 36
        ET.SubElement(comp, "sizeparam", attrib={
            "width": "520",
            "height": str(height_val),
            "minWidth": "40", "minHeight": "30",
            "maxWidth": "2000", "maxHeight": "2000",
            "minDesiredWidth": "0", "minDesiredHeight": "0"
        })
        ET.SubElement(comp, "hidden", attrib={"value": "false"})
        ET.SubElement(comp, "enabled", attrib={"value": "true"})
        ET.SubElement(comp, "cdrectangleparam", attrib={"minX": "10", "maxX": "2500", "minY": "10", "maxY": "1500"})
        ET.SubElement(comp, "infoparam", attrib={"name": "activity", "value": "Verification Steps"})
        ET.SubElement(comp, "new", attrib={"d": "false"})
        for i, cp in enumerate(act_cp):
            ET.SubElement(comp, "TGConnectingPoint", attrib={"num": str(i), "id": str(cp)})

        # action states
        sub_index = 0
        last_cp = start_cp
        y = 140
        for step in steps:
            entry = next_cp()
            exitp = next_cp()
            sc = ET.SubElement(panel, "SUBCOMPONENT", attrib={
                "type": "5506",
                "id": str(comp_id),
                "index": str(2 + sub_index),
                "uid": str(uuid.uuid4())
            })
            comp_id += 1
            ET.SubElement(sc, "father", attrib={"id": "2", "num": str(sub_index)})
            ET.SubElement(sc, "cdparam", attrib={"x": "200", "y": str(y)})
            ET.SubElement(sc, "sizeparam", attrib={"width": "360", "height": "24", "minWidth": "30", "minHeight": "0", "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"})
            ET.SubElement(sc, "hidden", attrib={"value": "false"})
            ET.SubElement(sc, "enabled", attrib={"value": "true"})
            ET.SubElement(sc, "cdrectangleparam", attrib={"minX": "0", "maxX": "520", "minY": "0", "maxY": "300"})
            ET.SubElement(sc, "infoparam", attrib={"name": "action state", "value": step})
            ET.SubElement(sc, "new", attrib={"d": "false"})
            ET.SubElement(sc, "TGConnectingPoint", attrib={"num": "0", "id": str(entry)})
            ET.SubElement(sc, "TGConnectingPoint", attrib={"num": "1", "id": str(exitp)})
            # connector from last to this
            conn = ET.SubElement(panel, "CONNECTOR", attrib={"type": "5500", "id": str(100 + sub_index), "index": str(sub_index), "uid": str(uuid.uuid4())})
            ET.SubElement(conn, "cdparam", attrib={"x": "150", "y": str(y)})
            ET.SubElement(conn, "sizeparam", attrib={"width": "0", "height": "0", "minWidth": "0", "minHeight": "0", "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"})
            ET.SubElement(conn, "infoparam", attrib={"name": "connector", "value": "null"})
            ET.SubElement(conn, "P1", attrib={"x": "150", "y": str(y), "id": str(last_cp)})
            ET.SubElement(conn, "P2", attrib={"x": "200", "y": str(y), "id": str(entry)})
            ET.SubElement(conn, "AutomaticDrawing", attrib={"data": "true"})
            ET.SubElement(conn, "new", attrib={"d": "false"})

            last_cp = exitp
            sub_index += 1
            y += 36

        # stop state
        stop_cp = next_cp()
        comp = ET.SubElement(panel, "COMPONENT", attrib={"type": "5502", "id": str(comp_id), "index": str(2 + sub_index), "uid": str(uuid.uuid4())})
        ET.SubElement(comp, "cdparam", attrib={"x": "140", "y": str(y)})
        ET.SubElement(comp, "sizeparam", attrib={"width": "20", "height": "20", "minWidth": "0", "minHeight": "0", "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"})
        ET.SubElement(comp, "hidden", attrib={"value": "false"})
        ET.SubElement(comp, "cdrectangleparam", attrib={"minX": "10", "maxX": "2500", "minY": "10", "maxY": "1500"})
        ET.SubElement(comp, "infoparam", attrib={"name": "stop state", "value": "null"})
        ET.SubElement(comp, "new", attrib={"d": "false"})
        ET.SubElement(comp, "TGConnectingPoint", attrib={"num": "0", "id": str(stop_cp)})

        conn = ET.SubElement(panel, "CONNECTOR", attrib={"type": "5500", "id": str(100 + sub_index + 1), "index": str(sub_index + 1), "uid": str(uuid.uuid4())})
        ET.SubElement(conn, "cdparam", attrib={"x": "150", "y": str(y)})
        ET.SubElement(conn, "sizeparam", attrib={"width": "0", "height": "0", "minWidth": "0", "minHeight": "0", "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"})
        ET.SubElement(conn, "infoparam", attrib={"name": "connector", "value": "null"})
        ET.SubElement(conn, "P1", attrib={"x": "200", "y": str(y), "id": str(last_cp)})
        ET.SubElement(conn, "P2", attrib={"x": "140", "y": str(y), "id": str(stop_cp)})
        ET.SubElement(conn, "AutomaticDrawing", attrib={"data": "true"})
        ET.SubElement(conn, "new", attrib={"d": "false"})

        return panel

    @staticmethod
    def collect_issue_steps(modeldata) -> list[str]:
        """Collect warnings/errors into ordered steps (errors first)."""
        steps = []
        severity_order = {"Attention Required!": 2, "Warning!": 1, "Well Written": 0}
        def _add(label, meta):
            for c in meta.get("Comments", []):
                steps.append((severity_order.get(meta.get("Action","Well Written"),0), f"{label}: {c}"))

        for model in modeldata or []:
            for _, tab in model.items():
                for ucd in tab.get("Ucd Data", []):
                    for ucd_name, details in ucd.items():
                        for name, meta in details.get("Primary Actors", []):
                            _add(f"Actor {name}", meta)
                        for name, meta in details.get("Secondary Actors", []):
                            _add(f"Actor {name}", meta)
                        for name, meta in details.get("Use Cases", []):
                            _add(f"Use Case {name}", meta)
                        for cid, meta in details.get("Connectors", []):
                            _add(f"Relationship {meta.get('Source Name','?')}->{meta.get('Target Name','?')}", meta)
                        for name, meta in details.get("System Boundary", []):
                            _add(f"System {name}", meta)

        # sort errors first, then warnings, preserve insertion for same severity
        steps = [s for _, s in sorted(steps, key=lambda x: (-x[0], steps.index(x) if x in steps else 0))]
        if not steps:
            steps = ["Review diagram — no verification issues detected."]
        return steps

    @staticmethod
    def append_activity_panel(xml_content: str, steps: list[str]) -> str:
        """Append an AvatarADPanel with steps to the XML and return updated string."""
        root = ET.fromstring(xml_content)
        modeling = root.find(".//Modeling[@type='Avatar Analysis']") or root.find("Modeling")
        if modeling is None:
            return xml_content
        panel = element_validation._build_activity_panel("Verification Steps", steps)
        modeling.append(panel)
        return ET.tostring(root, encoding="utf-8").decode("utf-8")
class TextValidationTools:
    
    # ------------------------------------------------------------------ #
    #  one-time resources
    # ------------------------------------------------------------------ #
    WORD_LIST   = set(words.words())
    _lemmatizer = getLemmatizer()
    _flair      = getFlairPosTagger()
    _nlp        = getSpacyModel()

    # ================================================================== #
    #  1.  ACTOR / SYSTEM  NAME  VALIDATOR
    # ================================================================== #
    @staticmethod
    def isMeaningfulCommonSingularNounPhrase(name: str) -> tuple[bool, str | list]:
        """
        Validate a noun-phrase that should end with a **common singular noun**.
        Returns (True, "") on success, otherwise (False, reason).
        """
        # ── 0) Flair POS tagging ────────────────────────────────────────────────
        sent = Sentence(name)
        TextValidationTools._flair.predict(sent)
        tags = [(t.text, t.get_labels('pos')[0].value) for t in sent]

        # ── 1)  post-processing overrides  ──────────────────────────────────────
        MISCLASSIFIED_SINGULAR = {
            "data", "information", "equipment", "software", "hardware",
            "system", "staff", "personnel", "admin", "administrator", "management"
        }
        tags = [(tok, "NN") if tok.lower() in MISCLASSIFIED_SINGULAR else (tok, tag)
                for tok, tag in tags]
        tags = TextValidationTools.applyAcronymOverride(name, tags)
        tags = [(tok, TextValidationTools._normaliseVerbTag(tok, tag))
                for tok, tag in tags]

        # ── 2) pronoun blocks (unchanged) ───────────────────────────────────────
        INDEFINITE = {"anyone","anybody","someone","somebody","everyone","everybody","nobody","none"}
        if any(tok.lower() in INDEFINITE for tok, _ in tags):
            bad = [tok.title() for tok, _ in tags if tok.lower() in INDEFINITE]
            return False, f"actor names must not contain indefinite pronouns ({', '.join(bad)})"
        if any(tag in {"PRP","PRP$","WP","WP$","EX"} for _, tag in tags):
            bad = [tok for tok, tag in tags if tag in {"PRP","PRP$","WP","WP$","EX"}]
            return False, f"actor names must not contain pronouns ({', '.join(bad)})"

        # ── 3) head-word (last token) checks ────────────────────────────────────
        last_tok, last_tag = tags[-1]
        kind_map = {"NNS": "plural", "NNP": "proper singular", "NNPS": "proper plural"}
        if last_tag in kind_map:
            return False, (
                f"actor must end with a **common singular noun** "
                f"(found '{last_tok}' which is {kind_map[last_tag]})"
            )

        # NEW ── 3a) FULL-CAPS acronym short-circuit  ───────────────────────────
        # If the head word is an all-caps acronym (≥2 letters, possible trailing S),
        # we treat it as acceptable singular and skip both plural heuristics below.
        ACRONYM = re.compile(r'^[A-Z]{2,}S?$')
        if not ACRONYM.fullmatch(last_tok):
            # ❶ lemma-based plural test
            lemma = TextValidationTools._lemmatizer.lemmatize(last_tok.lower(), "n")
            if last_tok.lower().endswith("s") and last_tok.lower() != lemma:
                return False, f"actor must end with singular noun (found plural '{last_tok}')"

            # ── NEW: skip spaCy test for known mass-noun exceptions ──────────
            MASS_NOUN_EXCEPTIONS = {
                "data", "information", "equipment", "software", "hardware",
                "system", "staff", "personnel", "admin", "administrator",
                "management"
            }
            if last_tok.lower() not in MASS_NOUN_EXCEPTIONS:
                
                # ❷ spaCy fallback plural test
                spacy_last = list(TextValidationTools._nlp(name))[-1]
                if spacy_last.tag_ in {"NNS", "NNPS"}:
                    return False, (
                        f"actor must end with singular noun "
                        f"(spaCy detected plural '{last_tok}')"
                    )

        # ── 4) adjective placement (unchanged) ──────────────────────────────────
        for i, (tok, tag) in enumerate(tags[:-1]):
            if tag in {"JJ", "VBG", "VBN"} and tags[i + 1][1] not in {"NN", "NNP"}:
                return False, f"adjective '{tok}' must be followed by a noun"

        # ── 5) POS whitelist (unchanged) ────────────────────────────────────────
        ALLOWED = {"NN", "JJ", "NNP", "IN", "RP"}
        bad = [(tok, tg) for tok, tg in tags if tg not in ALLOWED]
        if bad:
            return False, [
                f"'{tok}' is tagged {tg} which is not allowed in actor/system names"
                for tok, tg in bad
            ]

        return True, ""        # ✔ all good

    # ================================================================== #
    #  2.  USE-CASE  TITLE  VALIDATOR
    # ================================================================== #
    @staticmethod
    def isMeaningfulBaseVerbPhrase(title: str, element: str) -> tuple[bool, str]:
        """
        Validate a use-case title:  
        ▸ starts with an **imperative / base** verb  
        ▸ ends   with a **noun** (sing./plural/proper ok)  
        ▸ optional adjectives / prepositions in the middle
        """
        # ── 0) single-word shortcut -------------------------------------------
        tokens_ws = title.split()
        if len(tokens_ws) == 1:
            word = tokens_ws[0]
            if TextValidationTools.flairIsBaseVerb(word):
                return True, ""
            return False, (
                "single-word use cases must be an imperative/base verb "
                f"(e.g. 'Checkout', 'Login'); '{word}' is not recognised "
                "as a base verb"
            )

        # ── 1) do not reuse actor / system name exactly ------------------------
        if re.search(rf"\b{re.escape(element.lower())}\b", title.lower()):
            return False, f"use-case name must not reuse actor/system name (‘{element}’)"

        # ── 2) Flair POS tagging  + corrections -------------------------------
        sent = Sentence(title)
        TextValidationTools._flair.predict(sent)
        tags = [(t.text, t.get_labels('pos')[0].value) for t in sent]

        EXCEPT_SINGULAR = {
            "data", "information", "equipment", "software",
            "hardware", "system", "staff", "personnel",
            "admin", "administrator", "management"
        }
        tags = [
            (tok, "NN") if tok.lower() in EXCEPT_SINGULAR else (tok, tag)
            for tok, tag in tags
        ]
        tags = TextValidationTools.applyAcronymOverride(title, tags)
        tags = [(tok, TextValidationTools._normaliseVerbTag(tok, tag))
                for tok, tag in tags]

        # ── 3) pronoun / indef-pronoun rejection ------------------------------
        INDEFINITE = {
            "anyone", "anybody", "someone", "somebody",
            "everyone", "everybody", "nobody", "none"
        }
        if any(tok.lower() in INDEFINITE for tok, _ in tags):
            bad = [tok.title() for tok, _ in tags if tok.lower() in INDEFINITE]
            return False, f"use-case titles must not contain indefinite pronouns ({', '.join(bad)})"

        if any(tag in {"PRP", "PRP$", "WP", "WP$", "EX"} for _, tag in tags):
            bad = [tok for tok, tag in tags if tag in {"PRP", "PRP$", "WP", "WP$", "EX"}]
            return False, f"use-case titles must not contain pronouns ({', '.join(bad)})"

        # ── 4) first token must be a base verb ---------------------------------
        first_tok, first_tag = tags[0]
        if first_tag not in {"VB", "VBP"} and not TextValidationTools.flairIsBaseVerb(first_tok):
            return False, f"use-case should begin with an imperative/base verb (got '{first_tok}')"

        # ── 5) last token must be some kind of noun ---------------------------
        last_tok, last_tag = tags[-1]
        if last_tag not in {"NN", "NNP", "NNS", "NNPS"}:
            return False, f"use-case should end with a noun (ends with '{last_tok}')"

        # ── 6) adjective placement -------------------------------------------
        for i, (tok, tag) in enumerate(tags[:-1]):
            if tag == "JJ" and tags[i + 1][1] not in {"NN", "NNP", "NNS", "NNPS"}:
                return False, f"adjective '{tok}' must be followed by a noun"

        # ── 7) at least one base verb before the last noun --------------------
        verb_count = sum(
            1 for tok, tag in tags[:-1]
            if tag in {"VB", "VBP"} or TextValidationTools.flairIsBaseVerb(tok)
        )
        if verb_count == 0:
            return False, "use-case must contain at least one base verb before the final noun"

        # ── 8) allowed POS whitelist ------------------------------------------
        ALLOWED = {"VB", "VBP", "NN", "NNS", "NNP", "NNPS", "JJ", "IN", "RP"}
        bad = [(tok, tag) for tok, tag in tags if tag not in ALLOWED]
        if bad:
            bad_str = "; ".join(f"'{tok}' ({tag})" for tok, tag in bad)
            return False, f"invalid token(s): {bad_str}"

        return True, ""  # ✔ OK



    # ------------------------------------------------------------------ #
    #  small utility helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normaliseVerbTag(tok: str, tag: str) -> str:
        SAME = {"set", "put", "cut", "shut", "let", "hit"}
        if tag in {"VBD", "VBN"}:
            if (tok.lower() in SAME
                    or TextValidationTools._lemmatizer.lemmatize(tok.lower(), "v") == tok.lower()):
                if TextValidationTools.flairIsBaseVerb(tok):
                    return "VB"
        return tag

    @staticmethod
    def flairIsBaseVerb(word: str) -> bool:
        probes = [
            "{} the object", "{} something", "{} the thing",
            "{} it", "to {}", "I {}"
        ]
        for p in probes:
            s = Sentence(p.format(word))
            TextValidationTools._flair.predict(s)
            for t in s:
                if (t.text.lower() == word.lower()
                        and t.get_labels("pos")[0].value in {"VB", "VBP"}):
                    return True
        return False

    # --- split_words, applyAcronymOverride, toTitleCase … (unchanged) ----------

    # @staticmethod
    # def isPrimaryActor(actors_name):
    #     SOFTWARE_ARTIFACT_HEADS = {
    #         "system", "device", "tool", "module", "component", "machine", "software", "hardware","platform", "subsystem", "application", "framework", "interface", "server", "sensor", "actuator", "controller"
    #     }
    #     head = TextValidationTools.split_words(actors_name)[-1].lower()
    #     if head in SOFTWARE_ARTIFACT_HEADS:
    #         return False, "artifact"
        
    #     person_root = wordnet.synset("person.n.01")
    #     artifact_root = wordnet.synset("artifact.n.01")
    #     system_root = wordnet.synset("system.n.01")
        
    #     head_syns = wordnet.synsets(head, pos=wordnet.NOUN)
    #     if head_syns:
    #         for syn in head_syns:
    #             if syn.lexname() in {"noun.person","noun.group"}:
    #                 return True, "person"
    #             for path in syn.hypernym_paths():
    #                 if person_root in path:
    #                     return True, "person"
    #         if head_syns[0].lexname() in {"noun.artifact", "noun.object"}:
    #             return False, "artifact"
            
    #         # if any(s.lexname() == "noun.person" for s in head_syns):
    #         #     return True, "person"
        
    #     compound_key = actors_name.replace(" ", "_").lower()
    #     syns = wordnet.synsets(compound_key, pos=wordnet.NOUN)
    #     print(syns)
    #     if syns:
    #         person_syn = next((s for s in syns if s.lexname() == "noun.person"), None)
    #         if person_syn:
    #             return True, "person"
    #     if head.lower().endswith(("er", "or", "ist", "ian")):
    #         return True, "person"
            
    #     else:
    #         tokens = word_tokenize(actors_name)
    #         tags = pos_tag(tokens)
    #         head, head_tag = tags[-1]
    #         synsets = wordnet.synsets(head, pos=wordnet.NOUN)
    #         if not synsets:
    #             return TextValidationTools.flairIsPerson(actors_name)
    #         syn = synsets[0]

    #     lex = syn.lexname()
    #     if lex == "noun.person":
    #         return True, "person"
    #     if lex == "noun.artifact" or lex == "noun.group":
    #         return False, "artifact"
        
    #     for path in syn.hypernym_paths():
    #         if person_root in path:
    #             return True, "person"
    #         if artifact_root in path or system_root in path:
    #             return False, "artifact"

    #     return TextValidationTools.flairIsPerson(actors_name)
    
    @staticmethod
    def flairIsPerson(text):
        flairTagger=getFlairPosTagger()
        sentence = Sentence(text.lower())
        flairTagger.predict(sentence)
        for entity in sentence.get_spans('ner'):
            if entity.get_label('ner').value == 'PER':
                return True, "person"
        return False, "other"
    
    @staticmethod
    def isPrimaryActor(name: str) -> tuple[bool, str]:
        """
        Decide whether *name* looks like a “primary” actor (= person / role).

        Returns
        -------
        (True,  "person")   → looks like a human / role
        (False, "artifact") → looks like a physical / software artefact
        (False, "other")    → cannot be determined reliably
        """
        lemmatizer = getLemmatizer()

        # ── HEAD WORD ------------------------------------------------------------
        sentence = Sentence(name)
        getFlairPosTagger().predict(sentence)
        words   = [t.text for t in sentence]
        head    = lemmatizer.lemmatize(words[-1].lower(), pos="n")

        # 1) unmistakable artefact keywords
        CLEAR_ARTIFACT = {
            "system", "device", "tool", "module", "component", "machine",
            "software", "hardware", "platform", "subsystem", "application",
            "framework", "interface", "server", "sensor", "actuator",
            "equipment", "infrastructure", "network", "terminal", "robot",
            "processor", "data"
            #  ↯ -- “controller”, “operator”, “manager” removed from this set
        }
        if head in CLEAR_ARTIFACT:
            return False, "artifact"

        # 2) heads that can represent EITHER a person OR an artefact
        AMBIGUOUS = {"controller", "operator", "provider" , "service"}
        if head in AMBIGUOUS:
            # Do a quick NER check – if Flair tags the full phrase as PER, accept it
            is_per, _ = TextValidationTools.flairIsPerson(name)
            if is_per:
                return True, "person"
            # otherwise boarderline → let the caller decide how severe to treat it
            return False, "other"

        # 3) WordNet back-off -----------------------------------------------------
        person_root   = wordnet.synset("person.n.01")
        artifact_root = wordnet.synset("artifact.n.01")

        synsets = wordnet.synsets(head, pos=wordnet.NOUN)
        if synsets:
            for syn in synsets:
                # direct lexical clues
                if syn.lexname() in {"noun.person", "noun.group"}:
                    return True, "person"
                # walk the hypernym tree
                for path in syn.hypernym_paths():
                    if person_root in path:
                        return True, "person"
                    if artifact_root in path:
                        return False, "artifact"

            # top-sense heuristic
            if synsets[0].lexname() in {"noun.artifact", "noun.object"}:
                return False, "artifact"

        # 4) still inconclusive
        return False, "other"
    
    @staticmethod
    def split_words(text):
        words=[]
        for word in text.split():
            parts=re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+', word)
            if parts:
                words.extend(parts)
            else:
                words.append(word)
        return words

    @staticmethod
    def toPascalCase(text):
        words=TextValidationTools.split_words(text)
        return ''.join(w if w.isupper() else w.capitalize() for w in words)

    @staticmethod
    def toTitleCase(text):
        words=TextValidationTools.split_words(text)
        return ' '.join(w if w.isupper() else w.capitalize() for w in words)
    
    @staticmethod
    def toTitleCaseSmart(text):
        words = TextValidationTools.split_words(text)
        nlp = getSpacyModel()
        doc = nlp(' '.join(words))

        result = []
        for i, token in enumerate(doc):
            if token.pos_ == "ADP":
                result.append(token.text.lower())
            else:
                result.append(token.text if token.text.isupper() else token.text.capitalize())
        return ' '.join(result)
    
    @staticmethod
    def isTruePreposition(word, sentence):
        nlp = getSpacyModel()
        doc = nlp(sentence)
        for token in doc:
            if token.text.lower() == word.lower():
                if token.dep_ == "prep" and token.head.pos_ != "VERB":
                    return True
                elif token.dep_ in {"mark", "advmod", "complm"}:
                    return False
        return False
    
    @staticmethod
    def phraseSimilarity(phrase1, phrase2):
        model=getSimilarityEncoder()
        # embs = model.encode([f"query: {phrase1}", f"query: {phrase2}"], normalize_embeddings=True)
        raw = float(model.predict([(phrase1, phrase2)])[0])
        score = 1 / (1 + math.exp(-raw))
        return score
    
    @staticmethod
    def applyAcronymOverride(orig_text, flair_tags):
        ACRONYM_RE = re.compile(r'^[A-Z]{2,}$')
        orig_tokens = orig_text.split()
        new_tags = []

        for i, (flair_tok, flair_tag) in enumerate(flair_tags):
            if i < len(orig_tokens):
                orig_tok = orig_tokens[i]
                if ACRONYM_RE.match(orig_tok.upper()):  # <-- Force uppercase for comparison
                    new_tags.append((flair_tok, 'NN'))  # force NN tag for acronyms
                else:
                    new_tags.append((flair_tok, flair_tag))
            else:
                new_tags.append((flair_tok, flair_tag))
        return new_tags
