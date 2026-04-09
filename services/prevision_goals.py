import numpy as np
from .prevision_models import PrevisionResult, GoalMetrics

def compute_goal_metrics(result: PrevisionResult) -> GoalMetrics:
    """
    Analyse les résultats des prévisions vis-à-vis d'un objectif de patrimoine cible.
    """
    target = result.config.target_goal_amount
    if not target or result.trajectories_df is None or result.trajectories_df.empty:
        return GoalMetrics(0.0, None, None)
        
    final_values = result.trajectories_df.iloc[-1].values
    successes = final_values >= target
    prob = float(np.sum(successes) / len(final_values)) if len(final_values) > 0 else 0.0
    
    # Calcul du manque à gagner médian (pour ceux qui échouent)
    shortfalls = target - final_values[~successes]
    median_shortfall = float(np.median(shortfalls)) if len(shortfalls) > 0 else 0.0
    
    return GoalMetrics(
        probability_of_success=prob,
        median_shortfall=median_shortfall,
        years_to_goal_median=None  # TODO: Calculer le temps d'atteinte
    )
