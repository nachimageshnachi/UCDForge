"""
generation/step2_hybrid_retrieval.py
=====================================
Step 2: Hybrid Retrieval Phase

Runs Python CBR (semantic) and myCBR REST API (symbolic) in parallel,
displays results side-by-side, and highlights common top-ranked cases.
"""

import streamlit as st
import concurrent.futures
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from generation.step_manager import render_navigation, reset_from_step
from generation.shared import dedupe

_MYCBR_BASE_URL = "http://localhost:8080"

# Absolute path to the launcher .bat — resolve relative to this package file
_BAT_FILE = Path(__file__).parent.parent / "start_mycbr_rest.bat"


# ─── helpers ──────────────────────────────────────────────────────────────────

def _check_mycbr_alive(url: str = _MYCBR_BASE_URL) -> bool:
    from MyCBR.mycbr_rest import mycbr_is_alive
    return mycbr_is_alive(url)


def _start_mycbr_server() -> bool:
    """Launch start_mycbr_rest.bat in the background. Returns True if launched."""
    bat = _BAT_FILE.resolve()
    if not bat.exists():
        return False
    try:
        # CREATE_NEW_CONSOLE opens a new terminal window so the server
        # does not block the Streamlit process.
        subprocess.Popen(
            [str(bat)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    except Exception as exc:
        print(f"[myCBR launcher] failed to start: {exc}")
        return False


def _poll_mycbr_ready(url: str, max_wait: int = 30, interval: float = 1.5) -> bool:
    """Poll until myCBR server responds or timeout. Returns True if alive."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _check_mycbr_alive(url):
            return True
        time.sleep(interval)
    return False


def _run_python_cbr(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from cbr_search import find_similar_cases
        return find_similar_cases(query, mode="CBR", threshold=0.0, limit=100) or []
    except Exception as e:
        print(f"[Python CBR] failed: {e}")
        return []


def _run_mycbr_rest(query: Dict[str, Any], url: str) -> List[Dict[str, Any]]:
    try:
        from MyCBR.mycbr_rest import MyCBRRestClient
        client = MyCBRRestClient(base_url=url)
        return client.retrieve(query, limit=5, threshold=0.0) or []
    except ConnectionError as e:
        print(f"[myCBR REST] server unreachable: {e}")
        return []
    except Exception as e:
        print(f"[myCBR REST] failed: {e}")
        return []


def _clear_kb_suggestions():
    """Clear the selected KB case and any downstream suggestion payload."""
    for key in [
        "cbr_top_case",
        "cbr_kb_case",
        "cbr_suggested_primary",
        "cbr_suggested_secondary",
        "cbr_suggested_use_cases",
        "cbr_suggested_relationships",
    ]:
        st.session_state.pop(key, None)


def _normalize_case_db_id(case_id: Any) -> int | None:
    """Convert SQL ids and labels like UCD_0049 into the DB case id integer."""
    text = str(case_id or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    match = re.search(r"(\d+)\s*$", text)
    if match:
        return int(match.group(1))
    return None


def _case_choice_key(match: Dict[str, Any]) -> str:
    """Stable selection key for a retrieved case across both retrieval engines."""
    db_case_id = _normalize_case_db_id(match.get("case_id"))
    if db_case_id is not None:
        return f"db:{db_case_id}"
    case_key = str(match.get("case_key") or "").strip()
    if case_key:
        return case_key
    title = str(match.get("title") or "Untitled").strip().lower()
    source = str(match.get("source") or "case").strip().lower()
    return f"{source}:{title}"


def _build_case_choices(py_matches: List[Dict[str, Any]],
                        my_matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine Python CBR and myCBR lists into unique selectable cases."""
    merged: Dict[str, Dict[str, Any]] = {}

    for match in list(py_matches or []) + list(my_matches or []):
        key = _case_choice_key(match)
        score = float(match.get("relevance", 0.0))
        source = str(match.get("source") or "case")
        if key not in merged:
            merged[key] = {
                **match,
                "_choice_key": key,
                "_sources": [source],
                "_best_relevance": score,
            }
            continue

        item = merged[key]
        if source not in item["_sources"]:
            item["_sources"].append(source)
        if score > float(item.get("_best_relevance", 0.0)):
            for field in ["case_id", "case_key", "title", "relevance", "source"]:
                item[field] = match.get(field)
            item["_best_relevance"] = score

    return sorted(
        merged.values(),
        key=lambda item: float(item.get("_best_relevance", 0.0)),
        reverse=True,
    )


def _format_case_choice(match: Dict[str, Any]) -> str:
    """Readable label for the user-selected case control."""
    title = str(match.get("title") or "Untitled").strip()
    case_id = str(match.get("case_id") or "N/A").strip()
    sources = ", ".join(match.get("_sources") or [str(match.get("source") or "case")])
    score = float(match.get("_best_relevance", match.get("relevance", 0.0)) or 0.0)
    return f"{title} | {case_id} | {sources} | score {score:.4f}"


def _setup_kb_suggestions(selected_match: Dict[str, Any] | None,
                           primary_actors, secondary_actors,
                           use_cases, system_name):
    """Store KB suggestions for downstream steps from the chosen retrieved case."""
    try:
        if not selected_match:
            _clear_kb_suggestions()
            return
        from cbr_merge import fetch_case_data, merge_user_with_case

        db_case_id = _normalize_case_db_id(selected_match.get("case_id"))
        if db_case_id is None:
            _clear_kb_suggestions()
            return

        top = dict(selected_match)
        st.session_state.cbr_top_case = top
        kb = fetch_case_data(db_case_id)
        st.session_state.cbr_kb_case = kb

        user_payload = {
            "system_name":      system_name,
            "primary_actors":   list(primary_actors),
            "secondary_actors": list(secondary_actors),
            "use_cases":        list(use_cases),
            "relationships":    list(st.session_state.get("ucd_relationships", [])),
        }
        merged = merge_user_with_case(user_payload, kb)

        user_all_actors = set(st.session_state.get("ucd_actors", []))
        user_ucs = set(use_cases)

        st.session_state.cbr_suggested_primary = [
            a for a in merged.get("primary_actors", []) if a not in user_all_actors
        ]
        st.session_state.cbr_suggested_secondary = [
            a for a in merged.get("secondary_actors", []) if a not in user_all_actors
        ]
        st.session_state.cbr_suggested_use_cases = [
            u for u in merged.get("use_cases", []) if u not in user_ucs
        ]
        st.session_state.cbr_suggested_relationships = [
            r for r in merged.get("relationships", [])
            if r not in st.session_state.get("ucd_relationships", [])
        ]
    except Exception as e:
        print(f"[KB merge] failed: {e}")


def _render_case_card(idx: int, match: Dict[str, Any], is_common: bool,
                      extra_field_key: str, is_selected: bool = False):
    """Render a styled case result card."""
    title    = match.get("title", f"Case #{idx + 1}")
    score    = float(match.get("relevance", 0.0))
    extra_v  = match.get(extra_field_key, "N/A")

    if is_selected:
        border_color = "#1459c7"
        bg_color = "#eef5ff"
        badge_text = "Chosen for Next Step"
        badge_bg = "#1459c7"
    else:
        border_color = "#2d8a4e" if is_common else "#d0d0d0"
        bg_color     = "#f0faf4" if is_common else "#fafafa"
        badge_text   = "⭐ Common Match" if is_common else f"#{idx + 1}"
        badge_bg     = "#2d8a4e" if is_common else "#888"

    st.markdown(
        f"""
        <div style="border:2px solid {border_color};background:{bg_color};
                    padding:12px 14px;border-radius:10px;margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-weight:700;font-size:1em;">{title}</span>
                <span style="background:{badge_bg};color:white;padding:2px 9px;
                             border-radius:12px;font-size:0.78em;">{badge_text}</span>
            </div>
            <div style="margin-top:7px;color:#555;font-size:0.88em;display:flex;gap:16px;">
                <span>🎯 <b>Score:</b> {score:.4f}</span>
                <span>📂 <b>Source:</b> {match.get("source","N/A")}</span>
                <span>🔑 <b>{extra_field_key}:</b> {extra_v}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ─── main render ──────────────────────────────────────────────────────────────

def render():
    st.markdown(
        "### 🔍 Hybrid Retrieval Phase\n"
        "Running **Python CBR** (semantic) and **myCBR Engine** (symbolic) in parallel "
        "on the same extracted feature set."
    )

    # ── 1. Display normalized input ──────────────────────────────────────────
    para             = st.session_state.get("ucd_paragraph", "")
    system_name      = st.session_state.get("ucd_system_name", "")
    domains          = st.session_state.get("ucd_domains", []) or []
    primary_actors   = st.session_state.get("ucd_primary_actors", []) or []
    secondary_actors = st.session_state.get("ucd_secondary_actors", []) or []
    use_cases        = st.session_state.get("ucd_use_cases", []) or []
    relationships    = st.session_state.get("ucd_relationships", []) or []

    with st.expander("📄 Normalized Input Features", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**System Name:** {system_name or '—'}")
            st.write(f"**Domains:** {', '.join(domains) if domains else '—'}")
            st.write(f"**Primary Actors:** {', '.join(primary_actors) if primary_actors else '—'}")
        with c2:
            st.write(f"**Secondary Actors:** {', '.join(secondary_actors) if secondary_actors else '—'}")
            st.write(f"**Use Cases:** {', '.join(use_cases) if use_cases else '—'}")
            st.write(f"**Relationships:** {len(relationships)}")
        st.caption("Original paragraph:")
        st.info(para)

    # ── 2. myCBR server status + auto-launch ─────────────────────────────────
    st.markdown("---")
    url_col, status_col = st.columns([3, 1])
    with url_col:
        server_url = st.text_input(
            "myCBR REST Server URL",
            value=st.session_state.get("_mycbr_rest_url", _MYCBR_BASE_URL),
            key="_mycbr_url_input",
            help="myCBR Workbench must be running with REST server mode enabled. "
                 "Default port is 8080.",
        )
        st.session_state["_mycbr_rest_url"] = server_url

    # Auto-start: when user first reaches this step and server is offline,
    # automatically launch the .bat file once per session.
    if not st.session_state.get("_mycbr_autostart_attempted"):
        st.session_state["_mycbr_autostart_attempted"] = True
        if not _check_mycbr_alive(server_url):
            with st.spinner("🚀 myCBR REST server not running — launching automatically…"):
                launched = _start_mycbr_server()
                if launched:
                    alive = _poll_mycbr_ready(server_url, max_wait=30)
                    st.session_state["_mycbr_server_alive"] = alive
                    # (toast not shown here — rerun renders the persistent status banner instead)
                else:
                    st.session_state["_mycbr_server_alive"] = False
                    st.error(f"❌ Could not find `{_BAT_FILE.name}`. Start the server manually.")
            st.rerun()
        else:
            st.session_state["_mycbr_server_alive"] = True

    with status_col:
        st.markdown("<br>", unsafe_allow_html=True)
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("🔄 Check", use_container_width=True):
                alive = _check_mycbr_alive(server_url)
                st.session_state["_mycbr_server_alive"] = alive
        with btn_col2:
            if st.button("🚀 Start", use_container_width=True,
                         help="Launch start_mycbr_rest.bat and wait for the server to come online."):
                with st.spinner("Starting myCBR REST server…"):
                    launched = _start_mycbr_server()
                    if launched:
                        alive = _poll_mycbr_ready(server_url, max_wait=30)
                        st.session_state["_mycbr_server_alive"] = alive
                    else:
                        st.session_state["_mycbr_server_alive"] = False
                st.rerun()

    alive = st.session_state.get("_mycbr_server_alive", None)
    if alive is True:
        st.success(f"✅ myCBR REST server is **online** at `{server_url}`")
    elif alive is False:
        st.error(
            f"❌ myCBR REST server is **offline** at `{server_url}`. "
            "Click **🚀 Start** to launch automatically, or start it manually with `start_mycbr_rest.bat`."
        )
    # if alive is None (not yet checked), show nothing — auto-start spinner handles it

    # ── 3. Run hybrid retrieval ──────────────────────────────────────────────
    query = {
        "system_name":  system_name,
        "description":  para,
        "domains":      domains,
        "actors":       dedupe(primary_actors + secondary_actors),
        "use_cases":    use_cases,
        "relationships": relationships,
    }

    col_run, col_rerun = st.columns([3, 1])
    with col_run:
        run_label = "▶ Run Hybrid Retrieval" if not st.session_state.get("_hybrid_retrieval_done") else "✅ Retrieval Complete"
        do_run = st.button(run_label, type="primary", use_container_width=True,
                           disabled=st.session_state.get("_hybrid_retrieval_done", False))
    with col_rerun:
        if st.button("🔁 Re-run", use_container_width=True,
                     help="Clear cached results and re-run both retrieval algorithms"):
            for key in ["_hybrid_retrieval_done", "_py_matches", "_my_matches",
                        "_excel_report_bytes", "cbr_selected_case_key"]:
                st.session_state.pop(key, None)
            _clear_kb_suggestions()
            st.rerun()

    if do_run and not st.session_state.get("_hybrid_retrieval_done"):
        with st.spinner("⚙️ Running hybrid retrieval in parallel — Python CBR (semantic) + myCBR (symbolic)…"):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                fut_py = pool.submit(_run_python_cbr, query)
                fut_my = pool.submit(_run_mycbr_rest, query, server_url)
                py_results = fut_py.result()
                my_results = fut_my.result()

        st.session_state["_py_matches"] = py_results
        st.session_state["_my_matches"] = my_results
        st.session_state["_hybrid_retrieval_done"] = True

        st.session_state.pop("cbr_selected_case_key", None)
        _clear_kb_suggestions()
        st.rerun()

    # ── 4. Side-by-side result display ──────────────────────────────────────
    if st.session_state.get("_hybrid_retrieval_done"):
        py_matches = st.session_state.get("_py_matches", [])[:5]
        my_matches = st.session_state.get("_my_matches", [])[:5]

        # Find common cases by title (normalized)
        py_titles  = {m.get("title", "").strip().lower() for m in py_matches if m.get("title")}
        my_titles  = {m.get("title", "").strip().lower() for m in my_matches if m.get("title")}
        # Also attempt matching by numeric case_id (Python CBR uses int, myCBR uses "UCD_XXXX")
        py_ids = set()
        for m in py_matches:
            cid = str(m.get("case_id", ""))
            py_ids.add(cid)
            py_ids.add(f"UCD_{int(cid):04d}" if cid.isdigit() else cid)
        my_ids = {str(m.get("case_id", "")) for m in my_matches}
        common_ids    = py_ids & my_ids
        common_titles = py_titles & my_titles

        def _is_common(match: Dict) -> bool:
            t = match.get("title", "").strip().lower()
            cid = str(match.get("case_id", ""))
            return t in common_titles or cid in common_ids

        case_choices = _build_case_choices(py_matches, my_matches)
        choice_map = {match["_choice_key"]: match for match in case_choices}

        # Banner for common matches
        # Count unique common cases (a single case can appear in both title and id sets)
        common_case_count = sum(1 for m in case_choices if _is_common(m))
        if common_case_count:
            st.success(f"🏆 **{common_case_count} common top-ranked case(s)** found in both systems (highlighted in green)")
        else:
            st.info("No common top-ranked cases between both systems at this time.")
        if case_choices:
            default_key = case_choices[0]["_choice_key"]
            if st.session_state.get("cbr_selected_case_key") not in choice_map:
                st.session_state["cbr_selected_case_key"] = default_key
            selected_choice_key = st.selectbox(
                "Choose the one CBR case to use in the next step",
                options=list(choice_map.keys()),
                format_func=lambda key: _format_case_choice(choice_map[key]),
                key="cbr_selected_case_key",
                help="This chosen case will drive the suggested actors, use cases, and relationships on the next page.",
            )
            selected_match = choice_map[selected_choice_key]
            if _case_choice_key(st.session_state.get("cbr_top_case") or {}) != selected_choice_key:
                _setup_kb_suggestions(
                    selected_match,
                    primary_actors,
                    secondary_actors,
                    use_cases,
                    system_name,
                )
            st.caption(
                f"Selected KB case for the next step: {selected_match.get('title', 'Untitled')} "
                f"({selected_match.get('case_id', 'N/A')})."
            )
        else:
            selected_choice_key = None
            _clear_kb_suggestions()

        st.markdown("---")
        left_col, right_col = st.columns(2)

        with left_col:
            st.subheader("🐍 Python CBR")
            st.caption("Semantic similarity — embeddings + Jaccard")
            if not py_matches:
                st.warning("No results returned from Python CBR.")
            else:
                for idx, match in enumerate(py_matches):
                    _render_case_card(
                        idx,
                        match,
                        _is_common(match),
                        extra_field_key="case_id",
                        is_selected=_case_choice_key(match) == selected_choice_key,
                    )

        with right_col:
            st.subheader("⚙️ myCBR Engine")
            st.caption("Symbolic similarity — myCBR REST API")
            if not my_matches:
                st.warning(
                    "No results from myCBR server. "
                    "Ensure myCBR Workbench is running with REST mode enabled at "
                    f"`{server_url}`."
                )
            else:
                for idx, match in enumerate(my_matches):
                    _render_case_card(
                        idx,
                        match,
                        _is_common(match),
                        extra_field_key="case_id",
                        is_selected=_case_choice_key(match) == selected_choice_key,
                    )

    else:
        st.info("Click **▶ Run Hybrid Retrieval** above to start both retrieval algorithms.")

    # ── 5. Excel Export ──────────────────────────────────────────────────────
    if st.session_state.get("_hybrid_retrieval_done"):
        st.markdown("---")
        st.markdown("#### 📥 Export Similarity Scores")
        st.caption(
            "Download a styled Excel workbook with per-parameter similarity, "
            "weight, and product columns for both CBR engines."
        )
        try:
            from cbr_excel_export import build_excel_report
            from datetime import datetime

            py_matches_export = st.session_state.get("_py_matches", [])
            my_matches_export = st.session_state.get("_my_matches", [])
            export_query = {
                "system_name":      system_name,
                "description":      para,
                "domains":          domains,
                "actors":           dedupe(primary_actors + secondary_actors),
                "primary_actors":   primary_actors,
                "secondary_actors": secondary_actors,
                "use_cases":        use_cases,
                "relationships":    relationships,
            }
            # Build the xlsx bytes (cached in session so it only builds once)
            cache_key = "_excel_report_bytes"
            if cache_key not in st.session_state:
                with st.spinner("Building Excel report…"):
                    xlsx_bytes = build_excel_report(
                        query=export_query,
                        py_matches=py_matches_export,
                        my_matches=my_matches_export,
                    )
                st.session_state[cache_key] = xlsx_bytes
            else:
                xlsx_bytes = st.session_state[cache_key]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename  = f"CBR_Similarity_Report_{timestamp}.xlsx"

            st.download_button(
                label="⬇️ Download Similarity Report (.xlsx)",
                data=xlsx_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )
        except Exception as _exc:
            st.warning(f"Excel export unavailable: {_exc}")

    # ── 6. Navigation ────────────────────────────────────────────────────────
    def _on_next():
        reset_from_step(2)
        return True

    render_navigation(
        show_prev=True,
        next_label="Continue to Elements →",
        on_next=_on_next,
    )
