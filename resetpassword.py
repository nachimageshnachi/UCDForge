import streamlit as st
from admin_login_operations import admin_login_operations
from connection import connection
import bcrypt

def app():
    
    st.title("Reset Password")

    with st.form("reset_password_form", clear_on_submit=True):
        username = st.text_input("Enter your username or Email address").lower()
        submitted = st.form_submit_button("Submit")
        username = username.lower().strip()

    if submitted:
        with connection.get_cursor() as cursor:
            cursor.execute(
                "SELECT email_id FROM credentials WHERE username = %s OR email_id = %s",
                (username, username),
            )
            user = cursor.fetchone()

        if not user:
            st.error("No users found in the database.")
            return

        user_mail_id = user["email_id"]
        st.session_state["reset_user"] = user_mail_id
        otp = admin_login_operations.generateOtp()
        admin_login_operations.otp = otp
        admin_login_operations.resetPassword(user_mail_id, otp)
        st.success(f"Verification code sent to {user_mail_id}")

    if "reset_user" in st.session_state:
        code_input = st.text_input("Enter verification code")

        if code_input:
            try:
                code_input = int(code_input)
                expected_code = admin_login_operations.otp
                if code_input == expected_code:
                    st.session_state["code_verified"] = True
                else:
                    st.error("Invalid Code. Please Try Again!")
            except ValueError:
                st.error("Please enter a valid numeric code.")

    if st.session_state.get("code_verified"):
        new_password = st.text_input("Enter new password", type="password")
        hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
        confirm = st.button("Reset Password")
        if confirm:
            with connection.get_cursor() as cursor:
                cursor.execute(
                    "UPDATE credentials SET hash_password = %s WHERE email_id = %s",
                    (hashed_password, st.session_state["reset_user"]),
                )
                connection.commit()
            st.success("Password reset successfully.")
            for key in ["reset_user", "code_verified"]:
                st.session_state.pop(key, None)
            st.session_state["reset_complete"] = True
            st.rerun()
