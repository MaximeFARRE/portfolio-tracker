import sqlite3
import pandas as pd
from typing import Optional

from services.repositories import df_from_rows


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enterprises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL,
            valuation_eur REAL NOT NULL DEFAULT 0,
            debt_eur REAL NOT NULL DEFAULT 0,
            note TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enterprise_shares (
            enterprise_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL,
            pct REAL NOT NULL DEFAULT 0,
            initial_invest_eur REAL NOT NULL DEFAULT 0,
            cca_eur REAL NOT NULL DEFAULT 0,
            initial_invest_date TEXT,
            PRIMARY KEY (enterprise_id, person_id),
            FOREIGN KEY (enterprise_id) REFERENCES enterprises(id) ON DELETE CASCADE,
            FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
        );
        """
    )


    # --- migrations safe (si une ancienne table existe sans colonnes) ---
    cols = [r[1] for r in conn.execute("PRAGMA table_info(enterprise_shares);").fetchall()]
    if "initial_invest_date" not in cols:
        conn.execute("ALTER TABLE enterprise_shares ADD COLUMN initial_invest_date TEXT;")

    if "cca_eur" not in cols:
        conn.execute("ALTER TABLE enterprise_shares ADD COLUMN cca_eur REAL NOT NULL DEFAULT 0;");
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enterprise_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enterprise_id INTEGER NOT NULL,
            changed_at TEXT NOT NULL DEFAULT (datetime('now')),
            effective_date TEXT NOT NULL DEFAULT (date('now')),
            valuation_eur REAL NOT NULL,
            debt_eur REAL NOT NULL,
            note TEXT,
            FOREIGN KEY (enterprise_id) REFERENCES enterprises(id) ON DELETE CASCADE
        );
        """
    )
    cols_h = [r[1] for r in conn.execute("PRAGMA table_info(enterprise_history);").fetchall()]
    if "effective_date" not in cols_h:
        conn.execute("ALTER TABLE enterprise_history ADD COLUMN effective_date TEXT;")
        conn.execute("UPDATE enterprise_history SET effective_date = COALESCE(effective_date, substr(changed_at, 1, 10));")
        conn.execute("UPDATE enterprise_history SET effective_date = COALESCE(effective_date, date('now'));")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_eh_ent_date ON enterprise_history(enterprise_id, effective_date);")
    conn.commit()




def list_enterprises(conn: sqlite3.Connection) -> pd.DataFrame:
    ensure_tables(conn)
    rows = conn.execute("SELECT * FROM enterprises ORDER BY name;").fetchall()
    return df_from_rows(rows, ["id", "name", "entity_type", "valuation_eur", "debt_eur", "note", "updated_at"])


def get_enterprise(conn: sqlite3.Connection, enterprise_id: int):
    ensure_tables(conn)
    return conn.execute("SELECT * FROM enterprises WHERE id = ?;", (enterprise_id,)).fetchone()


def list_shares(conn: sqlite3.Connection, enterprise_id: int) -> pd.DataFrame:
    ensure_tables(conn)
    rows = conn.execute(
        """
        SELECT
            es.enterprise_id,
            es.person_id,
            es.pct,
            p.name AS person_name,
            es.initial_invest_eur,
            es.cca_eur,
            es.initial_invest_date
        FROM enterprise_shares es
        JOIN people p ON p.id = es.person_id
        WHERE es.enterprise_id = ?
        ORDER BY p.id;
        """,
        (enterprise_id,),
    ).fetchall()
    return df_from_rows(
        rows,
        ["enterprise_id", "person_id", "pct", "person_name", "initial_invest_eur", "cca_eur", "initial_invest_date"],
    )


def list_positions_for_person(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    """
    Retourne toutes les positions non-cotées d'une personne (une ligne par entreprise).
    Inclut la valo/dette actuelle, les parts, initial, CCA, et la date de début (1ère valo connue).
    """
    ensure_tables(conn)
    rows = conn.execute(
        """
        SELECT
            e.id AS enterprise_id,
            e.name AS enterprise_name,
            e.entity_type,
            e.valuation_eur,
            e.debt_eur,
            es.pct,
            es.initial_invest_eur,
            es.cca_eur,
            es.initial_invest_date,
            (SELECT MIN(h.effective_date) FROM enterprise_history h WHERE h.enterprise_id = e.id) AS start_at
        FROM enterprise_shares es
        JOIN enterprises e ON e.id = es.enterprise_id
        WHERE es.person_id = ?
        ORDER BY e.name;
        """,

        (int(person_id),),
    ).fetchall()

    return df_from_rows(
        rows,
        [
            "enterprise_id",
            "enterprise_name",
            "entity_type",
            "valuation_eur",
            "debt_eur",
            "pct",
            "initial_invest_eur",
            "cca_eur",
            "initial_invest_date",
            "start_at",
        ],
    )


def create_enterprise(conn: sqlite3.Connection,name: str,entity_type: str,valuation_eur: float,debt_eur: float,note: Optional[str],effective_date: Optional[str] = None,) -> int:
    ensure_tables(conn)
    cur = conn.execute(
        """
        INSERT INTO enterprises(name, entity_type, valuation_eur, debt_eur, note)
        VALUES (?,?,?,?,?);
        """,
        (name.strip(), entity_type, float(valuation_eur), float(debt_eur), note),
    )
    enterprise_id = int(cur.lastrowid)

    if effective_date is None:
        effective_date = pd.Timestamp.today().date().isoformat()


    # Historique initial
    conn.execute(
        """
        INSERT INTO enterprise_history(enterprise_id, effective_date, valuation_eur, debt_eur, note)
        VALUES (?,?,?,?,?);
        """,
        (
            enterprise_id,
            effective_date,
            float(valuation_eur),
            float(debt_eur),
            "Création" if not note else f"Création — {note}",
        ),
    )



    conn.commit()
    return enterprise_id


def replace_shares(conn, enterprise_id: int, shares_by_person_id: dict) -> None:
    ensure_tables(conn)
    conn.execute("DELETE FROM enterprise_shares WHERE enterprise_id = ?;", (enterprise_id,))

    for person_id, v in shares_by_person_id.items():
        if isinstance(v, dict):
            pct = float(v.get("pct", 0.0))
            initial = float(v.get("initial", 0.0))
            initial_date = v.get("initial_date")  # "YYYY-MM-DD" ou None
            cca = float(v.get("cca", 0.0))
        else:
            pct = float(v)
            initial = 0.0
            cca = 0.0
            initial_date = None


        conn.execute(
            """
            INSERT INTO enterprise_shares(enterprise_id, person_id, pct, initial_invest_eur, cca_eur, initial_invest_date)
            VALUES (?,?,?,?,?,?);
            """,
            (int(enterprise_id), int(person_id), pct, initial, cca, initial_date),
        )


    conn.commit()



def update_enterprise(conn: sqlite3.Connection, enterprise_id: int, entity_type: str, valuation_eur: float, debt_eur: float, note: Optional[str]) -> None:
    ensure_tables(conn)

    conn.execute(
        """
        UPDATE enterprises
        SET entity_type = ?,
            valuation_eur = ?,
            debt_eur = ?,
            note = ?,
            updated_at = datetime('now')
        WHERE id = ?;
        """,
        (entity_type, float(valuation_eur), float(debt_eur), note, int(enterprise_id)),
    )

    # Historique
    conn.execute(
        """
        INSERT INTO enterprise_history(enterprise_id, valuation_eur, debt_eur, note)
        VALUES (?,?,?,?);
        """,
        (int(enterprise_id), float(valuation_eur), float(debt_eur), note),
    )

    conn.commit()


def list_history(conn: sqlite3.Connection, enterprise_id: int, limit: int = 20) -> pd.DataFrame:
    ensure_tables(conn)
    rows = conn.execute(
        """
        SELECT id, effective_date, changed_at, valuation_eur, debt_eur, note
        FROM enterprise_history
        WHERE enterprise_id = ?
        ORDER BY effective_date DESC, id DESC
        LIMIT ?;
        """,
        (int(enterprise_id), int(limit)),
    ).fetchall()
    return df_from_rows(rows, ["id", "effective_date", "changed_at", "valuation_eur", "debt_eur", "note"])
