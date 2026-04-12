import pytest
from unittest.mock import patch
import pandas as pd
from services.prevision_models import PrevisionConfig
from services.prevision import run_prevision, get_prevision_base_for_scope
from services.projection_service import ProjectionService
from services.projections import ScenarioParams

@pytest.fixture
def dummy_conn():
    return None

def test_prevision_base_person(dummy_conn):
    # Mock des sources de vérité pour éviter d'avoir besoin de DB
    fake_metrics = {
        "net": 120000.0,
        "liq": 20000.0,
        "bourse": 80000.0,
        "immo_value": 0.0,
        "pe_value": 5000.0,
        "ent_value": 0.0,
        "credits": 15000.0,
        "capacite_epargne_avg": 500.0,
        "asof_date": "2026-04-07"
    }
    with patch("services.vue_ensemble_metrics.get_vue_ensemble_metrics", return_value=fake_metrics):
        base = get_prevision_base_for_scope(dummy_conn, "person", 1)
        
        assert base.current_net_worth == 120000.0
        assert base.assets_breakdown["Liquidités"] == 20000.0
        assert base.assets_breakdown["Bourse"] == 80000.0
        assert base.assets_breakdown["PE"] == 5000.0
        assert base.current_credits == 15000.0
        assert base.current_savings_per_year == 6000.0
        assert "scope_type" in base.metadata
        assert "scope_id" in base.metadata
        
        # Test que la somme des assets correspond au gross (allocation)
        assert base.allocation["Bourse"] == (80000.0 / 105000.0 * 100)

def test_run_prevision_deterministic(dummy_conn):
    config = PrevisionConfig(
        horizon_years=5,
        monthly_contribution=1000.0,
        expected_equity_return=0.08,
        expected_cash_return=0.02,
        inflation_rate=0.02
    )
    fake_metrics = {"net": 100000.0, "liq": 20000.0, "bourse": 80000.0}
    with patch("services.vue_ensemble_metrics.get_vue_ensemble_metrics", return_value=fake_metrics):
        result = run_prevision(dummy_conn, "person", 1, config, engine="deterministic")
        
        assert result is not None
        assert result.base.current_net_worth == 100000.0
        assert result.final_net_worth_median > 100000.0
        assert len(result.median_series) == 61
        assert result.risk_metrics is not None
        assert result.diagnostics is not None

def test_run_prevision_monte_carlo(dummy_conn):
    config = PrevisionConfig(
        horizon_years=3,
        num_simulations=100,
        target_goal_amount=120000.0,
        seed=42
    )
    fake_metrics = {"net": 100000.0, "liq": 50000.0, "bourse": 50000.0}
    with patch("services.vue_ensemble_metrics.get_vue_ensemble_metrics", return_value=fake_metrics):
        result = run_prevision(dummy_conn, "person", 1, config, engine="monte_carlo")
        
        assert result is not None
        assert result.trajectories_df is not None
        assert result.trajectories_df.shape == (37, 100)
        assert result.percentile_10_series is not None
        assert result.percentile_90_series is not None
        assert result.risk_metrics is not None
        assert result.goal_metrics is not None

def test_run_prevision_with_dynamic_debt(dummy_conn):
    # On simule un patrimoine de 100k€ avec 50k€ de bourse et 50k€ de liq
    # Et une dette qui s'éteint de 20k€ à 0€ en 12 mois
    config = PrevisionConfig(horizon_years=2, num_simulations=10, seed=42)
    fake_metrics = {"net": 80000.0, "liq": 50000.0, "bourse": 50000.0, "credits": 20000.0}
    
    start_date = pd.Timestamp.today().normalize().replace(day=1)
    dates = pd.date_range(start=start_date, periods=25, freq='MS')
    # Dette qui diminue de 20000 à 0 sur 12 mois puis reste à 0
    debt_values = [max(20000 - 2000*i, 0) for i in range(25)]
    debt_series = pd.Series(debt_values, index=dates)
    
    with patch("services.vue_ensemble_metrics.get_vue_ensemble_metrics", return_value=fake_metrics), \
         patch("services.prevision_base._get_aggregated_debts_schedule", return_value=debt_series):
        
        result = run_prevision(dummy_conn, "person", 1, config, engine="deterministic")
        
        # Au début : Net = 100k (actifs) - 20k (dette) = 80k
        assert result.median_series.iloc[0] == 80000.0
        
        # Après 12 mois, la dette est à 0. Le patrimoine net a donc "gagné" 20k par simple amortissement
        # (en plus du rendement des actifs)
        assert result.median_series.iloc[12] > 100000.0 # 80k + >20k amortis


def test_projection_service_routes_to_legacy(dummy_conn):
    params = ScenarioParams(label="Test", horizon_years=2)
    expected = pd.DataFrame([{"month_index": 0, "projected_net_worth": 1000.0}])
    with patch.object(ProjectionService, "run_legacy_projection", return_value=expected) as mock_legacy:
        out = ProjectionService.generate_projection(
            conn=dummy_conn,
            scope_type="person",
            scope_id=1,
            engine_type="legacy",
            options={"params": params, "exclude_primary_residence": True},
        )
        assert out is expected
        mock_legacy.assert_called_once_with(dummy_conn, "person", 1, params, True)


def test_projection_service_routes_to_advanced_and_defaults_scope_id(dummy_conn):
    config = object()
    expected = object()
    with patch.object(ProjectionService, "run_advanced_prevision", return_value=expected) as mock_adv:
        out = ProjectionService.generate_projection(
            conn=dummy_conn,
            scope_type="family",
            scope_id=None,
            engine_type="advanced",
            options={"config": config, "engine": "deterministic"},
        )
        assert out is expected
        mock_adv.assert_called_once_with(dummy_conn, "family", 1, config, "deterministic")


def test_projection_service_rejects_missing_or_invalid_inputs(dummy_conn):
    with pytest.raises(ValueError):
        ProjectionService.generate_projection(
            conn=dummy_conn,
            scope_type="person",
            scope_id=1,
            engine_type="legacy",
            options={},
        )

    with pytest.raises(ValueError):
        ProjectionService.generate_projection(
            conn=dummy_conn,
            scope_type="person",
            scope_id=1,
            engine_type="advanced",
            options={},
        )

    with pytest.raises(ValueError):
        ProjectionService.generate_projection(
            conn=dummy_conn,
            scope_type="person",
            scope_id=1,
            engine_type="unknown",  # type: ignore[arg-type]
            options={},
        )


def test_prevision_base_fire_expenses_from_cashflow_mean(conn_with_person):
    fake_metrics = {
        "net": 100000.0,
        "liq": 30000.0,
        "bourse": 70000.0,
        "immo_value": 0.0,
        "pe_value": 0.0,
        "ent_value": 0.0,
        "credits": 0.0,
        "capacite_epargne_avg": 500.0,
        "asof_date": "2026-04-07",
    }
    conn = conn_with_person
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2025-01-01', 'Vie', 100.0)"
    )
    conn.execute(
        "INSERT INTO depenses(person_id, mois, categorie, montant) VALUES (1, '2025-02-01', 'Vie', 300.0)"
    )
    conn.commit()

    with patch("services.vue_ensemble_metrics.get_vue_ensemble_metrics", return_value=fake_metrics), \
         patch("services.prevision_base._get_aggregated_debts_schedule", return_value=pd.Series(dtype=float)):
        base = get_prevision_base_for_scope(conn, "person", 1)

    assert base.fire_annual_expenses == pytest.approx(2400.0)


def test_prevision_base_family_uses_family_kpis_alloc_and_cashflow(conn):
    conn.execute("INSERT INTO people(name) VALUES ('Alice')")
    conn.execute("INSERT INTO people(name) VALUES ('Bob')")
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

    debt_series = pd.Series([55_000.0, 54_000.0], index=pd.to_datetime(["2026-04-01", "2026-05-01"]))
    with patch("services.prevision_base._get_aggregated_debts_schedule", return_value=debt_series):
        base = get_prevision_base_for_scope(conn, "family", 1)

    assert base.current_net_worth == pytest.approx(210_000.0)
    assert base.current_cash == pytest.approx(42_000.0)
    assert base.current_equity == pytest.approx(26_000.0)
    assert base.current_real_estate == pytest.approx(182_000.0)
    assert base.current_credits == pytest.approx(55_000.0)
    assert base.current_savings_per_year == pytest.approx(29_400.0)
    assert base.debts_schedule.equals(debt_series)


def test_prevision_deterministic_preserves_t0_net_when_no_debt_schedule(conn_with_person):
    fake_metrics = {
        "net": 80_000.0,
        "liq": 50_000.0,
        "bourse": 50_000.0,
        "immo_value": 0.0,
        "pe_value": 0.0,
        "ent_value": 0.0,
        "credits": 20_000.0,
        "capacite_epargne_avg": 0.0,
        "asof_date": "2026-04-07",
    }
    config = PrevisionConfig(
        horizon_years=1,
        monthly_contribution=0.0,
        expected_equity_return=0.0,
        expected_cash_return=0.0,
        inflation_rate=0.0,
    )
    with patch("services.vue_ensemble_metrics.get_vue_ensemble_metrics", return_value=fake_metrics), \
         patch("services.prevision_base._get_aggregated_debts_schedule", return_value=pd.Series(dtype=float)):
        result = run_prevision(conn_with_person, "person", 1, config, engine="deterministic")

    assert result.median_series.iloc[0] == pytest.approx(80_000.0)


def test_legacy_vs_advanced_minimal_consistency_on_zero_growth_case(conn_with_person):
    conn = conn_with_person
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, immobilier_value, pe_value, ent_value, credits_remaining
        ) VALUES (1, '2026-03-30', datetime('now'), 'REBUILD', 100000, 120000, 60000, 60000, 0, 0, 0, 20000)
        """
    )
    conn.commit()

    params = ScenarioParams(
        horizon_years=1,
        return_liquidites_pct=0.0,
        return_bourse_pct=0.0,
        return_immobilier_pct=0.0,
        return_pe_pct=0.0,
        return_entreprises_pct=0.0,
        inflation_pct=0.0,
        monthly_savings_override=0.0,
    )
    legacy_df = ProjectionService.run_legacy_projection(conn, "person", 1, params)

    config = PrevisionConfig(
        horizon_years=1,
        monthly_contribution=0.0,
        expected_equity_return=0.0,
        expected_cash_return=0.0,
        inflation_rate=0.0,
    )
    with patch("services.prevision_base._get_aggregated_debts_schedule", return_value=pd.Series(dtype=float)):
        advanced_res = run_prevision(conn, "person", 1, config, engine="deterministic")

    assert float(legacy_df.iloc[0]["projected_net_worth"]) == pytest.approx(100_000.0)
    assert float(legacy_df.iloc[-1]["projected_net_worth"]) == pytest.approx(100_000.0)
    assert float(advanced_res.median_series.iloc[0]) == pytest.approx(100_000.0)
    assert float(advanced_res.median_series.iloc[-1]) == pytest.approx(100_000.0)
