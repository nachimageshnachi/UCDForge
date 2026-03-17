"""
Build a styled Excel workbook for the hybrid retrieval results.

Sheet 1: Python CBR
    Each parameter is exported as three adjacent columns:
    similarity, weight, and raw product (similarity * weight).

Sheet 2: myCBR Engine
    Each active myCBR query attribute is exported with the same
    similarity, weight, and product triplet.
    The myCBR REST endpoint only returns an overall score, so the local
    per-attribute similarities in this sheet are derived in Python from
    the configured feature model and the matched case data.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Mapping, Sequence

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

try:
    from MyCBR.project_export import _case_features as _mycbr_case_features
    from MyCBR.repository import load_all_cases
except Exception:
    _mycbr_case_features = None
    load_all_cases = None

try:
    from cbr_search import find_all_uc_similarities as _find_all_uc_similarities
except Exception:
    _find_all_uc_similarities = None

try:
    from embeddings import CBR_WEIGHTS as _CBR_WEIGHTS
except Exception:
    _CBR_WEIGHTS = None


# Always mirror the ranking weights from embeddings.py (single source of truth)
PY_CBR_WEIGHTS: Dict[str, float] = _CBR_WEIGHTS if _CBR_WEIGHTS is not None else {
    "sim_title":    round(0.10 / 0.88, 4),
    "sim_desc":     round(0.15 / 0.88, 4),
    "sim_domains":  round(0.08 / 0.88, 4),
    "sim_actors":   round(0.20 / 0.88, 4),
    "sim_usecases": round(0.30 / 0.88, 4),
    "sim_lexical":  round(0.05 / 0.88, 4),
}

PY_CBR_LABELS: Dict[str, str] = {
    "sim_title": "System Name",
    "sim_desc": "Description",
    "sim_domains": "Domains",
    "sim_actors": "Actors",
    "sim_usecases": "Use Cases",
    "sim_lexical": "Lexical Overlap",
}

# GA-optimized weights (from Genetic Algorithm simulation on 50 cases)
GA_WEIGHTS: Dict[str, float] = {
    "sim_title":    0.1507,   # 15.1%
    "sim_desc":     0.1867,   # 18.7%
    "sim_domains":  0.1881,   # 18.8%
    "sim_actors":   0.1978,   # 19.8%  (average across trials)
    "sim_usecases": 0.2146,   # 21.5%
    "sim_lexical":  0.1771,   # 17.7%
}

MYCBR_WEIGHTS: Dict[str, float] = {
    # Mirrored from Python CBR proportions (embeddings.py):
    # Use Cases ≈ 35%  → UseCaseNames + UseCaseCount
    # Actors    ≈ 23%  → ActorNames + PrimaryActorCount + SecondaryActorCount
    # Domains   ≈ 18%  → PrimaryDomain + DomainList
    # Desc      ≈ 12%  → Description
    # Title     ≈  6%  → SystemName
    # Lexical   ≈  6%  → RelationshipTypes (lexical proxy)
    "SystemName":           0.5,
    "Description":          1.0,
    "PrimaryDomain":        1.5,
    "SystemKind":           0.5,
    "ActorNames":           2.0,
    "UseCaseNames":         3.5,
    "RelationshipTypes":    0.5,
    "DomainList":           1.5,
    "PrimaryActorCount":    1.5,
    "SecondaryActorCount":  1.5,
    "UseCaseCount":         3.5,
    "RelationshipCount":    0.5,
    "HasInclude":           0.5,
    "HasExtend":            0.5,
    "HasGeneralization":    0.5,
    "CaseOrigin":           0.2,
}

MYCBR_LABELS: Dict[str, str] = {
    "SystemName": "System Name",
    "Description": "Description",
    "PrimaryDomain": "Primary Domain",
    "SystemKind": "System Kind",
    "ActorNames": "Actor Names",
    "UseCaseNames": "Use Case Names",
    "RelationshipTypes": "Relationship Types",
    "DomainList": "Domain List",
    "PrimaryActorCount": "Primary Actor Count",
    "SecondaryActorCount": "Secondary Actor Count",
    "UseCaseCount": "Use Case Count",
    "RelationshipCount": "Relationship Count",
    "HasInclude": "Has Include",
    "HasExtend": "Has Extend",
    "HasGeneralization": "Has Generalization",
    "CaseOrigin": "Case Origin",
}

_THIN = Side(style="thin", color="BDBDBD")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


_HEADER_FILL = _fill("1565C0")
_HEADER_FILL_GREEN = _fill("2E7D32")
_SUB_FILL = _fill("E3F2FD")
_SUB_FILL_GREEN = _fill("E8F5E9")
_NOTE_FILL = _fill("FFF8E1")
_ALT_ROW_FILL = _fill("F5F9FF")
_COMMON_FILL = _fill("E8F5E9")
_TOTAL_FILL = _fill("FFF9C4")

_BOLD_WHITE = Font(bold=True, color="FFFFFF", size=11)
_BOLD_DARK = Font(bold=True, color="1A237E", size=10)
_NORMAL = Font(size=10)
_ITALIC = Font(italic=True, size=9, color="616161")


def _cell(
    ws,
    row: int,
    col: int,
    value: Any,
    *,
    font: Font | None = None,
    fill: PatternFill | None = None,
    align_h: str = "left",
    number_format: str | None = None,
    border: bool = True,
):
    cell = ws.cell(row=row, column=col, value=value)
    if font:
        cell.font = font
    if fill:
        cell.fill = fill
    if border:
        cell.border = _BORDER
    cell.alignment = Alignment(horizontal=align_h, vertical="center", wrap_text=True)
    if number_format:
        cell.number_format = number_format
    return cell


def _merge(
    ws,
    row: int,
    col_start: int,
    col_end: int,
    value: Any,
    *,
    font: Font | None = None,
    fill: PatternFill | None = None,
    align_h: str = "left",
):
    ws.merge_cells(
        start_row=row,
        start_column=col_start,
        end_row=row,
        end_column=col_end,
    )
    cell = ws.cell(row=row, column=col_start, value=value)
    if font:
        cell.font = font
    if fill:
        cell.fill = fill
    cell.alignment = Alignment(horizontal=align_h, vertical="center", wrap_text=True)
    cell.border = _BORDER
    return cell


def _normalise_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _yes_no(flag: Any) -> str:
    if isinstance(flag, bool):
        return "Yes" if flag else "No"
    text = str(flag or "").strip().lower()
    return "Yes" if text in {"yes", "true", "1"} else "No"


def _pipe_join(items: Sequence[str]) -> str:
    return " | ".join(str(item).strip() for item in items if str(item).strip())


def _build_mycbr_query_values(query: Mapping[str, Any]) -> Dict[str, Any]:
    system_name = str(query.get("system_name") or "").strip()
    domains = list(query.get("domains") or [])
    primary_actors = list(query.get("primary_actors") or [])
    secondary_actors = list(query.get("secondary_actors") or [])
    actors = list(query.get("actors") or []) or (primary_actors + secondary_actors)
    use_cases = list(query.get("use_cases") or [])
    relationships = list(query.get("relationships") or [])

    rel_types: List[str] = []
    for rel in relationships:
        if isinstance(rel, dict):
            rel_types.append(str(rel.get("relationship_type") or "").strip().lower())
        else:
            rel_types.append(str(rel).strip().lower())

    payload: Dict[str, Any] = {}
    if system_name:
        payload["SystemName"] = system_name
    if actors:
        payload["ActorNames"] = _pipe_join(actors)
    if use_cases:
        payload["UseCaseNames"] = _pipe_join(use_cases)
    if domains:
        payload["PrimaryDomain"] = str(domains[0])

    payload["PrimaryActorCount"] = float(len(actors))
    payload["UseCaseCount"] = float(len(use_cases))
    payload["RelationshipCount"] = float(len(relationships))
    payload["HasInclude"] = _yes_no("include" in rel_types)
    payload["HasExtend"] = _yes_no("extend" in rel_types)
    payload["HasGeneralization"] = _yes_no("generalization" in rel_types)
    return payload


def _case_lookup_tokens(case_payload: Mapping[str, Any]) -> List[str]:
    tokens: List[str] = []

    def _push(raw: Any) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        lowered = text.lower()
        if lowered not in tokens:
            tokens.append(lowered)
        match = re.search(r"(\d+)\s*$", text)
        if match:
            number_token = str(int(match.group(1)))
            label_token = f"ucd_{int(match.group(1)):04d}"
            if number_token not in tokens:
                tokens.append(number_token)
            if label_token not in tokens:
                tokens.append(label_token)

    _push(case_payload.get("case_id"))
    _push(case_payload.get("case_key"))
    _push(case_payload.get("title"))
    _push(case_payload.get("system_name"))
    return tokens


def _load_case_indexes() -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    if load_all_cases is None:
        return {}, {}
    try:
        cases = load_all_cases()
    except Exception:
        return {}, {}

    by_token: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        for token in _case_lookup_tokens(case):
            by_token.setdefault(token, case)
        title_key = _normalise_text(case.get("title") or case.get("system_name"))
        if title_key:
            by_title.setdefault(title_key, case)
    return by_token, by_title


def _resolve_match_case(
    match: Mapping[str, Any],
    by_token: Mapping[str, Dict[str, Any]],
    by_title: Mapping[str, Dict[str, Any]],
) -> Dict[str, Any] | None:
    probe = {
        "case_id": match.get("case_id"),
        "case_key": match.get("case_key"),
        "title": match.get("title"),
        "system_name": match.get("title"),
    }
    for token in _case_lookup_tokens(probe):
        if token in by_token:
            return by_token[token]
    title_key = _normalise_text(match.get("title"))
    if title_key and title_key in by_title:
        return by_title[title_key]
    return None


def _ngrams(text: Any, n: int = 3) -> Counter[str]:
    cleaned = _normalise_text(text)
    if not cleaned:
        return Counter()
    padded = f" {cleaned} "
    if len(padded) < n:
        return Counter({padded: 1})
    return Counter(padded[idx:idx + n] for idx in range(len(padded) - n + 1))


def _dice_similarity(left: Any, right: Any, n: int = 3) -> float:
    left_counts = _ngrams(left, n=n)
    right_counts = _ngrams(right, n=n)
    if not left_counts and not right_counts:
        return 1.0
    if not left_counts or not right_counts:
        return 0.0
    overlap = sum((left_counts & right_counts).values())
    total = sum(left_counts.values()) + sum(right_counts.values())
    return overlap * 2.0 / total if total else 0.0


def _jaro_winkler_similarity(left: Any, right: Any) -> float:
    s1 = str(left or "")
    s2 = str(right or "")
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1 = len(s1)
    len2 = len(s2)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    s1_m = [s1[i] for i in range(len1) if s1_matches[i]]
    s2_m = [s2[i] for i in range(len2) if s2_matches[i]]
    transpositions = sum(ch1 != ch2 for ch1, ch2 in zip(s1_m, s2_m)) / 2.0

    jaro = (
        (matches / len1)
        + (matches / len2)
        + ((matches - transpositions) / matches)
    ) / 3.0

    prefix = 0
    for ch1, ch2 in zip(s1, s2):
        if ch1 != ch2:
            break
        prefix += 1
        if prefix == 4:
            break

    return jaro + 0.1 * prefix * (1.0 - jaro)


def _count_similarity(query_value: Any, case_value: Any, exponent: float = 3.5, max_for_quotient: float = 10.0) -> float:
    try:
        left = float(query_value)
        right = float(case_value)
    except (TypeError, ValueError):
        return 0.0
    diff = abs(left - right)
    scaled = diff / max(max_for_quotient, 1e-9)
    return max(0.0, min(1.0, 1.0 / (1.0 + scaled ** exponent)))


def _mycbr_local_similarity(attr: str, query_value: Any, case_value: Any) -> float:
    if attr == "SystemName":
        return _dice_similarity(query_value, case_value, n=3)
    if attr == "Description":
        return _jaro_winkler_similarity(query_value, case_value)
    if attr in {"PrimaryActorCount", "SecondaryActorCount", "UseCaseCount", "RelationshipCount"}:
        return _count_similarity(query_value, case_value, exponent=3.5)
    return 1.0 if _normalise_text(query_value) == _normalise_text(case_value) else 0.0


def _write_triplet_headers(
    ws,
    *,
    group_row: int,
    header_row: int,
    start_col: int,
    labels: Sequence[str],
    fill: PatternFill,
):
    col = start_col
    for label in labels:
        _merge(ws, group_row, col, col + 2, label, font=_BOLD_DARK, fill=fill, align_h="center")
        _cell(ws, header_row, col, "Similarity", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
        _cell(ws, header_row, col + 1, "Weight", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
        _cell(ws, header_row, col + 2, "Product", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
        col += 3


def _write_python_sheet(
    ws,
    query: Dict[str, Any],
    py_matches: List[Dict[str, Any]],
    now_str: str,
    common_titles: set[str],
) -> None:
    categories = list(PY_CBR_WEIGHTS.keys())
    total_cols = 3 + len(categories) * 3 + 3

    _merge(
        ws,
        1,
        1,
        total_cols,
        "Python CBR - Similarity Score Report",
        font=Font(bold=True, color="FFFFFF", size=14),
        fill=_fill("0D47A1"),
        align_h="center",
    )
    _merge(ws, 2, 1, 4, f"Generated: {now_str}", font=_ITALIC)
    _merge(ws, 2, 5, total_cols, f"Query System: {query.get('system_name') or '-'}", font=_ITALIC)
    _merge(ws, 3, 1, 4, f"Actors: {', '.join(query.get('actors') or []) or '-'}", font=_ITALIC)
    _merge(ws, 3, 5, total_cols, f"Use Cases: {', '.join(query.get('use_cases') or []) or '-'}", font=_ITALIC)
    _merge(ws, 4, 1, 4, f"Domains: {', '.join(query.get('domains') or []) or '-'}", font=_ITALIC)
    _merge(ws, 4, 5, total_cols, "Overall score = sum(products) / sum(weights)", font=_ITALIC)
    ws.row_dimensions[1].height = 28

    group_row = 5
    header_row = 6
    _cell(ws, header_row, 1, "Rank", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
    _cell(ws, header_row, 2, "Case Title", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
    _cell(ws, header_row, 3, "Source", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
    _write_triplet_headers(
        ws,
        group_row=group_row,
        header_row=header_row,
        start_col=4,
        labels=[PY_CBR_LABELS[key] for key in categories],
        fill=_SUB_FILL,
    )

    tail_col = 4 + len(categories) * 3
    _cell(ws, header_row, tail_col, "Total Product", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
    _cell(ws, header_row, tail_col + 1, "Overall Score", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
    _cell(ws, header_row, tail_col + 2, "Common Match?", font=_BOLD_WHITE, fill=_HEADER_FILL, align_h="center")
    _merge(ws, group_row, tail_col, tail_col + 2, "Summary", font=_BOLD_DARK, fill=_SUB_FILL, align_h="center")
    ws.row_dimensions[header_row].height = 32

    _UC_SUB_FILL  = _fill("E3F2FD")   # light blue for UC sub-rows
    _ACT_SUB_FILL = _fill("E8F5E9")   # light green for actor sub-rows
    _SUB_FONT     = Font(italic=True, size=9)

    current_row = header_row + 1

    for rank, match in enumerate(py_matches, start=1):
        is_common = _normalise_text(match.get("title")) in common_titles
        row_fill = _COMMON_FILL if is_common else (_ALT_ROW_FILL if rank % 2 == 0 else None)

        _cell(ws, current_row, 1, rank, align_h="center", fill=row_fill)
        _cell(ws, current_row, 2, match.get("title", ""), fill=row_fill)
        _cell(ws, current_row, 3, match.get("source", "python_cbr"), fill=row_fill, align_h="center")

        col = 4
        total_product = 0.0
        for key in categories:
            score = float(match.get(key, 0.0) or 0.0)
            weight = float(PY_CBR_WEIGHTS[key])
            product = score * weight
            total_product += product

            _cell(ws, current_row, col, round(score, 6), number_format="0.000000", align_h="center", fill=row_fill)
            _cell(ws, current_row, col + 1, weight, number_format="0.00", align_h="center", fill=row_fill)
            _cell(ws, current_row, col + 2, round(product, 6), number_format="0.000000", align_h="center", fill=row_fill)
            col += 3

        _cell(ws, current_row, tail_col, round(total_product, 6), number_format="0.000000", align_h="center", fill=_TOTAL_FILL)
        _cell(
            ws,
            current_row,
            tail_col + 1,
            round(float(match.get("relevance", 0.0) or 0.0), 6),
            number_format="0.000000",
            align_h="center",
            fill=_TOTAL_FILL,
            font=Font(bold=True, size=10),
        )
        _cell(
            ws,
            current_row,
            tail_col + 2,
            "Yes" if is_common else "No",
            align_h="center",
            fill=_COMMON_FILL if is_common else row_fill,
        )
        current_row += 1

        # ── Use Case sub-rows (all cases) ──────────────────────────────────────
        uc_bd = match.get("uc_breakdown") or []
        if uc_bd:
            uc_field_idx  = categories.index("sim_usecases")
            uc_sim_col    = 4 + uc_field_idx * 3       # Similarity column
            uc_wt_col     = uc_sim_col + 1             # Weight column
            uc_prod_col   = uc_sim_col + 2             # Product column
            uc_field_wt   = float(PY_CBR_WEIGHTS.get("sim_usecases", 0.0))
            per_uc_wt     = uc_field_wt / len(uc_bd)  # equal share per query UC

            # section label
            ws.merge_cells(
                start_row=current_row, start_column=2,
                end_row=current_row, end_column=tail_col + 2,
            )
            _cell(ws, current_row, 2,
                  f"  ▸ Use Case Comparisons  (field weight {round(uc_field_wt,4)}, "
                  f"per-UC weight {round(per_uc_wt,4)})",
                  font=Font(italic=True, bold=True, size=9, color="1565C0"),
                  fill=_UC_SUB_FILL, align_h="left")
            ws.row_dimensions[current_row].outline_level = 1
            ws.row_dimensions[current_row].height = 14
            current_row += 1

            for item in uc_bd:
                sim  = round(float(item.get("score", 0.0)), 6)
                prod = round(sim * per_uc_wt, 6)
                # left side: query → best_match (cols 2-4)
                _cell(ws, current_row, 2, item.get("query", ""),
                      fill=_UC_SUB_FILL, font=_SUB_FONT)
                _cell(ws, current_row, 3, "→",
                      fill=_UC_SUB_FILL, font=_SUB_FONT, align_h="center")
                _cell(ws, current_row, 4, item.get("best_match", ""),
                      fill=_UC_SUB_FILL, font=_SUB_FONT)
                # fill blank up to the UC column group
                for ec in range(5, uc_sim_col):
                    _cell(ws, current_row, ec, "", fill=_UC_SUB_FILL)
                # sim / weight / product in aligned columns
                _cell(ws, current_row, uc_sim_col,  sim,
                      number_format="0.000000", align_h="center",
                      fill=_UC_SUB_FILL, font=_SUB_FONT)
                _cell(ws, current_row, uc_wt_col,   round(per_uc_wt, 4),
                      number_format="0.0000", align_h="center",
                      fill=_UC_SUB_FILL, font=_SUB_FONT)
                _cell(ws, current_row, uc_prod_col, prod,
                      number_format="0.000000", align_h="center",
                      fill=_UC_SUB_FILL, font=_SUB_FONT)
                # fill remainder
                for ec in range(uc_prod_col + 1, tail_col + 3):
                    _cell(ws, current_row, ec, "", fill=_UC_SUB_FILL)
                ws.row_dimensions[current_row].outline_level = 1
                ws.row_dimensions[current_row].height = 14
                current_row += 1

        # ── Actor sub-rows (all cases) ─────────────────────────────────────────
        actor_bd = match.get("actor_breakdown") or []
        if actor_bd:
            act_field_idx = categories.index("sim_actors")
            act_sim_col   = 4 + act_field_idx * 3
            act_wt_col    = act_sim_col + 1
            act_prod_col  = act_sim_col + 2
            act_field_wt  = float(PY_CBR_WEIGHTS.get("sim_actors", 0.0))
            per_act_wt    = act_field_wt / len(actor_bd)

            ws.merge_cells(
                start_row=current_row, start_column=2,
                end_row=current_row, end_column=tail_col + 2,
            )
            _cell(ws, current_row, 2,
                  f"  ▸ Actor Comparisons  (field weight {round(act_field_wt,4)}, "
                  f"per-actor weight {round(per_act_wt,4)})",
                  font=Font(italic=True, bold=True, size=9, color="2E7D32"),
                  fill=_ACT_SUB_FILL, align_h="left")
            ws.row_dimensions[current_row].outline_level = 1
            ws.row_dimensions[current_row].height = 14
            current_row += 1

            for item in actor_bd:
                sim  = round(float(item.get("score", 0.0)), 6)
                prod = round(sim * per_act_wt, 6)
                _cell(ws, current_row, 2, item.get("query", ""),
                      fill=_ACT_SUB_FILL, font=_SUB_FONT)
                _cell(ws, current_row, 3, "→",
                      fill=_ACT_SUB_FILL, font=_SUB_FONT, align_h="center")
                _cell(ws, current_row, 4, item.get("best_match", ""),
                      fill=_ACT_SUB_FILL, font=_SUB_FONT)
                for ec in range(5, act_sim_col):
                    _cell(ws, current_row, ec, "", fill=_ACT_SUB_FILL)
                _cell(ws, current_row, act_sim_col,  sim,
                      number_format="0.000000", align_h="center",
                      fill=_ACT_SUB_FILL, font=_SUB_FONT)
                _cell(ws, current_row, act_wt_col,   round(per_act_wt, 4),
                      number_format="0.0000", align_h="center",
                      fill=_ACT_SUB_FILL, font=_SUB_FONT)
                _cell(ws, current_row, act_prod_col, prod,
                      number_format="0.000000", align_h="center",
                      fill=_ACT_SUB_FILL, font=_SUB_FONT)
                for ec in range(act_prod_col + 1, tail_col + 3):
                    _cell(ws, current_row, ec, "", fill=_ACT_SUB_FILL)
                ws.row_dimensions[current_row].outline_level = 1
                ws.row_dimensions[current_row].height = 14
                current_row += 1


    ws.freeze_panes = "A7"
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 14
    for col_idx in range(4, tail_col):
        remainder = (col_idx - 4) % 3
        ws.column_dimensions[get_column_letter(col_idx)].width = 14 if remainder != 1 else 10
    ws.column_dimensions[get_column_letter(tail_col)].width = 14
    ws.column_dimensions[get_column_letter(tail_col + 1)].width = 14
    ws.column_dimensions[get_column_letter(tail_col + 2)].width = 14



def _prepare_mycbr_breakdowns(
    query: Dict[str, Any],
    my_matches: List[Dict[str, Any]],
) -> tuple[List[str], List[Dict[str, Any]], str]:
    query_values = _build_mycbr_query_values(query)
    active_attrs = [attr for attr in MYCBR_WEIGHTS if attr in query_values]
    total_weight = sum(MYCBR_WEIGHTS[attr] for attr in active_attrs)

    by_token, by_title = _load_case_indexes()
    rows: List[Dict[str, Any]] = []
    unresolved = 0

    for match in my_matches:
        local_scores: Dict[str, float | None] = {}
        case_payload = _resolve_match_case(match, by_token, by_title)
        if case_payload is None or _mycbr_case_features is None:
            unresolved += 1
            for attr in active_attrs:
                local_scores[attr] = None
            derived_overall = None
            total_product = None
        else:
            case_values = _mycbr_case_features(case_payload)
            total_product_value = 0.0
            for attr in active_attrs:
                score = _mycbr_local_similarity(attr, query_values.get(attr), case_values.get(attr))
                local_scores[attr] = score
                total_product_value += score * MYCBR_WEIGHTS[attr]
            total_product = total_product_value
            derived_overall = total_product_value / total_weight if total_weight else None

        rows.append(
            {
                "match": match,
                "local_scores": local_scores,
                "total_product": total_product,
                "derived_overall": derived_overall,
            }
        )

    note = (
        "Local myCBR columns are derived from the active REST query attributes. "
        "The REST endpoint itself only returns the final overall similarity."
    )
    if unresolved:
        note += f" Case details could not be resolved for {unresolved} match(es), so those local cells are marked N/A."
    return active_attrs, rows, note


def _write_mycbr_sheet(
    ws,
    query: Dict[str, Any],
    my_matches: List[Dict[str, Any]],
    now_str: str,
    common_titles: set[str],
) -> None:
    active_attrs, breakdown_rows, note = _prepare_mycbr_breakdowns(query, my_matches)
    total_cols = 4 + len(active_attrs) * 3 + 4

    _merge(
        ws,
        1,
        1,
        total_cols,
        "myCBR Engine - Similarity Score Report",
        font=Font(bold=True, color="FFFFFF", size=14),
        fill=_fill("1B5E20"),
        align_h="center",
    )
    _merge(ws, 2, 1, 4, f"Generated: {now_str}", font=_ITALIC)
    _merge(ws, 2, 5, total_cols, f"Query System: {query.get('system_name') or '-'}", font=_ITALIC)
    _merge(ws, 3, 1, 4, f"Actors: {', '.join(query.get('actors') or []) or '-'}", font=_ITALIC)
    _merge(ws, 3, 5, total_cols, f"Use Cases: {', '.join(query.get('use_cases') or []) or '-'}", font=_ITALIC)
    _merge(ws, 4, 1, 4, f"Domains: {', '.join(query.get('domains') or []) or '-'}", font=_ITALIC)
    _merge(ws, 4, 5, total_cols, "Derived overall = sum(products) / sum(active weights)", font=_ITALIC)
    _merge(ws, 5, 1, total_cols, note, font=Font(italic=True, size=9, color="795548"), fill=_NOTE_FILL)
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[5].height = 34

    group_row = 6
    header_row = 7
    _cell(ws, header_row, 1, "Rank", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    _cell(ws, header_row, 2, "Case ID", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    _cell(ws, header_row, 3, "Case Title", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    _cell(ws, header_row, 4, "Source", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")

    col = 5
    for label in [MYCBR_LABELS[attr] for attr in active_attrs]:
        _merge(ws, group_row, col, col + 2, label, font=_BOLD_DARK, fill=_SUB_FILL_GREEN, align_h="center")
        _cell(ws, header_row, col, "Similarity", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
        _cell(ws, header_row, col + 1, "Weight", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
        _cell(ws, header_row, col + 2, "Product", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
        col += 3

    tail_col = col
    _merge(ws, group_row, tail_col, tail_col + 3, "Summary", font=_BOLD_DARK, fill=_SUB_FILL_GREEN, align_h="center")
    _cell(ws, header_row, tail_col, "Total Product", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    _cell(ws, header_row, tail_col + 1, "Derived Overall", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    _cell(ws, header_row, tail_col + 2, "REST Overall", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    _cell(ws, header_row, tail_col + 3, "Common Match?", font=_BOLD_WHITE, fill=_HEADER_FILL_GREEN, align_h="center")
    ws.row_dimensions[header_row].height = 32

    for rank, entry in enumerate(breakdown_rows, start=1):
        match = entry["match"]
        row = header_row + rank
        is_common = _normalise_text(match.get("title")) in common_titles
        row_fill = _COMMON_FILL if is_common else (_ALT_ROW_FILL if rank % 2 == 0 else None)

        _cell(ws, row, 1, rank, align_h="center", fill=row_fill)
        _cell(ws, row, 2, str(match.get("case_id", "")), align_h="center", fill=row_fill)
        _cell(ws, row, 3, match.get("title", ""), fill=row_fill)
        _cell(ws, row, 4, match.get("source", "mycbr"), align_h="center", fill=row_fill)

        col = 5
        for attr in active_attrs:
            score = entry["local_scores"].get(attr)
            weight = MYCBR_WEIGHTS[attr]
            product = None if score is None else score * weight

            if score is None:
                _cell(ws, row, col, "N/A", align_h="center", fill=row_fill)
                _cell(ws, row, col + 1, weight, number_format="0.00", align_h="center", fill=row_fill)
                _cell(ws, row, col + 2, "N/A", align_h="center", fill=row_fill)
            else:
                _cell(ws, row, col, round(score, 6), number_format="0.000000", align_h="center", fill=row_fill)
                _cell(ws, row, col + 1, weight, number_format="0.00", align_h="center", fill=row_fill)
                _cell(ws, row, col + 2, round(product or 0.0, 6), number_format="0.000000", align_h="center", fill=row_fill)
            col += 3

        total_product = entry["total_product"]
        derived_overall = entry["derived_overall"]

        if total_product is None:
            _cell(ws, row, tail_col, "N/A", align_h="center", fill=_TOTAL_FILL)
            _cell(ws, row, tail_col + 1, "N/A", align_h="center", fill=_TOTAL_FILL)
        else:
            _cell(ws, row, tail_col, round(total_product, 6), number_format="0.000000", align_h="center", fill=_TOTAL_FILL)
            _cell(
                ws,
                row,
                tail_col + 1,
                round(derived_overall or 0.0, 6),
                number_format="0.000000",
                align_h="center",
                fill=_TOTAL_FILL,
            )

        _cell(
            ws,
            row,
            tail_col + 2,
            round(float(match.get("relevance", 0.0) or 0.0), 6),
            number_format="0.000000",
            align_h="center",
            fill=_TOTAL_FILL,
            font=Font(bold=True, size=10),
        )
        _cell(
            ws,
            row,
            tail_col + 3,
            "Yes" if is_common else "No",
            align_h="center",
            fill=_COMMON_FILL if is_common else row_fill,
        )

    ws.freeze_panes = "A8"
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 12
    for col_idx in range(5, tail_col):
        remainder = (col_idx - 5) % 3
        ws.column_dimensions[get_column_letter(col_idx)].width = 14 if remainder != 1 else 10
    ws.column_dimensions[get_column_letter(tail_col)].width = 14
    ws.column_dimensions[get_column_letter(tail_col + 1)].width = 14
    ws.column_dimensions[get_column_letter(tail_col + 2)].width = 14
    ws.column_dimensions[get_column_letter(tail_col + 3)].width = 14


def _write_detail_sheet(
    ws,
    query: Dict[str, Any],
    py_matches: List[Dict[str, Any]],
    now_str: str,
) -> None:
    """Sheet 3 – Similarity Details (full breakdown per matched case).

    7 columns:
      Case Title | Field | Query Value | Best Case Match | Similarity | Weight | Product

    Each case has three blocks:
      1. CBR Field Summary  – all 6 fields with sim / weight / product
      2. Use Case Pairs     – per-query-UC best-match + individual cosine
      3. Actor Pairs        – per-query-actor best-match + individual cosine
    """
    # ── fills ──────────────────────────────────────────────────────────────
    _HDR_FILL     = _fill("0D47A1")   # title bar
    _COL_FILL     = _fill("37474F")   # column header row
    _CASE_FILL    = _fill("1565C0")   # case title banner
    _SUM_FILL     = _fill("E8EAF6")   # field summary rows
    _UC_FILL      = _fill("E3F2FD")   # UC pair rows
    _ACT_FILL     = _fill("E8F5E9")   # Actor pair rows
    _AVG_FILL     = _fill("FFF9C4")   # average / total rows
    _SECT_FILL    = _fill("ECEFF1")   # section sub-header

    BW   = Font(bold=True, color="FFFFFF", size=11)
    BWS  = Font(bold=True, color="FFFFFF", size=10)
    BD   = Font(bold=True, color="1A237E", size=10)
    BW2  = Font(bold=True, color="FFFFFF", size=10)
    IT   = Font(italic=True, size=9, color="616161")
    NRM  = Font(size=10)

    NCOLS = 7
    COL_WIDTHS = [28, 18, 30, 30, 14, 10, 14]
    COL_HDRS   = ["Case Title", "CBR Field", "Query Value",
                  "Best Case Match", "Similarity", "Weight", "Product"]

    # ── report title ────────────────────────────────────────────────────────
    _merge(ws, 1, 1, NCOLS,
           "Python CBR – Similarity Details (Full Breakdown)",
           font=BW, fill=_HDR_FILL, align_h="center")
    _merge(ws, 2, 1, 3, f"Generated: {now_str}", font=IT)
    _merge(ws, 2, 4, NCOLS,
           f"Query System: {query.get('system_name') or '-'}", font=IT)
    ws.row_dimensions[1].height = 28

    # ── column header row (row 3) ────────────────────────────────────────
    for ci, (hdr, w) in enumerate(zip(COL_HDRS, COL_WIDTHS), start=1):
        _cell(ws, 3, ci, hdr, font=BWS, fill=_COL_FILL, align_h="center")
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[3].height = 22
    ws.freeze_panes = "A4"

    # ── ordered fields (must match PY_CBR_WEIGHTS key order) ────────────────
    FIELD_META = [
        ("sim_title",    "System Name",    query.get("system_name") or "-"),
        ("sim_desc",     "Description",    (query.get("description") or "-")[:60]),
        ("sim_domains",  "Domains",        ", ".join(query.get("domains") or []) or "-"),
        ("sim_actors",   "Actors (avg)",   ", ".join(query.get("actors") or []) or "-"),
        ("sim_usecases", "Use Cases (avg)",", ".join(query.get("use_cases") or []) or "-"),
        ("sim_lexical",  "Lexical",        "-"),
    ]

    current_row = 4

    for rank, match in enumerate(py_matches, start=1):
        title    = match.get("title", "") or ""
        uc_bd    = match.get("uc_breakdown")    or []
        actor_bd = match.get("actor_breakdown") or []

        # ── case title banner ─────────────────────────────────────────────
        _merge(ws, current_row, 1, NCOLS,
               f"#{rank}  {title}",
               font=Font(bold=True, color="FFFFFF", size=11),
               fill=_CASE_FILL, align_h="left")
        ws.row_dimensions[current_row].height = 20
        current_row += 1

        # ── Block 1: CBR Field Summary ───────────────────────────────────
        _merge(ws, current_row, 1, NCOLS,
               "CBR Field Summary",
               font=BD, fill=_SECT_FILL, align_h="left")
        current_row += 1

        total_product = 0.0
        for key, label, qval in FIELD_META:
            sim    = float(match.get(key, 0.0) or 0.0)
            weight = float(PY_CBR_WEIGHTS.get(key, 0.0))
            prod   = sim * weight
            total_product += prod
            _cell(ws, current_row, 1, title,              fill=_SUM_FILL)
            _cell(ws, current_row, 2, label,              fill=_SUM_FILL, font=Font(bold=True, size=10))
            _cell(ws, current_row, 3, qval,               fill=_SUM_FILL)
            _cell(ws, current_row, 4, "-",                fill=_SUM_FILL, align_h="center")
            _cell(ws, current_row, 5, round(sim, 6),      fill=_SUM_FILL,
                  number_format="0.000000", align_h="center")
            _cell(ws, current_row, 6, round(weight, 4),   fill=_SUM_FILL,
                  number_format="0.0000",   align_h="center")
            _cell(ws, current_row, 7, round(prod, 6),     fill=_SUM_FILL,
                  number_format="0.000000", align_h="center")
            current_row += 1

        # total / overall row
        relevance = float(match.get("relevance", 0.0) or 0.0)
        _cell(ws, current_row, 1, "", fill=_AVG_FILL)
        _cell(ws, current_row, 2, "", fill=_AVG_FILL)
        _cell(ws, current_row, 3, "", fill=_AVG_FILL)
        _cell(ws, current_row, 4, "Overall Score",
              font=Font(bold=True, size=10), fill=_AVG_FILL)
        _cell(ws, current_row, 5, round(relevance, 6),
              number_format="0.000000", align_h="center",
              fill=_AVG_FILL, font=Font(bold=True, size=10))
        _cell(ws, current_row, 6, round(sum(PY_CBR_WEIGHTS.values()), 4),
              number_format="0.0000", align_h="center", fill=_AVG_FILL)
        _cell(ws, current_row, 7, round(total_product, 6),
              number_format="0.000000", align_h="center",
              fill=_AVG_FILL, font=Font(bold=True, size=10))
        current_row += 1

        # ── Block 2: Use Case Pairs ──────────────────────────────────────
        _merge(ws, current_row, 1, NCOLS,
               "Use Case Comparisons (Query UC → Best Case UC)",
               font=BD, fill=_SECT_FILL, align_h="left")
        current_row += 1

        if uc_bd:
            for item in uc_bd:
                s = round(float(item.get("score", 0.0)), 6)
                _cell(ws, current_row, 1, title,                      fill=_UC_FILL)
                _cell(ws, current_row, 2, "Use Case",                 fill=_UC_FILL, align_h="center")
                _cell(ws, current_row, 3, item.get("query", ""),      fill=_UC_FILL)
                _cell(ws, current_row, 4, item.get("best_match", ""), fill=_UC_FILL)
                _cell(ws, current_row, 5, s, number_format="0.000000",
                      align_h="center", fill=_UC_FILL)
                _cell(ws, current_row, 6, "-", align_h="center",      fill=_UC_FILL)
                _cell(ws, current_row, 7, "-", align_h="center",      fill=_UC_FILL)
                current_row += 1
            # avg row
            sim_uc = float(match.get("sim_usecases", 0.0) or 0.0)
            for col, val in [(1,""), (2,""), (3,""),
                             (4,"Avg UC Similarity"),
                             (5, round(sim_uc, 6)), (6,""), (7,"")]:
                kw = {"fill": _AVG_FILL, "font": Font(bold=True, size=10)}
                if isinstance(val, float):
                    _cell(ws, current_row, col, val,
                          number_format="0.000000", align_h="center", **kw)
                else:
                    _cell(ws, current_row, col, val, **kw)
            current_row += 1
        else:
            _merge(ws, current_row, 1, NCOLS,
                   "No use cases in query or case.",
                   font=IT, fill=_UC_FILL, align_h="center")
            current_row += 1

        # ── Block 3: Actor Pairs ─────────────────────────────────────────
        _merge(ws, current_row, 1, NCOLS,
               "Actor Comparisons (Query Actor → Best Case Actor)",
               font=BD, fill=_SECT_FILL, align_h="left")
        current_row += 1

        if actor_bd:
            for item in actor_bd:
                s = round(float(item.get("score", 0.0)), 6)
                _cell(ws, current_row, 1, title,                      fill=_ACT_FILL)
                _cell(ws, current_row, 2, "Actor",                    fill=_ACT_FILL, align_h="center")
                _cell(ws, current_row, 3, item.get("query", ""),      fill=_ACT_FILL)
                _cell(ws, current_row, 4, item.get("best_match", ""), fill=_ACT_FILL)
                _cell(ws, current_row, 5, s, number_format="0.000000",
                      align_h="center", fill=_ACT_FILL)
                _cell(ws, current_row, 6, "-", align_h="center",      fill=_ACT_FILL)
                _cell(ws, current_row, 7, "-", align_h="center",      fill=_ACT_FILL)
                current_row += 1
            # avg row
            sim_act = float(match.get("sim_actors", 0.0) or 0.0)
            for col, val in [(1,""), (2,""), (3,""),
                             (4,"Avg Actor Similarity"),
                             (5, round(sim_act, 6)), (6,""), (7,"")]:
                kw = {"fill": _AVG_FILL, "font": Font(bold=True, size=10)}
                if isinstance(val, float):
                    _cell(ws, current_row, col, val,
                          number_format="0.000000", align_h="center", **kw)
                else:
                    _cell(ws, current_row, col, val, **kw)
            current_row += 1
        else:
            _merge(ws, current_row, 1, NCOLS,
                   "No actors in query or case.",
                   font=IT, fill=_ACT_FILL, align_h="center")
            current_row += 1

        # spacer row between cases
        current_row += 1




def _write_weight_comparison_sheet(
    ws,
    py_matches: List[Dict[str, Any]],
    now_str: str,
) -> None:
    """Weight Comparison Sheet — side-by-side score comparison.

    Shows each Python CBR case scored under:
      1. Current domain-driven weights (CBR_WEIGHTS)
      2. Genetic Algorithm optimized weights (GA_WEIGHTS)

    Columns: Rank | Case | Current Score | GA Score | Δ Score | Winner
    """
    _HDR     = _fill("4A148C")          # deep purple header
    _COL_HDR = _fill("6A1B9A")          # column sub-headers
    _CUR_BG  = _fill("E8EAF6")          # current weights column bg
    _GA_BG   = _fill("F3E5F5")          # GA weights column bg
    _WIN_CUR = _fill("C8E6C9")          # green highlight - current wins
    _WIN_GA  = _fill("FFCCBC")          # orange highlight - GA wins
    _DRAW    = _fill("FFF9C4")          # yellow - same

    BW   = Font(bold=True, color="FFFFFF", size=13)
    BWS  = Font(bold=True, color="FFFFFF", size=10)
    BD   = Font(bold=True, color="1A237E", size=10)
    IT   = Font(italic=True, size=9, color="616161")
    BOLD = Font(bold=True, size=10)

    categories = list(PY_CBR_WEIGHTS.keys())
    denom = max(sum(PY_CBR_WEIGHTS.values()), 1e-9)
    ga_denom = max(sum(GA_WEIGHTS.values()), 1e-9)

    # ── title banner
    _merge(ws, 1, 1, 8,
           "Weight Comparison — Current vs. Genetic Algorithm Weights",
           font=BW, fill=_HDR, align_h="center")
    _merge(ws, 2, 1, 4, f"Generated: {now_str}", font=IT)
    _merge(ws, 2, 5, 8,
           "Scores are re-computed here; Current weights = domain-driven (embeddings.py); GA weights from simulation.",
           font=IT)
    ws.row_dimensions[1].height = 28

    # ── weight table (row 3-4)
    _cell(ws, 3, 1, "Feature", font=BWS, fill=_COL_HDR, align_h="center")
    _cell(ws, 3, 2, "Current Weight", font=BWS, fill=_COL_HDR, align_h="center")
    _cell(ws, 3, 3, "Current %", font=BWS, fill=_COL_HDR, align_h="center")
    _cell(ws, 3, 4, "GA Weight", font=BWS, fill=_COL_HDR, align_h="center")
    _cell(ws, 3, 5, "GA %", font=BWS, fill=_COL_HDR, align_h="center")
    for c in range(6, 9):
        _cell(ws, 3, c, "", fill=_COL_HDR)

    label_map = PY_CBR_LABELS
    for fi, key in enumerate(categories, start=4):
        cw = PY_CBR_WEIGHTS[key]
        gw = GA_WEIGHTS[key]
        _cell(ws, fi, 1, label_map.get(key, key), font=BD, fill=_CUR_BG)
        _cell(ws, fi, 2, round(cw, 4), number_format="0.0000", align_h="center", fill=_CUR_BG)
        _cell(ws, fi, 3, f"{cw/denom*100:.1f}%", align_h="center", fill=_CUR_BG)
        _cell(ws, fi, 4, round(gw, 4), number_format="0.0000", align_h="center", fill=_GA_BG)
        _cell(ws, fi, 5, f"{gw/ga_denom*100:.1f}%", align_h="center", fill=_GA_BG)

    next_section = 4 + len(categories) + 1  # gap row, then score table

    # ── column headers for score table
    score_row = next_section + 1
    headers = ["Rank", "Case Title", "Current Score", "GA Score", "Δ (GA − Current)", "Winner", "Source", "Common Match"]
    col_widths = [6, 34, 15, 15, 18, 14, 14, 14]
    for ci, (hdr, cw) in enumerate(zip(headers, col_widths), start=1):
        _cell(ws, score_row, ci, hdr, font=BWS, fill=_COL_HDR, align_h="center")
        ws.column_dimensions[get_column_letter(ci)].width = cw
    ws.row_dimensions[score_row].height = 22
    ws.freeze_panes = f"A{score_row + 1}"

    # determine common titles across all matches (for the Common column)
    all_titles = {m.get("title", "").strip().lower() for m in py_matches}

    current_row = score_row + 1
    for rank, match in enumerate(py_matches, start=1):
        feats = {k: min(max(float(match.get(k, 0.0) or 0.0), 0.0), 1.0) for k in categories}

        cur_raw = sum(feats[k] * PY_CBR_WEIGHTS[k] for k in categories)
        cur_score = cur_raw / denom

        ga_raw = sum(feats[k] * GA_WEIGHTS[k] for k in categories)
        ga_score = ga_raw / ga_denom

        delta = ga_score - cur_score

        if abs(delta) < 0.0001:
            winner = "Draw"
            row_fill = _DRAW
        elif delta > 0:
            winner = "GA Weights"
            row_fill = _WIN_GA
        else:
            winner = "Current Weights"
            row_fill = _WIN_CUR

        _cell(ws, current_row, 1, rank, align_h="center", fill=row_fill)
        _cell(ws, current_row, 2, match.get("title", ""), fill=row_fill)
        _cell(ws, current_row, 3, round(cur_score, 6), number_format="0.000000",
              align_h="center", fill=_CUR_BG, font=BOLD)
        _cell(ws, current_row, 4, round(ga_score, 6), number_format="0.000000",
              align_h="center", fill=_GA_BG, font=BOLD)
        _cell(ws, current_row, 5, round(delta, 6), number_format="+0.000000;-0.000000",
              align_h="center", fill=row_fill)
        _cell(ws, current_row, 6, winner, align_h="center", fill=row_fill,
              font=Font(bold=True, size=10,
                        color="1B5E20" if winner == "Current Weights" else
                             ("BF360C" if winner == "GA Weights" else "5D4037")))
        _cell(ws, current_row, 7, match.get("source", "python_cbr"), align_h="center", fill=row_fill)
        _cell(ws, current_row, 8, "Yes" if match.get("title", "").strip().lower() in all_titles else "No",
              align_h="center", fill=row_fill)
        current_row += 1


def _write_uc_relevance_sheet(
    ws,
    query: Dict[str, Any],
    now_str: str,
) -> None:
    """Sheet 4 – UC Relevance Ranking.

    Lists every use case from every case in the database, scored by
    how similar it is to the query use cases, sorted descending.
    Columns: Rank | Case Title | Use Case | Best Matching Query UC | Similarity
    """
    _HDR_FILL  = _fill("0D47A1")
    _COL_FILL  = _fill("37474F")
    _HIGH_FILL = _fill("E8F5E9")   # green  >= 0.7
    _MID_FILL  = _fill("FFF9C4")   # yellow >= 0.5
    _LOW_FILL  = _fill("FFEBEE")   # red    <  0.5
    IT  = Font(italic=True, size=9, color="616161")
    BWS = Font(bold=True, color="FFFFFF", size=10)
    BW  = Font(bold=True, color="FFFFFF", size=14)

    NCOLS = 5
    _merge(ws, 1, 1, NCOLS,
           "Use Case Relevance Ranking (All Cases in Database)",
           font=BW, fill=_HDR_FILL, align_h="center")
    _merge(ws, 2, 1, 2, f"Generated: {now_str}", font=IT)
    _merge(ws, 2, 3, NCOLS,
           f"Query UCs: {', '.join(query.get('use_cases') or []) or '-'}", font=IT)
    ws.row_dimensions[1].height = 28

    col_hdrs   = ["Rank", "Case Title", "Use Case", "Best Matching Query UC", "Similarity"]
    col_widths = [6, 30, 36, 36, 14]
    for ci, (hdr, w) in enumerate(zip(col_hdrs, col_widths), start=1):
        _cell(ws, 3, ci, hdr, font=BWS, fill=_COL_FILL, align_h="center")
        ws.column_dimensions[get_column_letter(ci)].width = w
    ws.row_dimensions[3].height = 22
    ws.freeze_panes = "A4"

    if _find_all_uc_similarities is None:
        _merge(ws, 4, 1, NCOLS,
               "cbr_search module not available – cannot compute UC similarities.",
               font=IT, align_h="center")
        return

    rows = _find_all_uc_similarities(query)
    if not rows:
        _merge(ws, 4, 1, NCOLS,
               "No query use cases provided or no cases in database.",
               font=IT, align_h="center")
        return

    for rank, row in enumerate(rows, start=1):
        sim  = float(row.get("similarity", 0.0))
        fill = _HIGH_FILL if sim >= 0.7 else (_MID_FILL if sim >= 0.5 else _LOW_FILL)
        r = rank + 3
        _cell(ws, r, 1, rank,                           fill=fill, align_h="center")
        _cell(ws, r, 2, row.get("case_title", ""),      fill=fill)
        _cell(ws, r, 3, row.get("uc_name", ""),         fill=fill)
        _cell(ws, r, 4, row.get("best_query_uc", ""),   fill=fill)
        _cell(ws, r, 5, round(sim, 6),
              number_format="0.000000", align_h="center",
              fill=fill,
              font=Font(bold=True, size=10) if sim >= 0.7 else None)


def build_excel_report(
    query: Dict[str, Any],
    py_matches: List[Dict[str, Any]],
    my_matches: List[Dict[str, Any]],
) -> bytes:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    py_titles = {
        _normalise_text(match.get("title"))
        for match in py_matches
        if match.get("title")
    }
    my_titles = {
        _normalise_text(match.get("title"))
        for match in my_matches
        if match.get("title")
    }
    common_titles = py_titles & my_titles

    workbook = openpyxl.Workbook()

    ws_python = workbook.active
    ws_python.title = "Python CBR"
    _write_python_sheet(ws_python, query, py_matches, now_str, common_titles)

    ws_mycbr = workbook.create_sheet("myCBR Engine")
    _write_mycbr_sheet(ws_mycbr, query, my_matches, now_str, common_titles)

    ws_detail = workbook.create_sheet("Similarity Details")
    _write_detail_sheet(ws_detail, query, py_matches, now_str)

    ws_wc = workbook.create_sheet("Weight Comparison")
    _write_weight_comparison_sheet(ws_wc, py_matches, now_str)

    ws_uc = workbook.create_sheet("UC Relevance")
    _write_uc_relevance_sheet(ws_uc, query, now_str)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
