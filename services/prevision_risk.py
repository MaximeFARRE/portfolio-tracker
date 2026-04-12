import numpy as np
from .prevision_models import PrevisionResult, RiskMetrics

def compute_risk_metrics(result: PrevisionResult) -> RiskMetrics:
    """
    Calcule plusieurs métriques de risque (VaR, Drawdown) pour évaluer
    la robustesse du patrimoine face au scénario choisi.
    """
    if result.trajectories_df is None or result.trajectories_df.empty:
        return RiskMetrics(0.0, 0.0, 0.0, 0.0)
        
    df = result.trajectories_df
    
    final_values = df.iloc[-1].values
    initial_value = result.base.current_net_worth
    
    # Value at Risk 95% (Approximation simple sur le PnL global)
    # Perte max rencontrée dans 5% des pires cas
    losses = initial_value - final_values
    var_95 = float(np.percentile(losses, 95)) if len(losses) > 0 else 0.0
    if var_95 < 0: var_95 = 0.0
    
    # Conditional VaR (Expected shortfall)
    tail_losses = [loss for loss in losses if loss >= var_95]
    cvar_95 = float(np.mean(tail_losses)) if len(tail_losses) > 0 else 0.0
    if cvar_95 < 0 or np.isnan(cvar_95): cvar_95 = 0.0
    
    # Max drawdown estimé sur le P10 (scénario défavorable)
    # La médiane étant croissante par construction, son drawdown serait quasi-nul.
    # Le P10 représente un scénario réaliste de perte.
    dd_series = result.percentile_10_series if result.percentile_10_series is not None else result.median_series
    roll_max = dd_series.cummax()
    drawdown = (dd_series - roll_max) / roll_max
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
    
    return RiskMetrics(
        volatility=result.config.expected_equity_volatility,
        max_drawdown=max_dd,
        var_95=var_95,
        cvar_95=cvar_95
    )
