import pymysql
import streamlit as st
from contextlib import contextmanager

class connection:
    _TIMEOUT = 10

    @staticmethod
    def _get_connection():
        # Use st.secrets for credentials
        db_config = st.secrets["mysql"]
        return pymysql.connect(
            host=db_config["host"],
            port=db_config["port"],
            user=db_config["user"],
            password=db_config["password"],
            db=db_config["database"],
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=connection._TIMEOUT,
            read_timeout=connection._TIMEOUT,
            write_timeout=connection._TIMEOUT,
            cursorclass=pymysql.cursors.DictCursor,
        )

    @staticmethod
    @contextmanager
    def get_cursor(dictionary: bool = False):
        # Create a new connection per request/context to ensure thread safety
        conn = connection._get_connection()
        try:
            if dictionary:
                cur = conn.cursor(pymysql.cursors.DictCursor)
            else:
                cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        finally:
            conn.close()

    @staticmethod
    def commit():
        # With the new pattern, commit is handled in get_cursor context
        # This method might be redundant but kept for compatibility if needed,
        # though ideally logic should move to using the context manager properly.
        pass

    @staticmethod
    def rollback():
        pass

    @staticmethod
    def close_connection(conn=None):
        # Connections are closed automatically in the context manager
        pass