"""
Tests DB pour le module services/credits.py.
Couvre : upsert_credit, replace_amortissement, get_credit_kpis,
         get_crd_a_date, cout_reel_mois_credit_via_bankin.
"""
import pytest
from services.credits import (
    upsert_credit,
    get_credit_by_account,
    replace_amortissement,
    get_amortissements,
    get_credit_kpis,
    get_crd_a_date,
    cout_reel_mois_credit_via_bankin,
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


# ─── get_crd_a_date ────────────────────────────────────────────────────────

def _insert_amortissement_2_mois(conn, credit_id: int) -> None:
    """Insere deux échéances pour les tests de CRD."""
    rows = [
        {
            "date_echeance": "2025-01-01",
            "mensualite": 1025.0,
            "capital_amorti": 700.0,
            "interets": 285.0,
            "assurance": 40.0,
            "crd": 99_300.0,
            "annee": 2025,
            "mois": 1,
        },
        {
            "date_echeance": "2025-02-01",
            "mensualite": 1025.0,
            "capital_amorti": 706.0,
            "interets": 279.0,
            "assurance": 40.0,
            "crd": 98_594.0,
            "annee": 2025,
            "mois": 2,
        },
    ]
    replace_amortissement(conn, credit_id, rows)


def test_get_crd_a_date_retourne_derniere_echeance_passee(conn_credit):
    """get_crd_a_date renvoie le CRD de la dernière échéance <= date_ref."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())
    _insert_amortissement_2_mois(conn_credit, credit_id)

    crd = get_crd_a_date(conn_credit, credit_id=credit_id, date_ref="2025-01-15")
    assert crd == pytest.approx(99_300.0)


def test_get_crd_a_date_apres_toutes_echeances(conn_credit):
    """get_crd_a_date après la dernière échéance renvoie le CRD de la dernière ligne."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())
    _insert_amortissement_2_mois(conn_credit, credit_id)

    crd = get_crd_a_date(conn_credit, credit_id=credit_id, date_ref="2030-01-01")
    assert crd == pytest.approx(98_594.0)


def test_get_crd_a_date_avant_premiere_echeance_renvoie_premier_crd(conn_credit):
    """get_crd_a_date avant toute échéance renvoie le CRD de la première ligne (fallback)."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())
    _insert_amortissement_2_mois(conn_credit, credit_id)

    crd = get_crd_a_date(conn_credit, credit_id=credit_id, date_ref="2024-01-01")
    # Fallback : première échéance disponible
    assert crd == pytest.approx(99_300.0)


def test_get_crd_a_date_sans_amortissement_retourne_zero(conn_credit):
    """Aucune échéance en base : get_crd_a_date retourne 0.0 sans planter."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())
    crd = get_crd_a_date(conn_credit, credit_id=credit_id, date_ref="2025-06-01")
    assert crd == pytest.approx(0.0)


# ─── cout_reel_mois_credit_via_bankin ──────────────────────────────────────

@pytest.fixture
def conn_credit_avec_payer(conn_credit):
    """Ajoute un compte payeur et le lie au crédit."""
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

    credit_id = conn_credit.execute(
        "SELECT id FROM credits WHERE account_id = 1"
    ).fetchone()[0]

    return conn_credit, credit_id, payer_id


def test_cout_reel_sans_payer_account_retourne_0(conn_credit):
    """Si payer_account_id est NULL, le coût réel est 0.0."""
    credit_id = upsert_credit(conn_credit, _base_credit_data())  # payer_account_id=None
    cout = cout_reel_mois_credit_via_bankin(
        conn_credit, credit_id=credit_id, mois_yyyy_mm_01="2025-01-01"
    )
    assert cout == pytest.approx(0.0)


def test_cout_reel_sans_transaction_retourne_0(conn_credit_avec_payer):
    """Aucune transaction pour ce mois : coût = 0.0."""
    conn, credit_id, _ = conn_credit_avec_payer
    cout = cout_reel_mois_credit_via_bankin(
        conn, credit_id=credit_id, mois_yyyy_mm_01="2025-01-01"
    )
    assert cout == pytest.approx(0.0)


def test_cout_reel_avec_transaction_echeance_pret(conn_credit_avec_payer):
    """Une transaction catégorie 'echeance pret' de type DEPENSE est comptée."""
    conn, credit_id, payer_id = conn_credit_avec_payer

    # Insérer une transaction correspondant à une échéance de crédit
    conn.execute(
        "INSERT INTO transactions(person_id, account_id, date, type, amount, category) "
        "VALUES (1, ?, '2025-01-15', 'DEPENSE', 1025.0, 'echeance pret immobilier')",
        (payer_id,)
    )
    conn.commit()

    cout = cout_reel_mois_credit_via_bankin(
        conn, credit_id=credit_id, mois_yyyy_mm_01="2025-01-01"
    )
    assert cout == pytest.approx(1025.0)


def test_cout_reel_ignore_transactions_hors_mois(conn_credit_avec_payer):
    """Les transactions hors du mois demandé ne sont pas comptées."""
    conn, credit_id, payer_id = conn_credit_avec_payer

    # Transaction en février : ne doit pas apparaitre dans janvier
    conn.execute(
        "INSERT INTO transactions(person_id, account_id, date, type, amount, category) "
        "VALUES (1, ?, '2025-02-15', 'DEPENSE', 1025.0, 'echeance pret immobilier')",
        (payer_id,)
    )
    conn.commit()

    cout = cout_reel_mois_credit_via_bankin(
        conn, credit_id=credit_id, mois_yyyy_mm_01="2025-01-01"
    )
    assert cout == pytest.approx(0.0)
