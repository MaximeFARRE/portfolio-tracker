from services import import_aliases_service as alias_svc
from services import tr_import
import pandas as pd


def _seed_person_and_account(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'PEA Alice', 'PEA', 'EUR')"
    )
    conn.commit()


def _seed_asset(conn, symbol: str, name: str = "Asset") -> int:
    cur = conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) VALUES (?, ?, 'etf', 'EUR')",
        (symbol, name),
    )
    conn.commit()
    return int(cur.lastrowid)


def _mock_tr_dataframe(date: str, isin: str, title: str = "World ETF") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date,
                "amount": -100,
                "type": "trade",
                "title": title,
                "isin": isin,
                "shares": 1,
                "price": 100,
                "fees": 0,
            }
        ]
    )


def test_import_tr_uses_saved_alias_mapping(conn, monkeypatch):
    _seed_person_and_account(conn)
    canonical_asset_id = _seed_asset(conn, "CW8.PA", "MSCI World")

    alias_svc.upsert_import_alias(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        canonical_asset_id=canonical_asset_id,
        raw_symbol="RAWTR.DE",
        raw_isin="IE000TEST0001",
    )

    monkeypatch.setattr(
        "services.isin_resolver.batch_resolve_isins",
        lambda _conn, _isins: {"IE000TEST0001": "RAWTR.DE"},
    )
    monkeypatch.setattr(
        tr_import,
        "parse_tr_csv",
        lambda _filepath: _mock_tr_dataframe("2026-01-10", "IE000TEST0001"),
    )

    out = tr_import.import_tr_transactions(
        conn,
        "tr.csv",
        person_id=1,
        account_id=1,
        dry_run=False,
    )
    assert out["to_insert"] == 1

    row = conn.execute(
        "SELECT asset_id FROM transactions WHERE person_id = 1 AND account_id = 1 LIMIT 1"
    ).fetchone()
    assert row is not None
    assert int(row["asset_id"]) == canonical_asset_id


def test_import_tr_saves_alias_when_user_overrides_canonical_symbol(conn, monkeypatch):
    _seed_person_and_account(conn)
    canonical_asset_id = _seed_asset(conn, "CW8.PA", "MSCI World")

    monkeypatch.setattr(
        "services.isin_resolver.batch_resolve_isins",
        lambda _conn, _isins: {"IE000TEST0001": "RAWTR.DE"},
    )
    monkeypatch.setattr(
        tr_import,
        "parse_tr_csv",
        lambda _filepath: _mock_tr_dataframe("2026-01-11", "IE000TEST0001"),
    )

    out = tr_import.import_tr_transactions(
        conn,
        "tr_override.csv",
        person_id=1,
        account_id=1,
        dry_run=False,
        canonical_symbol_map={"RAWTR.DE": "CW8.PA"},
    )
    assert out["to_insert"] == 1

    found = alias_svc.find_canonical_asset_for_import(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        raw_symbol="RAWTR.DE",
        raw_isin="IE000TEST0001",
    )
    assert found is not None
    assert int(found["asset_id"]) == canonical_asset_id
