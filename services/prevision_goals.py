import datetime
import numpy as np
import pandas as pd
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
        years_to_goal_median=None
    )


def compute_fire_date(
    median_series: pd.Series,
    fire_target: float,
) -> dict:
    """
    Détermine quand le patrimoine médian franchit la cible FIRE.

    Parcourt la série mensuelle et retourne le premier mois
    où la valeur dépasse fire_target.

    Args:
        median_series: Série pandas des valeurs médianes mensuelles.
        fire_target:   Cible patrimoniale FIRE en euros.

    Returns:
        dict avec :
          - fire_reached (bool)
          - fire_years (float | None)       : années depuis aujourd'hui
          - fire_year_calendar (int | None) : année calendaire estimée
    """
    _empty = {"fire_reached": False, "fire_years": None, "fire_year_calendar": None}

    if fire_target <= 0 or median_series is None or median_series.empty:
        return _empty

    current_year = datetime.date.today().year

    for month_idx, value in enumerate(median_series):
        if value >= fire_target:
            fire_years = month_idx / 12.0
            fire_year_calendar = current_year + int(fire_years)
            return {
                "fire_reached": True,
                "fire_years": round(fire_years, 1),
                "fire_year_calendar": fire_year_calendar,
            }

    return _empty
