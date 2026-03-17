import streamlit as st
from helpers import get_db_values, match_case, reverse_lookup, TextValidationTools
from connection import connection
import time

def app():
    # st.set_page_config(page_title="UCD Generation")
    st.title("Case-Based Reasoning for Use Case Diagrams")

    st.markdown("Start typing keywords — suggestions will appear based on past cases, or add your own.")

    db_values = get_db_values()

    def build_autocomplete_list(expanded_dict):
        results = set()
        for readable, data in expanded_dict.items():
            results.add(TextValidationTools.normalize(readable))
            results.update(TextValidationTools.normalize(s) for s in data["synonyms"])
        return sorted(results)

    actor_options = build_autocomplete_list(db_values["actors"])
    usecase_options = build_autocomplete_list(db_values["use_cases"])
    domain_options = sorted(TextValidationTools.normalize(d) for d in db_values["domains"])

    def normalize_comma_input(text):
        return [TextValidationTools.normalize(x) for x in text.split(",") if x.strip()]

    with st.form("smart_input_form"):
        title = st.text_input("Case Title", placeholder="e.g. Online Ticket Booking")
        description = st.text_area("Scenario Description", height=120)

        selected_domains = st.multiselect("Domain(s)", options=domain_options)
        custom_domains = st.text_input("Custom Domain(s) — comma separated")

        selected_actors = st.multiselect("Key Actors", actor_options)
        custom_actors = st.text_input("Custom Actor(s) — comma separated")

        selected_use_cases = st.multiselect("Use Cases", usecase_options)
        custom_usecases = st.text_input("Custom Use Case(s) — comma separated")

        submitted = st.form_submit_button("Match Best Case")

    if submitted:
        if not title.strip():
            st.error("Title is required.")
            return
        if not (selected_actors or selected_use_cases or custom_actors or custom_usecases):
            st.error("At least one actor or use case must be provided.")
            return

        final_domains = selected_domains + normalize_comma_input(custom_domains)
        final_actors = [reverse_lookup(db_values["actors"], a) for a in selected_actors + normalize_comma_input(custom_actors)]
        final_use_cases = [reverse_lookup(db_values["use_cases"], u) for u in selected_use_cases + normalize_comma_input(custom_usecases)]

        user_input = {
            "title": title.strip(),
            "description": description.strip(),
            "domains": final_domains,
            "actors": final_actors,
            "use_cases": final_use_cases
        }

        with st.spinner("Matching best case..."):
            time.sleep(1)
            match = match_case(user_input)

            if match:
                st.success("✅ Match found!")
                st.subheader("🎯 Matched Use Case")
                st.markdown(f"""
                - **Title:** `{match['title']}`
                - **Similarity Score:** `{round(match['total_score'] * 100)}%`
                """)

                with connection.get_cursor() as cursor:
                    cursor.execute(
                        "SELECT xml_content FROM diagrams WHERE case_id = %s ORDER BY created_at DESC LIMIT 1",
                        (match["case_id"],)
                    )
                    result = cursor.fetchone()
                    if result:
                        st.download_button(
                            "Download Matched Use Case Diagram",
                            data=result["xml_content"],
                            file_name=f"{match['title'].replace(' ', '_')}.xml",
                            mime="application/xml"
                        )
                    else:
                        st.info("No diagram found for the matched case.")
            else:
                st.warning("No similar case found.")
