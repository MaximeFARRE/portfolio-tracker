from dataclasses import dataclass, field
from typing import List, Dict, Optional
import pandas as pd

@dataclass
class PrevisionConfig:
    """Paramètres globaux pour la simulation de prévision."""
    horizon_years: int = 20
    monthly_contribution: float = 0.0
    
    # Hypothèses simples par classe d'actifs (V1)
    # Les clés doivent correspondre aux clés de assets_breakdown
    expected_returns: Dict[str, float] = field(default_factory=lambda: {
        "Liquidités": 0.02,
        "Bourse": 0.07,
        "Immobilier": 0.03,
        "PE": 0.10,
        "Entreprises": 0.05,
        "Crypto": 0.0,
    })
    
    expected_volatilities: Dict[str, float] = field(default_factory=lambda: {
        "Liquidités": 0.01,
        "Bourse": 0.15,
        "Immobilier": 0.05,
        "PE": 0.20,
        "Entreprises": 0.15,
        "Crypto": 0.50,
    })
    
    # Matrice de corrélation simple entre ces 6 classes (ordre: Liq, Bourse, Immo, PE, Ent, Crypto)
    # Dans une V2 on l'importera dynamiquement, ici V1 pédagogique
    correlation_matrix: Optional[List[List[float]]] = None

    expected_equity_return: float = 0.07 # Historique/Fallback
    expected_equity_volatility: float = 0.15 # Historique/Fallback
    expected_cash_return: float = 0.02 # Historique/Fallback
    
    num_simulations: int = 1000
    target_goal_amount: Optional[float] = None
    inflation_rate: float = 0.02
    seed: Optional[int] = 42

@dataclass
class PrevisionBase:
    """État patrimonial consolidé de départ pour la projection."""
    current_net_worth: float
    current_cash: float
    current_equity: float
    current_real_estate: float
    current_pe: float = 0.0
    current_business: float = 0.0
    current_crypto: float = 0.0
    current_credits: float = 0.0
    
    # Evolution de la dette totale (déterministe)
    debts_schedule: Optional[pd.Series] = None
    
    # Flux annuels
    current_savings_per_year: float = 0.0
    current_passive_income_per_year: float = 0.0
    
    # Suivi et diagnostique
    metadata: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def assets_breakdown(self) -> Dict[str, float]:
        return {
            "Liquidités": self.current_cash,
            "Bourse": self.current_equity,
            "Immobilier": self.current_real_estate,
            "PE": self.current_pe,
            "Entreprises": self.current_business,
            "Crypto": self.current_crypto
        }
        
    @property
    def allocation(self) -> Dict[str, float]:
        gross = sum(self.assets_breakdown.values())
        if gross <= 0:
            return {k: 0.0 for k in self.assets_breakdown.keys()}
        return {k: (v / gross * 100) for k, v in self.assets_breakdown.items()}
    
@dataclass
class RiskMetrics:
    """Métriques de risque calculées sur l'ensemble de la projection."""
    volatility: float
    max_drawdown: float
    var_95: float
    cvar_95: float
    # TODO: Ajouter ratios qualitatifs par la suite (Sharpe, Sortino)

@dataclass
class GoalMetrics:
    """Évaluation de l'atteinte des objectifs patrimoniaux."""
    probability_of_success: float
    median_shortfall: Optional[float]
    years_to_goal_median: Optional[float]

@dataclass
class PrevisionResult:
    """Payload de résultat consolidé d'une simulation."""
    config: PrevisionConfig
    base: PrevisionBase
    
    # Séries temporelles
    median_series: pd.Series
    percentile_10_series: Optional[pd.Series] = None
    percentile_90_series: Optional[pd.Series] = None
    
    # Toutes les trajectoires si l'approche est stochastique
    trajectories_df: Optional[pd.DataFrame] = None
    
    final_net_worth_median: float = 0.0
    
    risk_metrics: Optional[RiskMetrics] = None
    goal_metrics: Optional[GoalMetrics] = None
    diagnostics: List[str] = field(default_factory=list)
