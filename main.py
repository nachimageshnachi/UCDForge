import streamlit as st
st.set_page_config(page_title="Methodological Assistant for SysML")

from streamlit_option_menu import option_menu
import home, ucd_verification, ucd_generation, admin_login, resetpassword, view, edit, logout, fileupload

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "logout_triggered" not in st.session_state:
    st.session_state["logout_triggered"] = False
if "just_logged_out" not in st.session_state:
    st.session_state["just_logged_out"] = False
if "menu_selection" not in st.session_state:
    st.session_state["menu_selection"] = "Home"

class MultiApp:
    def __init__(self):
        self.apps = []

    def addApp(self, title, func, login_required=False):
        self.apps.append({
            "title": title,
            "function": func,
            "login_required": login_required
        })

    def run(self):
        with st.sidebar:

            if not st.session_state["logged_in"]:
                menu_options = ["Home", "UCD Verification", "UCD Generation", "Admin Login"]
                if st.session_state["menu_selection"] not in menu_options:
                    st.session_state["menu_selection"] = menu_options[0]

                app = option_menu(
                    menu_title="Menu",
                    options=menu_options,
                    icons=["house-door", "diagram-3", "diagram-3", "person"],
                    menu_icon="list",
                    default_index=menu_options.index(st.session_state["menu_selection"]),
                    styles={
                        "container": {"padding": "5!important", "background-color": "#FFFFFF"},
                        "icon": {"color": "black", "font-size": "23px"},
                        "nav-link": {"color": "black", "font-size": "20px", "text-align": "left"},
                        "nav-link-selected": {"background-color": "#02ab21"}
                    }
                )   

            else:
                menu_options = ["Upload XML", "View", "Edit", "Logout"]
                if st.session_state["menu_selection"] not in menu_options:
                    st.session_state["menu_selection"] = menu_options[0]

                app = option_menu(
                    menu_title="Logged In",
                    options=menu_options,
                    icons=["file-earmark-arrow-up-fill", "eye", "pencil", "box-arrow-left"],
                    menu_icon="person",
                    default_index=menu_options.index(st.session_state["menu_selection"]),
                    styles={
                        "container": {"padding": "5!important", "background-color": "#FFFFFF"},
                        "icon": {"color": "black", "font-size": "23px"},
                        "nav-link": {"color": "black", "font-size": "20px", "text-align": "left"},
                        "nav-link-selected": {"background-color": "#02ab21"}
                    }
                )

            if app != st.session_state["menu_selection"]:
                st.session_state["menu_selection"] = app
                st.rerun()

        for a in self.apps:
            if a["title"] == app:
                if a.get("login_required", False) and not st.session_state["logged_in"]:
                    st.error("You must be logged in to access this page.")
                    return
                st.session_state["current_page"] = a["title"].replace(" ", "_").lower()
                a["function"]()
                return

app = MultiApp()
app.addApp("Home", home.app)
app.addApp("UCD Verification", ucd_verification.app)
app.addApp("UCD Generation", ucd_generation.app)
app.addApp("Admin Login", admin_login.app)
app.addApp("Reset Password", resetpassword.app)
app.addApp("Upload XML", fileupload.app, login_required=True)
app.addApp("View", view.app, login_required=True)
app.addApp("Edit", edit.app, login_required=True)
app.addApp("Logout", logout.app, login_required=True)

app.run()
