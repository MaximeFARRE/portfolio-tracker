import pytest
from services.credits import build_amortissement, CreditParams, _mensualite_standard


def test_mensualite_standard_taux_zero():
    # Si taux = 0 : mensualité = capital / durée
    assert _mensualite_standard(120_000, 0, 240) == pytest.approx(500.0)


def test_mensualite_standard_taux_normal():
    # Capital 200 000 €, 1.88% annuel, 240 mois
    r_m = 1.88 / 100 / 12
    m = _mensualite_standard(200_000, r_m, 240)
    assert 800 < m < 1200  # plage raisonnable


def test_build_amortissement_3_mois():
    params = CreditParams(
        capital=12_000.0,
        taux_annuel=6.0,
        duree_mois=3,
        date_debut="2025-01-01",
        assurance_mensuelle=0.0,
    )
    rows = build_amortissement(params)
    assert len(rows) == 3

    # Vérifications de base
    for r in rows:
        assert r["capital_amorti"] >= 0.0
        assert r["interets"] >= 0.0
        assert r["crd"] >= 0.0

    # Le CRD doit diminuer
    crds = [r["crd"] for r in rows]
    assert crds[0] > crds[-1]

    # CRD final doit être proche de 0
    assert crds[-1] < 10.0


def test_build_amortissement_assurance():
    params = CreditParams(
        capital=100_000.0,
        taux_annuel=2.0,
        duree_mois=12,
        date_debut="2025-01-01",
        assurance_mensuelle=50.0,
    )
    rows = build_amortissement(params)
    assert all(r["assurance"] == pytest.approx(50.0) for r in rows)


def test_build_amortissement_differe_partiel():
    params = CreditParams(
        capital=100_000.0,
        taux_annuel=2.0,
        duree_mois=6,
        date_debut="2025-01-01",
        differe_mois=2,
        differe_type="partiel",
    )
    rows = build_amortissement(params)
    assert len(rows) == 6
    # Pendant le différé : capital_amorti = 0
    assert rows[0]["capital_amorti"] == pytest.approx(0.0)
    assert rows[1]["capital_amorti"] == pytest.approx(0.0)
    # Après différé : amortissement
    assert rows[2]["capital_amorti"] > 0.0


def test_safe_float_via_replace_amortissement(conn_with_person):
    """Vérifie que replace_amortissement accepte des valeurs numériques."""
    from services.credits import replace_amortissement

    # Insère directement sans passer par upsert_credit (payer_account_id absent du schéma)
    cur = conn_with_person.execute(
        "INSERT INTO credits(person_id, account_id, nom, capital_emprunte, taux_nominal, duree_mois, date_debut, actif) "
        "VALUES (1, 1, 'Test', 100000.0, 2.0, 12, '2025-01-01', 1)"
    )
    conn_with_person.commit()
    credit_id = cur.lastrowid

    rows = [
        {"date_echeance": "2025-01-01", "mensualite": 850.0, "capital_amorti": 700.0,
         "interets": 150.0, "assurance": 30.0, "crd": 99300.0, "annee": 2025, "mois": 1},
    ]
    n = replace_amortissement(conn_with_person, credit_id, rows)
    assert n == 1


def test_build_amortissement_differe_total_interets_payes_keeps_crd_stable_during_differe():
    params = CreditParams(
        capital=1000.0,
        taux_annuel=12.0,
        duree_mois=2,
        date_debut="2025-01-01",
        assurance_mensuelle=10.0,
        differe_mois=1,
        differe_type="total",
        interets_pendant_differe="payes",
    )
    rows = build_amortissement(params)
    first = rows[0]

    assert first["interets"] == pytest.approx(10.0)
    assert first["mensualite"] == pytest.approx(20.0)
    assert first["capital_amorti"] == pytest.approx(0.0)
    assert first["crd"] == pytest.approx(1000.0)


def test_build_amortissement_differe_total_interets_capitalises_increases_crd():
    params = CreditParams(
        capital=1000.0,
        taux_annuel=12.0,
        duree_mois=2,
        date_debut="2025-01-01",
        assurance_mensuelle=10.0,
        differe_mois=1,
        differe_type="total",
        interets_pendant_differe="capitalises",
    )
    rows = build_amortissement(params)
    first = rows[0]

    assert first["interets"] == pytest.approx(0.0)
    assert first["mensualite"] == pytest.approx(10.0)
    assert first["capital_amorti"] == pytest.approx(0.0)
    assert first["crd"] == pytest.approx(1010.0)
