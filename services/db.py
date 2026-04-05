import os
import sqlite3
import logging
from pathlib import Path

try:
    import libsql
except ImportError:
    libsql = None

_logger = logging.getLogger(__name__)

# ── Chemins absolus (résistants aux changements de CWD) ──────────────────
_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _ROOT / "patrimoine.db"
SCHEMA_PATH = _ROOT / "db" / "schema.sql"
MIGRATIONS_PATH = _ROOT / "db" / "migrations"

# ──────────────────────────────────────────────────────────────
# Compat libsql ↔ sqlite3 : DictRow + WrappedCursor
# libsql retourne des tuples, sqlite3.Row supporte row["col"].
# Ce wrapper rend les deux transparents pour tout le codebase.
# ──────────────────────────────────────────────────────────────

class DictRow:
    """Simule sqlite3.Row : accès par clé ET par index."""

    __slots__ = ("_values", "_columns", "_map")

    def __init__(self, values, columns: list[str]):
        self._values = tuple(values)
        self._columns = columns
        self._map = {c: i for i, c in enumerate(columns)}

    # --- accès par clé ("col") ou par index (0) ---
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._map[key]]

    # --- dict(row) fonctionne grâce à keys() + __getitem__ ---
    def keys(self):
        return list(self._columns)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        pairs = ", ".join(f"{c}={v!r}" for c, v in zip(self._columns, self._values))
        return f"DictRow({pairs})"

    def __bool__(self):
        return True


class WrappedCursor:
    """Intercepte fetchone/fetchall pour retourner des DictRow."""

    def __init__(self, real_cursor):
        self._cursor = real_cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def _columns(self) -> list[str]:
        desc = self._cursor.description
        return [d[0] for d in desc] if desc else []

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        # sqlite3.Row a déjà keys() → pas besoin de wrapper
        if hasattr(row, "keys"):
            return row
        return DictRow(row, self._columns())

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return rows
        if hasattr(rows[0], "keys"):
            return rows
        cols = self._columns()
        return [DictRow(r, cols) for r in rows]

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            raise StopIteration
        return row


class SyncedLibsqlConn:
    """
    Wrapper complet pour les connexions libsql :
    - execute() → retourne un WrappedCursor (DictRow compat)
    - commit()  → sync() vers Turso
    - close()   → safe
    - délègue tout le reste
    """
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    # --- Curseur wrappé : chaque execute retourne un WrappedCursor ---
    def execute(self, sql, params=None):
        if params is not None:
            cursor = self._conn.execute(sql, params)
        else:
            cursor = self._conn.execute(sql)
        return WrappedCursor(cursor)

    def executemany(self, sql, params_list):
        cursor = self._conn.executemany(sql, params_list)
        return WrappedCursor(cursor)

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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Si pas d'erreur, on commit+sync
        if exc_type is None:
            try:
                self.commit()
            except Exception:
                pass
        # ⚠️ On ne ferme PAS ici : singleton partagé.
        # La fermeture se fait via close_connection() à l'arrêt de l'app.
        return False




def get_conn():
    # Lire les credentials depuis les variables d'environnement
    url = os.getenv("TURSO_DATABASE_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")

    # 2) Si pas de secrets => fallback sqlite local (utile pour dev)
    if not url or not token:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64 MB de cache
        conn.execute("PRAGMA synchronous = NORMAL;")  # Bon compromis perf/sécurité
        _logger.info("Connexion SQLite locale : %s (WAL activé)", DB_PATH)
        return conn

    # 3) Embedded replica: fichier local + sync_url vers Turso
    replica_path = str(DB_PATH).replace(".db", "_turso.db")
    conn = libsql.connect(replica_path, sync_url=url, auth_token=token)

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

def _row_get(row, key: str, idx: int = 0):
    if row is None:
        return None
    try:
        return row[key]
    except Exception:
        return row[idx]


def run_migrations(conn) -> list:
    """
    Applique les migrations SQL manquantes dans l'ordre numérique.
    Retourne la liste des versions appliquées.
    """
    # Crée la table si absente (pour les DBs avant l'ajout du versioning)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY,
      applied_at TEXT DEFAULT (datetime('now')),
      description TEXT
    )
    """)

    # Numéro de version courant
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = 0
    if row:
        try:
            v = row["v"]
        except Exception:
            v = row[0]
        if v is not None:
            current = int(v)

    if not MIGRATIONS_PATH.exists():
        return []

    applied = []
    migration_files = sorted(MIGRATIONS_PATH.glob("*.sql"))
    for mf in migration_files:
        # extrait le numéro depuis le nom de fichier (ex: 001_initial.sql -> 1)
        try:
            num = int(mf.stem.split("_")[0])
        except (ValueError, IndexError):
            continue

        if num <= current:
            continue

        sql = mf.read_text(encoding="utf-8")
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # index déjà présent etc.

        applied.append(num)

    if applied:
        conn.commit()

    return applied


def init_db() -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema introuvable : {SCHEMA_PATH}")

    with get_conn() as conn:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

        # ✅ Turso/libsql ne supporte pas executescript().
        # On exécute le schema instruction par instruction.
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        for stmt in statements:
            conn.execute(stmt)

        ensure_snapshots_table(conn)
        ensure_weekly_tables(conn)
        ensure_people_columns(conn)
        ensure_import_batches_table(conn)
        run_migrations(conn)

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
        immobilier_value REAL DEFAULT 0,
        credits_remaining REAL DEFAULT 0,

        notes TEXT,

        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
        UNIQUE(person_id, snapshot_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_person_date ON patrimoine_snapshots(person_id, snapshot_date);")

def _row_value(row, key: str, idx: int = 0):
    """
    Compat sqlite3.Row (row["c"]) ET tuples libsql (row[0]).
    """
    if row is None:
        return None
    try:
        return row[key]
    except Exception:
        return row[idx]


def seed_minimal() -> None:
    """
    Seed V1 :
    - 4 personnes : Papa, Maman, Maxime, Valentin
    - 1 compte BANQUE "Banque principale" par personne (modifiable/supprimable ensuite)
    ⚠️ Ne pas appeler init_db() ici — c'est fait par get_connection() avant.
    """
    with get_conn() as conn:
        # People
        row = conn.execute("SELECT COUNT(*) AS c FROM people;").fetchone()
        c = _row_value(row, "c", 0)
        if c == 0:
            for name in ["Papa", "Maman", "Maxime", "Valentin"]:
                conn.execute("INSERT INTO people(name) VALUES (?);", (name,))
            conn.commit()

        # Accounts
        row = conn.execute("SELECT COUNT(*) AS c FROM accounts;").fetchone()
        c2 = _row_value(row, "c", 0)
        if c2 == 0:
            people = conn.execute("SELECT id, name FROM people ORDER BY id;").fetchall()
            for p in people:
                person_id = _row_value(p, "id", 0)
                conn.execute(
                    """
                    INSERT INTO accounts(person_id, name, account_type, institution, currency)
                    VALUES (?,?,?,?,?)
                    """,
                    (person_id, "Banque principale", "BANQUE", None, "EUR"),
                )
            conn.commit()

def ensure_people_columns(conn) -> None:
    """Migrations additionnelles sur la table people."""
    try:
        conn.execute("ALTER TABLE people ADD COLUMN tr_phone TEXT;")
        conn.commit()
    except Exception:
        pass  # colonne déjà présente


def ensure_import_batches_table(conn) -> None:
    """Crée la table import_batches et ajoute import_batch_id aux tables de données (AM-19)."""
    # Table des batches d'import
    conn.execute("""
        CREATE TABLE IF NOT EXISTS import_batches (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          import_type  TEXT NOT NULL,
          person_id    INTEGER,
          person_name  TEXT,
          account_id   INTEGER,
          account_name TEXT,
          filename     TEXT,
          imported_at  TEXT DEFAULT (datetime('now')),
          nb_rows      INTEGER DEFAULT 0,
          status       TEXT NOT NULL DEFAULT 'ACTIVE',
          FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_import_batches_person "
        "ON import_batches(person_id, imported_at);"
    )

    # Colonne import_batch_id sur transactions, depenses, revenus
    for table in ("transactions", "depenses", "revenus"):
        try:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN import_batch_id INTEGER "
                f"REFERENCES import_batches(id) ON DELETE SET NULL;"
            )
        except Exception:
            pass  # colonne déjà présente

    try:
        conn.commit()
    except Exception:
        pass


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
      immobilier_value REAL DEFAULT 0,
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
    immobilier_value REAL DEFAULT 0,
    credits_remaining REAL DEFAULT 0,

    notes TEXT,
    UNIQUE(family_id, week_date)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_psfw_family_week ON patrimoine_snapshots_family_weekly(family_id, week_date);")

    # enterprise_history est geree par entreprises_repository.ensure_tables()

    # Migration : immobilier_value dans les snapshots existants
    for table in ["patrimoine_snapshots", "patrimoine_snapshots_weekly", "patrimoine_snapshots_family_weekly"]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN immobilier_value REAL DEFAULT 0;")
        except Exception:
            pass # déjà présente

    # Composite index pour les queries filtrées sur person + account
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_person_account_date ON transactions(person_id, account_id, date);")
    conn.commit()


def ensure_credits_migrations(conn) -> None:
    """Ajoute les colonnes manquantes à la table credits (BUG-05)."""
    try:
        conn.execute("ALTER TABLE credits ADD COLUMN payer_account_id INTEGER;")
        conn.commit()
        _logger.info("Migration : colonne payer_account_id ajoutée à credits.")
    except Exception:
        pass  # colonne déjà présente
