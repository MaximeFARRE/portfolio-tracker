import os
import sqlite3
from pathlib import Path

DB_PATH = Path("patrimoine.db")
SCHEMA_PATH = Path("db") / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema introuvable : {SCHEMA_PATH}")

    with get_conn() as conn:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()


def seed_minimal() -> None:
    """
    Seed V1 :
    - 4 personnes : Papa, Maman, Maxime, Valentin
    - 1 compte BANQUE "Banque principale" par personne (modifiable/supprimable ensuite)
    """
    init_db()
    with get_conn() as conn:
        # People
        c = conn.execute("SELECT COUNT(*) AS c FROM people;").fetchone()["c"]
        if c == 0:
            for name in ["Papa", "Maman", "Maxime", "Valentin"]:
                conn.execute("INSERT INTO people(name) VALUES (?);", (name,))
            conn.commit()

        # Accounts
        c2 = conn.execute("SELECT COUNT(*) AS c FROM accounts;").fetchone()["c"]
        if c2 == 0:
            people = conn.execute("SELECT id, name FROM people ORDER BY id;").fetchall()
            for p in people:
                conn.execute(
                    """
                    INSERT INTO accounts(person_id, name, account_type, institution, currency)
                    VALUES (?,?,?,?,?)
                    """,
                    (p["id"], "Banque principale", "BANQUE", None, "EUR"),
                )
            conn.commit()
