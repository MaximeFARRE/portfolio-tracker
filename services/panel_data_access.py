"""
Requêtes SQL élémentaires utilisées par les panels Qt.
Centralise les lookups directs (assets, prices, credits) afin que la UI
n'exécute plus de SQL brut.  Retourne des sqlite3.Row ou None.
"""
from __future__ import annotations


def get_asset_symbol(conn, asset_id: int):
    """Retourne la row (symbol,) de l'actif, ou None."""
    return conn.execute(
        "SELECT symbol FROM assets WHERE id = ?",
        (int(asset_id),),
    ).fetchone()


def list_non_coted_assets_with_last_price(conn, asset_ids: list[int]):
    """Retourne les actifs non-cotés (scpi, pe, fonds…) avec leur dernier prix connu."""
    if not asset_ids:
        return []
    placeholders = ",".join("?" * len(asset_ids))
    return conn.execute(
        f"""
        SELECT
            a.id        AS asset_id,
            a.symbol,
            a.name,
            a.asset_type,
            a.currency,
            (SELECT p.price FROM prices p
             WHERE p.asset_id = a.id
             ORDER BY p.date DESC LIMIT 1) AS last_price,
            (SELECT p.date FROM prices p
             WHERE p.asset_id = a.id
             ORDER BY p.date DESC LIMIT 1) AS last_price_date
        FROM assets a
        WHERE a.id IN ({placeholders})
          AND a.asset_type IN (
              'scpi','private_equity','non_cote',
              'fonds','fonds_euros','autre'
          )
        ORDER BY a.name
        """,
        tuple(asset_ids),
    ).fetchall()


def get_latest_asset_price(conn, asset_id: int):
    """Retourne la row (price, date, currency) du dernier prix enregistré, ou None."""
    return conn.execute(
        """
        SELECT p.price, p.date, p.currency
        FROM prices p
        WHERE p.asset_id = ?
        ORDER BY p.date DESC
        LIMIT 1
        """,
        (int(asset_id),),
    ).fetchone()


def get_asset_currency(conn, asset_id: int):
    """Retourne la row (currency,) de l'actif, ou None."""
    return conn.execute(
        "SELECT currency FROM assets WHERE id = ?",
        (int(asset_id),),
    ).fetchone()


def get_credit_by_id(conn, credit_id: int):
    """Retourne la row complète du crédit, ou None."""
    return conn.execute(
        "SELECT * FROM credits WHERE id = ?",
        (int(credit_id),),
    ).fetchone()


def get_credit_account_and_person(conn, credit_id: int):
    """Retourne la row (account_id, person_id) du crédit, ou None."""
    return conn.execute(
        "SELECT account_id, person_id FROM credits WHERE id = ?",
        (int(credit_id),),
    ).fetchone()


def asset_symbol_exists(conn, symbol: str) -> bool:
    """Retourne True si un actif avec ce symbole existe déjà."""
    return conn.execute(
        "SELECT id FROM assets WHERE symbol = ?",
        (symbol,),
    ).fetchone() is not None


def get_asset_symbol_name(conn, asset_id: int):
    """Retourne la row (symbol, name) de l'actif, ou None."""
    return conn.execute(
        "SELECT symbol, name FROM assets WHERE id = ?",
        (int(asset_id),),
    ).fetchone()


def get_asset_type(conn, asset_id: int):
    """Retourne la row (asset_type,) de l'actif, ou None."""
    return conn.execute(
        "SELECT asset_type FROM assets WHERE id = ?",
        (int(asset_id),),
    ).fetchone()
