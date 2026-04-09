from dataclasses import dataclass, field
from typing import Dict, Optional
import pandas as pd
from .prevision_models import PrevisionResult

@dataclass
class AssetStress:
    """Altérations applicables à une classe d'actifs (pour un bucket)."""
    immediate_drop_pct: float = 0.0      # Baisse immédiate au mois 0 (ex: 0.20 pour -20%)
    progressive_drop_pct: float = 0.0    # Baisse (ou perte de rendement) répartie sur la durée du stress
    recovery_months: int = 0             # Temps avant un retour pur et simple à la normale des rendements (si 0 = pas de rebond technique forcé)

@dataclass
class IncomeStress:
    """Altérations sur les flux (revenus, épargne)."""
    savings_drop_pct: float = 0.0        # Perte d'épargne. Ex: 1.0 = on n'épargne plus rien (chômage)
    duration_months: int = 0             # Durée pendant laquelle la perte d'épargne s'applique

@dataclass
class StressScenario:
    """Scénario complet de stress."""
    name: str
    description: str
    # Les clés doivent matcher celles de PrevisionBase.assets_breakdown
    assets_stress: Dict[str, AssetStress] = field(default_factory=dict)
    income_stress: Optional[IncomeStress] = None
    stress_duration_months: int = 12     # Durée du scénario de crise avant retour à la "normale" des marchés, influe progressive_drop

@dataclass
class StressResult:
    """Résultat comparatif entre le scénario normal (baseline) et le scénario de stress."""
    scenario: StressScenario
    baseline_result: PrevisionResult
    stressed_result: PrevisionResult
    
    # Métriques de comparaison et robustesse
    baseline_final_net_worth: float
    stressed_final_net_worth: float
    delta_final_net_worth: float
    delta_final_pct: float
    
    max_drawdown_pct: float
    lowest_net_worth: float
    
    # Métriques de Recovery
    months_to_recover_pre_shock: Optional[int]  # Mois pour repasser au-dessus du patrimoine juste avant la crise
    months_to_recover_baseline: Optional[int]   # Mois pour recroiser la courbe de croissance normale (baseline)
