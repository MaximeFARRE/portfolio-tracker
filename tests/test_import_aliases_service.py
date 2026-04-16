from services import import_aliases_service as alias_svc


def _insert_asset(conn, symbol: str, name: str = "Asset") -> int:
    cur = conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) VALUES (?, ?, 'etf', 'EUR')",
        (symbol, name),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_find_canonical_asset_for_import_prioritizes_isin(conn):
    asset_isin = _insert_asset(conn, "CW8.PA", "MSCI World")
    asset_alias = _insert_asset(conn, "ALT.PA", "Alt Asset")
    conn.execute(
        "INSERT INTO asset_meta(asset_id, isin, status) VALUES (?, ?, 'OK')",
        (asset_isin, "IE00B4L5Y983"),
    )
    conn.commit()

    alias_svc.upsert_import_alias(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        canonical_asset_id=asset_alias,
        raw_symbol="EUNL.DE",
        raw_isin="IE00B4L5Y983",
    )

    found = alias_svc.find_canonical_asset_for_import(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        raw_symbol="EUNL.DE",
        raw_isin="IE00B4L5Y983",
    )
    assert found is not None
    assert int(found["asset_id"]) == asset_isin
    assert str(found["match_source"]).startswith("isin")


def test_find_canonical_asset_for_import_uses_alias_when_isin_unknown(conn):
    asset = _insert_asset(conn, "CW8.PA", "MSCI World")
    alias_svc.upsert_import_alias(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        canonical_asset_id=asset,
        raw_symbol="EUNL.DE",
        raw_isin="",
    )

    found = alias_svc.find_canonical_asset_for_import(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        raw_symbol="EUNL.DE",
        raw_isin="US0000000000",
    )
    assert found is not None
    assert int(found["asset_id"]) == asset
    assert found["match_source"] == "alias"


def test_upsert_import_alias_updates_canonical_asset(conn):
    asset_old = _insert_asset(conn, "OLD.PA")
    asset_new = _insert_asset(conn, "NEW.PA")

    ok1 = alias_svc.upsert_import_alias(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        canonical_asset_id=asset_old,
        raw_symbol="RAW.TR",
        raw_isin="",
    )
    ok2 = alias_svc.upsert_import_alias(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        canonical_asset_id=asset_new,
        raw_symbol="RAW.TR",
        raw_isin="",
    )
    assert ok1 is True
    assert ok2 is True

    found = alias_svc.find_canonical_asset_for_import(
        conn,
        alias_svc.IMPORT_SOURCE_TRADE_REPUBLIC,
        raw_symbol="RAW.TR",
        raw_isin="",
    )
    assert found is not None
    assert int(found["asset_id"]) == asset_new
