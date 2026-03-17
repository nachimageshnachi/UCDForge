import streamlit as st
from edit_operations import edit_operations
from connection import connection

def app():
  st.title("Edit Page")
  st.write("This is the Edit page.")
  edit_operations.dataFromTables()
  connection.close_connection()