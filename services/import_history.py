# services/import_history.py
"""
AM-19 — Historique des imports avec annulation.

Fournit :
  - create_batch()   : ouvre un nouveau batch d'import, retourne son id
  - close_batch()    : finalise le batch avec le nombre de lignes insérées
  - list_batches()   : liste les batches (pour l'UI historique)
  - rollback_batch() : annule un batch (supprime les lignes associées)
"""
from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers compat sqlite3.Row / libsql tuple
# ---------------------------------------------------------------------------

def _row_val(row, key: str, idx: int = 0):
    if row is None:
        return None
    try:
        return row[key]
    except Exception:
        return row[idx]


# ---------------------------------------------------------------------------
# Création / clôture d'un batch
# ---------------------------------------------------------------------------

def create_batch(
    conn,
    import_type: str,
    person_id: int | None = None,
    person_name: str | None = None,
    account_id: int | None = None,
    account_name: str | None = None,
    filename: str | None = None,
) -> int:
    """
    Crée un nouveau batch d'import et retourne son id.

    import_type : 'TR' | 'BANKIN' | 'DEPENSES' | 'REVENUS'
    """
    cur = conn.execute(
        """INSERT INTO import_batches
             (import_type, person_id, person_name, account_id, account_name, filename, nb_rows, status)
           VALUES (?, ?, ?, ?, ?, ?, 0, 'ACTIVE')""",
        (import_type, person_id, person_name, account_id, account_name, filename),
    )
    conn.commit()
    return cur.lastrowid


def close_batch(conn, batch_id: int, nb_rows: int) -> None:
    """Met à jour le batch avec le nombre de lignes réellement insérées."""
    conn.execute(
        "UPDATE import_batches SET nb_rows = ? WHERE id = ?",
        (nb_rows, batch_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Lecture de l'historique
# ---------------------------------------------------------------------------

def list_batches(conn, limit: int = 100) -> list[dict[str, Any]]:
    """
    Retourne les batches du plus récent au plus ancien.
    Inclut une indication du nombre de lignes encore présentes en base.
    """
    rows = conn.execute(
        """SELECT id, import_type, person_name, account_name,
                  filename, imported_at, nb_rows, status, account_id
           FROM import_batches
           ORDER BY imported_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    alive_by_batch = _count_alive_rows_bulk(conn, rows)

    result = []
    for r in rows:
        batch_id   = _row_val(r, "id", 0)
        itype      = _row_val(r, "import_type", 1)
        status     = _row_val(r, "status", 7)
        alive = int(alive_by_batch.get(int(batch_id), 0))

        result.append({
            "id":           batch_id,
            "import_type":  itype,
            "person_name":  _row_val(r, "person_name", 2),
            "account_name": _row_val(r, "account_name", 3),
            "filename":     _row_val(r, "filename", 4),
            "imported_at":  _row_val(r, "imported_at", 5),
            "nb_rows":      _row_val(r, "nb_rows", 6),
            "status":       status,
            "alive_rows":   alive,
        })
    return result


def _count_rows_by_batch_ids(conn, table: str, batch_ids: list[int]) -> dict[int, int]:
    if not batch_ids:
        return {}
    placeholders = ",".join(["?"] * len(batch_ids))
    rows = conn.execute(
        f"SELECT import_batch_id, COUNT(*) FROM {table} "
        f"WHERE import_batch_id IN ({placeholders}) "
        "GROUP BY import_batch_id",
        tuple(int(bid) for bid in batch_ids),
    ).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _count_alive_rows_bulk(conn, batch_rows) -> dict[int, int]:
    """
    Compte les lignes encore vivantes pour une liste de batches en minimisant
    les allers-retours SQL (évite le N+1 de _count_alive_rows par batch).
    """
    out: dict[int, int] = {}
    if not batch_rows:
        return out

    grouped_ids: dict[str, list[int]] = {
        "TR": [],
        "BANKIN": [],
        "DEPENSES": [],
        "REVENUS": [],
        "CREDIT": [],
    }
    credit_account_by_batch: dict[int, int] = {}

    for r in batch_rows:
        bid = int(_row_val(r, "id", 0))
        itype = str(_row_val(r, "import_type", 1) or "").upper()
        grouped_ids.setdefault(itype, [])
        grouped_ids[itype].append(bid)
        if itype == "CREDIT":
            acc_id = _row_val(r, "account_id", 8)
            if acc_id is not None:
                credit_account_by_batch[bid] = int(acc_id)

    tx_ids = grouped_ids.get("TR", []) + grouped_ids.get("BANKIN", [])
    dep_ids = grouped_ids.get("DEPENSES", [])
    rev_ids = grouped_ids.get("REVENUS", [])
    cred_ids = grouped_ids.get("CREDIT", [])

    out.update(_count_rows_by_batch_ids(conn, "transactions", tx_ids))
    out.update(_count_rows_by_batch_ids(conn, "depenses", dep_ids))
    out.update(_count_rows_by_batch_ids(conn, "revenus", rev_ids))

    if cred_ids:
        account_ids = sorted({credit_account_by_batch.get(bid) for bid in cred_ids if credit_account_by_batch.get(bid) is not None})
        if account_ids:
            placeholders = ",".join(["?"] * len(account_ids))
            rows = conn.execute(
                f"SELECT account_id, COUNT(*) FROM credits "
                f"WHERE account_id IN ({placeholders}) "
                "GROUP BY account_id",
                tuple(int(aid) for aid in account_ids),
            ).fetchall()
            count_by_account = {int(r[0]): int(r[1]) for r in rows}
            for bid in cred_ids:
                acc_id = credit_account_by_batch.get(bid)
                if acc_id is not None:
                    out[bid] = int(count_by_account.get(int(acc_id), 0))

    return out


def _count_alive_rows(conn, batch_id: int, import_type: str) -> int:
    """Compte les lignes encore présentes en base pour ce batch."""
    if import_type in ("TR", "BANKIN"):
        table = "transactions"
    elif import_type == "DEPENSES":
        table = "depenses"
    elif import_type == "REVENUS":
        table = "revenus"
    elif import_type == "CREDIT":
        try:
            r = conn.execute(
                "SELECT account_id FROM import_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if not r or r[0] is None:
                return 0
            r2 = conn.execute(
                "SELECT COUNT(*) FROM credits WHERE account_id = ?", (r[0],)
            ).fetchone()
            return int(r2[0]) if r2 else 0
        except Exception:
            return 0
    else:
        return 0
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Rollback d'un batch
# ---------------------------------------------------------------------------

def rollback_batch(conn, batch_id: int) -> dict[str, Any]:
    """
    Annule un batch d'import :
      - Supprime toutes les lignes associées (transactions / depenses / revenus)
      - Met le batch en status 'ROLLED_BACK'

    Retourne un dict avec le nombre de lignes supprimées par table.
    """
    # Récupérer le type du batch
    row = conn.execute(
        "SELECT import_type, status FROM import_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Batch {batch_id} introuvable.")

    status = _row_val(row, "status", 1)
    if status == "ROLLED_BACK":
        raise ValueError(f"Le batch {batch_id} a déjà été annulé.")

    import_type = _row_val(row, "import_type", 0)

    deleted: dict[str, int] = {}

    if import_type in ("TR", "BANKIN"):
        cur = conn.execute(
            "DELETE FROM transactions WHERE import_batch_id = ?", (batch_id,)
        )
        deleted["transactions"] = cur.rowcount
    elif import_type == "DEPENSES":
        cur = conn.execute(
            "DELETE FROM depenses WHERE import_batch_id = ?", (batch_id,)
        )
        deleted["depenses"] = cur.rowcount
    elif import_type == "REVENUS":
        cur = conn.execute(
            "DELETE FROM revenus WHERE import_batch_id = ?", (batch_id,)
        )
        deleted["revenus"] = cur.rowcount
    elif import_type == "CREDIT":
        raise ValueError(
            "Les crédits ne peuvent pas être annulés automatiquement : "
            "la fiche crédit et son amortissement doivent être supprimés "
            "manuellement depuis la page Crédits."
        )

    conn.execute(
        "UPDATE import_batches SET status = 'ROLLED_BACK' WHERE id = ?",
        (batch_id,),
    )
    conn.commit()

    total = sum(deleted.values())
    _logger.info("Rollback batch %d (%s) : %d lignes supprimées", batch_id, import_type, total)
    return {"batch_id": batch_id, "deleted": deleted, "total_deleted": total}
