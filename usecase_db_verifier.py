import concurrent.futures
from typing import Optional

import streamlit as st

from fetch_ucd_entities import (
    fetch_use_cases,
    fetch_actors,
    validate_use_case_name,
)
import nltk
from nltk.corpus import wordnet as wn


st.set_page_config(page_title="Use-Case Validator", page_icon="✅", layout="wide")


def _format_result(res):
    if res["valid"]:
        return f"✅ **{res['name']}** — OK"
    msg = "; ".join(res["messages"]) if res["messages"] else "Issues found"
    return f"⚠️ **{res['name']}** — {msg}"


def run_validation(case_id: Optional[int]):
    try:
        # Pre-load WordNet once to avoid thread-safety issues in concurrent workers
        try:
            wn.ensure_loaded()
        except Exception:
            nltk.download("wordnet", quiet=True)
            nltk.download("omw-1.4", quiet=True)
            wn.ensure_loaded()

        use_cases = fetch_use_cases(case_id)
        actors = fetch_actors(case_id)
    except Exception as e:
        st.error("Failed to fetch data from the database.")
        with st.expander("Show error details"):
            st.exception(e)
        return

    if not use_cases:
        st.info("No use cases found for the given criteria.")
        return

    st.write(f"Found **{len(use_cases)}** use cases; validating...")
    progress = st.progress(0)
    status = st.empty()
    results_area = [st.empty() for _ in use_cases]

    completed = 0
    max_workers = min(8, max(1, len(use_cases)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(validate_use_case_name, uc, actors): idx
            for idx, uc in enumerate(use_cases)
        }
        for future in concurrent.futures.as_completed(future_map):
            idx = future_map[future]
            try:
                res = future.result()
            except Exception as e:
                res = {"name": use_cases[idx], "valid": False, "messages": [f"Validation error: {e}"]}
            results_area[idx].markdown(_format_result(res))
            completed += 1
            progress.progress(completed / len(use_cases))
            status.write(f"Validated {completed}/{len(use_cases)}")

    status.success("Validation complete.")


def main():
    st.title("Database Use-Case Validator")
    st.write("Validate all stored use-case names (grammar + actor collisions) using spaCy/Flair.")

    case_id_input = st.text_input("Filter by case_id (optional)")
    case_id: Optional[int] = None
    if case_id_input.strip():
        try:
            case_id = int(case_id_input.strip())
        except ValueError:
            st.warning("case_id must be an integer; ignoring filter.")

    if st.button("Run validation", type="primary"):
        with st.spinner("Running validations..."):
            run_validation(case_id)


if __name__ == "__main__":
    main()
