from __future__ import annotations

import sqlite3

IMPORT_SOURCE_TRADE_REPUBLIC = "TRADE_REPUBLIC"


def _norm_import_source(import_source: str) -> str:
    return (import_source or "").strip().upper()


def _norm_symbol(raw_symbol: str | None) -> str:
    return (raw_symbol or "").strip().upper()


def _norm_isin(raw_isin: str | None) -> str:
    return (raw_isin or "").strip().upper()


def _to_int(row, key: str, fallback_idx: int = 0) -> int:
    if hasattr(row, "keys"):
        return int(row[key])
    return int(row[fallback_idx])


def _to_str(row, key: str, fallback_idx: int = 0) -> str:
    if hasattr(row, "keys"):
        return str(row[key] or "")
    return str(row[fallback_idx] or "")


def _ensure_alias_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_import_aliases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          import_source TEXT NOT NULL,
          raw_symbol TEXT NOT NULL DEFAULT '',
          raw_isin TEXT NOT NULL DEFAULT '',
          canonical_asset_id INTEGER NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT DEFAULT (datetime('now')),
          last_used_at TEXT DEFAULT (datetime('now')),
          FOREIGN KEY(canonical_asset_id) REFERENCES assets(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_import_aliases_key "
        "ON asset_import_aliases(import_source, raw_symbol, raw_isin)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_import_aliases_source_symbol "
        "ON asset_import_aliases(import_source, raw_symbol)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_import_aliases_source_isin "
        "ON asset_import_aliases(import_source, raw_isin)"
    )
    conn.commit()


def _find_asset_by_isin(conn: sqlite3.Connection, raw_isin: str) -> dict | None:
    isin = _norm_isin(raw_isin)
    if not isin:
        return None

    row = conn.execute(
        """
        SELECT a.id AS asset_id, a.symbol, a.name
        FROM asset_meta am
        JOIN assets a ON a.id = am.asset_id
        WHERE UPPER(COALESCE(am.isin, '')) = ?
        ORDER BY a.id
        LIMIT 1
        """,
        (isin,),
    ).fetchone()
    if row is not None:
        return {
            "asset_id": _to_int(row, "asset_id"),
            "symbol": _to_str(row, "symbol", 1),
            "name": _to_str(row, "name", 2),
            "match_source": "isin",
        }

    # Compat legacy: certains imports historiques stockaient l'ISIN comme symbol.
    row = conn.execute(
        "SELECT id AS asset_id, symbol, name FROM assets WHERE UPPER(symbol) = ? LIMIT 1",
        (isin,),
    ).fetchone()
    if row is None:
        return None
    return {
        "asset_id": _to_int(row, "asset_id"),
        "symbol": _to_str(row, "symbol", 1),
        "name": _to_str(row, "name", 2),
        "match_source": "isin_legacy_symbol",
    }


def find_canonical_asset_for_import(
    conn: sqlite3.Connection,
    import_source: str,
    *,
    raw_symbol: str | None = None,
    raw_isin: str | None = None,
) -> dict | None:
    """
    Résout un actif canonique pour un import externe.

    Priorité:
    1) ISIN déjà connu en base (asset_meta.isin ou assets.symbol legacy)
    2) alias mémorisé (asset_import_aliases)
    """
    source = _norm_import_source(import_source)
    symbol = _norm_symbol(raw_symbol)
    isin = _norm_isin(raw_isin)
    if not source:
        return None

    # 1) Matching ISIN prioritaire
    by_isin = _find_asset_by_isin(conn, isin)
    if by_isin is not None:
        return by_isin

    if not symbol and not isin:
        return None

    # 2) Alias import mémorisé
    _ensure_alias_table(conn)
    row = conn.execute(
        """
        SELECT
          aia.canonical_asset_id AS asset_id,
          a.symbol AS symbol,
          a.name AS name
        FROM asset_import_aliases aia
        JOIN assets a ON a.id = aia.canonical_asset_id
        WHERE aia.import_source = ?
          AND (
            (? <> '' AND aia.raw_isin = ?)
            OR (? <> '' AND aia.raw_symbol = ?)
          )
        ORDER BY
          CASE WHEN (? <> '' AND aia.raw_isin = ?) THEN 0 ELSE 1 END,
          CASE WHEN (? <> '' AND aia.raw_symbol = ?) THEN 0 ELSE 1 END,
          aia.updated_at DESC
        LIMIT 1
        """,
        (source, isin, isin, symbol, symbol, isin, isin, symbol, symbol),
    ).fetchone()
    if row is None:
        return None

    conn.execute(
        """
        UPDATE asset_import_aliases
        SET last_used_at = datetime('now')
        WHERE canonical_asset_id = ?
          AND import_source = ?
          AND (
            (? <> '' AND raw_isin = ?)
            OR (? <> '' AND raw_symbol = ?)
          )
        """,
        (_to_int(row, "asset_id"), source, isin, isin, symbol, symbol),
    )
    conn.commit()

    return {
        "asset_id": _to_int(row, "asset_id"),
        "symbol": _to_str(row, "symbol", 1),
        "name": _to_str(row, "name", 2),
        "match_source": "alias",
    }


def upsert_import_alias(
    conn: sqlite3.Connection,
    import_source: str,
    *,
    canonical_asset_id: int,
    raw_symbol: str | None = None,
    raw_isin: str | None = None,
) -> bool:
    """Crée ou met à jour un alias import -> actif canonique."""
    source = _norm_import_source(import_source)
    symbol = _norm_symbol(raw_symbol)
    isin = _norm_isin(raw_isin)
    if not source or not canonical_asset_id:
        return False
    if not symbol and not isin:
        return False

    _ensure_alias_table(conn)
    conn.execute(
        """
        INSERT INTO asset_import_aliases(
          import_source, raw_symbol, raw_isin, canonical_asset_id,
          created_at, updated_at, last_used_at
        )
        VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
        ON CONFLICT(import_source, raw_symbol, raw_isin) DO UPDATE SET
          canonical_asset_id = excluded.canonical_asset_id,
          updated_at = datetime('now'),
          last_used_at = datetime('now')
        """,
        (source, symbol, isin, int(canonical_asset_id)),
    )
    conn.commit()
    return True
