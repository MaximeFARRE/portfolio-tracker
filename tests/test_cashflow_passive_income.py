import pytest

from services.cashflow import get_cashflow_for_scope, get_person_monthly_savings_series


def test_person_cashflow_includes_dividendes_and_interets(conn_with_person):
    conn = conn_with_person
    conn.execute(
        "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (2, 1, 'CTO', 'CTO', 'EUR')"
    )
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2025-03-01', 'Salaire', 1000)"
    )
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2025-03-01', 'Vie', 300)"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-03-10', 1, 2, 'DIVIDENDE', 50, 0)"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-03-20', 1, 2, 'INTERETS', 20, 0)"
    )
    conn.commit()

    df = get_cashflow_for_scope(conn, "person", 1)
    row = df[df["mois_dt"].dt.strftime("%Y-%m-%d") == "2025-03-01"].iloc[-1]
    assert float(row["income"]) == pytest.approx(1070.0)
    assert float(row["expenses"]) == pytest.approx(300.0)
    assert float(row["savings"]) == pytest.approx(770.0)


def test_family_cashflow_includes_passive_income_for_all_people(conn):
    conn.execute("INSERT INTO people(id, name) VALUES (1, 'Alice')")
    conn.execute("INSERT INTO people(id, name) VALUES (2, 'Bob')")
    conn.execute(
        "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (10, 1, 'CTO Alice', 'CTO', 'EUR')"
    )
    conn.execute(
        "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (20, 2, 'CTO Bob', 'CTO', 'EUR')"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-04-02', 1, 10, 'DIVIDENDE', 30, 0)"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-04-03', 2, 20, 'INTERETS', 15, 0)"
    )
    conn.commit()

    df = get_cashflow_for_scope(conn, "family")
    row = df[df["mois_dt"].dt.strftime("%Y-%m-%d") == "2025-04-01"].iloc[-1]
    assert float(row["income"]) == pytest.approx(45.0)
    assert float(row["expenses"]) == pytest.approx(0.0)
    assert float(row["savings"]) == pytest.approx(45.0)


def test_monthly_savings_series_uses_passive_income(conn_with_person):
    conn = conn_with_person
    conn.execute(
        "INSERT INTO accounts(id, person_id, name, account_type, currency) VALUES (2, 1, 'PEA', 'PEA', 'EUR')"
    )
    conn.execute(
        "INSERT INTO transactions(date, person_id, account_id, type, amount, fees) VALUES ('2025-05-10', 1, 2, 'DIVIDENDE', 120, 0)"
    )
    conn.commit()

    df = get_person_monthly_savings_series(conn, 1, n_mois=1, end_month="2025-05-15")
    assert list(df["mois"]) == ["2025-05-01"]
    assert float(df.iloc[0]["revenus"]) == pytest.approx(120.0)
    assert float(df.iloc[0]["epargne"]) == pytest.approx(120.0)
    assert float(df.iloc[0]["taux_epargne"]) == pytest.approx(100.0)
