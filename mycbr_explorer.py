"""
Standalone Streamlit page for exploring the project's myCBR-style retrieval logic.

Run with:
    streamlit run mycbr_explorer.py
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from cbr_merge import fetch_case_data
from cbr_search import find_similar_cases
from connection import connection
from embeddings import CBR_WEIGHTS, IR_WEIGHTS


FEATURE_LABELS = {
    "sim_title": "System Name Similarity",
    "sim_desc": "Description Similarity",
    "sim_domains": "Domain Overlap",
    "sim_actors": "Actor Similarity",
    "sim_usecases": "Use-Case Similarity",
    "sim_lexical": "Lexical Overlap",
}


def _split_items(text: str) -> List[str]:
    if not text:
        return []
    items: List[str] = []
    seen: set[str] = set()
    for raw_line in text.replace(",", "\n").splitlines():
        item = raw_line.strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            items.append(item)
    return items


@st.cache_data(show_spinner=False)
def _fetch_case_catalog() -> List[Dict[str, Any]]:
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute(
            """
            SELECT case_id, title, description, domain_json
            FROM cases
            ORDER BY case_id DESC
            """
        )
        rows = cursor.fetchall() or []
    return rows


@st.cache_data(show_spinner=False)
def _fetch_case_text(case_id: int) -> Dict[str, Any]:
    with connection.get_cursor(dictionary=True) as cursor:
        cursor.execute(
            """
            SELECT case_id, title, description, domain_json
            FROM cases
            WHERE case_id=%s
            """,
            (case_id,),
        )
        row = cursor.fetchone() or {}

    try:
        domains = [d for d in json.loads(row.get("domain_json") or "[]") if d]
    except Exception:
        domains = []

    return {
        "case_id": row.get("case_id"),
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "domains": domains,
    }


def _weights_for_mode(mode: str) -> Dict[str, float]:
    return CBR_WEIGHTS if mode.upper() == "CBR" else IR_WEIGHTS


def _score_breakdown(match: Dict[str, Any], weights: Dict[str, float]) -> pd.DataFrame:
    denom = max(sum(weights.values()), 1e-9)
    rows = []
    for feature, weight in weights.items():
        local = float(match.get(feature, 0.0) or 0.0)
        raw = local * weight
        rows.append(
            {
                "Feature": FEATURE_LABELS.get(feature, feature),
                "Local Similarity": round(local, 4),
                "Weight": round(weight, 4),
                "Weighted Contribution": round(raw / denom, 4),
            }
        )
    return pd.DataFrame(rows)


def _case_option_label(row: Dict[str, Any]) -> str:
    title = (row.get("title") or "").strip() or "Untitled"
    return f"{row.get('case_id')} - {title}"


def _load_case_into_query(case_id: int) -> None:
    text_meta = _fetch_case_text(case_id)
    case_meta = fetch_case_data(case_id)

    st.session_state["mycbr_system_name"] = case_meta.get("system_name") or text_meta.get("title") or ""
    st.session_state["mycbr_description"] = text_meta.get("description") or ""
    st.session_state["mycbr_domains"] = "\n".join(text_meta.get("domains") or [])

    primary = [name for name, actor_type in (case_meta.get("actors") or []) if str(actor_type).lower().startswith("primary")]
    secondary = [name for name, actor_type in (case_meta.get("actors") or []) if str(actor_type).lower().startswith("secondary")]
    st.session_state["mycbr_actors"] = "\n".join(primary + secondary)
    st.session_state["mycbr_use_cases"] = "\n".join(case_meta.get("use_cases") or [])


def _render_match(match: Dict[str, Any], mode: str) -> None:
    weights = _weights_for_mode(mode)
    case_id = int(match["case_id"])
    case_meta = fetch_case_data(case_id)
    text_meta = _fetch_case_text(case_id)
    breakdown = _score_breakdown(match, weights)

    with st.container(border=True):
        st.subheader(f"{match.get('title') or case_meta.get('system_name') or 'Case'}")
        st.caption(f"Case ID: {case_id}")

        col1, col2, col3 = st.columns(3)
        col1.metric("Final Relevance", f"{float(match.get('relevance', 0.0)):.3f}")
        col2.metric("Top Actor Similarity", f"{float(match.get('sim_actors', 0.0)):.3f}")
        col3.metric("Top Use-Case Similarity", f"{float(match.get('sim_usecases', 0.0)):.3f}")

        st.dataframe(breakdown, use_container_width=True, hide_index=True)

        with st.expander("Case Details", expanded=False):
            st.markdown(f"**System Name:** {case_meta.get('system_name') or '-'}")
            st.markdown(f"**Case Title:** {text_meta.get('title') or '-'}")
            st.markdown(f"**Domains:** {', '.join(text_meta.get('domains') or []) or '-'}")
            st.markdown(f"**Primary Actors:** {', '.join([n for n, t in case_meta.get('actors', []) if str(t).lower().startswith('primary')]) or '-'}")
            st.markdown(f"**Secondary Actors:** {', '.join([n for n, t in case_meta.get('actors', []) if str(t).lower().startswith('secondary')]) or '-'}")
            st.markdown(f"**Use Cases:** {', '.join(case_meta.get('use_cases') or []) or '-'}")
            st.markdown(f"**Relationships:** {len(case_meta.get('relationships') or [])}")

            description = (text_meta.get("description") or "").strip()
            if description:
                st.text_area(
                    "Stored Description",
                    value=description,
                    height=160,
                    disabled=True,
                    key=f"desc_{case_id}",
                )


def main() -> None:
    st.set_page_config(page_title="myCBR Similarity Explorer", layout="wide")

    st.title("myCBR Similarity Explorer")
    st.caption("Standalone exploratory page. It reuses the current project retrieval stack without modifying your main app.")

    st.info(
        "This page demonstrates the same pattern you described for myCBR: "
        "you define the fields and weighting model in advance, then the system "
        "automatically computes local similarities, aggregates them, ranks cases, "
        "and returns the most similar matches."
    )

    st.markdown(
        """
**How this project currently checks similarity**

1. A query is represented using `system_name`, `description`, `domains`, `actors`, and `use_cases`.
2. Existing embedding functions compute semantic vectors for those fields.
3. Retrieval computes local similarities such as title, description, actors, use cases, domains, and lexical overlap.
4. A weighted aggregation model combines them into one final relevance score.
5. Cases are ranked automatically and the highest-scoring ones are returned.
        """
    )

    try:
        catalog = _fetch_case_catalog()
    except Exception as exc:
        st.error(f"Could not read the case base: {exc}")
        catalog = []

    with st.sidebar:
        st.header("Explorer Controls")

        mode = st.radio("Ranking Mode", ["CBR", "IR"], horizontal=True)
        threshold = st.slider("Minimum Relevance", 0.0, 1.0, 0.35, 0.01)
        limit = st.slider("Max Results", 1, 20, 5, 1)

        st.markdown("**Weight Profile**")
        st.dataframe(
            pd.DataFrame(
                [{"Feature": FEATURE_LABELS.get(k, k), "Weight": v} for k, v in _weights_for_mode(mode).items()]
            ),
            use_container_width=True,
            hide_index=True,
        )

        if catalog:
            selected_label = st.selectbox(
                "Load Existing Case Into Query",
                options=[""] + [_case_option_label(row) for row in catalog],
                index=0,
            )
            if st.button("Load Case", use_container_width=True):
                if selected_label:
                    selected_case_id = int(selected_label.split(" - ", 1)[0])
                    _load_case_into_query(selected_case_id)
                    st.success(f"Loaded case {selected_case_id} into the query form.")
                else:
                    st.warning("Select a case first.")
        else:
            st.caption("No stored cases were found in the database.")

    if "mycbr_system_name" not in st.session_state:
        st.session_state["mycbr_system_name"] = st.session_state.get("ucd_system_name", "")
    if "mycbr_description" not in st.session_state:
        st.session_state["mycbr_description"] = st.session_state.get("ucd_paragraph", "")
    if "mycbr_domains" not in st.session_state:
        st.session_state["mycbr_domains"] = "\n".join(st.session_state.get("ucd_domains", []) or [])
    if "mycbr_actors" not in st.session_state:
        existing_actors = st.session_state.get("ucd_actors", []) or []
        st.session_state["mycbr_actors"] = "\n".join(existing_actors)
    if "mycbr_use_cases" not in st.session_state:
        existing_ucs = st.session_state.get("ucd_use_cases", []) or []
        st.session_state["mycbr_use_cases"] = "\n".join(existing_ucs)

    st.subheader("Query")
    left, right = st.columns(2)
    with left:
        system_name = st.text_input("System Name", key="mycbr_system_name")
        description = st.text_area("Description", key="mycbr_description", height=180)
        domains_text = st.text_area("Domains", key="mycbr_domains", height=100, help="One item per line or comma-separated.")
    with right:
        actors_text = st.text_area("Actors", key="mycbr_actors", height=140, help="One item per line or comma-separated.")
        use_cases_text = st.text_area("Use Cases", key="mycbr_use_cases", height=140, help="One item per line or comma-separated.")

    query = {
        "system_name": system_name.strip(),
        "description": description.strip(),
        "domains": _split_items(domains_text),
        "actors": _split_items(actors_text),
        "use_cases": _split_items(use_cases_text),
    }

    if st.button("Run Similarity Retrieval", type="primary", use_container_width=True):
        if not any([query["system_name"], query["description"], query["domains"], query["actors"], query["use_cases"]]):
            st.warning("Provide at least one query field before running retrieval.")
            return

        with st.spinner("Computing similarities and ranking cases..."):
            try:
                matches = find_similar_cases(query, mode=mode, threshold=threshold, limit=limit)
            except Exception as exc:
                st.error(f"Retrieval failed: {exc}")
                return

        st.subheader("Results")
        if not matches:
            st.info("No cases met the current threshold.")
            return

        st.success(f"Found {len(matches)} matching case(s).")

        summary_rows = [
            {
                "Case ID": m["case_id"],
                "Title": m.get("title") or "",
                "Relevance": round(float(m.get("relevance", 0.0)), 4),
                "Title Sim": round(float(m.get("sim_title", 0.0)), 4),
                "Desc Sim": round(float(m.get("sim_desc", 0.0)), 4),
                "Actor Sim": round(float(m.get("sim_actors", 0.0)), 4),
                "UC Sim": round(float(m.get("sim_usecases", 0.0)), 4),
                "Domain Sim": round(float(m.get("sim_domains", 0.0)), 4),
                "Lexical": round(float(m.get("sim_lexical", 0.0)), 4),
            }
            for m in matches
        ]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        for match in matches:
            _render_match(match, mode)


if __name__ == "__main__":
    main()
