"""
Tests pour services/cashflow.py :: get_family_flux_summary.

Cas couverts :
- aucune personne en base → résultat vide sans planter
- aucune transaction → résultat vide sans planter
- solde global calculé correctement depuis les transactions
- cashflow du mois correct (filtrage par year/month)
- ventilation par personne (colonnes + valeurs)
- ventilation par compte (colonnes + valeurs)
- year/month None → utilise le mois courant sans planter
"""
import pytest
import pandas as pd
from services.cashflow import get_family_flux_summary


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conn_famille(conn):
    """Connexion avec 2 personnes et 1 compte chacune."""
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute("INSERT INTO people(name) VALUES ('Bob')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) "
        "VALUES (1, 'Banque Alice', 'BANQUE', 'EUR')"
    )
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) "
        "VALUES (2, 'Banque Bob', 'BANQUE', 'EUR')"
    )
    conn.commit()
    return conn


def _insert_tx(conn, person_id: int, account_id: int,
               date: str, tx_type: str, amount: float) -> None:
    """Helper : insère une transaction minimale."""
    conn.execute(
        "INSERT INTO transactions(person_id, account_id, date, type, amount) "
        "VALUES (?, ?, ?, ?, ?)",
        (person_id, account_id, date, tx_type, amount),
    )
    conn.commit()


# ── Cas limites ───────────────────────────────────────────────────────────────

def test_family_flux_aucune_personne_retourne_vide(conn):
    """Sans personne en base, la fonction retourne un résultat vide sans planter."""
    result = get_family_flux_summary(conn, year=2025, month=1)

    assert result["solde_total"] == pytest.approx(0.0)
    assert result["cashflow_mois"] == pytest.approx(0.0)
    assert result["n_operations"] == 0
    assert isinstance(result["par_personne"], pd.DataFrame)
    assert isinstance(result["par_compte"], pd.DataFrame)


def test_family_flux_aucune_transaction_retourne_vide(conn_famille):
    """Personnes en base mais aucune transaction → résultat vide sans planter."""
    result = get_family_flux_summary(conn_famille, year=2025, month=1)

    assert result["solde_total"] == pytest.approx(0.0)
    assert result["n_operations"] == 0


def test_family_flux_year_month_none_ne_plante_pas(conn_famille):
    """year=None, month=None utilise le mois courant sans lever d'exception."""
    result = get_family_flux_summary(conn_famille)  # year et month = None
    assert "solde_total" in result
    assert "cashflow_mois" in result


# ── Calculs nominaux ──────────────────────────────────────────────────────────

def test_family_flux_solde_total(conn_famille):
    """Le solde total agrège les transactions des deux personnes."""
    _insert_tx(conn_famille, 1, 1, "2025-01-10", "DEPOT", 1000.0)
    _insert_tx(conn_famille, 1, 1, "2025-01-15", "DEPENSE", 200.0)
    _insert_tx(conn_famille, 2, 2, "2025-01-20", "DEPOT", 500.0)

    result = get_family_flux_summary(conn_famille, year=2025, month=1)

    # DEPOT +1000, DEPENSE -200, DEPOT +500 = 1300
    assert result["solde_total"] == pytest.approx(1300.0)
    assert result["n_operations"] == 3


def test_family_flux_cashflow_mois_filtre(conn_famille):
    """cashflow_mois ne tient compte que du mois demandé."""
    _insert_tx(conn_famille, 1, 1, "2024-12-01", "DEPOT", 999.0)  # autre mois
    _insert_tx(conn_famille, 1, 1, "2025-01-10", "DEPOT", 1000.0)
    _insert_tx(conn_famille, 1, 1, "2025-01-20", "DEPENSE", 300.0)

    result = get_family_flux_summary(conn_famille, year=2025, month=1)

    # Cashflow janvier = 1000 - 300 = 700 (999 de décembre ignoré)
    assert result["cashflow_mois"] == pytest.approx(700.0)


# ── Ventilation par personne ──────────────────────────────────────────────────

def test_family_flux_par_personne_colonnes(conn_famille):
    """Le DataFrame par_personne a les bonnes colonnes et une ligne par personne."""
    _insert_tx(conn_famille, 1, 1, "2025-01-10", "DEPOT", 500.0)

    result = get_family_flux_summary(conn_famille, year=2025, month=1)
    df = result["par_personne"]

    assert set(df.columns) >= {"Personne", "Solde (flux)", "Opérations"}
    assert len(df) == 2  # Alice + Bob


def test_family_flux_par_personne_soldes_isoles(conn_famille):
    """Le solde de chaque personne ne mélange pas les transactions des autres."""
    _insert_tx(conn_famille, 1, 1, "2025-01-10", "DEPOT", 800.0)
    _insert_tx(conn_famille, 2, 2, "2025-01-10", "DEPOT", 300.0)

    result = get_family_flux_summary(conn_famille, year=2025, month=1)
    df = result["par_personne"]

    alice_row = df[df["Personne"] == "Alice"]
    bob_row   = df[df["Personne"] == "Bob"]

    assert float(alice_row["Solde (flux)"].iloc[0]) == pytest.approx(800.0)
    assert float(bob_row["Solde (flux)"].iloc[0]) == pytest.approx(300.0)


# ── Ventilation par compte ────────────────────────────────────────────────────

def test_family_flux_par_compte_colonnes(conn_famille):
    """Le DataFrame par_compte a les bonnes colonnes et une ligne par compte."""
    _insert_tx(conn_famille, 1, 1, "2025-01-10", "DEPOT", 500.0)

    result = get_family_flux_summary(conn_famille, year=2025, month=1)
    df = result["par_compte"]

    assert set(df.columns) >= {"Personne", "Compte", "Solde (flux)", "Opérations"}
    assert len(df) == 2  # Banque Alice + Banque Bob


def test_family_flux_par_compte_solde_correct(conn_famille):
    """Le solde par compte reflète uniquement les transactions de ce compte."""
    _insert_tx(conn_famille, 1, 1, "2025-01-10", "DEPOT", 600.0)
    _insert_tx(conn_famille, 1, 1, "2025-01-20", "DEPENSE", 100.0)

    result = get_family_flux_summary(conn_famille, year=2025, month=1)
    df = result["par_compte"]

    alice_compte = df[df["Compte"] == "Banque Alice"]
    assert float(alice_compte["Solde (flux)"].iloc[0]) == pytest.approx(500.0)

    bob_compte = df[df["Compte"] == "Banque Bob"]
    assert float(bob_compte["Solde (flux)"].iloc[0]) == pytest.approx(0.0)


# ── Clés de retour ────────────────────────────────────────────────────────────

def test_family_flux_cles_retour_completes(conn_famille):
    """Le dictionnaire retourné contient toutes les clés attendues."""
    result = get_family_flux_summary(conn_famille, year=2025, month=1)

    expected_keys = {
        "solde_total", "cashflow_mois", "n_operations",
        "par_personne", "par_compte", "dernieres_operations",
    }
    assert expected_keys <= result.keys()
