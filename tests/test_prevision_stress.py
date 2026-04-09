import pytest
import pandas as pd
from services.prevision_models import PrevisionConfig, PrevisionBase
from services.prevision_stress_models import StressScenario, AssetStress, IncomeStress
from services.prevision_stress import get_equity_crash_20, get_income_shock_12m, get_double_shock
from services.prevision_engines.stress_engine import run_stress_test

def make_dummy_base():
    return PrevisionBase(
        current_net_worth=200000.0,
        current_cash=50000.0,
        current_equity=100000.0,
        current_real_estate=50000.0,
        current_credits=0.0
    )

def make_dummy_config():
    return PrevisionConfig(
        horizon_years=5,
        monthly_contribution=1000.0,
        inflation_rate=0.02
    )

def test_equity_crash_reduces_trajectory():
    base = make_dummy_base()
    config = make_dummy_config()
    scenario = get_equity_crash_20()
    
    result = run_stress_test(base, config, scenario)
    
    # Validation du delta
    assert result.delta_final_net_worth < 0
    assert result.delta_final_pct < 0
    
    # Le krach de 20% sur 100k€ de bourse = -20k immédiat
    # On vérifie que la série stressée commence plus bas que la série de base
    baseline_t0 = result.baseline_result.median_series.iloc[0]
    stress_t0 = result.stressed_result.median_series.iloc[0]
    
    assert stress_t0 < baseline_t0
    assert (baseline_t0 - stress_t0) == 20000.0
    
    assert result.max_drawdown_pct <= 0.0

def test_income_shock_impacts_final_worth():
    base = make_dummy_base()
    config = make_dummy_config()
    scenario = get_income_shock_12m()
    
    result = run_stress_test(base, config, scenario)
    
    # A t=0, pas de choc sur le capital, les deux séries sont au même point
    baseline_t0 = result.baseline_result.median_series.iloc[0]
    stress_t0 = result.stressed_result.median_series.iloc[0]
    assert baseline_t0 == stress_t0
    
    # A t=5 ans, l'arrêt de 1k€/mois pendant 1 an a fait perdre (12k + intérêts composés)
    assert result.delta_final_net_worth < -12000.0

def test_double_shock_is_worse_than_single():
    base = make_dummy_base()
    config = make_dummy_config()
    
    res_equity = run_stress_test(base, config, get_equity_crash_20())
    res_double = run_stress_test(base, config, get_double_shock())
    
    assert res_double.stressed_final_net_worth < res_equity.stressed_final_net_worth
    assert res_double.delta_final_net_worth < res_equity.delta_final_net_worth

def test_missing_buckets_handled_gracefully():
    # Tout en liquidités, on crash la bourse : l'impact doit être nul
    base = PrevisionBase(
        current_net_worth=100000.0,
        current_cash=100000.0,
        current_equity=0.0,
        current_real_estate=0.0
    )
    config = make_dummy_config()
    scenario = get_equity_crash_20()
    
    result = run_stress_test(base, config, scenario)
    
    # Le delta devrait être extrêmement proche de 0
    # Car l'apport ira en partie en bourse si on ne force pas (mais l'initial est de 0 donc l'apport va 100% sur liquidité dans stress_engine)
    assert abs(result.delta_final_net_worth) < 1.0

def test_stress_result_metrics():
    base = make_dummy_base()
    config = make_dummy_config()
    
    # On fait un krach de bourse massif (-90%) pour s'assurer que ça met longtemps à récupérer
    scenario = StressScenario(
        name="apocalypse",
        description="Crash",
        assets_stress={"Bourse": AssetStress(immediate_drop_pct=0.90)}
    )
    
    result = run_stress_test(base, config, scenario)
    
    assert result.lowest_net_worth <= result.stressed_result.median_series.iloc[0]
    assert result.max_drawdown_pct < -20.0 # Baisse d'au moins 20% car la bourse pèse 50% de l'actif
