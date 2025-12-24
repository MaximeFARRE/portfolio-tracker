import streamlit as st
import sqlite3
from services.db import get_conn, init_db, seed_minimal


@st.cache_resource
def cached_conn() -> sqlite3.Connection:
    # Initialise DB + seed au premier lancement
    init_db()
    seed_minimal()
    return get_conn()


def reset_cache():
    st.cache_resource.clear()
    st.cache_data.clear()
