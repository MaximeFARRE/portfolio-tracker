import os
import sqlite3
import libsql 
import streamlit as st
from pathlib import Path

DB_PATH = Path("patrimoine.db")
SCHEMA_PATH = Path("db") / "schema.sql"

class SyncedLibsqlConn:
    """
    Wrapper minimal:
    - commit() => sync() (pour pousser sur Turso)
    - close() safe
    - délègue tout le reste
    """
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def commit(self):
        self._conn.commit()
        # très important avec embedded replicas
        try:
            self._conn.sync()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

def get_conn():
    # 1) Lire les secrets Streamlit (Cloud) ou env vars (local)
    url = None
    token = None

    # Streamlit Cloud: st.secrets
    try:
        url = st.secrets.get("TURSO_DATABASE_URL")
        token = st.secrets.get("TURSO_AUTH_TOKEN")
    except Exception:
        url = None
        token = None

    # fallback env vars (utile en local)
    url = url or os.getenv("TURSO_DATABASE_URL")
    token = token or os.getenv("TURSO_AUTH_TOKEN")

    # 2) Si pas de secrets => fallback sqlite local (utile pour dev)
    if not url or not token:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    # 3) Embedded replica: fichier local + sync_url vers Turso
    # NB: le fichier local peut être perdu sur Streamlit, mais sync() le rehydrate
    conn = libsql.connect(str(DB_PATH), sync_url=url, auth_token=token)

    # Sync au démarrage pour récupérer l'état Turso
    try:
        conn.sync()
    except Exception:
        pass

    # Compat (certaines impl libsql n'ont pas row_factory, on tente sans casser)
    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass

    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass

    return SyncedLibsqlConn(conn)



def init_db() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema introuvable : {SCHEMA_PATH}")

    with get_conn() as conn:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        ensure_snapshots_table(conn)
        ensure_weekly_tables(conn)


        conn.commit()

def ensure_snapshots_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS patrimoine_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        snapshot_date TEXT NOT NULL,        -- 'YYYY-MM-DD'
        created_at TEXT NOT NULL,           -- ISO datetime
        mode TEXT DEFAULT 'AUTO',

        patrimoine_net REAL DEFAULT 0,
        patrimoine_brut REAL DEFAULT 0,

        liquidites_total REAL DEFAULT 0,
        bank_cash REAL DEFAULT 0,
        bourse_cash REAL DEFAULT 0,
        pe_cash REAL DEFAULT 0,

        bourse_holdings REAL DEFAULT 0,
        pe_value REAL DEFAULT 0,
        ent_value REAL DEFAULT 0,
        credits_remaining REAL DEFAULT 0,

        notes TEXT,

        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
        UNIQUE(person_id, snapshot_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_person_date ON patrimoine_snapshots(person_id, snapshot_date);")



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

def ensure_weekly_tables(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS asset_prices_weekly (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL,
      week_date TEXT NOT NULL,
      adj_close REAL NOT NULL,
      currency TEXT,
      source TEXT DEFAULT 'YFINANCE',
      created_at TEXT DEFAULT (datetime('now')),
      UNIQUE(symbol, week_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_apw_symbol_week ON asset_prices_weekly(symbol, week_date);")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS fx_rates_weekly (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      base_ccy TEXT NOT NULL,
      quote_ccy TEXT NOT NULL,
      week_date TEXT NOT NULL,
      rate REAL NOT NULL,
      source TEXT DEFAULT 'YFINANCE',
      created_at TEXT DEFAULT (datetime('now')),
      UNIQUE(base_ccy, quote_ccy, week_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fxw_pair_week ON fx_rates_weekly(base_ccy, quote_ccy, week_date);")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS patrimoine_snapshots_weekly (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      person_id INTEGER NOT NULL,
      week_date TEXT NOT NULL,
      created_at TEXT NOT NULL,
      mode TEXT DEFAULT 'MANUAL',

      patrimoine_net REAL DEFAULT 0,
      patrimoine_brut REAL DEFAULT 0,

      liquidites_total REAL DEFAULT 0,
      bank_cash REAL DEFAULT 0,
      bourse_cash REAL DEFAULT 0,
      pe_cash REAL DEFAULT 0,

      bourse_holdings REAL DEFAULT 0,
      pe_value REAL DEFAULT 0,
      ent_value REAL DEFAULT 0,
      credits_remaining REAL DEFAULT 0,

      notes TEXT,

      FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
      UNIQUE(person_id, week_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_psw_person_week ON patrimoine_snapshots_weekly(person_id, week_date);")
    
    conn.execute("""
    CREATE TABLE IF NOT EXISTS patrimoine_snapshots_family_weekly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER DEFAULT 1,
    week_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    mode TEXT DEFAULT 'REBUILD',

    patrimoine_net REAL DEFAULT 0,
    patrimoine_brut REAL DEFAULT 0,
    liquidites_total REAL DEFAULT 0,
    bourse_holdings REAL DEFAULT 0,
    pe_value REAL DEFAULT 0,
    ent_value REAL DEFAULT 0,
    credits_remaining REAL DEFAULT 0,

    notes TEXT,
    UNIQUE(family_id, week_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_psfw_family_week ON patrimoine_snapshots_family_weekly(family_id, week_date);")
    conn.commit()

class SyncedLibsqlConn:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # si pas d'erreur, on commit+sync
        if exc_type is None:
            try:
                self.commit()
            except Exception:
                pass
        # on ferme toujours
        try:
            self.close()
        except Exception:
            pass
        # False = ne pas masquer les exceptions
        return False

    def commit(self):
        self._conn.commit()
        try:
            self._conn.sync()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
