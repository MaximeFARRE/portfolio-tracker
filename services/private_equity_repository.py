# services/private_equity_repository.py
import pandas as pd

def list_pe_projects(conn, person_id: int) -> pd.DataFrame:
    _COLS = ["id", "person_id", "name", "platform", "project_type", "status", "created_at", "exit_date", "note"]
    rows = conn.execute(
        """
        SELECT id, person_id, name, platform, project_type, status, created_at, exit_date, note
        FROM pe_projects
        WHERE person_id = ?
        ORDER BY status, name
        """,
        (person_id,),
    ).fetchall()
    return pd.DataFrame(rows, columns=_COLS) if rows else pd.DataFrame(columns=_COLS)

def create_pe_project(conn, person_id: int, name: str, platform: str | None, project_type: str | None, note: str | None):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pe_projects (person_id, name, platform, project_type, status, note)
        VALUES (?, ?, ?, ?, 'EN_COURS', ?)
        """,
        (person_id, name.strip(), (platform or None), (project_type or None), (note or None)),
    )
    conn.commit()

def set_project_status(conn, project_id: int, status: str, exit_date: str | None = None):
    cur = conn.cursor()
    cur.execute(
        "UPDATE pe_projects SET status = ?, exit_date = ? WHERE id = ?",
        (status, exit_date, project_id),
    )
    conn.commit()

def list_pe_transactions(conn, person_id: int) -> pd.DataFrame:
    _COLS = ["id", "project_id", "project_name", "platform", "status", "date", "tx_type", "amount", "quantity", "unit_price", "note"]
    rows = conn.execute(
        """
        SELECT t.id, t.project_id, p.name AS project_name, p.platform, p.status,
               t.date, t.tx_type, t.amount, t.quantity, t.unit_price, t.note
        FROM pe_transactions t
        JOIN pe_projects p ON p.id = t.project_id
        WHERE p.person_id = ?
        ORDER BY t.date DESC, t.id DESC
        """,
        (person_id,),
    ).fetchall()
    return pd.DataFrame(rows, columns=_COLS) if rows else pd.DataFrame(columns=_COLS)

def list_pe_transactions_by_project(conn, project_id: int) -> pd.DataFrame:
    _COLS = ["id", "project_id", "date", "tx_type", "amount", "quantity", "unit_price", "note"]
    rows = conn.execute(
        """
        SELECT id, project_id, date, tx_type, amount, quantity, unit_price, note
        FROM pe_transactions
        WHERE project_id = ?
        ORDER BY date ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    return pd.DataFrame(rows, columns=_COLS) if rows else pd.DataFrame(columns=_COLS)

def add_pe_transaction(conn, project_id: int, date: str, tx_type: str, amount: float,
                      quantity: float | None = None, unit_price: float | None = None, note: str | None = None):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pe_transactions (project_id, date, tx_type, amount, quantity, unit_price, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, date, tx_type, float(amount), quantity, unit_price, (note or None)),
    )
    conn.commit()
