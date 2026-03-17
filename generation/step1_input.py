"""Step 1: System Description - paragraph input, PDF upload, and session restore."""

import streamlit as st
from generation.shared import dedupe
from generation.step_manager import (
    render_navigation, reset_from_step, set_processing,
)


def _render_llm_selector():
    """Mirror the provider selection used by the upload/parser flows."""
    provider = st.radio(
        "AI Processing Target",
        options=["Google Gemini (Free)", "LM Studio (Local)"],
        index=0,
        horizontal=True,
        key="generation_llm_provider_radio",
        help="Choose where the typed description or uploaded PDF text should be sent for extraction.",
    )
    st.session_state["llm_provider"] = (
        "google" if "Google" in provider else "openai"
    )


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract plain text from PDF bytes using pdfplumber (falls back to PyPDF2)."""
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages).strip()
    except Exception:
        pass
    try:
        import PyPDF2, io
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        pages = [reader.pages[i].extract_text() or "" for i in range(len(reader.pages))]
        return "\n".join(pages).strip()
    except Exception as e:
        st.error(f"Could not read PDF: {e}")
        return ""


def render():
    # Widget key versioning - reset counter forces brand-new empty widgets on reset
    rc = st.session_state.get("_reset_count", 0)
    key_xml   = f"ucd_xml_upload_{rc}"
    key_pdf   = f"ucd_pdf_upload_{rc}"
    key_para  = f"ucd_paragraph_{rc}"
    key_stage = f"_pdf_staged_{rc}"   # staging key for PDF text

    # -- Pre-widget setup (must happen BEFORE any widget with key_para is rendered) --
    # 1. Apply staged PDF text from a previous render
    if key_stage in st.session_state:
        st.session_state[key_para] = st.session_state.pop(key_stage)
    # 2. Restore paragraph when navigating back (after a successful extraction)
    elif key_para not in st.session_state:
        saved = st.session_state.get("_saved_paragraph", "")
        if saved:
            st.session_state[key_para] = saved

    st.markdown(
        "### AI Processing\n"
        "Choose which AI endpoint should process your typed description or uploaded PDF text."
    )
    _render_llm_selector()

    provider_name = "Google Gemini" if st.session_state.get("llm_provider") == "google" else "LM Studio"
    st.caption(f"Current processing target: **{provider_name}**")

    st.divider()

    # ---------------------------------------------------------------------------
    # OPTION 1 - Type a description
    # ---------------------------------------------------------------------------

    st.markdown(
        "### -- Option 1 - Describe your system\n"
        "Write a plain-English paragraph describing what your system does, "
        "who uses it, and what tasks it supports. "
        "The AI will automatically identify actors, use cases, and their relationships."
    )
    st.text_area(
        "System Description",
        height=180,
        placeholder=(
            "e.g. A system designed for real-time monitoring and control of operational "
            "processes, enabling maintenance actions upon request or scheduled maintenance "
            "routines. It facilitates data acquisition from sensors, computation through "
            "actuators, storage of results in a device, and communication with users."
        ),
        key=key_para,
    )

    st.divider()

    # ---------------------------------------------------------------------------
    # OPTION 2 - Upload a PDF
    # ---------------------------------------------------------------------------
    st.markdown(
        "### - Option 2 - Upload a PDF\n"
        "Have a requirements document or report in PDF format? "
        "Upload it here and the system will extract the text automatically "
        "and populate the description box above.\n\n"
        "*Maximum file size: 2 MB*"
    )
    uploaded_pdf = st.file_uploader(
        "Upload PDF",
        type=["pdf"],
        key=key_pdf,
        label_visibility="collapsed",
    )
    if uploaded_pdf is not None and not st.session_state.get(f"_pdf_loaded_{rc}"):
        if uploaded_pdf.size > 2 * 1024 * 1024:
            st.error("- PDF is too large - maximum allowed size is **2 MB**. "
                     "Please upload a smaller file.")
        else:
            pdf_text = _extract_pdf_text(uploaded_pdf.read())
            if pdf_text:
                st.session_state[key_stage] = pdf_text
                st.session_state[f"_pdf_loaded_{rc}"] = True
                st.rerun()

    st.divider()

    # ---------------------------------------------------------------------------
    # OPTION 3 - Restore a saved session
    # ---------------------------------------------------------------------------
    st.markdown(
        "### - Option 3 - Load a previous session\n"
        "Already worked on a diagram before? "
        "Upload the XML file you saved earlier to restore all your actors, "
        "use cases, and relationships exactly where you left off."
    )
    uploaded_xml = st.file_uploader(
        "Upload session XML",
        type=["xml"],
        key=key_xml,
        label_visibility="collapsed",
    )
    if uploaded_xml is not None and not st.session_state.get(f"_xml_loaded_{rc}"):
        from generation.session_io import xml_to_session
        if xml_to_session(uploaded_xml.read()):
            st.session_state[f"_xml_loaded_{rc}"] = True
            # Jump to the highest completed step so the user resumes where they left off
            completed = st.session_state.get("ucd_completed_steps") or set()
            if completed:
                from generation.step_manager import TOTAL_STEPS
                st.session_state["ucd_current_step"] = min(max(completed) + 1, TOTAL_STEPS)
            st.success("Session loaded! Use the stepper above to jump to any step.")
            st.rerun()



    # -- Navigation --------------------------------------------------------------
    def _on_extract():
        para = (st.session_state.get(key_para) or "").strip()
        if not para:
            st.error("Please enter a system description or upload a PDF first.")
            return False

        st.session_state["_saved_paragraph"] = para
        reset_from_step(1)

        set_processing(True)
        with st.spinner(
            "Extracting elements and inferring relationships-\n"
            "Please wait - this may take a moment.\n"
            "Navigation is locked until complete."
        ):
            try:
                from helpers import ask_llm_extract
                data = ask_llm_extract(para)
            except Exception as e:
                set_processing(False)
                st.error(f"Extraction failed: {e}")
                return False

        set_processing(False)

        st.session_state.ucd_system_name = data.get("system_name") or ""
        st.session_state.ucd_primary_actors = dedupe(data.get("primary_actors") or [])
        st.session_state.ucd_secondary_actors = dedupe(data.get("secondary_actors") or [])
        combined = (st.session_state.ucd_primary_actors +
                    st.session_state.ucd_secondary_actors)
        st.session_state.ucd_actors = dedupe(combined)
        st.session_state.ucd_use_cases = dedupe(data.get("use_cases") or [])
        st.session_state.ucd_domains = dedupe(data.get("domains") or [])
        st.session_state.ucd_relationships = list(data.get("relationships") or [])
        st.session_state.ucd_paragraph = para
        st.session_state.ucd_ready = True

        return True

    render_navigation(
        show_prev=False,
        next_label="Extract & Continue",
        on_next=_on_extract,
    )
