"""
Tests DB pour le module services/credits.py.
Couvre : upsert_credit, replace_amortissement, get_credit_kpis.
"""
import pytest
from services.credits import (
    upsert_credit,
    get_credit_by_account,
    replace_amortissement,
    get_amortissements,
    get_credit_kpis,
)


# ─── fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
def conn_credit(conn):
    """Connexion avec une personne et un compte CREDIT."""
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) "
        "VALUES (1, 'Crédit immo', 'CREDIT', 'EUR')"
    )
    conn.commit()
    return conn


def _base_credit_data(account_id: int = 1) -> dict:
    return {
        "person_id": 1,
        "account_id": account_id,
        "payer_account_id": None,
        "nom": "Crédit immo test",
        "banque": "BNP",
        "type_credit": "immobilier",
        "capital_emprunte": 200_000.0,
        "taux_nominal": 1.88,
        "taeg": 2.1,
        "duree_mois": 240,
        "mensualite_theorique": 985.0,
        "assurance_mensuelle_theorique": 40.0,
        "date_debut": "2024-01-01",
        "actif": 1,
    }


# ─── upsert_credit ───────────────────────────────────────────────────────────

def test_upsert_credit_creation(conn_credit):
    """upsert_credit crée la fiche et retourne un id > 0."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())
    assert credit_id > 0

    record = get_credit_by_account(conn_credit, account_id=1)
    assert record is not None
    assert record["nom"] == "Crédit immo test"
    assert float(record["capital_emprunte"]) == pytest.approx(200_000.0)


def test_upsert_credit_update_pas_de_doublon(conn_credit):
    """Un deuxième upsert sur le même account_id met à jour sans créer de doublon."""
    upsert_credit(conn_credit, _base_credit_data())

    data_updated = _base_credit_data()
    data_updated["nom"] = "Crédit immo v2"
    data_updated["mensualite_theorique"] = 1_010.0
    upsert_credit(conn_credit, data_updated)

    count = conn_credit.execute("SELECT COUNT(*) FROM credits WHERE account_id = 1").fetchone()[0]
    assert count == 1, "Il y a des doublons après double upsert"

    record = get_credit_by_account(conn_credit, account_id=1)
    assert record["nom"] == "Crédit immo v2"
    assert float(record["mensualite_theorique"]) == pytest.approx(1_010.0)


def test_upsert_credit_payer_account_id_persiste(conn_credit):
    """payer_account_id est correctement stocké et récupéré."""
    # Créer un deuxième compte (courant, qui paie le crédit)
    conn_credit.execute(
        "INSERT INTO accounts(person_id, name, account_type, currency) "
        "VALUES (1, 'Compte courant', 'BANQUE', 'EUR')"
    )
    conn_credit.commit()
    payer_id = conn_credit.execute(
        "SELECT id FROM accounts WHERE name = 'Compte courant'"
    ).fetchone()[0]

    data = _base_credit_data()
    data["payer_account_id"] = payer_id
    upsert_credit(conn_credit, data)

    record = get_credit_by_account(conn_credit, account_id=1)
    assert record["payer_account_id"] == payer_id


# ─── replace_amortissement ───────────────────────────────────────────────────

def _sample_rows(credit_id: int = 1) -> list:
    return [
        {
            "date_echeance": f"2024-0{i+1}-01",
            "mensualite": 1025.0,
            "capital_amorti": 700.0 + i * 10,
            "interets": 285.0 - i * 10,
            "assurance": 40.0,
            "crd": 200_000.0 - (700.0 + i * 10) * (i + 1),
            "annee": 2024,
            "mois": i + 1,
        }
        for i in range(3)
    ]


def test_replace_amortissement_idempotent(conn_credit):
    """Deux appels successifs n'empilent pas les lignes — seul le dernier reste."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())

    replace_amortissement(conn_credit, credit_id, _sample_rows())
    replace_amortissement(conn_credit, credit_id, _sample_rows())  # second replace

    df = get_amortissements(conn_credit, credit_id)
    assert len(df) == 3, "Les lignes ont été doublées au lieu d'être remplacées"


def test_replace_amortissement_vide_nettoie(conn_credit):
    """Un replace avec une liste vide supprime toutes les lignes existantes."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())
    replace_amortissement(conn_credit, credit_id, _sample_rows())

    nb = replace_amortissement(conn_credit, credit_id, [])
    assert nb == 0

    df = get_amortissements(conn_credit, credit_id)
    assert df.empty


# ─── get_credit_kpis ─────────────────────────────────────────────────────────

def test_get_credit_kpis_crd_toujours_positif_ou_zero(conn_credit):
    """Le CRD estimé retourné par get_credit_kpis ne peut pas être négatif."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())

    rows = [
        {
            "date_echeance": "2024-01-01",
            "mensualite": 1025.0,
            "capital_amorti": 700.0,
            "interets": 285.0,
            "assurance": 40.0,
            "crd": 199_300.0,
            "annee": 2024,
            "mois": 1,
        },
        {
            "date_echeance": "2024-02-01",
            "mensualite": 1025.0,
            "capital_amorti": 710.0,
            "interets": 275.0,
            "assurance": 40.0,
            "crd": 198_590.0,
            "annee": 2024,
            "mois": 2,
        },
    ]
    replace_amortissement(conn_credit, credit_id, rows)

    kpis = get_credit_kpis(conn_credit, credit_id)
    assert kpis["crd_estime"] >= 0.0
    assert kpis["interets_restants"] >= 0.0
    assert kpis["assurance_restante"] >= 0.0
    assert kpis["cout_restant_total"] == pytest.approx(
        kpis["interets_restants"] + kpis["assurance_restante"]
    )


def test_get_credit_kpis_sans_amortissement(conn_credit):
    """Sans amortissement, get_credit_kpis retourne des zéros sans planter."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())

    kpis = get_credit_kpis(conn_credit, credit_id)
    assert kpis["crd_estime"] == pytest.approx(0.0)
    assert kpis["interets_restants"] == pytest.approx(0.0)
