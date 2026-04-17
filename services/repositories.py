import sqlite3
import pandas as pd
from typing import Optional


def df_from_rows(rows, columns=None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns or [])
    try:
        # sqlite3.Row : dict(r) fonctionne car r.keys() est défini
        return pd.DataFrame([dict(r) for r in rows])
    except (TypeError, KeyError):
        # libsql retourne des tuples sans clés — on reconstruit avec la liste de colonnes
        return pd.DataFrame(list(rows), columns=columns)


# -------- People --------
def list_people(conn: sqlite3.Connection) -> pd.DataFrame:
    cols = ["id", "name"]
    rows = conn.execute("SELECT id, name FROM people ORDER BY id;").fetchall()
    return df_from_rows(rows, cols)


# -------- Accounts --------
def list_accounts(conn: sqlite3.Connection, person_id: Optional[int] = None) -> pd.DataFrame:
    cols = ["id", "person_id", "name", "account_type", "institution", "currency", "created_at"]
    if person_id is None:
        rows = conn.execute("SELECT * FROM accounts ORDER BY person_id, id;").fetchall()
    else:
        rows = conn.execute("SELECT * FROM accounts WHERE person_id = ? ORDER BY id;", (person_id,)).fetchall()
    return df_from_rows(rows, cols)


def create_account(conn: sqlite3.Connection, person_id: int, name: str, account_type: str, institution: Optional[str], currency: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO accounts(person_id, name, account_type, institution, currency)
        VALUES (?,?,?,?,?)
        """,
        (person_id, name, account_type, institution, currency),
    )
    conn.commit()
    return int(cur.lastrowid)

def get_account(conn: sqlite3.Connection, account_id: int) -> Optional[dict]:
    df = pd.read_sql_query(
        "SELECT * FROM accounts WHERE id = ?", conn, params=(int(account_id),)
    )
    return df.iloc[0].to_dict() if not df.empty else None


def get_account_currency(conn: sqlite3.Connection, account_id: int) -> str:
    df = pd.read_sql_query(
        "SELECT currency FROM accounts WHERE id = ?", conn, params=(int(account_id),)
    )
    if df.empty:
        return "EUR"
    val = df.iloc[0]["currency"]
    return (val if val else "EUR").upper()


# -------- Assets --------
def get_asset_by_symbol(conn: sqlite3.Connection, symbol: str):
    if not symbol:
        return None
    return conn.execute("SELECT * FROM assets WHERE symbol = ?;", (symbol,)).fetchone()


def list_assets(conn: sqlite3.Connection) -> pd.DataFrame:
    cols = ["id", "symbol", "name", "asset_type", "currency"]
    rows = conn.execute("SELECT * FROM assets ORDER BY symbol;").fetchall()
    return df_from_rows(rows, cols)


def create_asset(conn: sqlite3.Connection, symbol: str, name: str, asset_type: str, currency: str = "EUR") -> int:
    cur = conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) VALUES (?,?,?,?);",
        (symbol, name, asset_type, currency),
    )
    conn.commit()
    return int(cur.lastrowid)

def update_asset_currency(conn: sqlite3.Connection, asset_id: int, currency: str) -> None:
    conn.execute("UPDATE assets SET currency = ? WHERE id = ?;", (currency.upper(), asset_id))
    conn.commit()


def update_asset_type(conn: sqlite3.Connection, asset_id: int, asset_type: str) -> None:
    conn.execute("UPDATE assets SET asset_type = ? WHERE id = ?;", (asset_type, asset_id))
    conn.commit()


def get_latest_fx_rate(conn: sqlite3.Connection, base_ccy: str, quote_ccy: str):
    """
    Retourne le dernier taux connu base->quote (ex: USD->EUR).
    Hypothèse: table fx_rates(base_ccy, quote_ccy, asof, rate) existe déjà dans ta DB.
    """
    base_ccy = (base_ccy or "").upper()
    quote_ccy = (quote_ccy or "").upper()
    if not base_ccy or not quote_ccy:
        return None

    return conn.execute(
        """
        SELECT rate, asof
        FROM fx_rates
        WHERE base_ccy = ? AND quote_ccy = ?
        ORDER BY asof DESC
        LIMIT 1;
        """,
        (base_ccy, quote_ccy),
    ).fetchone()


def insert_fx_rate(conn: sqlite3.Connection, base_ccy: str, quote_ccy: str, asof: str, rate: float) -> None:
    """
    Insert simple (pas d'UPSERT) pour éviter tout problème de contrainte UNIQUE.
    """
    conn.execute(
        "INSERT INTO fx_rates(base_ccy, quote_ccy, asof, rate) VALUES (?,?,?,?);",
        ((base_ccy or "").upper(), (quote_ccy or "").upper(), asof, float(rate)),
    )
    conn.commit()

# -------- Transactions --------
def list_transactions(
    conn: sqlite3.Connection,
    person_id: Optional[int] = None,
    account_id: Optional[int] = None,
    limit: int = 300,
    date_asof: Optional[str] = None,
    include_deleted: bool = False,
) -> pd.DataFrame:
    cols = [
        "id", "date", "person_id", "account_id", "type", "asset_id", "quantity", "price",
        "fees", "amount", "category", "note", "import_batch_id", "created_at",
        "is_hidden_from_cashflow", "is_internal_transfer", "deleted_at", "analysis_state",
        "asset_symbol", "asset_name", "account_name", "person_name",
    ]

    base = """
    SELECT
           t.id, t.date, t.person_id, t.account_id, t.type, t.asset_id, t.quantity, t.price,
           t.fees, t.amount, t.category, t.note, t.import_batch_id, t.created_at,
           COALESCE(t.is_hidden_from_cashflow, 0) AS is_hidden_from_cashflow,
           COALESCE(t.is_internal_transfer, 0) AS is_internal_transfer,
           t.deleted_at,
           CASE
               WHEN t.deleted_at IS NOT NULL THEN 'DELETED'
               WHEN COALESCE(t.is_hidden_from_cashflow, 0) = 1 THEN 'HIDDEN'
               WHEN COALESCE(t.is_internal_transfer, 0) = 1 THEN 'INTERNAL_TRANSFER'
               ELSE 'NORMAL'
           END AS analysis_state,
           a.symbol as asset_symbol, a.name as asset_name,
           acc.name as account_name,
           p.name as person_name
    FROM transactions t
    LEFT JOIN assets a ON a.id = t.asset_id
    JOIN accounts acc ON acc.id = t.account_id
    JOIN people p ON p.id = t.person_id
    """

    params = []
    where = []
    if person_id is not None:
        where.append("t.person_id = ?")
        params.append(person_id)
    if account_id is not None:
        where.append("t.account_id = ?")
        params.append(account_id)
    if date_asof is not None:
        where.append("t.date <= ?")
        params.append(str(date_asof))
    if not include_deleted:
        where.append("t.deleted_at IS NULL")

    q = base
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY t.date DESC, t.id DESC LIMIT ?;"
    params.append(limit)

    rows = conn.execute(q, tuple(params)).fetchall()
    return df_from_rows(rows, cols)


def create_transaction(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO transactions(
            date, person_id, account_id, type, asset_id, quantity, price, fees, amount,
            category, note, is_hidden_from_cashflow, is_internal_transfer
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            data["date"],
            data["person_id"],
            data["account_id"],
            data["type"],
            data.get("asset_id"),
            data.get("quantity"),
            data.get("price"),
            data.get("fees", 0.0),
            data["amount"],
            data.get("category"),
            data.get("note"),
            1 if data.get("is_hidden_from_cashflow") else 0,
            1 if data.get("is_internal_transfer") else 0,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _month_key_from_tx_date(date_value: str | None) -> str | None:
    if not date_value:
        return None
    d = pd.to_datetime(str(date_value), errors="coerce")
    if pd.isna(d):
        return None
    return f"{d.year:04d}-{d.month:02d}-01"


def _sync_bankin_monthly_if_needed(conn: sqlite3.Connection, tx_row: dict | None) -> None:
    if not tx_row:
        return
    note = str(tx_row.get("note") or "")
    if not note.startswith("Bankin:"):
        return
    person_id = tx_row.get("person_id")
    month_key = _month_key_from_tx_date(tx_row.get("date"))
    if person_id is None or month_key is None:
        return
    from services.imports import sync_bankin_monthly_tables
    sync_bankin_monthly_tables(conn, int(person_id), months=[month_key])


def _fetch_transaction_for_update(conn: sqlite3.Connection, tx_id: int, include_deleted: bool = True) -> Optional[dict]:
    where = "id = ?"
    if not include_deleted:
        where += " AND deleted_at IS NULL"
    row = conn.execute(
        f"""
        SELECT id, date, person_id, account_id, type, amount, category, note,
               is_hidden_from_cashflow, is_internal_transfer, deleted_at
        FROM transactions
        WHERE {where}
        LIMIT 1
        """,
        (int(tx_id),),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_transaction_category(conn: sqlite3.Connection, transaction_id: int, new_category: Optional[str]) -> bool:
    tx = _fetch_transaction_for_update(conn, transaction_id, include_deleted=True)
    if tx is None:
        return False
    conn.execute(
        "UPDATE transactions SET category = ? WHERE id = ?",
        (new_category, int(transaction_id)),
    )
    conn.commit()
    _sync_bankin_monthly_if_needed(conn, tx)
    return True


def hide_transaction(conn: sqlite3.Connection, transaction_id: int, hidden: bool = True) -> bool:
    tx = _fetch_transaction_for_update(conn, transaction_id, include_deleted=True)
    if tx is None:
        return False
    conn.execute(
        "UPDATE transactions SET is_hidden_from_cashflow = ? WHERE id = ?",
        (1 if hidden else 0, int(transaction_id)),
    )
    conn.commit()
    _sync_bankin_monthly_if_needed(conn, tx)
    return True


def mark_transaction_as_internal_transfer(conn: sqlite3.Connection, transaction_id: int, value: bool = True) -> bool:
    tx = _fetch_transaction_for_update(conn, transaction_id, include_deleted=True)
    if tx is None:
        return False
    conn.execute(
        "UPDATE transactions SET is_internal_transfer = ? WHERE id = ?",
        (1 if value else 0, int(transaction_id)),
    )
    conn.commit()
    _sync_bankin_monthly_if_needed(conn, tx)
    return True


def delete_transaction(conn: sqlite3.Connection, tx_id: int) -> None:
    tx = _fetch_transaction_for_update(conn, tx_id, include_deleted=True)
    if tx is None:
        return
    conn.execute(
        "UPDATE transactions SET deleted_at = datetime('now') WHERE id = ?;",
        (int(tx_id),),
    )
    conn.commit()
    _sync_bankin_monthly_if_needed(conn, tx)


def restore_transaction(conn: sqlite3.Connection, tx_id: int) -> bool:
    tx = _fetch_transaction_for_update(conn, tx_id, include_deleted=True)
    if tx is None:
        return False
    conn.execute("UPDATE transactions SET deleted_at = NULL WHERE id = ?;", (int(tx_id),))
    conn.commit()
    _sync_bankin_monthly_if_needed(conn, tx)
    return True


def hard_delete_transaction(conn: sqlite3.Connection, tx_id: int) -> None:
    tx = _fetch_transaction_for_update(conn, tx_id, include_deleted=True)
    if tx is None:
        return
    conn.execute("DELETE FROM transactions WHERE id = ?;", (int(tx_id),))
    conn.commit()
    _sync_bankin_monthly_if_needed(conn, tx)

# -------- Pricing / Prices --------

def list_account_asset_ids(conn: sqlite3.Connection, account_id: int) -> list[int]:
    """
    Retourne la liste des asset_id distincts utilisés dans un compte via les transactions.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT asset_id
        FROM transactions
        WHERE account_id = ?
          AND asset_id IS NOT NULL
        """,
        (account_id,),
    ).fetchall()
    return [int(r["asset_id"]) for r in rows if r["asset_id"] is not None]


def upsert_price(conn: sqlite3.Connection, asset_id: int, date: str, price: float, currency: str = "EUR", source: str = "AUTO") -> None:
    """
    Insert ou remplace un prix (asset_id, date) unique.
    """
    conn.execute(
        """
        INSERT INTO prices(asset_id, date, price, currency, source)
        VALUES (?,?,?,?,?)
        ON CONFLICT(asset_id, date) DO UPDATE SET
            price=excluded.price,
            currency=excluded.currency,
            source=excluded.source
        """,
        (asset_id, date, float(price), currency, source),
    )
    conn.commit()


def get_latest_prices(conn: sqlite3.Connection, asset_ids: list[int]) -> pd.DataFrame:
    """
    Renvoie, pour chaque asset_id, le dernier prix disponible (date max).
    """
    if not asset_ids:
        return pd.DataFrame(columns=["asset_id", "date", "price", "currency", "source"])

    placeholders = ",".join(["?"] * len(asset_ids))
    rows = conn.execute(
        f"""
        SELECT p1.asset_id, p1.date, p1.price, p1.currency, p1.source
        FROM prices p1
        JOIN (
            SELECT asset_id, MAX(date) AS max_date
            FROM prices
            WHERE asset_id IN ({placeholders})
            GROUP BY asset_id
        ) last
        ON last.asset_id = p1.asset_id AND last.max_date = p1.date
        """,
        tuple(asset_ids),
    ).fetchall()

    return df_from_rows(rows, ["asset_id", "date", "price", "currency", "source"])


# -------------------------------------------------------------------
# BANQUE container -> sous-comptes (NOUVEAU, n'impacte pas l'existant)
# -------------------------------------------------------------------

def link_subaccount_to_bank(conn, bank_account_id: int, sub_account_id: int, subtype: str) -> None:
    subtype = (subtype or "").lower().strip()
    conn.execute(
        """
        INSERT OR IGNORE INTO bank_subaccounts(bank_account_id, sub_account_id, subtype)
        VALUES (?, ?, ?);
        """,
        (int(bank_account_id), int(sub_account_id), subtype),
    )
    conn.commit()


def list_bank_subaccounts(conn, bank_account_id: int) -> pd.DataFrame:
    _COLS = ["sub_account_id", "subtype", "account_name", "account_type", "account_currency", "institution"]
    rows = conn.execute(
        """
        SELECT b.sub_account_id,
               b.subtype,
               a.name       AS account_name,
               a.account_type AS account_type,
               a.currency   AS account_currency,
               a.institution AS institution
        FROM bank_subaccounts b
        JOIN accounts a ON a.id = b.sub_account_id
        WHERE b.bank_account_id = ?
        ORDER BY b.subtype, a.name
        """,
        (int(bank_account_id),),
    ).fetchall()
    return pd.DataFrame(rows, columns=_COLS) if rows else pd.DataFrame(columns=_COLS)


def list_all_subaccount_ids(conn, person_id: int) -> list[int]:
    """
    Sert à masquer les sous-comptes dans les onglets 'Personnes',
    pour qu'ils n'apparaissent que dans le container BANQUE.
    """
    rows = conn.execute(
        """
        SELECT b.sub_account_id
        FROM bank_subaccounts b
        JOIN accounts a ON a.id = b.sub_account_id
        WHERE a.person_id = ?;
        """,
        (int(person_id),),
    ).fetchall()
    return [int(r["sub_account_id"]) for r in rows]


def is_bank_container(conn, account_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM bank_subaccounts WHERE bank_account_id = ? LIMIT 1;",
        (int(account_id),),
    ).fetchone()
    return row is not None


def get_fx_rate_asof_or_before(conn: sqlite3.Connection, base_ccy: str, quote_ccy: str, asof: str):
    """
    Retourne le taux base->quote le plus récent dont asof <= date demandée.
    Exemple: USD->EUR au 2024-12-01.
    """
    base_ccy = (base_ccy or "").upper()
    quote_ccy = (quote_ccy or "").upper()
    if not base_ccy or not quote_ccy or not asof:
        return None

    return conn.execute(
        """
        SELECT rate, asof
        FROM fx_rates
        WHERE base_ccy = ? AND quote_ccy = ? AND asof <= ?
        ORDER BY asof DESC
        LIMIT 1;
        """,
        (base_ccy, quote_ccy, asof),
    ).fetchone()


# -------- Patrimoine snapshots --------
def upsert_patrimoine_snapshot(
    conn: sqlite3.Connection,
    person_id: int,
    snapshot_date: str,
    created_at: str,
    mode: str,
    patrimoine_net: float,
    patrimoine_brut: float,
    liquidites_total: float,
    bank_cash: float,
    bourse_cash: float,
    pe_cash: float,
    bourse_holdings: float,
    pe_value: float,
    ent_value: float,
    credits_remaining: float,
    notes: str = None,
):
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots(
            person_id, snapshot_date, created_at, mode,
            patrimoine_net, patrimoine_brut,
            liquidites_total, bank_cash, bourse_cash, pe_cash,
            bourse_holdings, pe_value, ent_value, credits_remaining,
            notes
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(person_id, snapshot_date) DO UPDATE SET
            created_at = excluded.created_at,
            mode = excluded.mode,
            patrimoine_net = excluded.patrimoine_net,
            patrimoine_brut = excluded.patrimoine_brut,
            liquidites_total = excluded.liquidites_total,
            bank_cash = excluded.bank_cash,
            bourse_cash = excluded.bourse_cash,
            pe_cash = excluded.pe_cash,
            bourse_holdings = excluded.bourse_holdings,
            pe_value = excluded.pe_value,
            ent_value = excluded.ent_value,
            credits_remaining = excluded.credits_remaining,
            notes = excluded.notes
        ;
        """,
        (
            person_id, snapshot_date, created_at, mode,
            float(patrimoine_net), float(patrimoine_brut),
            float(liquidites_total), float(bank_cash), float(bourse_cash), float(pe_cash),
            float(bourse_holdings), float(pe_value), float(ent_value), float(credits_remaining),
            notes,
        ),
    )
    conn.commit()


def count_snapshots_for_date(conn: sqlite3.Connection, snapshot_date: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM patrimoine_snapshots WHERE snapshot_date = ?;",
        (snapshot_date,),
    ).fetchone()
    return int(row["c"]) if row else 0


def list_patrimoine_snapshots(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT snapshot_date, created_at, mode,
               patrimoine_net, patrimoine_brut,
               liquidites_total, bank_cash, bourse_cash, pe_cash,
               bourse_holdings, pe_value, ent_value, credits_remaining
        FROM patrimoine_snapshots
        WHERE person_id = ?
        ORDER BY snapshot_date ASC;
        """,
        (person_id,),
    ).fetchall()
    return df_from_rows(rows)
