import pytest

from services import revenus_repository as rr


def test_revenus_consolides_include_passive_income(conn_with_person):
    conn = conn_with_person
    conn.execute(
        "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (2, 1, 'CTO', 'CTO', 'EUR')"
    )
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2025-06-01', 'Salaire', 900)"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-06-05', 1, 2, 'DIVIDENDE', 40, 0)"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-06-15', 1, 2, 'INTERETS', 10, 0)"
    )
    conn.commit()

    kpi = rr.revenus_kpis_mois(conn, 1, "2025-06-21")
    assert kpi["revenus_saisis"] == pytest.approx(900.0)
    assert kpi["dividendes"] == pytest.approx(40.0)
    assert kpi["interets"] == pytest.approx(10.0)
    assert kpi["total_revenus"] == pytest.approx(950.0)

    df_mois = rr.revenus_du_mois_consolides(conn, 1, "2025-06-01")
    assert not df_mois.empty
    assert "Dividendes (Bourse)" in set(df_mois["categorie"].tolist())
    assert "Intérêts (Bourse)" in set(df_mois["categorie"].tolist())

    df_hist = rr.revenus_par_mois_consolides(conn, 1)
    row = df_hist[df_hist["mois"] == "2025-06-01"].iloc[0]
    assert float(row["revenus_saisis"]) == pytest.approx(900.0)
    assert float(row["dividendes"]) == pytest.approx(40.0)
    assert float(row["interets"]) == pytest.approx(10.0)
    assert float(row["total"]) == pytest.approx(950.0)
