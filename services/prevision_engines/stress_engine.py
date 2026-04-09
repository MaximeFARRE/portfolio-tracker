import pandas as pd
import numpy as np
from typing import Dict, Optional
from ..prevision_models import PrevisionBase, PrevisionConfig, PrevisionResult
from ..prevision_stress_models import StressScenario, StressResult

def _run_bucket_deterministic(base: PrevisionBase, config: PrevisionConfig, scenario: Optional[StressScenario] = None) -> PrevisionResult:
    """
    Simule de façon déterministe les buckets indépendamment avec ou sans stress.
    C'est plus précis que le deterministic_engine classique pour de la crise car on peut 
    impacter une seule ligne.
    """
    years = config.horizon_years
    months = years * 12
    
    bucket_names = ["Liquidités", "Bourse", "Immobilier", "PE", "Entreprises", "Crypto"]
    breakdown = base.assets_breakdown
    
    # Init state
    current_values = {b: breakdown.get(b, 0.0) for b in bucket_names}
    
    # Paramètres de stress
    has_stress = scenario is not None
    assets_stress = scenario.assets_stress if has_stress else {}
    income_stress = scenario.income_stress if has_stress else None
    
    # 1. Choc immédiat dès T=0
    if has_stress:
        for b in bucket_names:
            if b in assets_stress:
                drop_pct = assets_stress[b].immediate_drop_pct
                current_values[b] = current_values[b] * (1.0 - drop_pct)
    
    # Initial weights for savings distribution (fallback à 100% Liquidités)
    total_val = sum(current_values.values())
    if total_val > 0:
        dist = {b: current_values[b] / total_val for b in bucket_names}
    else:
        dist = {b: 0.0 for b in bucket_names}
        dist["Liquidités"] = 1.0

    history_gross = [sum(current_values.values())]
    
    inflation_monthly = (1 + config.inflation_rate) ** (1/12) - 1
    
    for month in range(1, months + 1):
        # Contribution
        contrib = config.monthly_contribution
        if has_stress and income_stress and month <= income_stress.duration_months:
            contrib = contrib * (1.0 - income_stress.savings_drop_pct)
            contrib = max(0.0, contrib)
            
        # Evolution de chaque bucket
        for b in bucket_names:
            annual_return = config.expected_returns.get(b, 0.0)
            monthly_return = (1 + annual_return) ** (1/12) - 1
            
            # Application stress progressif
            if has_stress and b in assets_stress:
                # Perte progressive sur la durée du choc
                stress_dur = scenario.stress_duration_months
                if month <= stress_dur and stress_dur > 0:
                    prog_drop_annual = assets_stress[b].progressive_drop_pct
                    prog_drop_monthly = prog_drop_annual / 12.0
                    monthly_return -= prog_drop_monthly
                
                # Rebond ? (Pas implémenté en V1 pour garder les choses simples, la reprise est organique)
                
            real_rate = (1 + monthly_return) / (1 + inflation_monthly) - 1
            
            # Capitalisation + Apport
            bucket_val = current_values[b]
            bucket_val = bucket_val * (1 + real_rate) + (contrib * dist[b])
            current_values[b] = max(0.0, bucket_val)
            
        history_gross.append(sum(current_values.values()))
        
    dates = pd.date_range(start=pd.Timestamp.today().normalize().replace(day=1), periods=months+1, freq='MS')
    series_gross = pd.Series(history_gross, index=dates)
    
    # Soustraction de la dette
    if base.debts_schedule is not None:
        debt_values = base.debts_schedule.reindex(dates).fillna(0.0)
        series_net = series_gross - debt_values
    else:
        series_net = series_gross - base.current_credits
        
    return PrevisionResult(
        config=config,
        base=base,
        median_series=series_net,
        final_net_worth_median=float(series_net.iloc[-1]),
        diagnostics=[f"Simulé {'avec' if has_stress else 'sans'} stress déterministe."]
    )

def run_stress_test(base: PrevisionBase, config: PrevisionConfig, scenario: StressScenario) -> StressResult:
    """
    Exécute et compare un scénario normal vs un scénario de stress, et calcule
    les métriques de drawdown et de recovery time.
    """
    # 1. Baseline
    baseline_result = _run_bucket_deterministic(base, config, scenario=None)
    
    # 2. Stresstest
    stressed_result = _run_bucket_deterministic(base, config, scenario=scenario)
    
    baseline_series = baseline_result.median_series
    stress_series = stressed_result.median_series
    
    final_base = float(baseline_series.iloc[-1])
    final_stress = float(stress_series.iloc[-1])
    delta_val = final_stress - final_base
    delta_pct = (delta_val / final_base) * 100.0 if final_base > 0 else 0.0
    
    initial_net = float(baseline_series.iloc[0])
    lowest_net = float(stress_series.min())
    
    # Max drawdown
    # On ajoute le net initial normal comme point temporel -1 pour que
    # le choc immédiat T=0 soit bien vu comme un drawdown.
    s_for_dd = pd.concat([pd.Series([initial_net]), stress_series])
    rolling_max = s_for_dd.cummax()
    drawdowns = (s_for_dd - rolling_max) / rolling_max
    drawdowns = drawdowns.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    max_dd = float(drawdowns.min() * 100.0) # Négatif
    
    # Recovery Pre-Shock
    recover_pre = None
    # Est-ce que le point bas repasse au-dessus de initial_net ?
    # Le mois du point bas
    idx_min = stress_series.argmin()
    post_min_series = stress_series.iloc[idx_min:]
    recovered_points = post_min_series[post_min_series >= initial_net]
    if not recovered_points.empty:
        recover_pre = int((recovered_points.index[0] - stress_series.index[0]).days // 30)
        
    # Recovery Baseline: est-ce que la courbe stressée rattrape la courbe baseline en fin de période ?
    # Très utile si la crise a un "recovery boost" (V2)
    recover_base = None
    post_min_diff = (stress_series.iloc[idx_min:] >= baseline_series.iloc[idx_min:])
    if post_min_diff.any():
        recover_idx = post_min_diff.idxmax()
        if post_min_diff[recover_idx]: # Vraiment repassé au-dessus
            recover_base = int((recover_idx - stress_series.index[0]).days // 30)

    res = StressResult(
        scenario=scenario,
        baseline_result=baseline_result,
        stressed_result=stressed_result,
        baseline_final_net_worth=final_base,
        stressed_final_net_worth=final_stress,
        delta_final_net_worth=delta_val,
        delta_final_pct=delta_pct,
        max_drawdown_pct=max_dd,
        lowest_net_worth=lowest_net,
        months_to_recover_pre_shock=recover_pre,
        months_to_recover_baseline=recover_base
    )
    return res
