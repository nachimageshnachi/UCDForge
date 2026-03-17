import streamlit as st
from connection import connection
import pandas as pd

class view_operations:
    
    editable_columns_by_table = {
        "actors": ["actor_type"],
        "relations": ["extension"],
        "systems": ["description", "domain"],
        "use_cases": ["description", "category"]
    }

    @staticmethod
    def dataFromTables():
        with connection.get_cursor() as cursor:
            cursor.execute("SHOW TABLES")
            table_names = [list(row.values())[0] for row in cursor.fetchall()]
        
        if "credentials" in table_names:
            table_names.remove("credentials")
        
        if not table_names:
            st.warning("No tables found.")
            return
        
        st.title("Tabbed View of All Tables")
        
        display_table_names = {
            "actors":    "Actors",
            "relations": "Relations",
            "systems":   "Systems",
            "use_cases": "Use Cases",
        }
        tabs = st.tabs([display_table_names.get(t, t.title()) for t in table_names])
        
        for tab, table in zip(tabs, table_names):
            tab_label = display_table_names.get(table, table.title())
            with tab:
                with connection.get_cursor() as cursor:
                    st.subheader(f"Table: `{tab_label}`")
                    cursor.execute(f"SELECT * FROM `{table}`")
                    rows = cursor.fetchall()
                    if rows:
                        df = pd.DataFrame(rows)
                        st.dataframe(df, use_container_width=True)
                        st.success(f"Fetched {len(df)} rows from `{table}`.")
                    
                    else:
                        st.info(f"No rows in `{table}`.")
                
        
        print("All Table's are Retrieved")
        