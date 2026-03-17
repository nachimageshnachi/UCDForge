import streamlit as st
from email.message import EmailMessage
from connection import connection
import bcrypt
import ssl
import smtplib
import random

class admin_login_operations:
    otp=0;
    @staticmethod
    def createTableCredentials():
        with connection.get_cursor() as cursor:
            statement = """
                CREATE TABLE credentials (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    email_id VARCHAR(255) NOT NULL UNIQUE,
                    hash_password VARBINARY(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """

            cursor.execute(statement)

        st.success("Created Credentials Table")
        
    @staticmethod
    def destroyCredentials():
        with connection.get_cursor() as cursor:

            cursor.execute("DROP TABLE credentials")

        st.success("Destroyed Credentials Table")
    
    @staticmethod 
    def addCredentialsToDB():
        with st.form("add_credentials_form"):
            username = st.text_input("Enter Username")
            email = st.text_input("Enter Email ID")
            raw_password = st.text_input("Enter Password", type="password")
            submitted = st.form_submit_button("Add Credentials")
            
            if submitted:
                if username and email and raw_password:
                    hashed_password = bcrypt.hashpw(raw_password.encode(), bcrypt.gensalt())
                    with connection.get_cursor() as cursor:
                        cursor.execute("INSERT INTO credentials (username, email_id, hash_password) VALUES (%s, %s, %s)",(username.lower(),email.lower(),hashed_password))
                    st.success('User Credentials Inserted Successfully')
                else:
                    st.error("Please fill all fields")
    
    @staticmethod
    def clearCredentials():
        with connection.get_cursor() as cursor:

            cursor.execute("DELETE FROM credentials")

        st.success("Cleared Credentials Table")
        
    @staticmethod
    def alterUsersPassword():
        with st.form("alter_password_form"):
            username = st.text_input("Enter Username to update")
            new_password = st.text_input("Enter New Password", type="password")
            submitted = st.form_submit_button("Update Password")

            if submitted:
                if username and new_password:
                    new_hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
                    
                    with connection.get_cursor() as cursor:
                        cursor.execute("SELECT username, email_id FROM credentials WHERE username = %s OR email_id = %s", (username, username))
                        user = cursor.fetchone()
                        
                        if user:
                            user_mail_id = user['email_id']
                            cursor.execute("UPDATE credentials SET hash_password = %s WHERE email_id = %s",(new_hashed, user_mail_id))
                            st.success("Password updated successfully.")
                        else:
                            st.error("Username not found.")
                else:
                    st.error("Please fill all fields")

    @staticmethod
    def verifyUser(username, password):
        with connection.get_cursor(dictionary=True) as cursor:
        
            cursor.execute("SELECT hash_password FROM credentials WHERE username = %s OR LOWER(email_id) = %s", (username.lower(),username.lower()))
            user = cursor.fetchone()
            
            if user is not None:
                stored_hashed = user["hash_password"]
                # Ensure stored_hashed is bytes
                if isinstance(stored_hashed, str):
                    stored_hashed = stored_hashed.encode('utf-8')
                
                if bcrypt.checkpw(password.encode(), stored_hashed):
                    st.success("Login successful!")
                    st.session_state["logged_in"] = True
                    st.rerun()
                else:
                    st.error("Invalid Credentials")
            else:
                st.error("Invalid Credentials")
    
    @staticmethod
    def displayAllCredentials():
        with connection.get_cursor(dictionary=True) as cursor:
        
            cursor.execute("SELECT * FROM credentials")

            rows = cursor.fetchall()
            st.write(f"Fetched: {len(rows)} rows")
            st.dataframe(rows)
    
    @staticmethod
    def resetPassword(id, otp):
        sender = st.secrets["email"]["sender"]
        password = st.secrets["email"]["password"]
        receiver=id
        
        subject="Verification Code"
        body=f"""
        We heard that you lost your Methodological Assistant access password. 
        Sorry about that! But don’t worry! 
        You can use the following code to reset your password:
        {otp}
        Thanks,
        Your Assistant's Master Team
        
        You're receiving this email because a password reset was requested for your account.
        """

        em=EmailMessage()
        em['From']=sender
        em['To']=receiver
        em['Subject']=subject
        em.set_content(body)
        
        context=ssl.create_default_context()
        
        with smtplib.SMTP_SSL('smtp.gmail.com',465,context=context) as smtp:
            smtp.login(sender,password)
            smtp.sendmail(sender, receiver, em.as_string())
    
    @staticmethod
    def generateOtp():
        number=random.randint(10000000,99999999)
        return number
        
