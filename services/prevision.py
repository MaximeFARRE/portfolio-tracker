"""
prevision.py

Façade publique pour le nouveau domaine de prévision patrimoniale avancée.
"""

from typing import Optional
from .prevision_models import PrevisionConfig, PrevisionBase, PrevisionResult
from .prevision_base import build_prevision_base_for_scope
from .prevision_engines import run_deterministic_projection, run_monte_carlo_projection
from .prevision_risk import compute_risk_metrics
from .prevision_goals import compute_goal_metrics
from .prevision_explain import generate_prevision_diagnostics

from .prevision_stress_models import StressScenario, StressResult
from .prevision_stress import list_standard_scenarios
from .prevision_engines import run_stress_test

def get_prevision_base_for_scope(conn, scope_type: str, scope_id: int) -> PrevisionBase:
    """
    Point d'entrée pour récupérer l'état patrimonial consolidé de départ pour les projections.
    """
    return build_prevision_base_for_scope(conn, scope_type, scope_id)

def run_prevision(
    conn, 
    scope_type: str, 
    scope_id: int, 
    config: PrevisionConfig,
    engine: str = "monte_carlo"
) -> PrevisionResult:
    """
    Point d'entrée principal pour lancer une prévision (déterministe ou probabiliste).
    """
    # 1. Base consolidée
    base = get_prevision_base_for_scope(conn, scope_type, scope_id)
    
    # 2. Moteur
    if engine == "deterministic":
        result = run_deterministic_projection(base, config)
    elif engine == "monte_carlo":
        result = run_monte_carlo_projection(base, config)
    else:
        raise ValueError(f"Moteur inconnu: {engine}")
        
    # 3. Enrichissements
    result.risk_metrics = compute_risk_metrics(result)
    result.goal_metrics = compute_goal_metrics(result)
    
    # 4. Diagnostics et insights
    result.diagnostics = generate_prevision_diagnostics(result)
    
    return result

def run_stress_prevision(
    conn,
    scope_type: str,
    scope_id: int,
    config: PrevisionConfig,
    scenario: StressScenario
) -> StressResult:
    """
    Point d'entrée pour évaluer le patrimoine face à un scénario de crise spécifique.
    Retourne StressResult encapsulant la baseline et la trajectoire de crise.
    """
    base = get_prevision_base_for_scope(conn, scope_type, scope_id)
    return run_stress_test(base, config, scenario)
