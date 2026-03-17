"""Run once to regenerate verification/ucd_rules.xml from data."""
import os
import xml.etree.ElementTree as ET

def make_component(panel, comp_id, index, uid, x, y, w, h, req_name,
                   first_cp_id, textlines, kind, criticality, req_type, rule_id, color="-1773070"):
    comp = ET.SubElement(panel, "COMPONENT", attrib={
        "type": "5200", "id": str(comp_id), "index": str(index), "uid": uid
    })
    ET.SubElement(comp, "cdparam", attrib={"x": str(x), "y": str(y)})
    ET.SubElement(comp, "sizeparam", attrib={
        "width": str(w), "height": str(h), "minWidth": "1", "minHeight": "30",
        "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"
    })
    ET.SubElement(comp, "hidden", attrib={"value": "false"})
    ET.SubElement(comp, "cdrectangleparam", attrib={"minX": "10", "maxX": "2500", "minY": "10", "maxY": "1500"})
    ET.SubElement(comp, "infoparam", attrib={"name": "Requirement", "value": req_name})
    ET.SubElement(comp, "new", attrib={"d": "false"})
    for i in range(43):
        ET.SubElement(comp, "TGConnectingPoint", attrib={"num": str(i), "id": str(first_cp_id + i)})
    extra = ET.SubElement(comp, "extraparam")
    for t in textlines:
        ET.SubElement(extra, "textline", attrib={"data": t})
    ET.SubElement(extra, "kind",         attrib={"data": kind})
    ET.SubElement(extra, "criticality",  attrib={"data": criticality})
    ET.SubElement(extra, "reqType",      attrib={"data": req_type, "color": color})
    ET.SubElement(extra, "id",           attrib={"data": rule_id})
    for tag in ("satisfied", "verified"):
        ET.SubElement(extra, tag, attrib={"data": "false"})
    for tag in ("attackTreeNode", "violatedAction", "referenceElements"):
        ET.SubElement(extra, tag, attrib={"data": ""})

def make_connector(panel, conn_id, index, uid_str, x, y, p1_id, p1x, p1y, p2_id, p2x, p2y):
    conn = ET.SubElement(panel, "CONNECTOR", attrib={
        "type": "5205", "id": str(conn_id), "index": str(index), "uid": uid_str
    })
    ET.SubElement(conn, "cdparam", attrib={"x": str(x), "y": str(y)})
    ET.SubElement(conn, "sizeparam", attrib={
        "width": "0", "height": "0", "minWidth": "0", "minHeight": "0",
        "maxWidth": "2000", "maxHeight": "2000", "minDesiredWidth": "0", "minDesiredHeight": "0"
    })
    ET.SubElement(conn, "infoparam", attrib={"name": "connector", "value": "<<composition>>"})
    ET.SubElement(conn, "TGConnectingPoint", attrib={"num": "0", "id": str(conn_id - 1)})
    ET.SubElement(conn, "P1", attrib={"x": str(p1x), "y": str(p1y), "id": str(p1_id)})
    ET.SubElement(conn, "P2", attrib={"x": str(p2x), "y": str(p2y), "id": str(p2_id)})
    ET.SubElement(conn, "AutomaticDrawing", attrib={"data": "true"})
    ET.SubElement(conn, "new", attrib={"d": "false"})

root_frag = ET.Element("RULES_FRAGMENT")

# ── Actor Rules ────────────────────────────────────────────────────────────────
import uuid as _uuid

def new_uid(): return str(_uuid.uuid4())

def make_panel():
    return ET.SubElement(
        ET.SubElement(root_frag, "Modeling", attrib={"type": "Avatar Requirement", "nameTab": ""}),
        "AvatarRDPanel", attrib={"name": "AVATARRD","minX":"10","maxX":"2500","minY":"10","maxY":"1500","zoom":"1.0"}
    )

# === Actor_Rules_AR ===
m = ET.SubElement(root_frag, "Modeling", attrib={"type":"Avatar Requirement","nameTab":"Actor_Rules_AR"})
p = ET.SubElement(m, "AvatarRDPanel", attrib={"name":"AVATARRD","minX":"10","maxX":"2500","minY":"10","maxY":"1500","zoom":"1.0"})

# ROOT: Actor_Rules_AR id=412, cp 369-411
make_component(p,412,16,new_uid(),473,57,325,78,"Actor_Rules_AR",369,
    ["The actors in the use case diagram shall be modeled ","in accordance with defined actor rules."],
    "Functional","Low","Actor_Modeling_Rules","1")
# AR_8 id=46, cp 3-45
make_component(p,46,1,new_uid(),10,71,314,75,"AR_8_Actor_Association_Restriction_Rule",3,
    ["Direct associations between actors ","shall not be permitted."],"Functional","Low","Actor_Modeling_Rules","0")
# AR_7 id=92, cp 49-91
make_component(p,92,3,new_uid(),928,69,301,76,"AR_7_Non_Human_Actor_Notation_Rule",49,
    ["Non-human actors shall be represented using the ","rectangular Actor stereotype notation."],"Functional","Low","Actor_Modeling_Rules","1.7")
# AR_6 id=138, cp 95-137
make_component(p,138,5,new_uid(),967,272,242,80,"AR_6_Actor_Notation_Rule",95,
    ["Human actors shall be represented ","using UML stickman notation."],"Functional","Low","Actor_Modeling_Rules","1.6")
# AR_5 id=184, cp 141-183
make_component(p,184,7,new_uid(),10,259,344,87,"AR_5_Actor_Redundancy_Prevention_Rule",141,
    ["Redundant associations between an actor and included","sub-use cases shall not be created unless the actor"," independently initiates the included use case."],"Functional","Low","Actor_Modeling_Rules","1.5")
# AR_4 id=236, cp 193-235
make_component(p,236,12,new_uid(),942,460,288,78,"AR_4_Actor_Association_Rule",193,
    ["Each actor shall be associated with at least one ","valid use case within the system boundary."],"Functional","Low","Actor_Modeling_Rules","1.4")
# AR_3 id=280, cp 237-279
make_component(p,280,13,new_uid(),646,460,279,78,"AR_3_Actor_Naming_Restriction_Rule",237,
    ["The actor names shall not be ","proper nouns."],"Functional","Low","Actor_Modeling_Rules","1.3")
# AR_2 id=324, cp 281-323
make_component(p,324,14,new_uid(),357,462,267,77,"AR_2_Actor_Uniqueness_Rule",281,
    ["Each actor name shall be unique ","within the use case diagram."],"Functional","Low","Actor_Modeling_Rules","1.2")
# AR_1 id=368, cp 325-367
make_component(p,368,15,new_uid(),10,463,328,79,"AR_1_Actor_Role_Rule",325,
    ["Each actor shall be represented as a","singular noun denoting a generic role."],"Functional","Low","Actor_Modeling_Rules","1.1")
# Connectors root→children  (p1=root cp, p2=child cp0)
make_connector(p,2,0,new_uid(),476,91, 370,473,96, 6,324,89)
make_connector(p,48,2,new_uid(),801,91, 373,798,96, 49,928,88)
make_connector(p,94,4,new_uid(),842,91, 374,798,115, 102,1088,272)
make_connector(p,140,6,new_uid(),476,91, 371,473,115, 148,182,259)
make_connector(p,186,8,new_uid(),570,227, 395,635,135, 244,785,460)
make_connector(p,188,9,new_uid(),570,227, 394,635,135, 199,1014,460)
make_connector(p,190,10,new_uid(),570,227, 393,635,135, 288,490,462)
make_connector(p,192,11,new_uid(),570,227, 379,635,135, 333,256,463)

# === Use_Case_Rules_UC ===
m = ET.SubElement(root_frag, "Modeling", attrib={"type":"Avatar Requirement","nameTab":"Use_Case_Rules_UC"})
p = ET.SubElement(m, "AvatarRDPanel", attrib={"name":"AVATARRD","minX":"10","maxX":"2500","minY":"10","maxY":"1500","zoom":"1.0"})
make_component(p,824,16,new_uid(),472,101,322,77,"Use_Case_Rules_UC",781,
    ["The Use cases in the use case diagram shall conform ","to defined use case modeling rules."],"Functional","Low","Use_Case_Modeling_Rules","2")
make_component(p,504,3,new_uid(),41,108,287,80,"UC_7_Use_Case_Dangling_Rule",461,
    ["A use case shall not exist"," without a valid connector."],"Functional","Low","Use_Case_Modeling_Rules","2.7")
make_component(p,460,2,new_uid(),899,102,289,75,"UC_8_Use_Case_Boundary_Placement_Rule",417,
    ["Each use case shall be placed ","inside the system boundary."],"Functional","Low","Use_Case_Modeling_Rules","2.8")
make_component(p,604,11,new_uid(),71,286,288,75,"UC_5_Use_Case_Plurality_Rule",561,
    ["The use case name shall end with a singular or ","plural noun representing a valid object."],"Functional","Low","Use_Case_Modeling_Rules","2.5")
make_component(p,552,6,new_uid(),933,264,270,79,"UC_6_Use_Case_Association_Rule",509,
    ["Each use case shall be associated with ","at least one actor or another use case."],"Functional","Low","Use_Case_Modeling_Rules","2.6")
make_component(p,648,12,new_uid(),959,494,219,76,"UC_4_Use_Case_Grammar_Rule",605,
    ["Each use case name shall be ","grammatically correct."],"Functional","Low","Use_Case_Modeling_Rules","2.4")
make_component(p,692,13,new_uid(),685,492,241,78,"UC_3_Use_Case_Uniqueness_Rule",649,
    ["Each use case name shall be unique ","within the use case diagram."],"Functional","Low","Use_Case_Modeling_Rules","2.3")
make_component(p,736,14,new_uid(),397,493,260,78,"UC_2_Use_Case_Meaningfulness_Rule",693,
    ["Each use case name shall be meaningful ","and non-empty."],"Functional","Low","Use_Case_Modeling_Rules","2.2")
make_component(p,780,15,new_uid(),97,493,271,80,"UC_1_Use_Case_Structure_Rule",737,
    ["Each use case shall be named using ","a Verb + Noun structure."],"Functional","Low","Use_Case_Modeling_Rules","2.1")
make_connector(p,414,0,new_uid(),480,122, 781,472,120, 464,328,128)
make_connector(p,416,1,new_uid(),779,122, 784,794,120, 417,899,120)
make_connector(p,506,4,new_uid(),779,143, 785,794,139, 515,1000,264)
make_connector(p,508,5,new_uid(),480,143, 782,472,139, 569,287,286)
make_connector(p,554,7,new_uid(),629,185, 807,633,178, 612,1068,494)
make_connector(p,556,8,new_uid(),629,185, 806,633,178, 656,805,492)
make_connector(p,558,9,new_uid(),629,185, 805,633,178, 700,527,493)
make_connector(p,560,10,new_uid(),629,185, 791,633,178, 744,232,493)

# === Relationship_Rules_RL ===
m = ET.SubElement(root_frag, "Modeling", attrib={"type":"Avatar Requirement","nameTab":"Relationship_Rules_RL"})
p = ET.SubElement(m, "AvatarRDPanel", attrib={"name":"AVATARRD","minX":"10","maxX":"2500","minY":"10","maxY":"1500","zoom":"1.0"})
make_component(p,1236,16,new_uid(),482,60,279,76,"Relationship_Rules_RL",1193,
    ["Relationships in the use case diagram shall ","conform to defined UML relationship rules."],"Functional","Low","Relationship_Modeling_Rules","3")
make_component(p,872,2,new_uid(),895,73,316,74,"RL_8_Invalid_Source_Target_Rule",829,
    ["The Invalid source-target combinations between ","model elements shall not be permitted."],"Functional","Low","Relationship_Modeling_Rules","3.8")
make_component(p,916,3,new_uid(),14,72,319,78,"RL_7_Generalization_Direction_Rule",873,
    ["The generalization relationship shall originate from ","the child element and target the parent element."],"Functional","Low","Relationship_Modeling_Rules","3.7")
make_component(p,962,5,new_uid(),898,237,331,78,"RL_6_Generalization_Type_Compatibility_Rule",919,
    ["The generalization relationship shall occur only ","between compatible element types."],"Functional","Low","Relationship_Modeling_Rules","3.6")
make_component(p,1016,11,new_uid(),12,242,330,77,"RL_5_Extension_Point_Existence_Rule",973,
    ["The extend relationship shall reference a valid ","extension point defined in the base use case."],"Functional","Low","Relationship_Modeling_Rules","3.5")
make_component(p,1060,12,new_uid(),973,465,266,80,"RL_4_Extend_Optional_Behavior_Rule",1017,
    ["The extend relationship shall represent ","optional or conditional behavior."],"Functional","Low","Relationship_Modeling_Rules","3.4")
make_component(p,1104,13,new_uid(),663,468,296,79,"RL_3_Extend_Direction_Rule",1061,
    ["The extend relationship shall originate from the ","extending use case and target the base use case."],"Functional","Low","Relationship_Modeling_Rules","3.3")
make_component(p,1148,14,new_uid(),327,467,322,76,"RL_2_Include_Mandatory_Behavior_Rule",1105,
    ["The include relationship shall represent mandatory"," behavior executed as part of the base use case."],"Functional","Low","Relationship_Modeling_Rules","3.2")
make_component(p,1192,15,new_uid(),10,467,305,78,"RL_1_Include_Direction_Rule",1149,
    ["The include relationship shall originate from the ","base use case and target the included use case."],"Functional","Low","Relationship_Modeling_Rules","3.1")
make_connector(p,826,0,new_uid(),761,79, 1196,761,79, 829,895,91)
make_connector(p,828,1,new_uid(),482,79, 1193,482,79, 876,333,91)
make_connector(p,918,4,new_uid(),761,117, 1198,761,117, 925,980,237)
make_connector(p,964,6,new_uid(),482,117, 1195,482,117, 981,259,242)
make_connector(p,966,7,new_uid(),621,136, 1219,621,136, 1068,811,468)
make_connector(p,968,8,new_uid(),621,136, 1218,621,136, 1024,1106,465)
make_connector(p,970,9,new_uid(),621,136, 1217,621,136, 1112,488,467)
make_connector(p,972,10,new_uid(),621,136, 1203,621,136, 1156,162,467)

# === Modeling_And_Representation_Rules_MR ===
m = ET.SubElement(root_frag, "Modeling", attrib={"type":"Avatar Requirement","nameTab":"Modeling_And_Representation_Rules_MR"})
p = ET.SubElement(m, "AvatarRDPanel", attrib={"name":"AVATARRD","minX":"10","maxX":"2500","minY":"10","maxY":"1500","zoom":"1.0"})
make_component(p,1556,12,new_uid(),398,79,386,71,"Modeling_And_Representation_Rules_MR",1513,
    ["Model elements in the use case diagram shall conform to defined ","representation and formatting rules."],"Functional","Low","Modeling_And_Representation_Rules","4")
make_component(p,1336,7,new_uid(),49,221,274,74,"MR_5_Actor_Placement_Rule",1293,
    ["Actors shall be placed outside ","the system boundary."],"Functional","Low","Modeling_And_Representation_Rules","4.5")
make_component(p,1284,2,new_uid(),918,215,261,79,"MR_6_Use_Case_Placement_Rule",1241,
    ["Use cases shall be placed inside ","the system boundary."],"Functional","Low","Modeling_And_Representation_Rules","4.6")
make_component(p,1380,8,new_uid(),939,423,258,80,"MR_4_Article_Formatting_Rule",1337,
    ["Articles within use case labels ","shall be written in lowercase."],"Functional","Low","Modeling_And_Representation_Rules","4.4")
make_component(p,1424,9,new_uid(),607,426,305,74,"MR_3_Extension_Text_Formatting_Rule",1381,
    ["Conditional extension text shall be grammatically ","correct and clearly written."],"Safety","Low","Modeling_And_Representation_Rules","4.3")
make_component(p,1468,10,new_uid(),303,425,277,75,"MR_2_Title_Case_Rule",1425,
    ["Use case and actor labels shall"," follow Title Case formatting."],"Functional","Low","Modeling_And_Representation_Rules","4.2")
make_component(p,1512,11,new_uid(),10,423,270,75,"MR_1_System_Boundary_Naming_Rule",1469,
    ["The system boundary shall be named ","using a noun phrase."],"Functional","Low","Modeling_And_Representation_Rules","4.1")
make_connector(p,1238,0,new_uid(),784,132, 1518,784,132, 1247,983,215)
make_connector(p,1240,1,new_uid(),398,132, 1515,398,132, 1301,254,221)
make_connector(p,1286,3,new_uid(),591,150, 1539,591,150, 1344,1068,423)
make_connector(p,1288,4,new_uid(),591,150, 1538,591,150, 1388,759,426)
make_connector(p,1290,5,new_uid(),591,150, 1537,591,150, 1432,441,425)
make_connector(p,1292,6,new_uid(),591,150, 1523,591,150, 1476,145,423)

# Write output
out = os.path.join(os.path.dirname(__file__), "ucd_rules.xml")
tree = ET.ElementTree(root_frag)
ET.indent(tree, space="  ")
tree.write(out, encoding="utf-8", xml_declaration=False)
print(f"Written: {out}")
