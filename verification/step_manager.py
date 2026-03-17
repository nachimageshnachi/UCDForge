"""
Step Manager — wizard orchestrator for the UCD Verification flow.

Manages:
  - Ordered step definitions (name, icon, render function)
  - Top horizontal stepper
  - Forward / backward navigation
  - Reset Session button

Mirrors the generation/step_manager.py pattern.
"""

import streamlit as st

# ---- Step registry --------------------------------------------------------

STEPS = [
    {"num": 1, "name": "Upload XML",              "short": "Upload",      "icon": ""},
    {"num": 2, "name": "System Verification",      "short": "System",      "icon": ""},
    {"num": 3, "name": "Actors Verification",      "short": "Actors",      "icon": ""},
    {"num": 4, "name": "Use Cases Verification",   "short": "Use Cases",   "icon": ""},
    {"num": 5, "name": "UCD Semantics",            "short": "Semantics",   "icon": ""},
    {"num": 6, "name": "Relationships",            "short": "Relations",   "icon": ""},
    {"num": 7, "name": "Results & Download",       "short": "Results",     "icon": ""},
]

TOTAL_STEPS = len(STEPS)

# Session-state keys owned by specific steps
_STEP_KEYS = {
    1: ["ver_ucd_instance", "ver_ucd_dataset", "ver_last_file_hash",
        "ver_uploaded_xml", "ver_diagram_list"],
    2: [],  # reads from step 1 data
    3: [],
    4: [],
    5: [],
    6: ["ver_validated_ucds"],
    7: ["ver_finalized"],
}


# ---- State helpers --------------------------------------------------------

def _init_state():
    """Ensure core wizard keys exist in session_state."""
    if "ver_current_step" not in st.session_state:
        st.session_state.ver_current_step = 1
    if "ver_completed_steps" not in st.session_state:
        st.session_state.ver_completed_steps = set()
    if "ver_processing" not in st.session_state:
        st.session_state.ver_processing = False
    if "ver_current_diagram" not in st.session_state:
        st.session_state.ver_current_diagram = 0


def current_step() -> int:
    _init_state()
    return st.session_state.ver_current_step


def completed_steps() -> set:
    _init_state()
    return st.session_state.ver_completed_steps


def go_to_step(n: int):
    """Navigate to step *n*. Blocked while processing."""
    _init_state()
    if st.session_state.ver_processing:
        return
    if 1 <= n <= TOTAL_STEPS:
        st.session_state.ver_current_step = n
        st.rerun()


def is_processing() -> bool:
    _init_state()
    return st.session_state.ver_processing


def set_processing(active: bool):
    _init_state()
    st.session_state.ver_processing = active


def complete_step(n: int):
    """Mark step *n* as completed and advance to n+1."""
    _init_state()
    st.session_state.ver_completed_steps.add(n)
    if n < TOTAL_STEPS:
        st.session_state.ver_current_step = n + 1
    st.rerun()


def reset_from_step(n: int):
    """Clear state for all steps > n and mark them incomplete."""
    _init_state()
    for step_num in range(n + 1, TOTAL_STEPS + 1):
        st.session_state.ver_completed_steps.discard(step_num)
        for key in _STEP_KEYS.get(step_num, []):
            st.session_state.pop(key, None)


def max_reachable_step() -> int:
    """Highest step the user may visit (completed + 1, capped at TOTAL)."""
    _init_state()
    if not st.session_state.ver_completed_steps:
        return 1
    return min(max(st.session_state.ver_completed_steps) + 1, TOTAL_STEPS)


def _do_reset():
    """Clear all wizard state and rerun to show Step 1."""
    keys_to_clear = ["ver_current_step", "ver_completed_steps",
                     "ver_current_diagram"]
    for step_keys in _STEP_KEYS.values():
        keys_to_clear.extend(step_keys)
    keys_to_clear += [
        "ver_finalized", "ver_validated_ucds",
        "_ver_show_reset_confirm", "_ver_reset_show_at_run",
        "_ver_run_count",
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)
    # Callers (reset_session, on_click callbacks) are responsible for st.rerun()


def reset_session():
    """Wipe all wizard state and restart from Step 1."""
    _do_reset()
    st.rerun()


# ---- Diagram helpers ------------------------------------------------------

def get_diagram_list():
    """Flatten the dataset into a list of (tab_name, ucd_index, ucd_name, ucd_details)."""
    diagrams = []
    ucd_dataset = st.session_state.get("ver_ucd_dataset", [])
    for model in ucd_dataset or []:
        for tab_name, tab_data in model.items():
            for ucd_index, ucd in enumerate(tab_data.get("Ucd Data", [])):
                for ucd_name, details in ucd.items():
                    diagrams.append((tab_name, ucd_index, ucd_name, details))
    return diagrams


def current_diagram_index() -> int:
    _init_state()
    return st.session_state.ver_current_diagram


def total_diagrams() -> int:
    return len(get_diagram_list())


def current_diagram():
    """Return (tab_name, ucd_index, ucd_name, ucd_details) for the current diagram, or None."""
    dl = get_diagram_list()
    idx = current_diagram_index()
    if 0 <= idx < len(dl):
        return dl[idx]
    return None


def advance_diagram():
    """Move to the next diagram or to step 7 if all diagrams are done."""
    _init_state()
    idx = st.session_state.ver_current_diagram + 1
    if idx < total_diagrams():
        st.session_state.ver_current_diagram = idx
        st.session_state.ver_current_step = 2  # loop back to System step
        # Clear completed marks for steps 2-6 so stepper re-highlights
        for s in (2, 3, 4, 5, 6):
            st.session_state.ver_completed_steps.discard(s)
        st.rerun()
    else:
        # All diagrams done → go to Results
        st.session_state.ver_completed_steps.add(6)
        st.session_state.ver_current_step = 7
        st.rerun()


# ---- UI components -------------------------------------------------------

def render_top_stepper():
    """Draw a compact, clickable horizontal stepper at the top."""
    _init_state()
    cur = current_step()
    done = completed_steps()
    reachable = max_reachable_step()
    processing = is_processing()

    def _jump_top(target_step):
        if not st.session_state.ver_processing:
            st.session_state.ver_current_step = target_step

    st.markdown(
        """<style>
        div[data-testid="stHorizontalBlock"]:first-of-type {
            gap: 0.25rem !important; overflow-x: auto !important;
            flex-wrap: nowrap !important; align-items: stretch !important;
            padding-bottom: 4px !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="stColumn"] {
            flex: 1 1 0 !important; min-width: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:first-of-type button,
        div[data-testid="stHorizontalBlock"]:first-of-type div[style*="background"] {
            padding: 6px 4px !important; font-size: 11px !important;
            line-height: 1.3 !important; height: 3rem !important;
            min-height: 3rem !important; max-height: 3rem !important;
            display: flex !important; align-items: center !important;
            justify-content: center !important; text-align: center !important;
            word-break: break-word !important; white-space: normal !important;
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
        </style>""",
        unsafe_allow_html=True,
    )

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
                st.markdown(
                    f'<div style="background:#2d8a4e;color:white;border-radius:6px;'
                    f'padding:6px 4px;font-size:11px;line-height:1.3;text-align:center;'
                    f'white-space:normal;word-break:break-word;font-weight:600;">'
                    f'{full_name}</div>',
                    unsafe_allow_html=True,
                )
            else:
                # Lock steps 2-6 until upload is done (step 1 completed)
                has_data = 1 in done
                st.button(
                    short_name,
                    key=f"ver_top_step_{n}",
                    use_container_width=True,
                    on_click=_jump_top,
                    args=(n,),
                    disabled=processing or not has_data,
                    help=full_name if has_data else f"{full_name} - Upload a file first.",
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
        _, col_btn, _ = st.columns([1, 2, 1])
        with col_btn:
            if st.button(next_label, key=f"ver_nav_next_{cur}",
                         use_container_width=True, disabled=next_disabled,
                         type="primary"):
                proceed = True
                if on_next:
                    proceed = on_next()
                if proceed:
                    complete_step(cur)
    elif is_last:
        pass  # Results page has its own controls
    else:
        col_prev, col_space, col_next = st.columns([1, 2, 1])
        with col_prev:
            if show_prev and cur > 1:
                if st.button("Previous", key=f"ver_nav_prev_{cur}",
                             use_container_width=True):
                    go_to_step(cur - 1)
        with col_next:
            if show_next:
                if st.button(next_label, key=f"ver_nav_next_{cur}",
                             use_container_width=True,
                             disabled=next_disabled,
                             type="primary"):
                    proceed = True
                    if on_next:
                        proceed = on_next()
                    if proceed:
                        complete_step(cur)


# ---- Main runner ----------------------------------------------------------

def run_wizard():
    """Entry point called by ``ucd_verification.app()``."""
    _init_state()

    # Reduce page padding (matches generation module)
    st.markdown(
        """<style>
        .block-container {padding-left: 0.75rem; padding-right: 0.75rem; max-width: 1700px;}
        </style>""",
        unsafe_allow_html=True,
    )

    st.title("Use Case Diagram Verifier")
    st.markdown(
        "Upload a TTool XML file containing Use Case Diagrams and follow "
        "the guided steps to verify each component."
    )

    render_top_stepper()

    # Reset Session button
    _run_count = st.session_state.get("_ver_run_count", 0) + 1
    st.session_state["_ver_run_count"] = _run_count
    if st.session_state.get("_ver_reset_show_at_run", -1) != _run_count:
        st.session_state["_ver_show_reset_confirm"] = False

    def _on_reset_click():
        st.session_state["_ver_show_reset_confirm"] = not st.session_state.get(
            "_ver_show_reset_confirm", False
        )
        st.session_state["_ver_reset_show_at_run"] = (
            st.session_state.get("_ver_run_count", 0) + 1
        )

    st.divider()
    _left, _reset_col, _right = st.columns([1, 2, 1])
    with _reset_col:
        st.button("Reset Session", key="ver_btn_reset_main",
                  use_container_width=True, on_click=_on_reset_click)

    if st.session_state.get("_ver_show_reset_confirm"):
        st.warning("Reset will clear all verification data.")
        _l2, rc2, _r2 = st.columns([1, 2, 1])
        with rc2:
            st.button("Confirm Reset", key="ver_btn_discard_reset_main",
                      use_container_width=True,
                      on_click=_do_reset)

    # Import step renderers lazily
    from verification.step1_upload import render as render_step1
    from verification.step2_system import render as render_step2
    from verification.step3_actors import render as render_step3
    from verification.step4_usecases import render as render_step4
    from verification.step5_semantics import render as render_step5
    from verification.step5_relationships import render as render_step6
    from verification.step6_results import render as render_step7

    step_renderers = {
        1: render_step1,
        2: render_step2,
        3: render_step3,
        4: render_step4,
        5: render_step5,
        6: render_step6,
        7: render_step7,
    }

    cur = current_step()
    step_info = STEPS[cur - 1]

    # Show diagram context for steps 2-6
    if 2 <= cur <= 6 and total_diagrams() > 0:
        d_idx = current_diagram_index()
        d_total = total_diagrams()
        d_info = current_diagram()
        d_name = d_info[2] if d_info else "?"
        st.markdown(f"### Step {cur}: {step_info['name']}")
        st.info(f"Diagram **{d_idx + 1}** of **{d_total}**: **{d_name}**")
    else:
        st.markdown(f"### Step {cur}: {step_info['name']}")

    renderer = step_renderers.get(cur)
    if renderer:
        renderer()
