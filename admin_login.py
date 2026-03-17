import streamlit as st
import resetpassword
from admin_login_operations import admin_login_operations
from connection import connection

def app():
    st.title("Admin Login Portal")

    view = st.radio(
        "Choose an option:",
        ["Login", "Forgot password"],
        key="nav_choice",
        horizontal=True,
    )

    if view == "Login":
        with st.form("login_form", clear_on_submit=True):
            username = st.text_input("Enter your Username")
            password = st.text_input("Enter your Password", type="password")
            login_button = st.form_submit_button("Login")

        if login_button:
            ok = admin_login_operations.verifyUser(username,password)
            if ok:
                st.success("Logged in")
            else:
                st.error("Invalid credentials")
    else:
        resetpassword.app()

    connection.close_connection()