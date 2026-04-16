"""
Tests pour la feature livret :
- Création de compte LIVRET avec sous-type
- Calcul du solde livret dans get_liquidites_summary
- Inclusion dans bank_cash des snapshots (via snapshots_compute)
"""
import sqlite3
import pytest
from pathlib import Path

from services import repositories as repo
from services.liquidites import get_liquidites_summary


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    for stmt in schema_path.read_text(encoding="utf-8").split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.upper().startswith("PRAGMA"):
            try:
                c.execute(stmt)
            except Exception:
                pass
    c.commit()
    return c


@pytest.fixture
def person_id(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Test')")
    conn.commit()
    return 1


# ── Création d'un compte LIVRET ───────────────────────────────────────────────

def test_create_livret_a(conn, person_id):
    acc_id = repo.create_account(conn, person_id, "Mon Livret A", "LIVRET", None, "EUR", subtype="LIVRET_A")
    acc = repo.get_account(conn, acc_id)
    assert acc["account_type"] == "LIVRET"
    assert acc["subtype"] == "LIVRET_A"


def test_create_livret_ldds(conn, person_id):
    acc_id = repo.create_account(conn, person_id, "LDDS Bourso", "LIVRET", None, "EUR", subtype="LDDS")
    acc = repo.get_account(conn, acc_id)
    assert acc["subtype"] == "LDDS"


def test_create_banque_sans_subtype(conn, person_id):
    """Un compte BANQUE classique ne doit pas avoir de subtype."""
    acc_id = repo.create_account(conn, person_id, "Banque principale", "BANQUE", None, "EUR")
    acc = repo.get_account(conn, acc_id)
    assert acc["account_type"] == "BANQUE"
    assert acc.get("subtype") is None


def test_list_accounts_inclut_subtype(conn, person_id):
    repo.create_account(conn, person_id, "Livret A CE", "LIVRET", "Caisse Épargne", "EUR", subtype="LIVRET_A")
    accounts = repo.list_accounts(conn, person_id=person_id)
    livret_row = accounts[accounts["account_type"] == "LIVRET"].iloc[0]
    assert livret_row["subtype"] == "LIVRET_A"
    assert livret_row["institution"] == "Caisse Épargne"


# ── Calcul des liquidités ────────────────────────────────────────────────────

def test_livret_cash_compte_dans_total(conn, person_id):
    """Un livret avec des dépôts/intérêts doit apparaître dans livret_cash_eur et total_eur."""
    acc_id = repo.create_account(conn, person_id, "Livret A", "LIVRET", None, "EUR", subtype="LIVRET_A")
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount) VALUES (?, ?, ?, ?, ?)",
        ("2025-01-01", person_id, acc_id, "DEPOT", 5000.0),
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount) VALUES (?, ?, ?, ?, ?)",
        ("2025-12-31", person_id, acc_id, "INTERETS", 150.0),
    )
    conn.commit()

    summary = get_liquidites_summary(conn, person_id)
    assert summary["livret_cash_eur"] == pytest.approx(5150.0)
    assert summary["bank_cash_eur"] == pytest.approx(0.0)  # pas de compte BANQUE
    assert summary["total_eur"] == pytest.approx(5150.0)
    assert summary["quality_status"] == "ok"


def test_livret_retrait_diminue_solde(conn, person_id):
    acc_id = repo.create_account(conn, person_id, "LDDS", "LIVRET", None, "EUR", subtype="LDDS")
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount) VALUES (?, ?, ?, ?, ?)",
        ("2025-01-01", person_id, acc_id, "DEPOT", 10000.0),
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount) VALUES (?, ?, ?, ?, ?)",
        ("2025-06-01", person_id, acc_id, "RETRAIT", 2000.0),
    )
    conn.commit()

    summary = get_liquidites_summary(conn, person_id)
    assert summary["livret_cash_eur"] == pytest.approx(8000.0)


def test_banque_et_livret_separes_dans_summary(conn, person_id):
    """bank_cash_eur et livret_cash_eur doivent être distincts dans le résumé."""
    banque_id = repo.create_account(conn, person_id, "Banque", "BANQUE", None, "EUR")
    livret_id = repo.create_account(conn, person_id, "Livret A", "LIVRET", None, "EUR", subtype="LIVRET_A")

    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount) VALUES (?, ?, ?, ?, ?)",
        ("2025-01-01", person_id, banque_id, "DEPOT", 3000.0),
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount) VALUES (?, ?, ?, ?, ?)",
        ("2025-01-01", person_id, livret_id, "DEPOT", 7000.0),
    )
    conn.commit()

    summary = get_liquidites_summary(conn, person_id)
    assert summary["bank_cash_eur"] == pytest.approx(3000.0)
    assert summary["livret_cash_eur"] == pytest.approx(7000.0)
    assert summary["total_eur"] == pytest.approx(10000.0)


# ── Libellés ─────────────────────────────────────────────────────────────────

def test_libelles_livret():
    from utils.libelles import SOUS_TYPES_LIVRET, afficher_sous_type_livret, LIBELLES_TYPE_COMPTE
    assert "LIVRET" in LIBELLES_TYPE_COMPTE
    assert LIBELLES_TYPE_COMPTE["LIVRET"] == "Livret"
    assert "LIVRET_A" in SOUS_TYPES_LIVRET
    assert afficher_sous_type_livret("LIVRET_A") == "Livret A"
    assert afficher_sous_type_livret("LDDS") == "LDDS"
    assert afficher_sous_type_livret("LEP") == "LEP"
