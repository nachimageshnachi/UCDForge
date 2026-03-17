from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from MyCBR.repository import OUTPUT_DIR, ensure_workspace


# ---------------------------------------------------------------------------
# Attribute specifications
# ---------------------------------------------------------------------------

NUMERIC_ATTRS = [
    ("PrimaryActorCount", "strict_primary_actor_count", "loose_primary_actor_count"),
    ("SecondaryActorCount", "strict_secondary_actor_count", "loose_secondary_actor_count"),
    ("UseCaseCount", "strict_use_case_count", "loose_use_case_count"),
    ("RelationshipCount", "strict_relationship_count", "loose_relationship_count"),
]

# Symbol attributes: equal/unequal matching (joined pipe-separated name lists)
SYMBOL_ATTRS = [
    "PrimaryDomain",
    "SystemKind",
    "HasInclude",
    "HasExtend",
    "HasGeneralization",
    "CaseOrigin",
    "ActorNames",
    "UseCaseNames",
    "RelationshipTypes",
    "DomainList",
]

# String attributes: state-of-the-art string similarity (NGram / JaroWinkler)
STRING_ATTRS = [
    # (attr_name,    fct_name,           stringMetric,   extra_params)
    ("SystemName",  "ngram_system",      "NGRAM",        'n="3"'),
    ("Description", "jarowinkler_desc",  "JAROWINKLER",  ""),
]

_SEP = " | "  # separator used when joining multi-value fields into a single Symbol


# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value).strip("_") or "Project"


def _project_names(project_name: str) -> Dict[str, str]:
    project_base = _safe_name(project_name)
    concept_name = f"{project_base}Case"
    casebase_name = f"{project_base}CB"
    return {"project": project_base, "concept": concept_name, "casebase": casebase_name}


def _system_kind(system_name: str) -> str:
    tokens = [tok for tok in str(system_name or "").split() if tok]
    return tokens[-1] if tokens else "System"


def _has_relationship(case_payload: Dict[str, Any], relationship_type: str) -> str:
    for rel in case_payload.get("relationships", []) or []:
        if str(rel.get("relationship_type") or "").lower() == relationship_type:
            return "Yes"
    return "No"


def _join_names(names: List[str], sep: str = _SEP) -> str:
    """Join a list of names into a single pipe-separated string, safe for myCBR Symbol values."""
    clean = [str(n).strip() for n in (names or []) if str(n).strip()]
    return (sep.join(clean)) if clean else "_undefined_"


def _rel_types(case_payload: Dict[str, Any]) -> str:
    types = sorted({
        str(rel.get("relationship_type") or "association").lower()
        for rel in (case_payload.get("relationships") or [])
        if rel.get("relationship_type")
    })
    return _join_names(types, sep=" | ") if types else "_undefined_"


def _case_features(case_payload: Dict[str, Any]) -> Dict[str, Any]:
    domains = case_payload.get("domains") or []
    primary_domain = domains[0] if domains else "Undefined"
    primary_actors = case_payload.get("primary_actors") or []
    secondary_actors = case_payload.get("secondary_actors") or []
    use_cases = case_payload.get("use_cases") or []
    all_actors = primary_actors + secondary_actors

    return {
        # --- identifiers (excluded from myCBR instance attributes) ---
        "CaseId":              case_payload.get("case_key") or f"Case_{case_payload.get('case_id')}",
        # --- String attrs (NGram / JaroWinkler similarity) ---
        "SystemName":          case_payload.get("system_name") or "",
        "Description":         case_payload.get("description") or "",
        # --- Symbol attrs (equal/unequal) ---
        "PrimaryDomain":       primary_domain,
        "SystemKind":          _system_kind(case_payload.get("system_name") or ""),
        "HasInclude":          _has_relationship(case_payload, "include"),
        "HasExtend":           _has_relationship(case_payload, "extend"),
        "HasGeneralization":   _has_relationship(case_payload, "generalization"),
        "CaseOrigin":          str(case_payload.get("source") or "retained").title(),
        "ActorNames":          _join_names(all_actors),
        "UseCaseNames":        _join_names(use_cases),
        "RelationshipTypes":   _rel_types(case_payload),
        "DomainList":          _join_names(domains),
        # --- Numeric attrs ---
        "PrimaryActorCount":   float(len(primary_actors)),
        "SecondaryActorCount": float(len(secondary_actors)),
        "UseCaseCount":        float(len(use_cases)),
        "RelationshipCount":   float(len(case_payload.get("relationships") or [])),
    }


# ---------------------------------------------------------------------------
# Symbol value collectors
# ---------------------------------------------------------------------------

def _symbol_values(cases: List[Dict[str, Any]], attr_name: str) -> List[str]:
    values = {"_others_", "_unknown_", "_undefined_"}
    for case_payload in cases:
        raw = str(_case_features(case_payload).get(attr_name) or "").strip()
        if raw:
            values.add(raw)
    return sorted(values)


def _numeric_range(cases: List[Dict[str, Any]], attr_name: str) -> tuple[float, float]:
    values = [float(_case_features(case_payload).get(attr_name) or 0.0) for case_payload in cases]
    maximum = max(values + [1.0])
    return 0.0, maximum


# ---------------------------------------------------------------------------
# XML descriptor builders
# ---------------------------------------------------------------------------

def _build_symbol_desc(attr_name: str, values: List[str]) -> str:
    symbols = "\n".join(
        f'      <symbol value="{escape(v)}" />'
        for v in values
        if v not in {"_others_", "_unknown_", "_undefined_"}
    )
    qsyms = "\n".join(f'<qsym name="{escape(v)}">\n</qsym>' for v in values)
    return (
        f'    <desc name="{attr_name}" type="Symbol" mult="false" >\n'
        f"{symbols}\n"
        f'<fct name="default function" type="Symbol" mt="PARTNER_QUERY" r="REUSE" t="MAX" symm="true">\n'
        f"{qsyms}\n"
        f"</fct>\n"
        f"    </desc>"
    )


def _build_string_desc(attr_name: str, fct_name: str, string_metric: str, extra_params: str) -> str:
    """Build a myCBR String-type descriptor with a named metric function plus a default equal fallback."""
    extra = f" {extra_params}" if extra_params else ""
    return (
        f'    <desc name="{attr_name}" type="String" mult="false" >\n'
        f'      <fct name="{fct_name}" type="String" stringMetric="{string_metric}"{extra} mt="PARTNER_QUERY" r="REUSE" t="MAX" symm="true"/>\n'
        f'      <fct name="default function" type="String" stringMetric="EQUAL" mt="PARTNER_QUERY" r="REUSE" t="MAX" symm="true"/>\n'
        f'    </desc>'
    )


def _build_numeric_desc(attr_name: str, strict_name: str, loose_name: str, minimum: float, maximum: float) -> str:
    return (
        f'    <desc name="{attr_name}" type="Float" min="{minimum:.1f}" max="{maximum:.1f}" mult="false" >\n'
        f'      <fct name="{strict_name}" type="Float" ltype="CONSTANT" lparam="1.0" rtype="POLYNOMIAL_WITH" rparam="1.5" mode="DIFFERENCE" symm="false" mt="PARTNER_QUERY" r="REUSE" t="MAX" maxForQuotient="10.0" />\n'
        f'      <fct name="{loose_name}" type="Float" ltype="CONSTANT" lparam="1.0" rtype="POLYNOMIAL_WITH" rparam="3.5" mode="DIFFERENCE" symm="false" mt="PARTNER_QUERY" r="REUSE" t="MAX" maxForQuotient="10.0" />\n'
        f'      <fct name="default function" type="Float" ltype="CONSTANT" lparam="1.0" rtype="CONSTANT" rparam="1.0" mode="DIFFERENCE" symm="true" mt="PARTNER_QUERY" r="REUSE" t="MAX" maxForQuotient="10.0" />\n'
        f"    </desc>"
    )


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def build_casebase_csv(cases: List[Dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    fieldnames = [
        "CaseId",
        "SystemName",
        "Description",
        "PrimaryDomain",
        "DomainList",
        "SystemKind",
        "ActorNames",
        "UseCaseNames",
        "PrimaryActorCount",
        "SecondaryActorCount",
        "UseCaseCount",
        "RelationshipCount",
        "RelationshipTypes",
        "HasInclude",
        "HasExtend",
        "HasGeneralization",
        "CaseOrigin",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for case_payload in cases:
        writer.writerow(_case_features(case_payload))
    return buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# myCBR model builder  (.myCBR)
# ---------------------------------------------------------------------------

def build_mycbr_model(project_name: str, cases: List[Dict[str, Any]]) -> str:
    names = _project_names(project_name)

    # String descriptors (NGram / JaroWinkler)
    string_descs = "\n".join(
        _build_string_desc(attr, fct, metric, extra)
        for attr, fct, metric, extra in STRING_ATTRS
    )

    # Symbol descriptors
    symbol_descs = "\n".join(
        _build_symbol_desc(attr, _symbol_values(cases, attr))
        for attr in SYMBOL_ATTRS
    )

    # Numeric descriptors
    numeric_descs = "\n".join(
        _build_numeric_desc(attr, strict, loose, *_numeric_range(cases, attr))
        for attr, strict, loose in NUMERIC_ATTRS
    )

    # ---- Amalgam: balanced_similarity (mirrors Python CBR weight proportions) ----
    # Use Cases ≈ 35% → UseCaseNames (3.5) + UseCaseCount (3.5)
    # Actors    ≈ 23% → ActorNames (2.0) + PrimaryActorCount (1.5) + SecondaryActorCount (1.5)
    # Domains   ≈ 18% → PrimaryDomain (1.5) + DomainList (1.5)
    # Desc      ≈ 12% → Description (1.0)
    # Title     ≈  6% → SystemName (0.5)
    # Lexical   ≈  6% → RelationshipTypes (0.5) + RelationshipCount (0.5)
    balanced_entries = "\n".join([
        # String fields
        '      <entry name="SystemName"        active="true" fct="ngram_system"        weight="0.5"/>',
        '      <entry name="Description"       active="true" fct="jarowinkler_desc"    weight="1.0"/>',
        # Symbol fields
        '      <entry name="PrimaryDomain"     active="true" fct="default function"    weight="1.5"/>',
        '      <entry name="SystemKind"        active="true" fct="default function"    weight="0.5"/>',
        '      <entry name="ActorNames"        active="true" fct="default function"    weight="2.0"/>',
        '      <entry name="UseCaseNames"      active="true" fct="default function"    weight="3.5"/>',
        '      <entry name="RelationshipTypes" active="true" fct="default function"    weight="0.5"/>',
        '      <entry name="DomainList"        active="true" fct="default function"    weight="1.5"/>',
        # Numeric fields
        '      <entry name="PrimaryActorCount"   active="true" fct="loose_primary_actor_count"   weight="1.5"/>',
        '      <entry name="SecondaryActorCount" active="true" fct="loose_secondary_actor_count" weight="1.5"/>',
        '      <entry name="UseCaseCount"        active="true" fct="loose_use_case_count"        weight="3.5"/>',
        '      <entry name="RelationshipCount"   active="true" fct="loose_relationship_count"    weight="0.5"/>',
        # Flags (minor contribution)
        '      <entry name="HasInclude"        active="true" fct="default function"    weight="0.5"/>',
        '      <entry name="HasExtend"         active="true" fct="default function"    weight="0.5"/>',
        '      <entry name="HasGeneralization" active="true" fct="default function"    weight="0.5"/>',
        '      <entry name="CaseOrigin"        active="true" fct="default function"    weight="0.2"/>',
    ])


    # ---- Amalgam: structure_focused_similarity ----
    structure_entries = "\n".join([
        '      <entry name="SystemName"          active="true" fct="ngram_system"             weight="2.5"/>',
        '      <entry name="Description"         active="true" fct="jarowinkler_desc"         weight="1.5"/>',
        '      <entry name="PrimaryDomain"       active="true" fct="default function"         weight="2.0"/>',
        '      <entry name="SystemKind"          active="true" fct="default function"         weight="2.0"/>',
        '      <entry name="RelationshipTypes"   active="true" fct="default function"         weight="2.0"/>',
        '      <entry name="UseCaseNames"        active="true" fct="default function"         weight="1.0"/>',
        '      <entry name="ActorNames"          active="true" fct="default function"         weight="0.5"/>',
        '      <entry name="DomainList"          active="true" fct="default function"         weight="1.0"/>',
        '      <entry name="PrimaryActorCount"   active="true" fct="strict_primary_actor_count"   weight="1.5"/>',
        '      <entry name="SecondaryActorCount" active="true" fct="strict_secondary_actor_count" weight="1.5"/>',
        '      <entry name="UseCaseCount"        active="true" fct="strict_use_case_count"        weight="3.0"/>',
        '      <entry name="RelationshipCount"   active="true" fct="strict_relationship_count"    weight="2.5"/>',
        '      <entry name="HasInclude"          active="true" fct="default function"         weight="1.0"/>',
        '      <entry name="HasExtend"           active="true" fct="default function"         weight="1.0"/>',
        '      <entry name="HasGeneralization"   active="true" fct="default function"         weight="1.5"/>',
    ])

    # ---- Amalgam: actor_focused_similarity ----
    actor_entries = "\n".join([
        '      <entry name="SystemName"          active="true" fct="ngram_system"             weight="1.0"/>',
        '      <entry name="Description"         active="true" fct="jarowinkler_desc"         weight="0.5"/>',
        '      <entry name="PrimaryDomain"       active="true" fct="default function"         weight="1.5"/>',
        '      <entry name="SystemKind"          active="true" fct="default function"         weight="1.0"/>',
        '      <entry name="ActorNames"          active="true" fct="default function"         weight="3.5"/>',
        '      <entry name="UseCaseNames"        active="true" fct="default function"         weight="1.5"/>',
        '      <entry name="RelationshipTypes"   active="true" fct="default function"         weight="0.5"/>',
        '      <entry name="DomainList"          active="true" fct="default function"         weight="1.0"/>',
        '      <entry name="PrimaryActorCount"   active="true" fct="loose_primary_actor_count"   weight="3.0"/>',
        '      <entry name="SecondaryActorCount" active="true" fct="loose_secondary_actor_count" weight="2.5"/>',
        '      <entry name="UseCaseCount"        active="true" fct="loose_use_case_count"        weight="1.5"/>',
        '      <entry name="RelationshipCount"   active="true" fct="loose_relationship_count"    weight="1.0"/>',
        '      <entry name="HasGeneralization"   active="true" fct="default function"         weight="1.0"/>',
    ])

    return (
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        f'<Project name="{names["project"]}" author="" >\n'
        "<svs>\n"
        '  <sv name="_others_"/>\n'
        '  <sv name="_unknown_"/>\n'
        '  <sv name="_undefined_"/>\n'
        '<fct name="default function" type="Symbol" mt="PARTNER_QUERY" r="REUSE" t="MAX" symm="true">\n'
        '<qsym name="_others_">\n</qsym>\n'
        '<qsym name="_unknown_">\n</qsym>\n'
        '<qsym name="_undefined_">\n</qsym>\n'
        "</fct>\n"
        "</svs>\n"
        "<model>\n"
        f'  <concept name="{names["concept"]}">\n'
        f"{string_descs}\n"
        f"{symbol_descs}\n"
        f"{numeric_descs}\n"
        '    <amalgam name="balanced_similarity" type="WEIGHTED_SUM" active="true" >\n'
        f"{balanced_entries}\n"
        "    </amalgam>\n"
        '    <amalgam name="structure_focused_similarity" type="WEIGHTED_SUM" active="false" >\n'
        f"{structure_entries}\n"
        "    </amalgam>\n"
        '    <amalgam name="actor_focused_similarity" type="WEIGHTED_SUM" active="false" >\n'
        f"{actor_entries}\n"
        "    </amalgam>\n"
        "  </concept>\n"
        "</model>\n"
        "<hierarchy>\n"
        '  <fct name="default function" type="Taxonomy" mt="PARTNER_QUERY" r="REUSE" t="MAX" qconfig="INNER_NODES_ANY" cconfig="INNER_NODES_ANY" top="inheritanceDesc" sim="0.0" symm="true" >\n'
        f'    <node name="{names["concept"]}" sim="1.0" parent="inheritanceDesc" />\n'
        "  </fct>\n"
        "</hierarchy>\n"
        f'<cases no="{len(cases)}" cb="{names["casebase"]}"/>\n'
        "</Project>\n"
    )


# ---------------------------------------------------------------------------
# myCBR case instances builder  (.myCB)
# ---------------------------------------------------------------------------

# Fields excluded from instance attributes (they are identifiers, not similarity features)
_INSTANCE_EXCLUDE = {"CaseId"}

# String attribute names (serialized differently — no Symbol required)
_STRING_ATTR_NAMES = {attr for attr, _, _, _ in STRING_ATTRS}


def build_mycbr_cases(project_name: str, cases: List[Dict[str, Any]]) -> str:
    names = _project_names(project_name)
    instances: List[str] = []
    case_refs: List[str] = []

    for index, case_payload in enumerate(cases):
        features = _case_features(case_payload)
        instance_id = f'{names["concept"]} #{index}'
        att_lines = []
        for key, value in features.items():
            if key in _INSTANCE_EXCLUDE:
                continue
            att_lines.append(f'    <att name="{key}" value="{escape(str(value))}" />')
        instances.append(
            f'  <instance id="{escape(instance_id)}" >\n'
            + "\n".join(att_lines)
            + "\n  </instance>"
        )
        case_refs.append(f'     <case name="{escape(instance_id)}" />')

    return (
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        f'<Project name="{names["project"]}" author="" >\n'
        f'<instances name="{names["concept"]}">\n'
        + "\n".join(instances)
        + "\n</instances>\n"
        f'<cb name="{names["casebase"]}">\n'
        + "\n".join(case_refs)
        + "\n</cb>\n"
        "</Project>\n"
    )


# ---------------------------------------------------------------------------
# Explanations builder  (.myExp)
# ---------------------------------------------------------------------------

def build_explanations(project_name: str) -> str:
    names = _project_names(project_name)
    return (
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        f'<Project name="{names["project"]}" author="" >\n'
        f'<exp obj="{names["concept"]}" type="Concept" >\n'
        "  <desc>\n"
        "Structured use-case-diagram cases exported from the repository case base.\n"
        "  </desc>\n"
        "</exp>\n"
        f'<exp obj="SystemName" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nFull system boundary name matched with NGram(3) string similarity.\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="Description" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nFull system description matched with JaroWinkler string similarity.\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="ActorNames" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nPipe-separated list of all actor names (primary and secondary).\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="UseCaseNames" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nPipe-separated list of all use-case names.\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="RelationshipTypes" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nPipe-separated sorted set of relationship types used (association, include, extend, generalization).\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="DomainList" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nPipe-separated list of domain tags.\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="PrimaryDomain" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nPrimary domain extracted from the case metadata.\n  </desc>\n"
        "</exp>\n"
        f'<exp obj="UseCaseCount" c="{names["concept"]}" type="AttributeDesc" >\n'
        "  <desc>\nNumber of use cases in the case.\n  </desc>\n"
        "</exp>\n"
        "</Project>\n"
    )


def build_config() -> str:
    return '<?xml version="1.0" encoding="ISO-8859-1"?>\n<Config author="" >\n</Config>\n'


# ---------------------------------------------------------------------------
# Bundle builders
# ---------------------------------------------------------------------------

def build_project_bundle(project_name: str, cases: List[Dict[str, Any]]) -> Dict[str, bytes]:
    names = _project_names(project_name)
    mycbr_xml = build_mycbr_model(project_name, cases).encode("iso-8859-1", errors="ignore")
    mycb_xml = build_mycbr_cases(project_name, cases).encode("iso-8859-1", errors="ignore")
    myexp_xml = build_explanations(project_name).encode("iso-8859-1", errors="ignore")
    config_xml = build_config().encode("iso-8859-1", errors="ignore")
    csv_bytes = build_casebase_csv(cases)

    prj_buffer = io.BytesIO()
    with zipfile.ZipFile(prj_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{names["project"]}.myCBR', mycbr_xml)
        zf.writestr(f'{names["project"]}.myCB', mycb_xml)
        zf.writestr(f'{names["project"]}.myExp', myexp_xml)
        zf.writestr(f'{names["project"]}.config', config_xml)

    workspace_buffer = io.BytesIO()
    with zipfile.ZipFile(workspace_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{names["project"]}/{names["project"]}.myCBR', mycbr_xml)
        zf.writestr(f'{names["project"]}/{names["project"]}.myCB', mycb_xml)
        zf.writestr(f'{names["project"]}/{names["project"]}.myExp', myexp_xml)
        zf.writestr(f'{names["project"]}/{names["project"]}.config', config_xml)
        zf.writestr(f'{names["project"]}/{names["project"]}.prj', prj_buffer.getvalue())
        zf.writestr(f'{names["project"]}/casebase.csv', csv_bytes)
        zf.writestr(
            f'{names["project"]}/README.txt',
            (
                "Open the .prj file in myCBR Workbench or import the CSV manually.\n"
                "This project provides three amalgams:\n"
                "  - balanced_similarity       : default, balances all fields\n"
                "  - structure_focused_similarity : emphasises counts and relationship types\n"
                "  - actor_focused_similarity    : emphasises actor names and counts\n"
                "\n"
                "String fields (SystemName, Description) use NGram(3) and JaroWinkler similarity\n"
                "respectively — these are state-of-the-art character-level string metrics.\n"
            ).encode("utf-8"),
        )

    return {
        f'{names["project"]}.myCBR': mycbr_xml,
        f'{names["project"]}.myCB': mycb_xml,
        f'{names["project"]}.myExp': myexp_xml,
        f'{names["project"]}.config': config_xml,
        f'{names["project"]}.prj': prj_buffer.getvalue(),
        f'{names["project"]}_workspace.zip': workspace_buffer.getvalue(),
        "casebase.csv": csv_bytes,
    }


def write_project_bundle(project_name: str, cases: List[Dict[str, Any]]) -> Dict[str, Path]:
    ensure_workspace()
    names = _project_names(project_name)
    target_dir = OUTPUT_DIR / names["project"]
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_project_bundle(project_name, cases)
    output_paths: Dict[str, Path] = {}
    for file_name, content in bundle.items():
        path = target_dir / file_name
        path.write_bytes(content)
        output_paths[file_name] = path
    return output_paths
