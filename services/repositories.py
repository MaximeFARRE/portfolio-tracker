import sqlite3
import pandas as pd
from typing import Optional


def df_from_rows(rows, columns=None) -> pd.DataFrame:
    if rows:
        return pd.DataFrame([dict(r) for r in rows])
    return pd.DataFrame(columns=columns or [])


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


# -------- Transactions --------
def list_transactions(conn: sqlite3.Connection, person_id: Optional[int] = None, account_id: Optional[int] = None, limit: int = 300) -> pd.DataFrame:
    cols = [
        "id","date","person_id","account_id","type","asset_id","quantity","price","fees","amount","category","note",
        "asset_symbol","asset_name","account_name","person_name"
    ]

    base = """
    SELECT t.*,
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

    q = base
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY date DESC, id DESC LIMIT ?;"
    params.append(limit)

    rows = conn.execute(q, tuple(params)).fetchall()
    return df_from_rows(rows, cols)


def create_transaction(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO transactions(date, person_id, account_id, type, asset_id, quantity, price, fees, amount, category, note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_transaction(conn: sqlite3.Connection, tx_id: int) -> None:
    conn.execute("DELETE FROM transactions WHERE id = ?;", (tx_id,))
    conn.commit()
