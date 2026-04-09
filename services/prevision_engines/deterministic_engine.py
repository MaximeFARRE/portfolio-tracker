import pandas as pd
from ..prevision_models import PrevisionBase, PrevisionConfig, PrevisionResult

def run_deterministic_projection(base: PrevisionBase, config: PrevisionConfig) -> PrevisionResult:
    """
    Moteur déterministe simple : applique des taux constants.
    Idéal pour une projection pédagogique très basique.
    """
    years = config.horizon_years
    months = years * 12
    
    # On simule la croissance sur le brut (actifs)
    total_assets = sum(base.assets_breakdown.values())
    
    if total_assets <= 0:
        # Fallback au net worth si le breakdown est vide (cas imprévu)
        total_assets = base.current_net_worth
    
    # Calcul d'un rendement global pondéré (V1)
    weighted_return = (
        (base.current_cash / total_assets * config.expected_cash_return) +
        (base.current_equity / total_assets * config.expected_equity_return)
        if total_assets > 0 else 0
    )
    
    monthly_rate = (1 + weighted_return) ** (1/12) - 1
    inflation_monthly = (1 + config.inflation_rate) ** (1/12) - 1
    
    # Taux réel simple
    real_rate = (1 + monthly_rate) / (1 + inflation_monthly) - 1
    
    values = [total_assets]
    current_val = total_assets
    
    for i in range(months):
        current_val = current_val * (1 + real_rate) + config.monthly_contribution
        values.append(current_val)
        
    dates = pd.date_range(start=pd.Timestamp.today().normalize().replace(day=1), periods=months+1, freq='MS')
    series = pd.Series(values, index=dates)
    
    # Recomposition du patrimoine net total
    if base.debts_schedule is not None:
        debt_values = base.debts_schedule.reindex(dates).fillna(0.0)
        # On définit le patrimoine net comme Valeurs des actifs (simulées) - Dette (déterministe)
        series = series - debt_values
    else:
        series = series - base.current_credits
    
    result = PrevisionResult(
        config=config,
        base=base,
        median_series=series,
        final_net_worth_median=float(series.iloc[-1])
    )
    
    return result
