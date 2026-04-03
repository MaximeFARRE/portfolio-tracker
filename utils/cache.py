"""
Compatibilité : utils/cache.py utilise désormais le singleton de core/db_connection.py
au lieu de st.cache_resource, pour fonctionner sans Streamlit.
"""
import sqlite3
from core.db_connection import get_connection


def cached_conn() -> sqlite3.Connection:
    """Retourne la connexion singleton (remplace @st.cache_resource)."""
    return get_connection()


def reset_cache():
    """No-op : plus de cache Streamlit à vider."""
    pass
