import io
import os
import tempfile
import zipfile
import streamlit as st
from Parser import ParserOperations


def app():
    st.title("Upload TTOOL Files Containing Use Case Diagrams")

    # Let the user pick which LLM provider to use for description generation
    ParserOperations.render_llm_selector()
    st.divider()

    # --- Database management options ---
    with st.expander("⚙️ Database Options", expanded=False):
        db_action = st.radio(
            "Before uploading, do you want to:",
            options=[
                "Append — keep existing data",
                "Clear — erase all rows but keep tables",
                "Reset — drop and recreate all tables",
            ],
            index=0,
            key="db_action",
        )
        if "Clear" in db_action or "Reset" in db_action:
            st.warning("⚠️ This will permanently delete existing case data.")
            confirm = st.checkbox(
                "I understand, proceed with the selected action", key="db_confirm"
            )
        else:
            confirm = True

    # --- Upload mode selector ---
    mode = st.radio(
        "Upload mode",
        ["Individual XML files", "ZIP archive containing XML files"],
        horizontal=True,
        key="upload_mode",
    )

    xml_files: list[tuple[str, bytes]] = []  # (filename, raw bytes)

    if mode == "Individual XML files":
        uploaded = st.file_uploader(
            "Upload TTool XML File(s)",
            type="xml",
            accept_multiple_files=True,
            key="xml_uploader",
        )
        if uploaded:
            xml_files = [(f.name, f.getvalue()) for f in uploaded]

    else:  # ZIP mode
        uploaded_zip = st.file_uploader(
            "Upload a ZIP folder containing TTool XML files",
            type="zip",
            key="zip_uploader",
        )
        if uploaded_zip:
            try:
                with zipfile.ZipFile(uploaded_zip) as zf:
                    xml_names = [
                        n for n in zf.namelist()
                        if n.lower().endswith(".xml") and not n.startswith("__MACOSX")
                    ]
                    if not xml_names:
                        st.error("No XML files found inside the ZIP.")
                    else:
                        st.info(f"Found **{len(xml_names)}** XML file(s) in the ZIP.")
                        for name in xml_names:
                            xml_files.append((os.path.basename(name), zf.read(name)))
            except zipfile.BadZipFile:
                st.error("The uploaded file is not a valid ZIP archive.")

    # --- Process files ---
    if xml_files:
        if ("Clear" in db_action or "Reset" in db_action) and not confirm:
            st.error("Please confirm the destructive action above before uploading.")
            return

        if st.button(
            f"🚀 Process {len(xml_files)} file(s)",
            type="primary",
            use_container_width=True,
            key="btn_process",
        ):
            # DB action (only once, before batch)
            if "Reset" in db_action and confirm:
                with st.spinner("Dropping and recreating tables…"):
                    ParserOperations.destroyTables()
                    ParserOperations.createTables()
                st.info("✅ Tables recreated.")
            elif "Clear" in db_action and confirm:
                with st.spinner("Clearing all rows…"):
                    ParserOperations.clearTables()
                st.info("✅ Tables cleared.")

            progress = st.progress(0, text="Processing…")
            ok, fail = 0, 0
            total = len(xml_files)

            for idx, (fname, raw) in enumerate(xml_files, start=1):
                progress.progress(idx / total, text=f"({idx}/{total}) {fname}")
                tmp_path = None
                try:
                    # Save to temp file so ParserOperations can use ET.parse + open()
                    with tempfile.NamedTemporaryFile(
                        suffix=".xml", delete=False, dir=tempfile.gettempdir()
                    ) as tmp:
                        tmp.write(raw)
                        tmp_path = tmp.name

                    parser = ParserOperations(tmp_path)
                    parser.addToDb()
                    st.success(f"✅ {fname}")
                    ok += 1
                except Exception as e:
                    st.error(f"❌ {fname}: {e}")
                    fail += 1
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            progress.empty()
            st.divider()
            st.markdown(
                f"**Done!** {ok} succeeded, {fail} failed out of {total} file(s)."
            )


# When run directly with `streamlit run fileupload.py`
if __name__ == "__main__":
    app()