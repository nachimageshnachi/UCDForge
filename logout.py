import streamlit as st

def app():
    st.session_state["logged_in"] = False
    st.session_state["logout_triggered"] = True
    st.session_state["just_logged_out"] = True
    st.session_state["menu_selection"] = "Home"
    st.rerun()  # Forces rerun to reset sidebar/menu
