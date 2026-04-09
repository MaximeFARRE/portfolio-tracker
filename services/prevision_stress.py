from .prevision_stress_models import StressScenario, AssetStress, IncomeStress

def get_equity_crash_20() -> StressScenario:
    """Krach immédiat de 20% sur les actions."""
    return StressScenario(
        name="equity_crash_20",
        description="Krach boursier de -20% à court terme.",
        assets_stress={
            "Bourse": AssetStress(immediate_drop_pct=0.20, progressive_drop_pct=0.0, recovery_months=24)
        },
        stress_duration_months=12
    )

def get_equity_crash_30() -> StressScenario:
    """Krach majeur de 30%."""
    return StressScenario(
        name="equity_crash_30",
        description="Krach boursier sévère de -30%.",
        assets_stress={
            "Bourse": AssetStress(immediate_drop_pct=0.30, progressive_drop_pct=0.0, recovery_months=36)
        },
        stress_duration_months=12
    )

def get_real_estate_slump() -> StressScenario:
    """Crise prolongée de l'immobilier, baisse de 15% sur 2 ans."""
    return StressScenario(
        name="real_estate_slump",
        description="Baisse immobilière progressive de -15% sur 2 ans.",
        assets_stress={
            "Immobilier": AssetStress(immediate_drop_pct=0.0, progressive_drop_pct=0.15, recovery_months=60)
        },
        stress_duration_months=24
    )

def get_income_shock_12m() -> StressScenario:
    """Chômage ou perte temporaire : arrêt total d'épargne pendant 1 an."""
    return StressScenario(
        name="income_shock_12m",
        description="Perte totale de la capacité d'épargne sur 1 an.",
        assets_stress={},
        income_stress=IncomeStress(savings_drop_pct=1.0, duration_months=12),
        stress_duration_months=12
    )

def get_double_shock() -> StressScenario:
    """Le cauchemar : Krach de 30% combiné avec une perte de revenu sur 1 an."""
    return StressScenario(
        name="double_shock",
        description="Combinaison d'un krach boursier (-30%) et de la perte d'épargne (1 an).",
        assets_stress={
            "Bourse": AssetStress(immediate_drop_pct=0.30, progressive_drop_pct=0.0, recovery_months=36)
        },
        income_stress=IncomeStress(savings_drop_pct=1.0, duration_months=12),
        stress_duration_months=12
    )

def list_standard_scenarios() -> dict[str, StressScenario]:
    """Retourne un dictionnaire des scénarios standards, pratique pour l'UI."""
    return {
        "equity_crash_20": get_equity_crash_20(),
        "equity_crash_30": get_equity_crash_30(),
        "real_estate_slump": get_real_estate_slump(),
        "income_shock_12m": get_income_shock_12m(),
        "double_shock": get_double_shock(),
    }
