import streamlit as st
from connection import connection
import pandas as pd
import json

class edit_operations:
    editable_columns_by_table = {
        "cases":     ["description", "domain_json"],
        "use_cases": ["description"],
    }

    @staticmethod
    def _table_list():
        with connection.get_cursor() as cur:
            cur.execute("SHOW TABLES")
            return [list(r.values())[0] for r in cur.fetchall()
                    if list(r.values())[0].lower() != "credentials"]

    @staticmethod
    def _pk_column(table):
        with connection.get_cursor() as cur:
            cur.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name='PRIMARY'")
            return cur.fetchone()["Column_name"]

    @classmethod
    def _editable_cols(cls, table):
        return cls.editable_columns_by_table.get(table, [])

    @classmethod
    def dataFromTables(cls):
        tables = cls._table_list()
        if not tables:
            st.warning("No tables found.")
            return

        label = lambda t: t.replace("_", " ").title()
        st.title("Database Tables")
        tabs = st.tabs([label(t) for t in tables])

        for tab, table in zip(tabs, tables):
            with tab:
                cls._render_table(table, label(table))

        if any(v for k, v in st.session_state.items() if k.startswith("unsaved_")):
            st.warning("⚠️ You have unsaved edits in at least one tab!")

    @classmethod
    def _render_table(cls, table, nice_name):
        st.subheader(f"`{nice_name}`")

        with connection.get_cursor(dictionary=True) as cur:
            cur.execute(f"SELECT * FROM `{table}`")
            rows = cur.fetchall()
        if not rows:
            st.info("No rows yet.")
            return

        df = pd.DataFrame(rows)

        # ✅ Display JSON list as comma-separated string
        if table == "cases" and "domain_json" in df.columns:
            def list_to_string(val):
                try:
                    parsed = json.loads(val) if isinstance(val, str) else val
                    return ", ".join(parsed) if isinstance(parsed, list) else ""
                except Exception:
                    return str(val) if val else ""
            df["domain_json"] = df["domain_json"].apply(list_to_string)

        editable = cls._editable_cols(table)
        disabled = [c for c in df.columns if c not in editable]

        column_config = {}
        for col in editable:
            column_config[col] = st.column_config.TextColumn(
                label=col,
                help="Comma-separated values" if col == "domain_json" else None
            )

        editor_key = f"editor_{table}"
        edited = st.data_editor(
            df,
            key=editor_key,
            use_container_width=True,
            disabled=disabled,
            column_config=column_config
        )

        if not editable:
            st.info("This table is read-only.")
            return

        changed = (df[editable].fillna("") != edited[editable].fillna("")).any(axis=1)
        st.session_state[f"unsaved_{table}"] = changed.any()

        if st.button("Save changes", key=f"save_{table}"):
            pk = cls._pk_column(table)
            updates = 0
            with connection.get_cursor() as cur:
                for idx, row_changed in changed.items():
                    if not row_changed:
                        continue
                    delta = {}
                    for col in editable:
                        new_val = edited.at[idx, col]
                        old_val = df.at[idx, col]
                        if new_val != old_val:
                            if col == "domain_json":
                                delta[col] = json.dumps([
                                    v.strip() for v in new_val.split(",") if v.strip()
                                ])
                            else:
                                delta[col] = new_val
                    if not delta:
                        continue
                    set_clause = ", ".join(f"`{c}` = %s" for c in delta)
                    sql = f"UPDATE `{table}` SET {set_clause} WHERE `{pk}` = %s"
                    cur.execute(sql, list(delta.values()) + [df.at[idx, pk]])
                    updates += 1

            st.session_state[f"unsaved_{table}"] = False
            if updates:
                st.success(f"Updated {updates} row(s).")
                st.rerun()
            else:
                st.info("Nothing to save.")
