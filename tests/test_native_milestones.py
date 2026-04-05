import pytest

from services.native_milestones import (
    NATIVE_MILESTONE_DEFINITIONS,
    build_native_milestones_for_scope,
    compute_current_milestone,
    get_featured_milestone_for_category,
    get_scope_milestone_metrics,
)


def test_compute_current_milestone_between_two_levels():
    result = compute_current_milestone(63_000, [60_000, 75_000, 100_000])
    assert result["current_level_index"] == 0
    assert result["current_level_value"] == pytest.approx(60_000.0)
    assert result["next_level_index"] == 1
    assert result["next_level_value"] == pytest.approx(75_000.0)
    assert result["progress_pct"] == pytest.approx(20.0)
    assert result["is_max_level"] is False


def test_compute_current_milestone_below_first_level():
    result = compute_current_milestone(250, [500, 1000])
    assert result["current_level_index"] == -1
    assert result["current_level_value"] == pytest.approx(0.0)
    assert result["next_level_index"] == 0
    assert result["next_level_value"] == pytest.approx(500.0)
    assert result["progress_pct"] == pytest.approx(50.0)


def test_compute_current_milestone_max_level():
    result = compute_current_milestone(2_500_000, [100_000, 500_000, 1_000_000])
    assert result["current_level_index"] == 2
    assert result["next_level_index"] is None
    assert result["is_max_level"] is True
    assert result["progress_pct"] == pytest.approx(100.0)


def test_get_scope_milestone_metrics_person(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, immobilier_value, pe_value, ent_value, credits_remaining
        ) VALUES (1, '2026-03-30', datetime('now'), 'REBUILD', 120000, 150000, 20000, 30000, 70000, 0, 0, 30000)
        """
    )
    conn.execute("INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2026-01-01', 'Salaire', 3000)")
    conn.execute("INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2026-02-01', 'Salaire', 3200)")
    conn.execute("INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2026-01-01', 'Vie', 1800)")
    conn.execute("INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2026-02-01', 'Vie', 1700)")
    conn.commit()

    metrics = get_scope_milestone_metrics(conn, "person", 1)
    assert metrics["net_worth"] == pytest.approx(120_000.0)
    assert metrics["liquidities"] == pytest.approx(20_000.0)
    assert metrics["stocks"] == pytest.approx(30_000.0)
    assert metrics["real_estate_value"] == pytest.approx(70_000.0)
    assert metrics["avg_monthly_income"] == pytest.approx(3_100.0)
    assert metrics["avg_monthly_expenses"] == pytest.approx(1_750.0)
    assert metrics["avg_monthly_savings"] == pytest.approx(1_350.0)
    assert metrics["savings_rate_12m"] > 0.0
    assert metrics["fire_progress"] > 0.0


def test_build_native_milestones_and_featured(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_family_weekly(
            family_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining
        ) VALUES (1, '2026-03-30', datetime('now'), 'REBUILD', 210000, 260000, 50000, 40000, 0, 0, 170000, 50000)
        """
    )
    conn.execute("INSERT INTO revenus(person_id, mois, categorie, montant) VALUES (1, '2026-01-01', 'Salaire', 4000)")
    conn.execute("INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2026-01-01', 'Vie', 2000)")
    conn.commit()

    milestones = build_native_milestones_for_scope(conn, "family")
    assert len(milestones) == len(NATIVE_MILESTONE_DEFINITIONS)

    featured = get_featured_milestone_for_category(milestones, "net_worth")
    assert featured is not None
    assert featured["category_label"] == "Patrimoine net"
    assert featured["level_number"] >= 1
