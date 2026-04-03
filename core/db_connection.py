"""
Singleton de connexion à la base de données.
Remplace utils/cache.py (st.cache_resource) pour l'application Qt.
Une seule connexion est maintenue pour toute la durée de vie de l'application.

Ordre d'initialisation :
  1. init_db()       → crée les tables (schema.sql + migrations)
  2. seed_minimal()  → insère les données de base si la DB est vide
  3. get_conn()      → retourne la connexion singleton
"""
import logging
from services.db import get_conn, init_db, seed_minimal, ensure_credits_migrations

_logger = logging.getLogger(__name__)
_conn = None


def get_connection():
    """Retourne la connexion singleton, en l'initialisant si nécessaire."""
    global _conn
    if _conn is None:
        _logger.info("Initialisation de la base de données...")
        init_db()
        seed_minimal()
        _conn = get_conn()
        # Migrations additionnelles (colonnes ajoutées post-schéma initial)
        ensure_credits_migrations(_conn)
        _logger.info("Connexion DB prête.")
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
