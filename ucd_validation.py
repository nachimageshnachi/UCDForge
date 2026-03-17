def app():
    st.title("Use Case Diagram Verifier")    
    st.write("Upload TTOOL files containing Use Case Diagrams for verification")
    
    for key, default in [
        ("finalized", False),
        ("validated_ucds", set()),
        ("last_file_hash", None),
        ("ucd_instance", None),
        ("ucd_dataset", None)
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    uploaded_file = st.file_uploader("Upload the TTool XML File", type="xml")
    
    if st.button("Reset Session"):
        for key in [
            "validated_ucds", "finalized", "last_file_hash",
            "ucd_instance", "ucd_dataset", "uploaded_xml"
        ]:
            st.session_state.pop(key, None)
        st.rerun()
    
    if uploaded_file is not None:
        file_hash = get_file_hash(uploaded_file)

        if "last_file_hash" not in st.session_state or st.session_state["last_file_hash"] != file_hash:
            with st.spinner("Extracting and verifying data..."):
                uploaded_file.seek(0)        
                ucd_instance = ucd_validation_operation(uploaded_file)
                ucd_dataset = ucd_instance.extractData()
                uploaded_file.seek(0)
                st.session_state["uploaded_xml"] = uploaded_file.getvalue().decode("utf-8", errors="ignore")
            st.session_state["validated_ucds"] = set()
            st.session_state["last_file_hash"] = file_hash
            st.session_state["finalized"] = False
            st.session_state["ucd_instance"] = ucd_instance
            st.session_state["ucd_dataset"] = ucd_dataset
        
        
        ucd_instance = st.session_state["ucd_instance"]
        ucd_dataset = st.session_state["ucd_dataset"]
        
        try:
            total_ucd_count = 0
            
            for model in ucd_dataset:
                for tab_name, tab_data in model.items():
                    ucddata=tab_data.get('Ucd Data', [])

                    for ucd_index, ucd in enumerate(ucddata):
                        for ucd_name, ucd_details in ucd.items():
                            connectors=ucd_details.get('Connectors', [])
                            
                            unique_ucd_id=f"{tab_name}_{ucd_index}"
                            total_ucd_count+=1

                            if not connectors:
                                st.info(f"No connectors found in diagram: {ucd_name}")
                                continue

                            with st.expander(f"Classify Relationships in Use Case Diagram: {ucd_name}", expanded=True):
                                st.markdown("### Use Case Relation Classification")
                                st.markdown("""
                                - **Include** → Target use case is always part of the source.
                                - **Extend** → Target use case happens optionally under certain conditions.
                                - **Generalization** → Target is a specialized version of the source.
                                - **None of the Above** → You are unsure or believe none of the above apply.
                                """)

                                user_choices={}
                                relation_keys=["Include", "Extend", "Generalization", "None of the Above"]

                                i=1
                                for idx, conn in enumerate(connectors):
                                    conn_id, conn_data=conn
                                    rel_val=conn_data.get("Relation Value", "")
                                    
                                    if rel_val not in ["Include", "Extend", "Generalization"]:
                                        continue
                                    
                                    A=conn_data['Source Name']
                                    B=conn_data['Target Name']
                                    src=f"{conn_data['Source Name']} ({conn_data['Source Type']})"
                                    tgt=f"{conn_data['Target Name']} ({conn_data['Target Type']})"
                                    auto_rel=rel_val

                                    radio_options = [
                                        f"Include - if {B} should always occur if {A} occurs",
                                        f"Extend - if {B} should optionally occur after {A} occurs",
                                        f"Generalization - if {A} can be subcategorized into {B}",
                                        f"None of the Above - Does none of these apply"
                                    ]
                                    
                                    option_to_type = {
                                        radio_options[0]: "Include",
                                        radio_options[1]: "Extend",
                                        radio_options[2]: "Generalization",
                                        radio_options[3]: "None of the Above"
                                    }
                                    
                                    default_index = relation_keys.index(rel_val)
                                    
                                    # --- Relationship Label ---
                                    st.markdown(f"### {i}. {rel_val} Relationship Verification")
                                    i+=1
                                    st.markdown(f"`{src}` → `{tgt}`")
                                    
                                    # --- Auto-detected display ---
                                    st.markdown(f"**Auto-detected:** `{auto_rel}`")

                                    # --- Radio with explanation shown directly ---
                                    selected_label = st.radio(
                                        label="Select Appropriate Relationship Type:",
                                        options=radio_options,
                                        index=default_index,
                                        key=f"reltype_{tab_name}_{ucd_name}_{conn_id}_{idx}"
                                    )
                                    
                                    selected_type = option_to_type[selected_label]
                                    
                                    disable_reverse = selected_type == "None of the Above"

                                    reverse_key = f"reverse_{tab_name}_{ucd_name}_{conn_id}_{idx}"

                                    if disable_reverse:
                                        st.session_state[reverse_key] = False
                                    
                                    # --- Reverse checkbox ---
                                    reverse = st.checkbox(
                                        label=f"Should the relationship direction be reversed from {B} → {A} ?",
                                        key=f"reverse_{tab_name}_{ucd_name}_{conn_id}_{idx}",
                                        disabled=disable_reverse
                                    )
                                    
                                    user_choices[conn_id] = {
                                        "type": selected_type,
                                        "reverse": reverse
                                    }
                                    
                                    st.markdown("---")
                                
                                if user_choices and st.button(
                                    f"Confirm Classifications for {ucd_name}",
                                    key=f"confirm_{tab_name}_{ucd_name}_{ucd_index}"
                                ):
                                    action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
                                    for conn in connectors:
                                        conn_id = conn[0]
                                        if conn_id in user_choices:
                                            choice = user_choices[conn_id]
                                            new_val = choice["type"]
                                            reverse = choice["reverse"]
                                            old_val = conn[1]["Relation Value"]
                                            
                                            comment=[]
                                            action_level = 0
                                            
                                            source=f"{conn[1]['Source Name']} ({conn[1]['Source Type']})"
                                            target=f"{conn[1]['Target Name']} ({conn[1]['Target Type']})"

                                            if new_val=="None of the Above":
                                                comment.append(f"'{source}' → {target} are expected to be independent elements in the diagram. So, remove the '{old_val}' relationship between them.")
                                                action_level=max(action_level,2)
                                            else:
                                                if reverse:
                                                    comment.append(f"'{source}' → '{target}' are expected to be reversed '{target}' → '{source}'.")
                                                    action_level=max(action_level,2)
                                                    if old_val!=new_val:
                                                        comment.append(f"'{target}' → '{source}' are expected to have '{new_val}' relationship between them in the diagram. So, replace the '{old_val}' relationship between them with '{new_val}' relationship.")
                                                        action_level=max(action_level,2)
                                                        if new_val=="Extend":
                                                            comment.append(f"'{target}' → '{source}' don't forget to add 'Extension Point' in the use case {A}.")
                                                            action_level=max(action_level,2)
                                                        if new_val=="Include":
                                                            comment.append(f"'{target}' → '{source}' don't forget to remove 'Extension Point' in the use case {A}.")
                                                            action_level=max(action_level,2)
                                                            
                                                else:
                                                    if old_val!=new_val:
                                                        comment.append(f"'{source}' → '{target}' are expected to have '{new_val}' relationship between them in the diagram. So, replace the '{old_val}' relationship between them with '{new_val}' relationship.")
                                                        action_level=max(action_level,2)
                                                        if new_val=="Extend":
                                                            comment.append(f"'{source}' → '{target}' don't forget to add 'Extension Point' in the use case {A}.")
                                                            action_level=max(action_level,2)
                                                        if new_val=="Include":
                                                            comment.append(f"'{source}' → '{target}' don't forget to remove 'Extension Point' in the use case {A}.")
                                                            action_level=max(action_level,2)

                                            action=action_map[action_level]
                                            conn[1]["Comments"].extend(comment)
                                            conn[1]["Action"]=action
                                    
                                    st.session_state["validated_ucds"].add(unique_ucd_id)

        except Exception as e:
            st.error(f"Unexpected error please contact the admin: {e}")
            with st.expander("Show technical details"):
                st.exception(e)
            
        st.markdown("---")
        validated_count = len(st.session_state["validated_ucds"])
        st.markdown("### Final Confirmation Progress")
        st.markdown(f"- Confirmed UCDs: **{validated_count} / {total_ucd_count}**")

        if validated_count == total_ucd_count:
            if not st.session_state["finalized"]:
                if st.button("Finalize & Apply All Validated Classifications"):
                    st.session_state["finalized"]=True
                    st.success("All classifications finalized successfully.")
                    
                    ucd_instance.processData(st.session_state["ucd_dataset"])
                    st.success("Verification complete.")
                    ucd_instance.showUcdTables(st.session_state["ucd_dataset"])
                    # Build downloadable XML with activity diagram of issues
                    steps = element_validation.collect_issue_steps(st.session_state["ucd_dataset"])
                    raw_xml = st.session_state.get("uploaded_xml", "")
                    if raw_xml:
                        xml_with_steps = element_validation.append_activity_panel(raw_xml, steps)
                    download_clicked = st.download_button(
                        "Download verification_with_activity.xml",
                        data=xml_with_steps,
                        file_name="verification_with_activity.xml",
                        mime="application/xml",
                        use_container_width=True,
                    )
                    if download_clicked:
                        default_ttool = "C:\\Users\\mages\\Downloads\\releaseTTool_2_0\\TTool\\ttool_windows.bat"
                        ttool_path = st.session_state.get("ttool_path", default_ttool)
                        st.session_state["ttool_path"] = ttool_path
                        ok, msg = _launch_ttool_app(ttool_path)
                        if ok:
                            st.info("File downloaded. TTool opened separately; load the XML manually if needed.")
                        else:
                            st.warning(f"Download saved. TTool not opened: {msg} (using path: {ttool_path})")
                        if st.button("Open in TTool (local)", use_container_width=True):
                            ttool_path = st.text_input(
                                "Path to TTool executable (e.g., C:\\Program Files\\TTool\\ttool.exe)",
                                value=st.session_state.get(
                                    "ttool_path",
                                    "C:\\Users\\mages\\Downloads\\releaseTTool_2_0\\TTool\\ttool_windows.bat",
                                ),
                            )
                            if ttool_path:
                                st.session_state["ttool_path"] = ttool_path
                                exe = ttool_path

                                # Resolve provided path
                                search_dir = None
                                if os.path.isdir(exe):
                                    search_dir = exe
                                elif not os.path.isfile(exe):
                                    parent = os.path.dirname(exe)
                                    if parent and os.path.isdir(parent):
                                        search_dir = parent

                                base_dir = search_dir or os.path.dirname(exe)
                                if search_dir:
                                    jar_candidate = os.path.join(search_dir, "bin", "ttool.jar")
                                    if os.path.isfile(jar_candidate):
                                        exe = jar_candidate
                                    else:
                                        for cand in ["ttool.exe", "ttool_windows.exe", "ttool_windows.bat", "ttool_windows", "ttool.jar"]:
                                            candidate = os.path.join(search_dir, cand)
                                            if os.path.isfile(candidate):
                                                exe = candidate
                                                break

                                if (not os.path.isfile(exe)) and exe.lower().endswith(".exe"):
                                    alt = exe[:-4] + ".bat"
                                    if os.path.isfile(alt):
                                        exe = alt
                                if not os.path.isfile(exe):
                                    jar_peer = os.path.join(base_dir, "bin", "ttool.jar") if base_dir else None
                                    if jar_peer and os.path.isfile(jar_peer):
                                        exe = jar_peer

                                if not os.path.isfile(exe):
                                    st.error(f"TTool executable not found at '{exe}'. Please provide the full path to ttool.exe/ttool.jar or its folder.")
                                else:
                                    try:
                                        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-8") as tf:
                                            tf.write(xml_with_steps)
                                            temp_path = os.path.abspath(tf.name)
                                        run_cwd = base_dir or os.path.dirname(exe) or None
                                        config_arg = ["-config", os.path.join(base_dir, "config_windows.xml")] if base_dir else []
                                        if exe.lower().endswith(".bat"):
                                            jar_path = os.path.join(base_dir, "bin", "ttool.jar") if base_dir else None
                                            if jar_path and os.path.isfile(jar_path):
                                                subprocess.Popen(["java", "-jar", jar_path, *config_arg, "-open", temp_path], cwd=run_cwd)
                                            else:
                                                subprocess.Popen(["cmd", "/c", exe, temp_path], cwd=run_cwd)
                                        elif exe.lower().endswith(".jar"):
                                            subprocess.Popen(["java", "-jar", exe, *config_arg, "-open", temp_path], cwd=run_cwd)
                                        else:
                                            subprocess.Popen([exe, *config_arg, "-open", temp_path], cwd=run_cwd)
                                        st.success(f"Launched TTool with {temp_path}")
                                    except Exception as e:
                                        st.error(f"Failed to open in TTool: {e}")
                            else:
                                st.warning("Enter the TTool executable path to launch.")
            else:
                st.success("Already finalized.")
                ucd_instance.processData(st.session_state["ucd_dataset"])
                st.success("Verification complete.")
                ucd_instance.showUcdTables(st.session_state["ucd_dataset"])
                steps = element_validation.collect_issue_steps(st.session_state["ucd_dataset"])
                raw_xml = st.session_state.get("uploaded_xml", "")
                if raw_xml:
                    xml_with_steps = element_validation.append_activity_panel(raw_xml, steps)
                    download_clicked = st.download_button(
                        "Download verification_with_activity.xml",
                        data=xml_with_steps,
                        file_name="verification_with_activity.xml",
                        mime="application/xml",
                        use_container_width=True,
                    )
                    # Auto-launch TTool (app only) right after download
                    if download_clicked:
                        default_ttool = "C:\\Users\\mages\\Downloads\\releaseTTool_2_0\\TTool\\ttool_windows.bat"
                        ttool_path = st.session_state.get("ttool_path", default_ttool)
                        st.session_state["ttool_path"] = ttool_path
                        ok, msg = _launch_ttool_app(ttool_path)
                        if ok:
                            st.info("File downloaded. TTool opened separately; load the XML manually if needed.")
                        else:
                            st.warning(f"Download saved. TTool not opened: {msg} (using path: {ttool_path})")
        else:
            st.warning("⚠️ You must confirm classifications for all UCDs before finalizing.")

import streamlit as st
from ucd_validation_operation import ucd_validation_operation, element_validation
import hashlib
import os
import tempfile
import subprocess


def _launch_ttool_app(exe_path: str):
    """
    Resolve exe/jar/bat and launch TTool without opening any file.
    Returns (ok, message)
    """
    if not exe_path:
        return False, "TTool path is empty."

    exe = exe_path
    search_dir = None
    if os.path.isdir(exe):
        search_dir = exe
    elif not os.path.isfile(exe):
        parent = os.path.dirname(exe)
        if parent and os.path.isdir(parent):
            search_dir = parent

    if search_dir:
        jar_candidate = os.path.join(search_dir, "bin", "ttool.jar")
        if os.path.isfile(jar_candidate):
            exe = jar_candidate
        else:
            for cand in ["ttool.exe", "ttool_windows.exe", "ttool_windows.bat", "ttool_windows", "ttool.jar"]:
                candidate = os.path.join(search_dir, cand)
                if os.path.isfile(candidate):
                    exe = candidate
                    break

    base_dir = search_dir or os.path.dirname(exe)
    if (not os.path.isfile(exe)) and exe.lower().endswith(".exe"):
        alt = exe[:-4] + ".bat"
        if os.path.isfile(alt):
            exe = alt
    if not os.path.isfile(exe):
        jar_peer = os.path.join(base_dir, "bin", "ttool.jar") if base_dir else None
        if jar_peer and os.path.isfile(jar_peer):
            exe = jar_peer

    if not os.path.isfile(exe):
        return False, f"TTool executable not found at '{exe}'. Please provide the full path."

    run_cwd = base_dir or os.path.dirname(exe) or None
    config_arg = ["-config", os.path.join(base_dir, "config_windows.xml")] if base_dir else []
    try:
        if exe.lower().endswith(".bat"):
            jar_path = os.path.join(base_dir, "bin", "ttool.jar") if base_dir else None
            if jar_path and os.path.isfile(jar_path):
                subprocess.Popen(["java", "-jar", jar_path, *config_arg], cwd=run_cwd)
            else:
                subprocess.Popen(["cmd", "/c", exe], cwd=run_cwd)
        elif exe.lower().endswith(".jar"):
            subprocess.Popen(["java", "-jar", exe, *config_arg], cwd=run_cwd)
        else:
            subprocess.Popen([exe, *config_arg], cwd=run_cwd)
        return True, "Launched TTool."
    except Exception as e:
        return False, f"Failed to launch TTool: {e}"

def get_file_hash(file):
    return hashlib.md5(file.getvalue()).hexdigest() if file else None
