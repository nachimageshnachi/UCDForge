"""
TTool launcher — resolve and launch TTool executable.

Also includes ``get_file_hash()`` for upload change detection.
"""

import os
import hashlib
import subprocess
from pathlib import Path


def _resolve_ttool_exe(exe_path: str):
    """Resolve exe/jar/bat path from an explicit path or containing directory."""
    if not exe_path:
        return None, None, "TTool path is empty."

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
        return None, None, f"TTool executable not found at '{exe}'. Please provide the full path."

    return exe, base_dir, None


def _launch_ttool(exe: str, base_dir: str | None, extra_args: list[str] | None = None):
    run_cwd = base_dir or os.path.dirname(exe) or None
    config_arg = ["-config", os.path.join(base_dir, "config_windows.xml")] if base_dir else []
    extra_args = extra_args or []
    try:
        if exe.lower().endswith(".bat"):
            jar_path = os.path.join(base_dir, "bin", "ttool.jar") if base_dir else None
            if jar_path and os.path.isfile(jar_path):
                subprocess.Popen(["java", "-jar", jar_path, *config_arg, *extra_args], cwd=run_cwd)
            else:
                subprocess.Popen(["cmd", "/c", exe, *extra_args], cwd=run_cwd)
        elif exe.lower().endswith(".jar"):
            subprocess.Popen(["java", "-jar", exe, *config_arg, *extra_args], cwd=run_cwd)
        else:
            subprocess.Popen([exe, *config_arg, *extra_args], cwd=run_cwd)
        return True, "Launched TTool."
    except Exception as e:
        return False, f"Failed to launch TTool: {e}"


def launch_ttool_app(exe_path: str):
    """
    Resolve exe/jar/bat and launch TTool without opening any file.
    Returns (ok, message)
    """
    exe, base_dir, err = _resolve_ttool_exe(exe_path)
    if err:
        return False, err
    return _launch_ttool(exe, base_dir)


def save_xml_to_default_downloads(file_name: str, xml_content: str):
    """Write the XML export to the user's default Downloads folder."""
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    output_path = downloads_dir / file_name
    output_path.write_text(xml_content, encoding="utf-8")
    return str(output_path)


def launch_ttool_with_file(exe_path: str, xml_path: str):
    """Launch TTool and ask it to open the provided XML file."""
    exe, base_dir, err = _resolve_ttool_exe(exe_path)
    if err:
        return False, err
    return _launch_ttool(exe, base_dir, ["-open", xml_path])


def get_file_hash(file):
    return hashlib.md5(file.getvalue()).hexdigest() if file else None
