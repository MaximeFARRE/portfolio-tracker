import os
import sqlite3
import logging
from pathlib import Path
from typing import Callable
from services.common_utils import row_get

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

# Versions des migrations "code" (évite les ALTER TABLE au fil de l'eau).
MIG_VER_ADD_TR_PHONE = 9001
MIG_VER_IMPORT_BATCHES = 9002
MIG_VER_ADD_IMMO_COLUMNS = 9003
MIG_VER_ADD_CREDITS_PAYER_ACCOUNT = 9004
MIG_VER_ADD_TX_PERSON_ACCOUNT_INDEX = 9005
MIG_VER_ADD_PRESET_VOL_COLUMNS = 9006
MIG_VER_ADD_ASSET_IMPORT_ALIASES = 9007
MIG_VER_ADD_ACCOUNT_SUBTYPE = 9008
MIG_VER_ADD_TX_ANALYSIS_FLAGS = 9009

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
        if exc_type is None:
            try:
                self.commit()
            except Exception:
                pass
        
        self.close()
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
        return SyncedLibsqlConn(conn)

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
def _ensure_schema_version_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
          version INTEGER PRIMARY KEY,
          applied_at TEXT DEFAULT (datetime('now')),
          description TEXT
        )
        """
    )


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1;",
        (table_name,),
    ).fetchone()
    return row is not None


def _index_exists(conn, index_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name = ? LIMIT 1;",
        (index_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
    for row in rows:
        try:
            name = str(row["name"])
        except Exception:
            name = str(row[1])
        if name == column_name:
            return True
    return False


def _applied_versions(conn) -> set[int]:
    _ensure_schema_version_table(conn)
    rows = conn.execute("SELECT version FROM schema_version;").fetchall()
    versions: set[int] = set()
    for row in rows:
        try:
            versions.add(int(row["version"]))
        except Exception:
            versions.add(int(row[0]))
    return versions


def _mark_version_applied(conn, version: int, description: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, description) VALUES (?, ?);",
        (int(version), str(description)),
    )


def _split_sql_statements(sql_text: str) -> list[str]:
    return [s.strip() for s in sql_text.split(";") if s.strip()]


def _is_benign_migration_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "duplicate column name" in msg
        or ("already exists" in msg and "schema_version" not in msg)
    )


def _apply_sql_file_migration(conn, migration_file: Path, version: int) -> None:
    sql = migration_file.read_text(encoding="utf-8")
    for stmt in _split_sql_statements(sql):
        try:
            conn.execute(stmt)
        except Exception as exc:
            if _is_benign_migration_error(exc):
                _logger.warning(
                    "Migration %s: erreur bénigne ignorée sur '%s': %s",
                    migration_file.name,
                    stmt[:80],
                    exc,
                )
                continue
            raise

    # Les fichiers historiques écrivent déjà schema_version, mais on sécurise ici.
    _mark_version_applied(conn, version, f"sql:{migration_file.name}")


def _migrate_add_tr_phone(conn) -> None:
    if _column_exists(conn, "people", "tr_phone"):
        return
    conn.execute("ALTER TABLE people ADD COLUMN tr_phone TEXT;")


def _migrate_import_batches(conn) -> None:
    conn.execute(
        """
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
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_import_batches_person "
        "ON import_batches(person_id, imported_at);"
    )

    for table in ("transactions", "depenses", "revenus"):
        if not _column_exists(conn, table, "import_batch_id"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN import_batch_id INTEGER "
                f"REFERENCES import_batches(id) ON DELETE SET NULL;"
            )


def _migrate_add_immobilier_columns(conn) -> None:
    for table in (
        "patrimoine_snapshots",
        "patrimoine_snapshots_weekly",
        "patrimoine_snapshots_family_weekly",
    ):
        if _table_exists(conn, table) and not _column_exists(conn, table, "immobilier_value"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN immobilier_value REAL DEFAULT 0;")


def _migrate_add_credits_payer_account(conn) -> None:
    if _table_exists(conn, "credits") and not _column_exists(conn, "credits", "payer_account_id"):
        conn.execute("ALTER TABLE credits ADD COLUMN payer_account_id INTEGER;")


def _migrate_add_tx_person_account_index(conn) -> None:
    if _table_exists(conn, "transactions") and not _index_exists(conn, "idx_tx_person_account_date"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tx_person_account_date "
            "ON transactions(person_id, account_id, date);"
        )


def _migrate_add_preset_vol_columns(conn) -> None:
    """Ajoute les colonnes de volatilité par classe d'actif sur simulation_preset_settings."""
    if not _table_exists(conn, "simulation_preset_settings"):
        return
    _VOL_COLUMNS = {
        "vol_liquidites_pct":   1.0,
        "vol_bourse_pct":      15.0,
        "vol_immobilier_pct":   5.0,
        "vol_pe_pct":          20.0,
        "vol_entreprises_pct": 15.0,
        "vol_crypto_pct":      50.0,
    }
    for col, default in _VOL_COLUMNS.items():
        if not _column_exists(conn, "simulation_preset_settings", col):
            conn.execute(
                f"ALTER TABLE simulation_preset_settings "
                f"ADD COLUMN {col} REAL DEFAULT {default};"
            )


def _migrate_add_asset_import_aliases(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_import_aliases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          import_source TEXT NOT NULL,
          raw_symbol TEXT NOT NULL DEFAULT '',
          raw_isin TEXT NOT NULL DEFAULT '',
          canonical_asset_id INTEGER NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT DEFAULT (datetime('now')),
          last_used_at TEXT DEFAULT (datetime('now')),
          FOREIGN KEY(canonical_asset_id) REFERENCES assets(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_import_aliases_key "
        "ON asset_import_aliases(import_source, raw_symbol, raw_isin);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_import_aliases_source_symbol "
        "ON asset_import_aliases(import_source, raw_symbol);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_import_aliases_source_isin "
        "ON asset_import_aliases(import_source, raw_isin);"
    )


def _migrate_add_account_subtype(conn) -> None:
    """Ajoute accounts.subtype pour distinguer les sous-types de livrets."""
    if not _table_exists(conn, "accounts"):
        return
    if _column_exists(conn, "accounts", "subtype"):
        return
    conn.execute("ALTER TABLE accounts ADD COLUMN subtype TEXT;")


def _migrate_add_transaction_analysis_flags(conn) -> None:
    if not _table_exists(conn, "transactions"):
        return
    if not _column_exists(conn, "transactions", "is_hidden_from_cashflow"):
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN is_hidden_from_cashflow INTEGER NOT NULL DEFAULT 0;"
        )
    if not _column_exists(conn, "transactions", "is_internal_transfer"):
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN is_internal_transfer INTEGER NOT NULL DEFAULT 0;"
        )
    if not _column_exists(conn, "transactions", "deleted_at"):
        conn.execute("ALTER TABLE transactions ADD COLUMN deleted_at TEXT;")


_CODE_MIGRATIONS: list[tuple[int, str, Callable]] = [
    (MIG_VER_ADD_TR_PHONE, "add people.tr_phone", _migrate_add_tr_phone),
    (MIG_VER_IMPORT_BATCHES, "add import_batches + import_batch_id refs", _migrate_import_batches),
    (MIG_VER_ADD_IMMO_COLUMNS, "add immobilier_value columns on snapshot tables", _migrate_add_immobilier_columns),
    (MIG_VER_ADD_CREDITS_PAYER_ACCOUNT, "add credits.payer_account_id", _migrate_add_credits_payer_account),
    (MIG_VER_ADD_TX_PERSON_ACCOUNT_INDEX, "add idx_tx_person_account_date", _migrate_add_tx_person_account_index),
    (MIG_VER_ADD_PRESET_VOL_COLUMNS, "add vol_* columns on simulation_preset_settings", _migrate_add_preset_vol_columns),
    (MIG_VER_ADD_ASSET_IMPORT_ALIASES, "add asset_import_aliases table", _migrate_add_asset_import_aliases),
    (MIG_VER_ADD_ACCOUNT_SUBTYPE, "add accounts.subtype for livret subtypes", _migrate_add_account_subtype),
    (MIG_VER_ADD_TX_ANALYSIS_FLAGS, "add transaction analysis flags", _migrate_add_transaction_analysis_flags),
]


def apply_code_migrations(conn) -> list[int]:
    applied_now: list[int] = []
    applied = _applied_versions(conn)

    for version, description, migrate_fn in sorted(_CODE_MIGRATIONS, key=lambda x: x[0]):
        if int(version) in applied:
            continue
        migrate_fn(conn)
        _mark_version_applied(conn, int(version), description)
        applied_now.append(int(version))
        applied.add(int(version))

    if applied_now:
        conn.commit()
    return applied_now


def _apply_single_code_migration(conn, version: int) -> bool:
    for v, description, migrate_fn in _CODE_MIGRATIONS:
        if int(v) != int(version):
            continue
        applied = _applied_versions(conn)
        if int(v) in applied:
            return False
        migrate_fn(conn)
        _mark_version_applied(conn, int(v), description)
        conn.commit()
        return True
    raise ValueError(f"Migration code inconnue: {version}")


def run_migrations(conn) -> list:
    """
    Applique les migrations SQL manquantes dans l'ordre numérique.
    Retourne la liste des versions appliquées.
    """
    _ensure_schema_version_table(conn)
    applied_versions = _applied_versions(conn)

    if not MIGRATIONS_PATH.exists():
        return apply_code_migrations(conn)

    applied = []
    migration_files = sorted(MIGRATIONS_PATH.glob("*.sql"))
    for mf in migration_files:
        # extrait le numéro depuis le nom de fichier (ex: 001_initial.sql -> 1)
        try:
            num = int(mf.stem.split("_")[0])
        except (ValueError, IndexError):
            continue

        if num in applied_versions:
            continue

        _apply_sql_file_migration(conn, mf, num)
        applied.append(num)
        applied_versions.add(num)

    if applied:
        conn.commit()

    applied.extend(apply_code_migrations(conn))
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
    return row_get(row, key, idx)


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
    """Compat API: applique la migration versionnée de people.tr_phone."""
    _apply_single_code_migration(conn, MIG_VER_ADD_TR_PHONE)


def ensure_import_batches_table(conn) -> None:
    """Compat API: applique la migration versionnée import_batches."""
    _apply_single_code_migration(conn, MIG_VER_IMPORT_BATCHES)


def ensure_asset_import_aliases_table(conn) -> None:
    """Compat API: applique la migration versionnée asset_import_aliases."""
    _apply_single_code_migration(conn, MIG_VER_ADD_ASSET_IMPORT_ALIASES)


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

    # Composite index pour les queries filtrées sur person + account
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_person_account_date ON transactions(person_id, account_id, date);")
    conn.commit()


def ensure_credits_migrations(conn) -> None:
    """Compat API: applique la migration versionnée de credits."""
    changed = _apply_single_code_migration(conn, MIG_VER_ADD_CREDITS_PAYER_ACCOUNT)
    if changed:
        _logger.info("Migration appliquée : colonne credits.payer_account_id.")
