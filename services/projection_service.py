"""
services/projection_service.py

Point d'entrée unique (façade) pour la génération de projections patrimoniales.

═══════════════════════════════════════════════════════════════════════════════
CONTRAT CANONIQUE — Source de données commune aux deux moteurs
═══════════════════════════════════════════════════════════════════════════════

Les deux moteurs lisent leurs données patrimoniales depuis les mêmes SSOT :
  - Snapshot personne  → services.snapshots.get_latest_person_snapshot()
  - Snapshot famille   → services.family_snapshots.get_family_weekly_series()
    (legacy délègue maintenant aussi via get_latest_family_snapshot → SSOT,
     aligné avec prevision_base.py depuis le refactor du 2026-04-11)
  - Cashflow           → services.cashflow.compute_savings_metrics()

MAPPING des champs entre les deux moteurs (même donnée, noms différents) :
  Champ SSOT / legacy         │ Champ PrevisionBase (advanced)
  ─────────────────────────────┼────────────────────────────────
  liquidities                  │ current_cash
  bourse                       │ current_equity
  immobilier                   │ current_real_estate
  private_equity               │ current_pe
  entreprises                  │ current_business
  credits                      │ current_credits
  avg_monthly_savings * 12     │ current_savings_per_year
  avg_monthly_expenses * 12    │ fire_annual_expenses

Ce mapping est documenté ici et NON déplacé pour préserver les API existantes.

DIVERGENCES RÉSIDUELLES (identifiées, non encore réduites) :
  1. Noms de champs différents (listés ci-dessus) — convention legacy vs advanced.
  2. `initial_net_worth_override` existe dans legacy (ScenarioParams), pas dans advanced.
  3. `exclude_primary_residence` géré dans legacy, non supporté dans advanced.
  4. Le moteur advanced calcule des percentiles (Monte Carlo) que legacy n'a pas.

═══════════════════════════════════════════════════════════════════════════════
"""

import pandas as pd
from typing import Literal, Any, Dict, Optional, Union

# --- Imports Legacy (V1) ---
from services.projections import (
    ScenarioParams,
    get_projection_base_for_scope as legacy_get_base,
    run_projection as legacy_run_projection,
    build_standard_scenarios as legacy_build_standard_scenarios,
    compute_weighted_return as legacy_compute_weighted_return,
    estimate_fire_reach_date as legacy_estimate_fire_reach_date,
    get_primary_residence_value_for_scope as legacy_get_pr_value
)

# --- Imports Advanced (Prevision) ---
from services.prevision import (
    run_prevision,
    run_stress_prevision,
    PrevisionConfig,
    PrevisionResult
)


class ProjectionService:
    """
    Service unifiant l'accès aux générateurs de projections et prévisions patrimoniales.
    Il permet une migration incrémentale.
    """

    @staticmethod
    def run_legacy_projection(
        conn: Any,
        scope_type: Literal["family", "person"],
        scope_id: Optional[int],
        params: ScenarioParams,
        exclude_primary_residence: bool = False
    ) -> pd.DataFrame:
        """
        Exécute la projection classique (V1) avec le moteur existant (services.projections).

        Args:
            conn: Connexion à la base de données.
            scope_type: "family" ou "person".
            scope_id: L'identifiant de la personne (ou None pour "family").
            params: Paramètres du scénario de projection.
            exclude_primary_residence: Booléen indiquant si la RP doit être exclue des actifs.

        Returns:
            pd.DataFrame: Un dataframe contenant les données mensuelles de projection.
        """
        base = legacy_get_base(
            conn=conn, 
            scope_type=scope_type, 
            scope_id=scope_id, 
            exclude_primary_residence=exclude_primary_residence
        )
        return legacy_run_projection(base, params)

    @staticmethod
    def run_advanced_prevision(
        conn: Any,
        scope_type: Literal["family", "person"],
        scope_id: int,
        config: PrevisionConfig,
        engine: Literal["deterministic", "monte_carlo"] = "monte_carlo"
    ) -> PrevisionResult:
        """
        Exécute la nouvelle prévision avancée avec services.prevision.

        Args:
            conn: Connexion à la base de données.
            scope_type: "family" ou "person".
            scope_id: L'identifiant cible (pour family, souvent 1).
            config: L'objet complet de configuration des prévisions (PrevisionConfig).
            engine: Le type de moteur spécifique ("monte_carlo" par défaut ou "deterministic").

        Returns:
            PrevisionResult: Les résultats enrichis (séries médianes, percentiles, métriques).
        """
        return run_prevision(
            conn=conn, 
            scope_type=scope_type, 
            scope_id=scope_id, 
            config=config, 
            engine=engine
        )

    @staticmethod
    def run_advanced_stress_prevision(
        conn: Any,
        scope_type: Literal["family", "person"],
        scope_id: int,
        config: PrevisionConfig,
        scenario: Any
    ):
        """
        Exécute la prévision de stress avancée avec services.prevision.

        Args:
            conn: Connexion à la base de données.
            scope_type: "family" ou "person".
            scope_id: L'identifiant cible (pour family, souvent 1).
            config: L'objet complet de configuration des prévisions (PrevisionConfig).
            scenario: L'objet de scénario de stress.

        Returns:
            PrevisionStressResult: Les résultats du stress test.
        """
        return run_stress_prevision(
            conn=conn,
            scope_type=scope_type,
            scope_id=scope_id,
            config=config,
            scenario=scenario
        )

    @classmethod
    def generate_projection(
        cls,
        conn: Any,
        scope_type: Literal["family", "person"],
        scope_id: Optional[int],
        engine_type: Literal["legacy", "advanced"] = "legacy",
        options: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        API unique agissant comme routeur principal pour les projections.
        
        Args:
            conn: Connexion à de la base de données.
            scope_type: "family" ou "person".
            scope_id: Identifiant de l'entité (peut être None pour legacy family).
            engine_type: Choisir "legacy" pour l'ancien moteur, "advanced" pour le nouveau.
            options: Dictionnaire avec les clés requises par le type de moteur:
                     - "legacy": "params" (ScenarioParams obligatoire), "exclude_primary_residence" (optionnel).
                     - "advanced": "config" (PrevisionConfig obligatoire), "engine" (optionnel), "scenario" (optionnel, pour l'exécuter en tant que stress).

        Returns:
            L'objet résultant en fonction du moteur (DataFrame, PrevisionResult, ou PrevisionStressResult).
        """
        if options is None:
            options = {}

        if engine_type == "legacy":
            params = options.get("params")
            if not isinstance(params, ScenarioParams):
                raise ValueError("L'option 'params' (type ScenarioParams) est requise pour engine_type='legacy'.")
            
            exc_rp = bool(options.get("exclude_primary_residence", False))
            return cls.run_legacy_projection(conn, scope_type, scope_id, params, exc_rp)

        elif engine_type == "advanced":
            config = options.get("config")
            # En duck typing on s'assure juste que ce n'est pas None (pour éviter les soucis d'import circulaires/types complexes)
            if config is None:
                raise ValueError("L'option 'config' (type PrevisionConfig) est requise pour engine_type='advanced'.")
            
            
            # scope_id est souvent 1 pour "family" dans les nouvelles APIs.
            resolved_scope_id = scope_id if scope_id is not None else 1
            
            scenario = options.get("scenario")
            if scenario is not None:
                return cls.run_advanced_stress_prevision(conn, scope_type, resolved_scope_id, config, scenario)

            engine = options.get("engine", "monte_carlo")
            return cls.run_advanced_prevision(conn, scope_type, resolved_scope_id, config, engine)

        else:
            raise ValueError(f"Type de moteur '{engine_type}' non reconnu. Utilisez 'legacy' ou 'advanced'.")

    # --- Utilitaires et helpers encapsulés ---

    @staticmethod
    def get_projection_base(
        conn: Any,
        scope_type: Literal["family", "person"],
        scope_id: Optional[int],
        exclude_primary_residence: bool = False
    ) -> Dict[str, Any]:
        return legacy_get_base(conn, scope_type, scope_id, exclude_primary_residence)

    @staticmethod
    def get_primary_residence_value(
        conn: Any,
        scope_type: Literal["family", "person"],
        scope_id: Optional[int]
    ) -> float:
        return legacy_get_pr_value(conn, scope_type, scope_id)

    @staticmethod
    def build_standard_scenarios(
        base_data: dict,
        horizon_years: int,
        presets: Optional[dict] = None
    ):
        return legacy_build_standard_scenarios(base_data, horizon_years, presets)

    @staticmethod
    def compute_weighted_return(base_data: dict, params: Any) -> float:
        return legacy_compute_weighted_return(base_data, params)

    @staticmethod
    def estimate_fire_reach_date(projection_df: pd.DataFrame) -> Optional[dict]:
        return legacy_estimate_fire_reach_date(projection_df)

    @staticmethod
    def list_standard_stress_scenarios() -> Dict[str, Any]:
        """
        Retourne la liste des scénarios de stress standards du moteur advanced.
        
        Returns:
            Un dictionnaire {clé: StressScenario}
        """
        from services.prevision_stress import list_standard_scenarios
        return list_standard_scenarios()

    @staticmethod
    def build_current_portfolio_backtest(
        conn: Any,
        person_id: int,
        horizon: str = "10y",
        benchmark_symbol: Optional[str] = None,
        ignore_limiting_assets: bool = False,
    ) -> Dict[str, Any]:
        """
        Point d'entree facade pour le backtest theorique du portefeuille actuel.

        Le moteur est implemente dans services.portfolio_backtest_service.
        """
        from services.portfolio_backtest_service import (
            build_current_portfolio_backtest as _build_current_portfolio_backtest,
        )

        return _build_current_portfolio_backtest(
            conn=conn,
            person_id=person_id,
            horizon=horizon,
            benchmark_symbol=(benchmark_symbol or "URTH"),
            ignore_limiting_assets=bool(ignore_limiting_assets),
        )
