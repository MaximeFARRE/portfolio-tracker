import pytest
from unittest.mock import patch
import pandas as pd
from services.prevision_models import PrevisionConfig
from services.prevision import run_prevision, get_prevision_base_for_scope

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
