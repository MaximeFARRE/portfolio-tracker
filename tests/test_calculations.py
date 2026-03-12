import pandas as pd
import pytest
from services.calculations import solde_compte, cashflow_mois


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
