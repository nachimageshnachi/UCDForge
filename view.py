import streamlit as st
from view_operations import view_operations
from connection import connection

def app():
  st.title("View Page")
  st.write("This is the View page.")
  view_operations.dataFromTables()
  connection.close_connection()
