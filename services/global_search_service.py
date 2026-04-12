"""
Recherche globale multi-objets (personnes, comptes, actifs, transactions).
Point d'entrée unique : query_global_search(conn, query).
"""
import logging
from services.common_utils import fmt_amount, row_get

logger = logging.getLogger(__name__)

# Aliases locaux pour raccourcir les appels inline dans query_global_search
_row_get = row_get
_fmt_amount = fmt_amount


def query_global_search(conn, query: str, limit_per_kind: int = 7) -> list[dict]:
    """Recherche rapide multi-objets : personnes, comptes, actifs, transactions."""
    q = query.strip().lower()
    if not q:
        return []

    like = f"%{q}%"
    results: list[dict] = []

    try:
        rows = conn.execute(
            """
            SELECT id, name
            FROM people
            WHERE lower(name) LIKE ?
            ORDER BY name
            LIMIT ?;
            """,
            (like, limit_per_kind),
        ).fetchall()
        for row in rows:
            name = str(_row_get(row, "name", 1))
            results.append(
                {
                    "kind": "person",
                    "person_id": int(_row_get(row, "id", 0)),
                    "person_name": name,
                    "label": f"👤 Personne · {name}",
                }
            )
    except Exception as exc:
        logger.warning("Recherche globale (people) en erreur : %s", exc)

    try:
        rows = conn.execute(
            """
            SELECT a.id, a.name, a.account_type,
                   p.id AS person_id, p.name AS person_name
            FROM accounts a
            JOIN people p ON p.id = a.person_id
            WHERE lower(a.name) LIKE ?
               OR lower(COALESCE(a.institution, '')) LIKE ?
               OR lower(p.name) LIKE ?
            ORDER BY p.name, a.name
            LIMIT ?;
            """,
            (like, like, like, limit_per_kind),
        ).fetchall()
        for row in rows:
            person_name = str(_row_get(row, "person_name", 4))
            account_name = str(_row_get(row, "name", 1))
            results.append(
                {
                    "kind": "account",
                    "account_id": int(_row_get(row, "id", 0)),
                    "account_name": account_name,
                    "account_type": str(_row_get(row, "account_type", 2)),
                    "person_id": int(_row_get(row, "person_id", 3)),
                    "person_name": person_name,
                    "label": f"🏦 Compte · {account_name} ({person_name})",
                }
            )
    except Exception as exc:
        logger.warning("Recherche globale (accounts) en erreur : %s", exc)

    try:
        rows = conn.execute(
            """
            SELECT a.id, a.symbol, a.name, a.asset_type,
                   (
                     SELECT t.person_id FROM transactions t
                     WHERE t.asset_id = a.id
                     ORDER BY t.date DESC, t.id DESC
                     LIMIT 1
                   ) AS person_id,
                   (
                     SELECT p.name FROM transactions t
                     JOIN people p ON p.id = t.person_id
                     WHERE t.asset_id = a.id
                     ORDER BY t.date DESC, t.id DESC
                     LIMIT 1
                   ) AS person_name,
                   (
                     SELECT t.account_id FROM transactions t
                     WHERE t.asset_id = a.id
                     ORDER BY t.date DESC, t.id DESC
                     LIMIT 1
                   ) AS account_id,
                   (
                     SELECT acc.name FROM transactions t
                     JOIN accounts acc ON acc.id = t.account_id
                     WHERE t.asset_id = a.id
                     ORDER BY t.date DESC, t.id DESC
                     LIMIT 1
                   ) AS account_name
            FROM assets a
            WHERE lower(a.symbol) LIKE ?
               OR lower(COALESCE(a.name, '')) LIKE ?
            ORDER BY a.symbol
            LIMIT ?;
            """,
            (like, like, limit_per_kind),
        ).fetchall()
        for row in rows:
            symbol = str(_row_get(row, "symbol", 1))
            asset_name = str(_row_get(row, "name", 2) or symbol)
            raw_person_id = _row_get(row, "person_id", 4)
            raw_account_id = _row_get(row, "account_id", 6)
            person_name = str(_row_get(row, "person_name", 5) or "")
            account_name = str(_row_get(row, "account_name", 7) or "")
            context = f" ({person_name})" if person_name else ""
            results.append({
                "kind": "asset",
                "asset_id": int(_row_get(row, "id", 0)),
                "symbol": symbol,
                "asset_name": asset_name,
                "asset_type": str(_row_get(row, "asset_type", 3) or ""),
                "person_id": int(raw_person_id) if raw_person_id is not None else None,
                "person_name": person_name,
                "account_id": int(raw_account_id) if raw_account_id is not None else None,
                "account_name": account_name,
                "label": f"📈 Actif · {symbol} — {asset_name}{context}",
            })
    except Exception as exc:
        logger.warning("Recherche globale (assets) en erreur : %s", exc)

    try:
        rows = conn.execute(
            """
            SELECT t.id, t.date, t.type, t.amount,
                   p.id AS person_id, p.name AS person_name,
                   acc.id AS account_id, acc.name AS account_name,
                   COALESCE(a.symbol, '') AS asset_symbol
            FROM transactions t
            JOIN people p ON p.id = t.person_id
            JOIN accounts acc ON acc.id = t.account_id
            LEFT JOIN assets a ON a.id = t.asset_id
            WHERE lower(p.name) LIKE ?
               OR lower(acc.name) LIKE ?
               OR lower(t.type) LIKE ?
               OR lower(COALESCE(t.category, '')) LIKE ?
               OR lower(COALESCE(t.note, '')) LIKE ?
               OR lower(COALESCE(a.symbol, '')) LIKE ?
               OR CAST(t.id AS TEXT) LIKE ?
            ORDER BY t.date DESC, t.id DESC
            LIMIT ?;
            """,
            (like, like, like, like, like, like, like, limit_per_kind),
        ).fetchall()
        for row in rows:
            tx_id = int(_row_get(row, "id", 0))
            date = str(_row_get(row, "date", 1))
            tx_type = str(_row_get(row, "type", 2))
            amount = _fmt_amount(_row_get(row, "amount", 3))
            person_name = str(_row_get(row, "person_name", 5))
            account_name = str(_row_get(row, "account_name", 7))
            asset_symbol = str(_row_get(row, "asset_symbol", 8) or "")
            suffix = f" · {asset_symbol}" if asset_symbol else ""
            results.append(
                {
                    "kind": "transaction",
                    "tx_id": tx_id,
                    "date": date,
                    "tx_type": tx_type,
                    "amount": amount,
                    "person_id": int(_row_get(row, "person_id", 4)),
                    "person_name": person_name,
                    "account_id": int(_row_get(row, "account_id", 6)),
                    "account_name": account_name,
                    "label": (
                        f"🧾 Transaction #{tx_id} · {date} · {tx_type} · "
                        f"{amount} € ({person_name}/{account_name}){suffix}"
                    ),
                }
            )
    except Exception as exc:
        logger.warning("Recherche globale (transactions) en erreur : %s", exc)

    return results[:32]
