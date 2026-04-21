from services import repositories as repo


def _seed_people_accounts_assets(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute("INSERT INTO people(name) VALUES ('Bob')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'PEA Alice', 'PEA', 'EUR')"
    )
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (2, 'CTO Bob', 'CTO', 'EUR')"
    )
    conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) VALUES ('CW8', 'Amundi MSCI World', 'etf', 'EUR')"
    )
    conn.commit()


def test_update_transaction_updates_fields(conn):
    _seed_people_accounts_assets(conn)
    tx_id = repo.create_transaction(
        conn,
        {
            "date": "2026-04-01",
            "person_id": 1,
            "account_id": 1,
            "type": "ACHAT",
            "asset_id": 1,
            "quantity": 10.0,
            "price": 100.0,
            "fees": 1.0,
            "amount": 1000.0,
            "category": "Investissement",
            "note": "initial",
        },
    )

    repo.update_transaction(
        conn,
        tx_id,
        {
            "type": "vente",
            "quantity": 4.0,
            "price": 110.0,
            "fees": 0.5,
            "amount": 440.0,
            "note": "edit",
        },
    )

    tx = repo.get_transaction(conn, tx_id)
    assert tx is not None
    assert tx["type"] == "VENTE"
    assert float(tx["quantity"]) == 4.0
    assert float(tx["price"]) == 110.0
    assert float(tx["fees"]) == 0.5
    assert float(tx["amount"]) == 440.0
    assert tx["note"] == "edit"


def test_update_transaction_validates_account_person_coherence(conn):
    _seed_people_accounts_assets(conn)
    tx_id = repo.create_transaction(
        conn,
        {
            "date": "2026-04-01",
            "person_id": 1,
            "account_id": 1,
            "type": "ACHAT",
            "asset_id": 1,
            "quantity": 1.0,
            "price": 100.0,
            "fees": 0.0,
            "amount": 100.0,
        },
    )

    try:
        repo.update_transaction(conn, tx_id, {"account_id": 2, "person_id": 1})
        assert False, "Expected ValueError when person_id and account_id mismatch"
    except ValueError:
        pass

    repo.update_transaction(conn, tx_id, {"account_id": 2})
    tx = repo.get_transaction(conn, tx_id)
    assert tx is not None
    assert int(tx["account_id"]) == 2
    assert int(tx["person_id"]) == 2


def test_delete_transaction_removes_row(conn):
    _seed_people_accounts_assets(conn)
    tx_id = repo.create_transaction(
        conn,
        {
            "date": "2026-04-01",
            "person_id": 1,
            "account_id": 1,
            "type": "DEPOT",
            "amount": 500.0,
            "fees": 0.0,
        },
    )
    assert repo.get_transaction(conn, tx_id) is not None

    repo.delete_transaction(conn, tx_id)
    assert repo.get_transaction(conn, tx_id) is None
    tx_df = repo.list_transactions(conn, account_id=1, limit=10)
    assert tx_df.empty
