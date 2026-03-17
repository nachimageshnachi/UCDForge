"""
Step Manager - wizard orchestrator for the UCD Generation flow.

Manages:
  - Ordered step definitions (name, icon, render function)
  - Sidebar step list (active / completed / locked indicators)
  - Top horizontal stepper
  - Forward / backward navigation with reset-on-modify
  - "Reset Session" button with save prompt
"""

import streamlit as st

# ---- Step registry --------------------------------------------------------

STEPS = [
    {"num": 1,  "name": "System Description",     "short": "Description", "icon": ""},
    {"num": 2,  "name": "Hybrid Retrieval",        "short": "Retrieval",   "icon": ""},
    {"num": 3,  "name": "Edit Actors & Use Cases", "short": "Elements",    "icon": ""},
    {"num": 4,  "name": "Review Extraction",       "short": "Review",      "icon": ""},
    {"num": 5,  "name": "Associations",            "short": "Assoc.",      "icon": ""},
    {"num": 6,  "name": "Include Relationships",   "short": "Include",     "icon": ""},
    {"num": 7,  "name": "Extend Relationships",    "short": "Extend",      "icon": ""},
    {"num": 8,  "name": "UC Generalization",       "short": "UC Gen.",     "icon": ""},
    {"num": 9,  "name": "Actor Generalization",    "short": "Actor Gen.",  "icon": ""},
    {"num": 10, "name": "CBR Matching & Export",   "short": "CBR Export",  "icon": ""},
]

TOTAL_STEPS = len(STEPS)

# Session-state keys owned by specific steps, so we know what to clear on reset
_STEP_KEYS = {
    1: ["ucd_paragraph", "ucd_system_name", "ucd_primary_actors",
        "ucd_secondary_actors", "ucd_actors", "ucd_use_cases",
        "ucd_domains", "ucd_relationships", "ucd_ready"],
    2: ["_py_matches", "_my_matches", "_hybrid_retrieval_done",
        "cbr_suggested_primary", "cbr_suggested_secondary",
        "cbr_suggested_use_cases", "cbr_suggested_relationships",
        "cbr_top_case", "cbr_kb_case", "cbr_selected_case_key",
        "_mycbr_autostart_attempted", "_mycbr_server_alive",
        "_excel_report_bytes"],
    3: ["ucd_elements_saved", "ucd_primary_multiselect",
        "ucd_secondary_multiselect", "ucd_usecases_multiselect",
        "_reset_primary_multiselect", "_reset_secondary_multiselect",
        "_reset_usecases_multiselect"],
    4: [],   # review is read-only
    5: ["ucd_match_pairs", "ucd_visible_actors", "ucd_actor_colors"],
    6: ["ucd_include_pairs"],
    7: ["ucd_extend_pairs", "ucd_extend_meta"],
    8: ["ucd_uc_gen_pairs", "ucd_uc_colors"],
    9: ["ucd_actor_gen_pairs"],
    10: ["cbr_matches", "cbr_expander_open", "ucd_generation_validation",
        "ucd_generation_validation_hash", "ucd_generation_export_signature",
        "ucd_ttool_xml", "ucd_ttool_xml_base"],
}


# ---- State helpers --------------------------------------------------------

def _init_state():
    """Ensure core wizard keys exist in session_state."""
    if "ucd_current_step" not in st.session_state:
        st.session_state.ucd_current_step = 1
    if "ucd_completed_steps" not in st.session_state:
        st.session_state.ucd_completed_steps = set()
    if "ucd_processing" not in st.session_state:
        st.session_state.ucd_processing = False


def current_step() -> int:
    _init_state()
    return st.session_state.ucd_current_step


def completed_steps() -> set:
    _init_state()
    return st.session_state.ucd_completed_steps


def go_to_step(n: int):
    """Navigate to step *n*. Blocked while processing."""
    _init_state()
    if st.session_state.ucd_processing:
        return
    if 1 <= n <= TOTAL_STEPS:
        st.session_state.ucd_current_step = n
        st.rerun()


def is_processing() -> bool:
    """Return True if a long-running operation is active."""
    _init_state()
    return st.session_state.ucd_processing


def set_processing(active: bool):
    """Set / clear the processing lock."""
    _init_state()
    st.session_state.ucd_processing = active


def complete_step(n: int):
    """Mark step *n* as completed and advance to n+1."""
    _init_state()
    st.session_state.ucd_completed_steps.add(n)
    if n < TOTAL_STEPS:
        st.session_state.ucd_current_step = n + 1
    st.rerun()


def reset_from_step(n: int):
    """Clear state for all steps > n and mark them incomplete."""
    _init_state()
    for step_num in range(n + 1, TOTAL_STEPS + 1):
        st.session_state.ucd_completed_steps.discard(step_num)
        for key in _STEP_KEYS.get(step_num, []):
            st.session_state.pop(key, None)


def max_reachable_step() -> int:
    """Highest step the user may visit (completed + 1, capped at TOTAL)."""
    _init_state()
    if not st.session_state.ucd_completed_steps:
        return 1
    return min(max(st.session_state.ucd_completed_steps) + 1, TOTAL_STEPS)


def _do_reset():
    """Clear all wizard state. Safe to call from on_click callbacks (no st.rerun)."""
    keys_to_clear = ["ucd_current_step", "ucd_completed_steps"]
    for step_keys in _STEP_KEYS.values():
        keys_to_clear.extend(step_keys)
    keys_to_clear += [
        "_saved_paragraph",
        "_show_reset_confirm", "_reset_show_at_run", "_run_count",
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)
    # Increment counter - all step1 widgets (textarea + uploaders) get new keys
    # so Streamlit creates brand-new empty instances after the next render.
    st.session_state["_reset_count"] = st.session_state.get("_reset_count", 0) + 1


def reset_session():
    """Wipe all wizard state and restart from Step 1."""
    _do_reset()
    st.rerun()


# ---- UI components -------------------------------------------------------

def render_sidebar_progress():
    """Sidebar only shows main menu - no UCD sub-steps."""
    pass  # Step nav removed; main menu is handled by the app shell.


def render_top_stepper():
    """Draw a compact, clickable horizontal stepper at the top."""
    _init_state()
    cur = current_step()
    done = completed_steps()
    reachable = max_reachable_step()
    processing = is_processing()

    def _jump_top(target_step):
        if not st.session_state.ucd_processing:
            st.session_state.ucd_current_step = target_step

    # Put JS inside the same markdown block - no extra iframe/whitespace
    st.markdown(
        """<style>
        div[data-testid="stHorizontalBlock"]:first-of-type {
            gap: 0.2rem !important; overflow-x: auto !important;
            flex-wrap: nowrap !important; align-items: stretch !important;
            padding-bottom: 4px !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"] {
            min-width: 80px !important; flex-shrink: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type button {
            padding: 5px 3px !important; font-size: 11px !important;
            line-height: 1.3 !important; height: auto !important;
            min-height: 2.4rem !important;
            transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type button:not(:disabled):hover {
            border-color: #2d8a4e !important;
            box-shadow: 0 0 0 2px rgba(45,138,78,0.35) !important;
            color: #2d8a4e !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type button:disabled:hover {
            border-color: #c0392b !important;
            box-shadow: 0 0 0 2px rgba(192,57,43,0.30) !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type::-webkit-scrollbar { height: 4px; }
        div[data-testid="stHorizontalBlock"]:first-of-type::-webkit-scrollbar-thumb {
            background: #ccc; border-radius: 2px;
        }
        </style>""",
        unsafe_allow_html=True,
    )

    # Info caption
    st.caption(
        "Move **forward one step at a time** (complete each step first). "
        "**Backtrack to any previous step** freely."
    )

    cols = st.columns(TOTAL_STEPS)
    for i, step in enumerate(STEPS):
        n = step["num"]
        full_name = step["name"]
        short_name = step["short"]
        with cols[i]:
            if n == cur:
                # Active step - full name, green filled
                st.markdown(
                    f'<div style="background:#2d8a4e;color:white;border-radius:6px;'
                    f'padding:6px 4px;font-size:11px;line-height:1.3;text-align:center;'
                    f'white-space:normal;word-break:break-word;font-weight:600;">'
                    f'{full_name}</div>',
                    unsafe_allow_html=True,
                )
            elif n in done or n <= reachable:
                # Clickable step - short name, green hover
                st.button(
                    short_name,
                    key=f"top_step_{n}",
                    use_container_width=True,
                    on_click=_jump_top,
                    args=(n,),
                    disabled=processing,
                    help=full_name,
                )
            else:
                # Locked step - short name, disabled
                st.button(
                    short_name,
                    key=f"top_step_{n}",
                    use_container_width=True,
                    disabled=True,
                    help=f"{full_name} - Complete the previous step to proceed further.",
                )


def render_navigation(show_prev=True, show_next=True,
                      next_label="Confirm & Continue",
                      on_next=None, next_disabled=False):
    """Render Previous / Next navigation buttons at the bottom of a step."""
    _init_state()
    cur = current_step()

    st.divider()

    only_next = show_next and (not show_prev or cur == 1)
    is_last = cur == TOTAL_STEPS

    if only_next and not is_last:
        # Step 1 - only a Next button: center it, green (primary)
        _, col_btn, _ = st.columns([1, 2, 1])
        with col_btn:
            if st.button(next_label, key=f"nav_next_{cur}",
                         use_container_width=True, disabled=next_disabled,
                         type="primary"):
                proceed = bool(on_next()) if on_next else True
                if proceed:
                    complete_step(cur)
    elif is_last:
        _, col_btn, _ = st.columns([1, 2, 1])
        with col_btn:
            st.success("You have completed all steps.")
    else:
        col_prev, col_space, col_next = st.columns([1, 2, 1])
        with col_prev:
            if show_prev and cur > 1:
                if st.button("Previous", key=f"nav_prev_{cur}",
                             use_container_width=True):
                    go_to_step(cur - 1)
        with col_next:
            if show_next:
                if st.button(next_label, key=f"nav_next_{cur}",
                             use_container_width=True,
                             disabled=next_disabled,
                             type="primary"):
                    proceed = bool(on_next()) if on_next else True
                    if proceed:
                        complete_step(cur)


# ---- Main runner ----------------------------------------------------------

def run_wizard():
    """Entry point called by ``ucd_generation.app()``."""
    from generation.shared import inject_global_styles

    _init_state()
    inject_global_styles()

    st.title("Case-Based Reasoning for Use Case Diagrams")
    st.markdown(
        "Provide a detailed system description and follow the guided steps "
        "to build a validated Use Case Diagram."
    )

    render_top_stepper()

    # Save Work + Reset - sentinel p#sr-row anchors yellow CSS via :has()
    from generation.session_io import session_to_xml

    # Session snapshots should not look like final TTool exports.
    import re as _re
    from datetime import date as _date
    _cur = current_step()
    _sys_raw = st.session_state.get("ucd_system_name") or ""
    _sys_safe = _re.sub(r'[\\/:*?"<>|\s]+', "_", _sys_raw).strip("_") or "UCD_Session"
    _date_str = _date.today().strftime("%Y-%m-%d")
    _save_filename = f"{_sys_safe}_session_{_date_str}.xml"
    _save_data = session_to_xml(step_name=STEPS[_cur - 1]["name"])


    # Auto-dismiss: the confirm dialog is only shown in the exact rerun
    # triggered by clicking Reset Session. Any other action clears it.
    _run_count = st.session_state.get("_run_count", 0) + 1
    st.session_state["_run_count"] = _run_count
    if st.session_state.get("_reset_show_at_run", -1) != _run_count:
        st.session_state._show_reset_confirm = False

    def _on_reset_click():
        # Toggle: click once to show, click again to hide
        st.session_state._show_reset_confirm = not st.session_state.get(
            "_show_reset_confirm", False
        )
        # Mark which run should keep the dialog visible
        st.session_state._reset_show_at_run = (
            st.session_state.get("_run_count", 0) + 1
        )

    st.markdown('<p id="sr-row" style="display:none;margin:0"></p>',
                unsafe_allow_html=True)
    _save_col, _spacer, _reset_col = st.columns([1, 4, 1])
    with _save_col:
        st.download_button(
            label="Save Session",
            data=_save_data,
            file_name=_save_filename,
            mime="application/xml",
            use_container_width=True,
            key="btn_save_xml_main",
        )
    with _reset_col:
        st.button("Reset Session", key="btn_reset_main",
                  use_container_width=True, on_click=_on_reset_click)

    if st.session_state.get("_show_reset_confirm"):
        st.warning("Reset will clear all current wizard data. Save your work first if needed.")
        rc1, _rsp, rc2 = st.columns([1, 4, 1])
        with rc1:
            st.download_button(
                label="Save Session & Reset",
                data=_save_data,
                file_name=_save_filename,
                mime="application/xml",
                use_container_width=True,
                key="btn_save_reset_main",
                on_click=_do_reset,
            )
        with rc2:
            st.button("Discard & Reset", key="btn_discard_reset_main",
                      use_container_width=True,
                      on_click=_do_reset)  # fires before render loop / auto-dismiss



    # Import step renderers lazily to avoid circular imports
    from generation.step1_input import render as render_step1
    from generation.step2_hybrid_retrieval import render as render_step2
    from generation.step2_elements import render as render_step3
    from generation.step3_review import render as render_step4
    from generation.step4_associations import render as render_step5
    from generation.step5_includes import render as render_step6
    from generation.step6_extends import render as render_step7
    from generation.step7_uc_generalization import render as render_step8
    from generation.step8_actor_generalization import render as render_step9
    from generation.step9_cbr_export import render as render_step10

    step_renderers = {
        1:  render_step1,
        2:  render_step2,   # Hybrid Retrieval (Python CBR + myCBR REST)
        3:  render_step3,   # Edit Actors & Use Cases
        4:  render_step4,   # Review
        5:  render_step5,   # Associations
        6:  render_step6,   # Include
        7:  render_step7,   # Extend
        8:  render_step8,   # UC Generalization
        9:  render_step9,   # Actor Generalization
        10: render_step10,  # CBR Export
    }

    cur = current_step()
    step_info = STEPS[cur - 1]
    st.markdown(f"### Step {cur}: {step_info['name']}")
    renderer = step_renderers.get(cur)
    if renderer:
        renderer()

