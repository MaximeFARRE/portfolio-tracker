import sqlite3

from services import repositories as repo
from services.imports import sync_bankin_monthly_tables


def _insert_person_and_account(conn: sqlite3.Connection) -> tuple[int, int]:
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) VALUES (1, 'Compte A', 'BANQUE', 'EUR')"
    )
    conn.commit()
    return 1, 1


def test_sync_bankin_monthly_excludes_hidden_internal_and_deleted(conn):
    person_id, account_id = _insert_person_and_account(conn)
    conn.execute(
        """
        INSERT INTO transactions(date, person_id, account_id, type, amount, category, note)
        VALUES ('2026-01-05', ?, ?, 'DEPENSE', 100, 'Courses', 'Bankin: Alimentation > Supermarché | Test')
        """,
        (person_id, account_id),
    )
    conn.execute(
        """
        INSERT INTO transactions(date, person_id, account_id, type, amount, category, note, is_internal_transfer)
        VALUES ('2026-01-06', ?, ?, 'DEPOT', 1000, 'Flux financiers', 'Bankin: Retraits, chèques et virements > Virements internes | Test', 1)
        """,
        (person_id, account_id),
    )
    conn.execute(
        """
        INSERT INTO transactions(date, person_id, account_id, type, amount, category, note)
        VALUES ('2026-01-10', ?, ?, 'DEPOT', 2500, 'Salaire', 'Bankin: Entrées d''argent > Salaires | Test')
        """,
        (person_id, account_id),
    )
    conn.commit()

    sync_bankin_monthly_tables(conn, person_id, months=["2026-01-01"])

    dep = conn.execute(
        "SELECT categorie, montant FROM depenses WHERE person_id = ? AND mois = '2026-01-01'",
        (person_id,),
    ).fetchall()
    rev = conn.execute(
        "SELECT categorie, montant FROM revenus WHERE person_id = ? AND mois = '2026-01-01'",
        (person_id,),
    ).fetchall()
    assert len(dep) == 1
    assert dep[0]["categorie"] == "Courses"
    assert float(dep[0]["montant"]) == 100.0
    assert len(rev) == 1
    assert rev[0]["categorie"] == "Salaire"
    assert float(rev[0]["montant"]) == 2500.0


def test_transaction_management_functions_resync_bankin_cashflow(conn):
    person_id, account_id = _insert_person_and_account(conn)
    tx_id = repo.create_transaction(
        conn,
        {
            "date": "2026-02-03",
            "person_id": person_id,
            "account_id": account_id,
            "type": "DEPENSE",
            "amount": 120.0,
            "category": "Restaurants",
            "note": "Bankin: Alimentation et restau. > Restaurants | Test",
        },
    )
    sync_bankin_monthly_tables(conn, person_id, months=["2026-02-01"])

    row = conn.execute(
        "SELECT categorie, montant FROM depenses WHERE person_id = ? AND mois = '2026-02-01'",
        (person_id,),
    ).fetchone()
    assert row is not None
    assert row["categorie"] == "Restaurants"

    assert repo.update_transaction_category(conn, tx_id, "Sorties")
    row = conn.execute(
        "SELECT categorie, montant FROM depenses WHERE person_id = ? AND mois = '2026-02-01'",
        (person_id,),
    ).fetchone()
    assert row is not None
    assert row["categorie"] == "Sorties"

    assert repo.hide_transaction(conn, tx_id, True)
    count_dep = conn.execute(
        "SELECT COUNT(*) AS c FROM depenses WHERE person_id = ? AND mois = '2026-02-01'",
        (person_id,),
    ).fetchone()
    assert int(count_dep["c"]) == 0

    assert repo.hide_transaction(conn, tx_id, False)
    assert repo.mark_transaction_as_internal_transfer(conn, tx_id, True)
    count_dep = conn.execute(
        "SELECT COUNT(*) AS c FROM depenses WHERE person_id = ? AND mois = '2026-02-01'",
        (person_id,),
    ).fetchone()
    assert int(count_dep["c"]) == 0

    assert repo.mark_transaction_as_internal_transfer(conn, tx_id, False)
    assert repo.delete_transaction(conn, tx_id) is None
    tx_visible = repo.list_transactions(conn, person_id=person_id, account_id=account_id, limit=50)
    assert tx_visible.empty

    tx_all = repo.list_transactions(
        conn,
        person_id=person_id,
        account_id=account_id,
        limit=50,
        include_deleted=True,
    )
    assert not tx_all.empty
    assert str(tx_all.iloc[0]["analysis_state"]) == "DELETED"
