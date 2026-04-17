import sqlite3

from services.db import (
    MIG_VER_ADD_CREDITS_PAYER_ACCOUNT,
    MIG_VER_ADD_IMMO_COLUMNS,
    MIG_VER_ADD_TX_ANALYSIS_FLAGS,
    MIG_VER_ADD_TR_PHONE,
    MIG_VER_ADD_TX_PERSON_ACCOUNT_INDEX,
    MIG_VER_IMPORT_BATCHES,
    apply_code_migrations,
    ensure_credits_migrations,
    run_migrations,
)


def _colnames(conn, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
    out = set()
    for row in rows:
        try:
            out.add(str(row["name"]))
        except Exception:
            out.add(str(row[1]))
    return out


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
        (table_name,),
    ).fetchone()
    return row is not None


def _index_exists(conn, index_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=? LIMIT 1;",
        (index_name,),
    ).fetchone()
    return row is not None


def test_apply_code_migrations_adds_missing_structural_elements():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    # Simule une base legacy avec les tables mais sans colonnes ajoutées ensuite.
    conn.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
    conn.execute("CREATE TABLE credits (id INTEGER PRIMARY KEY);")
    conn.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY, person_id INTEGER, account_id INTEGER, date TEXT);")
    conn.execute("CREATE TABLE depenses (id INTEGER PRIMARY KEY);")
    conn.execute("CREATE TABLE revenus (id INTEGER PRIMARY KEY);")
    conn.execute("CREATE TABLE patrimoine_snapshots (id INTEGER PRIMARY KEY);")
    conn.execute("CREATE TABLE patrimoine_snapshots_weekly (id INTEGER PRIMARY KEY);")
    conn.execute("CREATE TABLE patrimoine_snapshots_family_weekly (id INTEGER PRIMARY KEY);")
    conn.commit()

    applied = apply_code_migrations(conn)

    assert MIG_VER_ADD_TR_PHONE in applied
    assert MIG_VER_IMPORT_BATCHES in applied
    assert MIG_VER_ADD_IMMO_COLUMNS in applied
    assert MIG_VER_ADD_CREDITS_PAYER_ACCOUNT in applied
    assert MIG_VER_ADD_TX_PERSON_ACCOUNT_INDEX in applied
    assert MIG_VER_ADD_TX_ANALYSIS_FLAGS in applied

    assert "tr_phone" in _colnames(conn, "people")
    assert "payer_account_id" in _colnames(conn, "credits")
    assert "import_batch_id" in _colnames(conn, "transactions")
    assert "is_hidden_from_cashflow" in _colnames(conn, "transactions")
    assert "is_internal_transfer" in _colnames(conn, "transactions")
    assert "deleted_at" in _colnames(conn, "transactions")
    assert "import_batch_id" in _colnames(conn, "depenses")
    assert "import_batch_id" in _colnames(conn, "revenus")
    assert "immobilier_value" in _colnames(conn, "patrimoine_snapshots")
    assert "immobilier_value" in _colnames(conn, "patrimoine_snapshots_weekly")
    assert "immobilier_value" in _colnames(conn, "patrimoine_snapshots_family_weekly")
    assert _table_exists(conn, "import_batches")
    assert _index_exists(conn, "idx_import_batches_person")
    assert _index_exists(conn, "idx_tx_person_account_date")

    # Idempotence: un second passage ne doit rien réappliquer.
    assert apply_code_migrations(conn) == []

    versions = {
        int(r["version"])
        for r in conn.execute("SELECT version FROM schema_version;").fetchall()
    }
    assert MIG_VER_ADD_TR_PHONE in versions
    assert MIG_VER_IMPORT_BATCHES in versions
    assert MIG_VER_ADD_IMMO_COLUMNS in versions
    assert MIG_VER_ADD_CREDITS_PAYER_ACCOUNT in versions
    assert MIG_VER_ADD_TX_PERSON_ACCOUNT_INDEX in versions
    assert MIG_VER_ADD_TX_ANALYSIS_FLAGS in versions

    conn.close()


def test_ensure_credits_migrations_is_versioned_and_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE credits (id INTEGER PRIMARY KEY);")
    conn.commit()

    ensure_credits_migrations(conn)
    ensure_credits_migrations(conn)

    assert "payer_account_id" in _colnames(conn, "credits")
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM schema_version WHERE version = ?;",
        (MIG_VER_ADD_CREDITS_PAYER_ACCOUNT,),
    ).fetchone()
    assert int(row["c"]) == 1
    conn.close()


def test_run_migrations_applies_sql_and_code_versions(conn):
    applied_first = run_migrations(conn)
    assert applied_first  # migration initiale attendue

    versions = {
        int(r["version"])
        for r in conn.execute("SELECT version FROM schema_version;").fetchall()
    }

    # SQL files
    assert 1 in versions
    assert 2 in versions
    assert 3 in versions
    assert 4 in versions

    # Code migrations
    assert MIG_VER_ADD_TR_PHONE in versions
    assert MIG_VER_IMPORT_BATCHES in versions
    assert MIG_VER_ADD_IMMO_COLUMNS in versions
    assert MIG_VER_ADD_CREDITS_PAYER_ACCOUNT in versions
    assert MIG_VER_ADD_TX_PERSON_ACCOUNT_INDEX in versions
    assert MIG_VER_ADD_TX_ANALYSIS_FLAGS in versions

    # Idempotence complète
    assert run_migrations(conn) == []
