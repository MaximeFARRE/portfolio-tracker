import pandas as pd
import pytest
from services.calculations import solde_compte, cashflow_mois
from services.global_search_service import query_global_search


def _tx(*rows):
    """Helper: crée un DataFrame de transactions depuis des tuples (date, type, amount)."""
    return pd.DataFrame(rows, columns=["date", "type", "amount"])


def test_solde_vide():
    assert solde_compte(pd.DataFrame(columns=["date", "type", "amount"])) == 0.0


def test_solde_depot():
    tx = _tx(("2025-01-01", "DEPOT", 100.0))
    # RETRAIT est dans positifs dans validators.py (sens_flux), DEPOT aussi
    assert solde_compte(tx) == pytest.approx(100.0)


def test_solde_depot_et_depense():
    tx = _tx(
        ("2025-01-01", "DEPOT", 100.0),
        ("2025-01-15", "DEPENSE", 30.0),
    )
    # DEPOT +100, DEPENSE -30 -> 70
    assert solde_compte(tx) == pytest.approx(70.0)


def test_solde_achat_vente():
    tx = _tx(
        ("2025-01-01", "DEPOT", 200.0),
        ("2025-01-10", "ACHAT", 150.0),
        ("2025-02-01", "VENTE", 180.0),
    )
    # DEPOT +200, ACHAT -150, VENTE +180 = 230
    assert solde_compte(tx) == pytest.approx(230.0)


def test_cashflow_mois_filtre():
    tx = _tx(
        ("2025-01-15", "DEPOT", 1000.0),
        ("2025-02-10", "DEPOT", 500.0),
        ("2025-02-20", "DEPENSE", 200.0),
    )
    # cashflow février = 500 - 200 = 300
    assert cashflow_mois(tx, 2025, 2) == pytest.approx(300.0)


def test_cashflow_mois_vide():
    tx = _tx(("2025-01-15", "DEPOT", 1000.0))
    # aucune opération en mars
    assert cashflow_mois(tx, 2025, 3) == pytest.approx(0.0)


def test_global_search_service_empty_query_returns_empty(conn):
    assert query_global_search(conn, "   ") == []


def test_global_search_service_returns_expected_payload_shapes(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, institution, currency) "
        "VALUES (1, 'PEA Alice', 'PEA', 'BourseDirect', 'EUR')"
    )
    conn.execute(
        "INSERT INTO assets(symbol, name, asset_type, currency) "
        "VALUES ('AI', 'Air Liquide', 'action', 'EUR')"
    )
    conn.execute(
        """
        INSERT INTO transactions(
            date, person_id, account_id, type, asset_id, amount, category, note
        ) VALUES ('2026-01-10', 1, 1, 'ACHAT', 1, 1234.5, 'Invest', 'Achat AI')
        """
    )
    conn.commit()

    results_people = query_global_search(conn, "alice")
    kinds_people = {item["kind"] for item in results_people}
    assert {"person", "account", "transaction"}.issubset(kinds_people)

    results_assets = query_global_search(conn, "ai")
    kinds_assets = {item["kind"] for item in results_assets}
    assert "asset" in kinds_assets

    tx = next(item for item in results_people if item["kind"] == "transaction")
    assert tx["amount"] == "1 234.50"
    assert "🧾 Transaction #" in tx["label"]

    # Payload asset : person_id et account_id doivent être int ou None (jamais brut)
    asset = next(item for item in results_assets if item["kind"] == "asset")
    assert asset["person_id"] is None or isinstance(asset["person_id"], int)
    assert asset["account_id"] is None or isinstance(asset["account_id"], int)
    assert isinstance(asset["person_name"], str)
    assert isinstance(asset["account_name"], str)
