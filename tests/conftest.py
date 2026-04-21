import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def conn():
    """Connexion SQLite en mémoire avec le schéma complet."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")

    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    # On saute le PRAGMA foreign_keys (déjà fait) et on exécute statement par statement
    for stmt in schema_sql.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.upper().startswith("PRAGMA"):
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass  # index ou table déjà présents

    yield c
    c.close()


@pytest.fixture
def conn_with_person(conn):
    """Connexion avec une personne 'Test' et un compte BANQUE."""
    conn.execute("INSERT INTO people(name) VALUES ('Test')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'Banque Test', 'BANQUE', 'EUR')"
    )
    conn.commit()
    return conn
