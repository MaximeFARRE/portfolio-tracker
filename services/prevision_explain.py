from typing import List
from .prevision_models import PrevisionResult

def generate_prevision_diagnostics(result: PrevisionResult) -> List[str]:
    """
    Génère des insights métier textuels basés sur les résultats de la projection.
    
    Utile pour l'interprétation par l'utilisateur et la couche 'explicabilité'.
    """
    diagnostics = []
    
    if result.goal_metrics and result.goal_metrics.probability_of_success is not None:
        if result.goal_metrics.probability_of_success >= 0.8:
            diagnostics.append("Objectif hautement réalisable sous les hypothèses retenues.")
        elif result.goal_metrics.probability_of_success < 0.3:
            diagnostics.append("Attention : probabilité d'atteinte de l'objectif très faible.")
            
    if result.risk_metrics:
        # Si le maximal drawdown est très important (> 30%)
        if result.risk_metrics.max_drawdown < -0.30:
            diagnostics.append("Risque significatif de baisse transitoire du patrimoine (>30%).")
        elif result.risk_metrics.max_drawdown > -0.10:
            diagnostics.append("Profil de risque mesuré vis-à-vis des drawdowns attendus.")
            
    if not diagnostics:
        diagnostics.append("La trajectoire patrimoniale simulée ne présente pas d'alerte majeure.")
        
    return diagnostics
