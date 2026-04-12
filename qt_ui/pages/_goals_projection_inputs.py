"""
qt_ui/pages/_goals_projection_inputs.py

Logique de gestion des inputs de la page Objectifs & Projection.

Ce module contient les fonctions pures (sans widgets Qt) qui transforment
les valeurs de l'UI en ScenarioParams et vice-versa. Il ne touche pas à
l'affichage, seulement à la collecte et la normalisation des paramètres.
"""
from __future__ import annotations

from typing import Optional

from services.projections import ScenarioParams

# Mapping paramètre preset → valeur par défaut si preset absent
_PRESET_FIELD_DEFAULTS: dict[str, float] = {
    "return_liquidites_pct":  2.0,
    "return_bourse_pct":      7.0,
    "return_immobilier_pct":  3.5,
    "return_pe_pct":          10.0,
    "return_entreprises_pct": 5.0,
    "inflation_pct":          2.0,
    "income_growth_pct":      1.0,
    "expense_growth_pct":     1.0,
    "fire_multiple":          25.0,
}


def extract_preset_values(params: dict) -> dict[str, float]:
    """
    Extrait les valeurs numériques d'un dict preset (depuis le cache ou PRESET_DEFAULTS).

    Args:
        params: Dict de paramètres bruts du preset.

    Returns:
        Dict {champ: valeur float} avec fallback sur les defaults.
    """
    return {
        field: float(params.get(field, default))
        for field, default in _PRESET_FIELD_DEFAULTS.items()
    }


def build_scenario_params(
    *,
    label: str,
    horizon_years: int,
    return_liquidites_pct: float,
    return_bourse_pct: float,
    return_immobilier_pct: float,
    return_pe_pct: float,
    return_entreprises_pct: float,
    inflation_pct: float,
    income_growth_pct: float,
    expense_growth_pct: float,
    fire_multiple: float,
    savings_override_enabled: bool,
    savings_override_value: float,
    net_override_enabled: bool,
    net_override_value: float,
    exclude_rp: bool,
) -> ScenarioParams:
    """
    Construit un ScenarioParams depuis les valeurs lues dans les widgets UI.

    Toutes les valeurs sont passées explicitement pour rendre la collecte testable
    sans instancier la page Qt.

    Returns:
        ScenarioParams prêt pour ProjectionService.
    """
    savings_override: Optional[float] = savings_override_value if savings_override_enabled else None
    net_override: Optional[float] = net_override_value if net_override_enabled else None

    return ScenarioParams(
        label=label,
        horizon_years=horizon_years,
        return_liquidites_pct=return_liquidites_pct,
        return_bourse_pct=return_bourse_pct,
        return_immobilier_pct=return_immobilier_pct,
        return_pe_pct=return_pe_pct,
        return_entreprises_pct=return_entreprises_pct,
        inflation_pct=inflation_pct,
        income_growth_pct=income_growth_pct,
        expense_growth_pct=expense_growth_pct,
        monthly_savings_override=savings_override,
        fire_multiple=fire_multiple,
        initial_net_worth_override=net_override,
        exclude_primary_residence=exclude_rp,
    )


def extract_scenario_display_row(sc_row: dict, safe_float_fn) -> dict:
    """
    Transforme une ligne brute de scénario DB en dict d'affichage pour DataTableWidget.

    Args:
        sc_row: Dict brut depuis la DB (un .to_dict() d'une ligne DataFrame).
        safe_float_fn: Fonction _safe_float du module appelant.

    Returns:
        Dict formaté pour affichage.
    """
    return {
        "id": int(sc_row["id"]),
        "Nom": str(sc_row.get("name") or ""),
        "Par défaut": "Oui" if int(safe_float_fn(sc_row.get("is_default"), 0)) == 1 else "",
        "Horizon": int(safe_float_fn(sc_row.get("horizon_years"), 10)),
        "Rdt. global %": round(safe_float_fn(sc_row.get("expected_return_pct"), 0.0), 2),
        "Bourse %": round(safe_float_fn(sc_row.get("return_bourse_pct"), 0.0), 2),
        "Immo %": round(safe_float_fn(sc_row.get("return_immobilier_pct"), 0.0), 2),
        "PE %": round(safe_float_fn(sc_row.get("return_pe_pct"), 0.0), 2),
        "Excl. RP": "Oui" if int(safe_float_fn(sc_row.get("exclude_primary_residence"), 0)) else "",
        "Inflation %": round(safe_float_fn(sc_row.get("inflation_pct"), 0.0), 2),
        "Épargne personnalisée": (
            "—" if sc_row.get("monthly_savings_override") is None
            else round(safe_float_fn(sc_row.get("monthly_savings_override")), 2)
        ),
        "Multiple FIRE": round(safe_float_fn(sc_row.get("fire_multiple"), 25.0), 2),
        "Mis à jour": str(sc_row.get("updated_at") or ""),
    }


def build_scenario_payload_from_params(
    params: ScenarioParams,
    scenario_name: str,
    scope_type: str,
    scope_id: Optional[int],
) -> dict:
    """
    Construit le payload DB pour créer un scénario depuis les params actuels.

    Args:
        params: ScenarioParams courants de l'UI.
        scenario_name: Nom saisi par l'utilisateur.
        scope_type: "family" ou "person".
        scope_id: ID de la personne (ou None pour famille).

    Returns:
        Dict payload prêt pour create_scenario().
    """
    return {
        "name": scenario_name,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "is_default": 0,
        "horizon_years": int(params.horizon_years),
        "expected_return_pct": float(params.expected_return_pct),
        "inflation_pct": float(params.inflation_pct),
        "income_growth_pct": float(params.income_growth_pct),
        "expense_growth_pct": float(params.expense_growth_pct),
        "monthly_savings_override": params.monthly_savings_override,
        "fire_multiple": float(params.fire_multiple),
        "use_real_snapshot_base": 1 if params.initial_net_worth_override is None else 0,
        "initial_net_worth_override": params.initial_net_worth_override,
        "return_liquidites_pct": float(params.return_liquidites_pct),
        "return_bourse_pct": float(params.return_bourse_pct),
        "return_immobilier_pct": float(params.return_immobilier_pct),
        "return_pe_pct": float(params.return_pe_pct),
        "return_entreprises_pct": float(params.return_entreprises_pct),
        "exclude_primary_residence": params.exclude_primary_residence,
    }
