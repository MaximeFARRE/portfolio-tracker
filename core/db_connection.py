"""
Singleton de connexion à la base de données.
Remplace utils/cache.py (st.cache_resource) pour l'application Qt.
Une seule connexion est maintenue pour toute la durée de vie de l'application.
"""
from services.db import get_conn, init_db, seed_minimal

_conn = None


def get_connection():
    """Retourne la connexion singleton, en l'initialisant si nécessaire."""
    global _conn
    if _conn is None:
        init_db()
        seed_minimal()
        _conn = get_conn()
    return _conn


def close_connection():
    """Ferme proprement la connexion à l'arrêt de l'application."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
