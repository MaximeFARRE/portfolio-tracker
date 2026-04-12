"""
services/projections.py
Moteur de projections patrimoniales (V1, sans Monte Carlo).
Rendements par classe d'actif + exclusion résidence principale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
from services.common_utils import row_get, safe_float


# ── ScenarioParams ────────────────────────────────────────────────────────────

@dataclass
class ScenarioParams:
    """Paramètres d'un scénario de projection V1 — rendements par classe."""

    label: str = "Médian"
    horizon_years: int = 10

    # Rendements annuels par classe d'actif (%)
    return_liquidites_pct:   float = 2.0
    return_bourse_pct:       float = 7.0
    return_immobilier_pct:   float = 3.5
    return_pe_pct:           float = 10.0
    return_entreprises_pct:  float = 5.0

    # Macro
    inflation_pct:       float = 2.0
    income_growth_pct:   float = 0.0
    expense_growth_pct:  float = 0.0

    monthly_savings_override:    Optional[float] = None
    fire_multiple:               float = 25.0
    initial_net_worth_override:  Optional[float] = None
    exclude_primary_residence:   bool = False

    @property
    def expected_return_pct(self) -> float:
        """
        Moyenne pondérée à parts égales — utilisée pour l'affichage et la
        rétrocompatibilité avec l'ancienne API (project_patrimoine, tests).
        La vraie pondération par allocation est calculée dans run_projection().
        """
        return (
            self.return_liquidites_pct
            + self.return_bourse_pct
            + self.return_immobilier_pct
            + self.return_pe_pct
            + self.return_entreprises_pct
        ) / 5.0


# ── Helpers ───────────────────────────────────────────────────────────────────
def _annual_pct_to_monthly_rate(annual_pct: float) -> float:
    """Convertit un taux annuel (%) en taux mensuel équivalent."""
    pct = safe_float(annual_pct, 0.0)
    pct = max(pct, -99.0)
    return (1.0 + pct / 100.0) ** (1.0 / 12.0) - 1.0


def _empty_projection_base(scope_type: str, scope_id: Optional[int], scope_label: str) -> dict:
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "scope_label": scope_label,
        "net_worth": 0.0,
        "gross_worth": 0.0,
        "liquidities": 0.0,
        "bourse": 0.0,
        "immobilier": 0.0,
        "private_equity": 0.0,
        "entreprises": 0.0,
        "credits": 0.0,
        "avg_monthly_income": 0.0,
        "avg_monthly_expenses": 0.0,
        "avg_monthly_savings": 0.0,
        "fire_annual_expenses_base": 0.0,
        "primary_residence_excluded_value": 0.0,
        "has_cashflow": False,
    }


# ── Snapshots ───────────────────────────────────────────────────────────

def get_latest_person_snapshot(conn, person_id: int) -> dict:
    """Délègue à services.snapshots (SSOT). Retourne {} si aucun snapshot."""
    from services.snapshots import get_latest_person_snapshot as _snap_latest
    result = _snap_latest(conn, person_id)
    return result if result is not None else {}


def get_latest_family_snapshot(conn) -> dict:
    """
    Retourne le dernier snapshot hebdomadaire famille.
    Délègue à family_snapshots.get_family_weekly_series (SSOT),
    aligné avec prevision_base.py qui utilise la même source.
    """
    from services.family_snapshots import get_family_weekly_series
    df = get_family_weekly_series(conn, family_id=1)
    if df is None or df.empty:
        return {}
    last = df.iloc[-1]
    return {
        "week_date":         str(last.get("week_date", "")),
        "patrimoine_net":    safe_float(last.get("patrimoine_net")),
        "patrimoine_brut":   safe_float(last.get("patrimoine_brut")),
        "liquidites_total":  safe_float(last.get("liquidites_total")),
        "bourse_holdings":   safe_float(last.get("bourse_holdings")),
        "immobilier_value":  safe_float(last.get("immobilier_value")),
        "pe_value":          safe_float(last.get("pe_value")),
        "ent_value":         safe_float(last.get("ent_value")),
        "credits_remaining": safe_float(last.get("credits_remaining")),
    }


# ── Revenus / dépenses ──────────────────────────────────────────────────────────

def compute_average_income_expenses_for_person(conn, person_id: int, months: int = 12) -> dict:
    from services.cashflow import compute_savings_metrics
    if person_id is None:
        return {"avg_monthly_income": 0.0, "avg_monthly_expenses": 0.0,
                "avg_monthly_savings": 0.0, "months_used": 0}
    metrics = compute_savings_metrics(conn, person_id=int(person_id), n_mois=24)
    return {
        "avg_monthly_income": metrics.get("avg_monthly_income", 0.0),
        "avg_monthly_expenses": metrics.get("avg_monthly_expenses", 0.0),
        "avg_monthly_savings": metrics.get("avg_monthly_savings", 0.0),
        "months_used": 12,
        "has_cashflow": metrics.get("has_cashflow", False),
    }


def compute_average_income_expenses_for_family(conn, months: int = 12) -> dict:
    """
    Calcule les métriques cashflow famille.
    Utilise get_cashflow_for_scope (SSOT) — aligné sur la version personne.
    """
    from services.cashflow import get_cashflow_for_scope, _compute_savings_kpis_from_cashflow
    try:
        df = get_cashflow_for_scope(conn, "family")
        if df is None or df.empty:
            return {"avg_monthly_income": 0.0, "avg_monthly_expenses": 0.0,
                    "avg_monthly_savings": 0.0, "months_used": 0}
        # On passe le DataFrame à _compute_savings_kpis_from_cashflow,
        # chemin identique à celui utilisé pour la personne via compute_savings_metrics(df).
        metrics = _compute_savings_kpis_from_cashflow(df)
        return {
            "avg_monthly_income": metrics.get("avg_monthly_income", 0.0),
            "avg_monthly_expenses": metrics.get("avg_monthly_expenses", 0.0),
            "avg_monthly_savings": metrics.get("avg_monthly_savings", 0.0),
            "months_used": 12,
            "has_cashflow": metrics.get("has_cashflow", False),
        }
    except Exception:
        return {"avg_monthly_income": 0.0, "avg_monthly_expenses": 0.0,
                "avg_monthly_savings": 0.0, "months_used": 0}


def _get_person_label(conn, person_id: int) -> str:
    try:
        row = conn.execute("SELECT name FROM people WHERE id = ? LIMIT 1", (int(person_id),)).fetchone()
    except Exception:
        return f"Personne #{int(person_id)}"
    if row is None:
        return f"Personne #{int(person_id)}"
    name = row_get(row, "name")
    return str(name) if name else f"Personne #{int(person_id)}"


# ── Résidence principale ──────────────────────────────────────────────────────

def get_primary_residence_value_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> float:
    """
    Retourne la valeur totale des biens immobiliers de type 'RP' pour le scope.
    Pour la famille : somme de toutes les RP.
    Pour une personne : somme pondérée par sa part (pct / 100).
    """
    scope = (scope_type or "").strip().lower()
    try:
        if scope == "family":
            row = conn.execute(
                "SELECT COALESCE(SUM(valuation_eur), 0.0) AS rp_val "
                "FROM immobiliers WHERE property_type = 'RP'"
            ).fetchone()
        elif scope == "person" and scope_id is not None:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(i.valuation_eur * s.pct / 100.0), 0.0) AS rp_val
                FROM immobiliers i
                JOIN immobilier_shares s ON s.property_id = i.id
                WHERE i.property_type = 'RP' AND s.person_id = ?
                """,
                (int(scope_id),),
            ).fetchone()
        else:
            return 0.0
        return safe_float(row_get(row, "rp_val"))
    except Exception:
        return 0.0


# ── Base de projection ────────────────────────────────────────────────────────

def get_projection_base_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
    exclude_primary_residence: bool = False,
) -> dict:
    """
    Construit la base réelle de projection pour 'family' ou 'person'.
    Si exclude_primary_residence=True, soustrait la valeur des biens 'RP'
    du patrimoine et de l'allocation immobilier.
    """
    scope = (scope_type or "").strip().lower()
    if scope not in ("family", "person"):
        raise ValueError("scope_type must be 'family' or 'person'")

    if scope == "family":
        snap = get_latest_family_snapshot(conn)
        metrics = compute_average_income_expenses_for_family(conn)
        base = _empty_projection_base("family", None, "Famille")
    else:
        if scope_id is None:
            return _empty_projection_base("person", None, "Personne")
        person_id = int(scope_id)
        snap = get_latest_person_snapshot(conn, person_id)
        metrics = compute_average_income_expenses_for_person(conn, person_id)
        base = _empty_projection_base("person", person_id, _get_person_label(conn, person_id))

    net_worth  = safe_float(snap.get("patrimoine_net"))
    gross_worth = safe_float(snap.get("patrimoine_brut"), net_worth)
    credits    = safe_float(snap.get("credits_remaining"))

    if gross_worth == 0.0 and (net_worth != 0.0 or credits != 0.0):
        gross_worth = net_worth + credits

    avg_income   = safe_float(metrics.get("avg_monthly_income"))
    avg_expenses = safe_float(metrics.get("avg_monthly_expenses"))
    avg_savings  = safe_float(metrics.get("avg_monthly_savings"), avg_income - avg_expenses)

    base.update({
        "net_worth":            net_worth,
        "gross_worth":          gross_worth,
        "liquidities":          safe_float(snap.get("liquidites_total")),
        "bourse":               safe_float(snap.get("bourse_holdings")),
        "immobilier":           safe_float(snap.get("immobilier_value")),
        "private_equity":       safe_float(snap.get("pe_value")),
        "entreprises":          safe_float(snap.get("ent_value")),
        "credits":              credits,
        "avg_monthly_income":   avg_income,
        "avg_monthly_expenses": avg_expenses,
        "avg_monthly_savings":  avg_savings,
        "fire_annual_expenses_base": avg_expenses * 12.0,
        "snapshot_week_date":   snap.get("week_date"),
        "primary_residence_excluded_value": 0.0,
        "has_cashflow":         metrics.get("has_cashflow", False),
    })

    # Exclusion résidence principale
    if exclude_primary_residence:
        rp_value = get_primary_residence_value_for_scope(conn, scope, scope_id)
        if rp_value > 0.0:
            base["immobilier"]    = max(0.0, base["immobilier"] - rp_value)
            base["net_worth"]     = base["net_worth"] - rp_value
            base["gross_worth"]   = base["gross_worth"] - rp_value
            base["primary_residence_excluded_value"] = rp_value

    return base


# ── FIRE ──────────────────────────────────────────────────────────────────────

def compute_fire_target(monthly_expenses: float, fire_multiple: float) -> float:
    monthly  = max(safe_float(monthly_expenses), 0.0)
    multiple = max(safe_float(fire_multiple, 25.0), 0.0)
    return monthly * 12.0 * multiple


# ── Moteur de projection ──────────────────────────────────────────────────────

def compute_weighted_return(base: dict, params: ScenarioParams) -> float:
    """
    Calcule le rendement global effectif (moyenne pondérée par allocation actuelle).
    Utilisé pour l'affichage — pas pour la simulation elle-même.
    """
    liq   = max(safe_float(base.get("liquidities")), 0.0)
    brs   = max(safe_float(base.get("bourse")), 0.0)
    immo  = max(safe_float(base.get("immobilier")), 0.0)
    pe    = max(safe_float(base.get("private_equity")), 0.0)
    ent   = max(safe_float(base.get("entreprises")), 0.0)
    total = liq + brs + immo + pe + ent
    if total <= 0.0:
        return params.expected_return_pct
    return (
        liq  * params.return_liquidites_pct
        + brs  * params.return_bourse_pct
        + immo * params.return_immobilier_pct
        + pe   * params.return_pe_pct
        + ent  * params.return_entreprises_pct
    ) / total


def run_projection(base: dict, params: ScenarioParams) -> pd.DataFrame:
    """Exécute une projection mensuelle V1 avec rendements par classe d'actif."""
    horizon_months = max(int(params.horizon_years), 0) * 12

    # Taux mensuels par classe
    r_liq   = _annual_pct_to_monthly_rate(params.return_liquidites_pct)
    r_brs   = _annual_pct_to_monthly_rate(params.return_bourse_pct)
    r_immo  = _annual_pct_to_monthly_rate(params.return_immobilier_pct)
    r_pe    = _annual_pct_to_monthly_rate(params.return_pe_pct)
    r_ent   = _annual_pct_to_monthly_rate(params.return_entreprises_pct)

    monthly_income_growth   = _annual_pct_to_monthly_rate(params.income_growth_pct)
    monthly_expense_growth  = _annual_pct_to_monthly_rate(params.expense_growth_pct)
    monthly_inflation_factor = 1.0 + _annual_pct_to_monthly_rate(params.inflation_pct)

    # Patrimoine initial — override ou snapshot
    base_net = safe_float(base.get("net_worth"))
    if params.initial_net_worth_override is not None:
        net_override = safe_float(params.initial_net_worth_override)
        # Redistribuer proportionnellement à la structure du snapshot
        factor = (net_override / base_net) if base_net != 0.0 else 1.0
    else:
        net_override = None
        factor = 1.0

    liquidities = max(safe_float(base.get("liquidities")) * factor, 0.0)
    bourse      = max(safe_float(base.get("bourse"))      * factor, 0.0)
    immobilier  = max(safe_float(base.get("immobilier"))  * factor, 0.0)
    pe          = max(safe_float(base.get("private_equity")) * factor, 0.0)
    ent         = max(safe_float(base.get("entreprises")) * factor, 0.0)
    credits     = max(safe_float(base.get("credits")), 0.0)

    net_worth = (net_override if net_override is not None else base_net)

    monthly_income   = max(safe_float(base.get("avg_monthly_income")),   0.0)
    monthly_expenses = max(safe_float(base.get("avg_monthly_expenses")), 0.0)

    cumulative_growth        = 0.0
    cumulative_contributions = 0.0
    inflation_factor         = 1.0
    has_cashflow             = base.get("has_cashflow", False)

    rows = []
    for month_index in range(horizon_months + 1):
        if month_index > 0:
            # Croissance par classe
            g_liq  = liquidities * r_liq
            g_brs  = bourse      * r_brs
            g_immo = immobilier  * r_immo
            g_pe   = pe          * r_pe
            g_ent  = ent         * r_ent
            total_growth = g_liq + g_brs + g_immo + g_pe + g_ent

            # Épargne mensuelle
            if params.monthly_savings_override is None:
                monthly_savings = monthly_income - monthly_expenses
            else:
                monthly_savings = safe_float(params.monthly_savings_override)

            # Mise à jour des classes (les contributions entrent en liquidités)
            liquidities = max(0.0, liquidities + g_liq + monthly_savings)
            bourse      = max(0.0, bourse      + g_brs)
            immobilier  = max(0.0, immobilier  + g_immo)
            pe          = max(0.0, pe          + g_pe)
            ent         = max(0.0, ent         + g_ent)

            net_worth = liquidities + bourse + immobilier + pe + ent - credits

            cumulative_growth        += total_growth
            cumulative_contributions += monthly_savings

            monthly_income   = max(0.0, monthly_income   * (1.0 + monthly_income_growth))
            monthly_expenses = max(0.0, monthly_expenses * (1.0 + monthly_expense_growth))
            inflation_factor *= monthly_inflation_factor

        gross_worth = net_worth + credits

        # Rendement effectif pondéré à cet instant
        total_assets = liquidities + bourse + immobilier + pe + ent
        if total_assets > 0.0:
            w_return = (
                liquidities * params.return_liquidites_pct
                + bourse    * params.return_bourse_pct
                + immobilier* params.return_immobilier_pct
                + pe        * params.return_pe_pct
                + ent       * params.return_entreprises_pct
            ) / total_assets
        else:
            w_return = params.expected_return_pct

        fire_target = compute_fire_target(monthly_expenses, params.fire_multiple)
        if not has_cashflow and monthly_expenses <= 0.0:
            fire_target = None
            fire_progress_pct = None
            is_fire_reached = None
        elif fire_target <= 0.0:
            fire_progress_pct = 100.0
            is_fire_reached   = True
        else:
            fire_progress_pct = (net_worth / fire_target) * 100.0
            is_fire_reached   = net_worth >= fire_target

        net_worth_real = net_worth / inflation_factor if inflation_factor > 0 else net_worth

        rows.append({
            "month_index":                      month_index,
            "year":                             month_index // 12,
            "projected_net_worth":              round(net_worth, 2),
            "projected_net_worth_real":         round(net_worth_real, 2),
            "projected_gross_worth":            round(gross_worth, 2),
            "projected_liquidities":            round(liquidities, 2),
            "projected_bourse":                 round(bourse, 2),
            "projected_immobilier":             round(immobilier, 2),
            "projected_pe":                     round(pe, 2),
            "projected_ent":                    round(ent, 2),
            "projected_growth_component":       round(cumulative_growth, 2),
            "projected_contributions_component":round(cumulative_contributions, 2),
            "weighted_return_pct":              round(w_return, 2),
            "fire_target":                      round(fire_target, 2) if fire_target is not None else None,
            "fire_progress_pct":                round(fire_progress_pct, 2) if fire_progress_pct is not None else None,
            "is_fire_reached":                  bool(is_fire_reached) if is_fire_reached is not None else None,
        })

    return pd.DataFrame(rows)


# ── Scénarios standards ───────────────────────────────────────────────────────

def _scaled_savings(base_savings: float, factor: float) -> float:
    return safe_float(base_savings) * safe_float(factor, 1.0)


def build_standard_scenarios(
    base: dict,
    horizon_years: int,
    presets: Optional[dict] = None,
) -> list[ScenarioParams]:
    """
    Construit les 3 scénarios (Pessimiste / Médian / Optimiste) depuis les
    paramètres de presets.  Si `presets` est None, utilise les valeurs par défaut
    du module simulation_presets_repository.
    """
    from services.simulation_presets_repository import PRESET_DEFAULTS

    if presets is None:
        presets = PRESET_DEFAULTS

    base_savings = safe_float(base.get("avg_monthly_savings"))
    _label_map = {
        "pessimiste": "Pessimiste",
        "realiste":   "Médian",
        "optimiste":  "Optimiste",
    }

    scenarios = []
    for key in ("pessimiste", "realiste", "optimiste"):
        p = presets.get(key, PRESET_DEFAULTS[key])
        sf = safe_float(p.get("savings_factor", 1.0), 1.0)

        if sf == 1.0:
            savings_override = None  # épargne recalculée dynamiquement
        elif base_savings >= 0:
            savings_override = _scaled_savings(base_savings, sf)
        else:
            # Épargne négative : pessimiste aggrave, optimiste atténue
            savings_override = _scaled_savings(base_savings, 2.0 - sf)

        scenarios.append(ScenarioParams(
            label=_label_map[key],
            horizon_years=int(horizon_years),
            return_liquidites_pct=  safe_float(p.get("return_liquidites_pct",  2.0)),
            return_bourse_pct=      safe_float(p.get("return_bourse_pct",      7.0)),
            return_immobilier_pct=  safe_float(p.get("return_immobilier_pct",  3.5)),
            return_pe_pct=          safe_float(p.get("return_pe_pct",         10.0)),
            return_entreprises_pct= safe_float(p.get("return_entreprises_pct", 5.0)),
            inflation_pct=          safe_float(p.get("inflation_pct",          2.0)),
            income_growth_pct=      safe_float(p.get("income_growth_pct",      1.0)),
            expense_growth_pct=     safe_float(p.get("expense_growth_pct",     1.0)),
            monthly_savings_override=savings_override,
            fire_multiple=          safe_float(p.get("fire_multiple",         25.0)),
        ))

    return scenarios


def estimate_fire_reach_date(df_projection: pd.DataFrame) -> dict:
    """Estime la date d'atteinte FIRE depuis un DataFrame de projection."""
    default = {
        "fire_target":    0.0,
        "fire_reached":   False,
        "fire_month_index": None,
        "fire_year":      None,
        "fire_date_label": None,
    }
    if df_projection is None or df_projection.empty:
        return default

    last_target  = safe_float(df_projection.iloc[-1].get("fire_target", 0.0))
    reached_df   = df_projection[df_projection["is_fire_reached"] == True] \
        if "is_fire_reached" in df_projection.columns else pd.DataFrame()

    if reached_df.empty:
        default["fire_target"] = last_target
        return default

    first_reached = reached_df.iloc[0]
    month_index   = int(safe_float(first_reached.get("month_index", 0)))
    year          = int(safe_float(first_reached.get("year", month_index // 12)))
    fire_target   = safe_float(first_reached.get("fire_target", last_target))

    return {
        "fire_target":     fire_target,
        "fire_reached":    True,
        "fire_month_index": month_index,
        "fire_year":       year,
        "fire_date_label": f"M+{month_index} (année {year})",
    }


# ── Compatibilité ancienne API ────────────────────────────────────────────────

def _scenario_get(scenario: Any, key: str, default: Any):
    if isinstance(scenario, dict):
        return scenario.get(key, default)
    return getattr(scenario, key, default)


_PATRIMOINE_KEYS = {"bank", "bourse", "pe", "ent", "immobilier", "credits"}


def _validate_patrimoine_initial(d: dict) -> None:
    """
    Vérifie que le dict patrimoine_initial est complet et cohérent.

    Règles :
    - Toutes les clés de _PATRIMOINE_KEYS doivent être présentes.
    - Chaque valeur d'actif (bank, bourse, pe, ent, immobilier) doit être >= 0.
    - credits doit être >= 0 (c'est un CRD, toujours positif ou nul).

    Utiliser load_initial_patrimoine_from_family() pour construire ce dict
    depuis la base — cela garantit la cohérence assets/dettes.
    """
    missing = _PATRIMOINE_KEYS - d.keys()
    if missing:
        raise ValueError(
            f"patrimoine_initial incomplet — clés manquantes : {sorted(missing)}. "
            "Utilisez load_initial_patrimoine_from_family() pour un dict cohérent."
        )
    asset_keys = _PATRIMOINE_KEYS - {"credits"}
    for k in asset_keys:
        if float(d[k]) < 0:
            raise ValueError(
                f"patrimoine_initial['{k}'] = {d[k]} est négatif — les actifs doivent être >= 0."
            )
    if float(d["credits"]) < 0:
        raise ValueError(
            f"patrimoine_initial['credits'] = {d['credits']} est négatif — "
            "credits représente un CRD (toujours positif ou nul)."
        )


_PATRIMOINE_KEYS = {"bank", "bourse", "pe", "ent", "immobilier", "credits"}


def _validate_patrimoine_initial(d: dict) -> None:
    """
    Vérifie que le dict patrimoine_initial est complet et cohérent.

    Règles :
    - Toutes les clés de _PATRIMOINE_KEYS doivent être présentes.
    - Chaque valeur d'actif (bank, bourse, pe, ent, immobilier) doit être >= 0.
    - credits doit être >= 0 (c'est un CRD, toujours positif ou nul).

    Utiliser load_initial_patrimoine_from_family() pour construire ce dict
    depuis la base — cela garantit la cohérence assets/dettes.
    """
    missing = _PATRIMOINE_KEYS - d.keys()
    if missing:
        raise ValueError(
            f"patrimoine_initial incomplet — clés manquantes : {sorted(missing)}. "
            "Utilisez load_initial_patrimoine_from_family() pour un dict cohérent."
        )
    asset_keys = _PATRIMOINE_KEYS - {"credits"}
    for k in asset_keys:
        if float(d[k]) < 0:
            raise ValueError(
                f"patrimoine_initial['{k}'] = {d[k]} est négatif — les actifs doivent être >= 0."
            )
    if float(d["credits"]) < 0:
        raise ValueError(
            f"patrimoine_initial['credits'] = {d['credits']} est négatif — "
            "credits représente un CRD (toujours positif ou nul)."
        )


def project_patrimoine(
    patrimoine_initial: dict,
    scenario: ScenarioParams | dict,
    horizon_ans: int = 10,
) -> pd.DataFrame:
    """Compatibilité minimale avec l'ancienne API."""
    bank   = safe_float(patrimoine_initial.get("bank"))
    bourse = safe_float(patrimoine_initial.get("bourse"))
    pe     = safe_float(patrimoine_initial.get("pe"))
    ent    = safe_float(patrimoine_initial.get("ent"))
    credits = safe_float(patrimoine_initial.get("credits"))

    taux_bourse_annuel = safe_float(
        _scenario_get(scenario, "taux_bourse_annuel",
            _scenario_get(scenario, "expected_return_pct", 6.0)), 6.0)
    taux_pe_annuel = safe_float(
        _scenario_get(scenario, "taux_pe_annuel",
            _scenario_get(scenario, "expected_return_pct", 6.0)), 6.0)
    inflation_annuelle = safe_float(
        _scenario_get(scenario, "inflation_annuelle",
            _scenario_get(scenario, "inflation_pct", 2.0)), 2.0)
    epargne_mensuelle = _scenario_get(scenario, "epargne_mensuelle", None)
    if epargne_mensuelle is None:
        epargne_mensuelle = _scenario_get(scenario, "monthly_savings_override", 0.0)
    epargne_mensuelle = safe_float(epargne_mensuelle, 0.0)
    remboursement_mensuel_credit = safe_float(
        _scenario_get(scenario, "remboursement_mensuel_credit", 0.0), 0.0)

    immobilier = safe_float(patrimoine_initial.get("immobilier"))

    r_bourse_m = _annual_pct_to_monthly_rate(taux_bourse_annuel)
    r_pe_m     = _annual_pct_to_monthly_rate(taux_pe_annuel)
    defl_m     = 1.0 + _annual_pct_to_monthly_rate(inflation_annuelle)

    n_mois = max(int(horizon_ans), 0) * 12
    rows = []
    for m in range(n_mois + 1):
        brut = bank + bourse + pe + ent + immobilier
        net  = brut - credits
        net_reel = net / (defl_m ** m) if defl_m > 0 else net
        rows.append({
            "mois": m,
            "annee": m / 12,
            "bank": round(bank, 2),
            "bourse": round(bourse, 2),
            "pe": round(pe, 2),
            "ent": round(ent, 2),
            "immobilier": round(immobilier, 2),
            "credits": round(credits, 2),
            "patrimoine_brut": round(brut, 2),
            "patrimoine_net":  round(net, 2),
            "patrimoine_net_reel": round(net_reel, 2),
        })
        if m < n_mois:
            bourse *= 1.0 + r_bourse_m
            pe     *= 1.0 + r_pe_m
            bank   += epargne_mensuelle
            credits = max(0.0, credits - remboursement_mensuel_credit)
    return pd.DataFrame(rows)


def load_initial_patrimoine_from_family(conn, family_id: int = 1, person_ids: list[int] | None = None) -> dict:
    """
    Charge le dernier snapshot famille (source canonique),
    avec fallback agrégé personnes si la table famille est vide.
    """
    from services import family_snapshots as fs

    df_family = fs.get_family_weekly_series(conn, family_id=family_id, fallback_person_ids=person_ids or [])
    if df_family is None or df_family.empty:
        return {
            "bank": 0.0,
            "bourse": 0.0,
            "pe": 0.0,
            "ent": 0.0,
            "immobilier": 0.0,
            "credits": 0.0,
        }

    last = df_family.iloc[-1]
    return {
        "bank": float(last.get("liquidites_total", 0.0)),
        "bourse": float(last.get("bourse_holdings", 0.0)),
        "pe": float(last.get("pe_value", 0.0)),
        "ent": float(last.get("ent_value", 0.0)),
        "immobilier": float(last.get("immobilier_value", 0.0)),
        "credits": float(last.get("credits_remaining", 0.0)),
    }


def compute_three_scenarios(
    patrimoine_initial: dict,
    epargne_base: float,
    horizon_ans: int = 10,
    remboursement_mensuel: float = 0.0,
) -> dict[str, pd.DataFrame]:
    """Compatibilité minimale avec l'ancienne API 3 scénarios.

    Construire patrimoine_initial via load_initial_patrimoine_from_family()
    garantit la cohérence entre actifs et dettes (credits = CRD réel).
    """
    scenarios = [
        {"label": "Pessimiste", "taux_bourse_annuel": 4.0, "taux_pe_annuel": 5.0,
         "epargne_mensuelle": safe_float(epargne_base) * 0.8, "inflation_annuelle": 3.0,
         "remboursement_mensuel_credit": safe_float(remboursement_mensuel)},
        {"label": "Base", "taux_bourse_annuel": 7.0, "taux_pe_annuel": 10.0,
         "epargne_mensuelle": safe_float(epargne_base), "inflation_annuelle": 2.0,
         "remboursement_mensuel_credit": safe_float(remboursement_mensuel)},
        {"label": "Optimiste", "taux_bourse_annuel": 10.0, "taux_pe_annuel": 15.0,
         "epargne_mensuelle": safe_float(epargne_base) * 1.2, "inflation_annuelle": 1.0,
         "remboursement_mensuel_credit": safe_float(remboursement_mensuel)},
    ]
    return {str(s["label"]): project_patrimoine(patrimoine_initial, s, horizon_ans) for s in scenarios}


def summary_table(results: dict[str, pd.DataFrame], horizons: list[int] = None) -> pd.DataFrame:
    """Compatibilité minimale du tableau de synthèse."""
    if horizons is None:
        horizons = [1, 3, 5, 10]
    rows = []
    for label, df in results.items():
        row = {"Scénario": label}
        for h in horizons:
            m = int(h) * 12
            if "mois" in df.columns:
                sub = df[df["mois"] == m]
                val_col = "patrimoine_net"
            else:
                sub = df[df["month_index"] == m]
                val_col = "projected_net_worth"
            row[f"{h} an(s)"] = round(safe_float(sub.iloc[0][val_col]), 0) if not sub.empty else None
        rows.append(row)
    return pd.DataFrame(rows)

