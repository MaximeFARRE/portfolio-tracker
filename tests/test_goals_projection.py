from datetime import date

import pandas as pd
import pytest

from services.goals_projection_repository import compute_goal_monthly_required_amount
from services.goals_projection_repository import create_goal, create_scenario
from services.projections import (
    build_standard_scenarios,
    compute_fire_target,
    estimate_fire_reach_date,
    get_projection_base_for_scope,
)


def test_compute_goal_monthly_required_amount():
    required = compute_goal_monthly_required_amount(
        target_amount=12_000,
        current_amount=6_000,
        target_date="2026-10-01",
        today=date(2026, 4, 5),
    )
    assert required == pytest.approx(1_000.0)


def test_compute_fire_target():
    assert compute_fire_target(2_000, 25) == pytest.approx(600_000.0)


def test_estimate_fire_reach_date():
    df = pd.DataFrame(
        [
            {"month_index": 0, "year": 0, "fire_target": 300_000.0, "is_fire_reached": False},
            {"month_index": 1, "year": 0, "fire_target": 300_000.0, "is_fire_reached": False},
            {"month_index": 2, "year": 0, "fire_target": 300_000.0, "is_fire_reached": True},
        ]
    )
    fire = estimate_fire_reach_date(df)
    assert fire["fire_reached"] is True
    assert fire["fire_month_index"] == 2
    assert fire["fire_year"] == 0
    assert fire["fire_target"] == pytest.approx(300_000.0)


def test_get_projection_base_for_family(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute("INSERT INTO people(name) VALUES ('Bob')")

    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_family_weekly(
            family_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining
        ) VALUES (1, '2026-03-23', datetime('now'), 'REBUILD', 200000, 260000, 40000, 25000, 5000, 10000, 180000, 60000)
        """
    )
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_family_weekly(
            family_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining
        ) VALUES (1, '2026-03-30', datetime('now'), 'REBUILD', 210000, 265000, 42000, 26000, 6000, 9000, 182000, 55000)
        """
    )

    for month, a_income, b_income, a_exp, b_exp in [
        ("2026-01-01", 3000.0, 2000.0, 1500.0, 1000.0),
        ("2026-02-01", 3200.0, 1800.0, 1700.0, 900.0),
    ]:
        conn.execute(
            "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, ?, 'Salaire', ?)",
            (month, a_income),
        )
        conn.execute(
            "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (2, ?, 'Salaire', ?)",
            (month, b_income),
        )
        conn.execute(
            "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, ?, 'Vie', ?)",
            (month, a_exp),
        )
        conn.execute(
            "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (2, ?, 'Vie', ?)",
            (month, b_exp),
        )
    conn.commit()

    base = get_projection_base_for_scope(conn, "family")
    assert base["scope_type"] == "family"
    assert base["scope_label"] == "Famille"
    assert base["net_worth"] == pytest.approx(210_000.0)
    assert base["gross_worth"] == pytest.approx(265_000.0)
    assert base["avg_monthly_income"] == pytest.approx(5_000.0)
    assert base["avg_monthly_expenses"] == pytest.approx(2_550.0)
    assert base["avg_monthly_savings"] == pytest.approx(2_450.0)


def test_get_projection_base_for_person(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, immobilier_value, pe_value, ent_value, credits_remaining
        ) VALUES (1, '2026-03-30', datetime('now'), 'REBUILD', 100000, 130000, 25000, 20000, 70000, 5000, 2000, 30000)
        """
    )
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2026-01-01', 'Salaire', 3000)"
    )
    conn.execute(
        "INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2026-02-01', 'Salaire', 3100)"
    )
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2026-01-01', 'Vie', 1500)"
    )
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2026-02-01', 'Vie', 1400)"
    )
    conn.commit()

    base = get_projection_base_for_scope(conn, "person", 1)
    assert base["scope_type"] == "person"
    assert base["scope_id"] == 1
    assert base["scope_label"] == "Alice"
    assert base["net_worth"] == pytest.approx(100_000.0)
    assert base["avg_monthly_income"] == pytest.approx(3_050.0)
    assert base["avg_monthly_expenses"] == pytest.approx(1_450.0)
    assert base["avg_monthly_savings"] == pytest.approx(1_600.0)


def test_build_standard_scenarios():
    scenarios = build_standard_scenarios({"avg_monthly_savings": 1_000.0}, horizon_years=15)
    assert [s.label for s in scenarios] == ["Pessimiste", "Médian", "Optimiste"]

    pessimiste, median, optimiste = scenarios
    assert pessimiste.expected_return_pct == pytest.approx(3.0)
    assert pessimiste.inflation_pct == pytest.approx(3.0)
    assert pessimiste.monthly_savings_override == pytest.approx(850.0)

    assert median.expected_return_pct == pytest.approx(6.0)
    assert median.monthly_savings_override is None

    assert optimiste.expected_return_pct == pytest.approx(8.0)
    assert optimiste.inflation_pct == pytest.approx(1.5)
    assert optimiste.monthly_savings_override == pytest.approx(1_150.0)


def test_create_goal_validation(conn):
    with pytest.raises(ValueError):
        create_goal(
            conn,
            {
                "name": "   ",
                "scope_type": "family",
                "scope_id": None,
                "target_amount": 1000,
            },
        )

    with pytest.raises(ValueError):
        create_goal(
            conn,
            {
                "name": "Objectif test",
                "scope_type": "family",
                "scope_id": None,
                "target_amount": -1,
            },
        )


def test_create_scenario_validation(conn):
    with pytest.raises(ValueError):
        create_scenario(
            conn,
            {
                "name": "",
                "scope_type": "family",
                "scope_id": None,
            },
        )

    with pytest.raises(ValueError):
        create_scenario(
            conn,
            {
                "name": "Scénario test",
                "scope_type": "family",
                "scope_id": None,
                "horizon_years": 0,
            },
        )
