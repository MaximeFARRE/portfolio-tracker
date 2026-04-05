"""
services/projections.py
Moteur de projections patrimoniales (V1, sans Monte Carlo).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd


@dataclass
class ScenarioParams:
    """Paramètres d'un scénario de projection V1."""

    label: str = "Médian"
    horizon_years: int = 10
    expected_return_pct: float = 6.0
    inflation_pct: float = 2.0
    income_growth_pct: float = 0.0
    expense_growth_pct: float = 0.0
    monthly_savings_override: Optional[float] = None
    fire_multiple: float = 25.0
    initial_net_worth_override: Optional[float] = None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _row_get(row: Any, key: str, index: int = 0):
    if row is None:
        return None
    try:
        return row[key]
    except Exception:
        try:
            return row[index]
        except Exception:
            return None


def _annual_pct_to_monthly_rate(annual_pct: float) -> float:
    """Convertit un taux annuel (%) en taux mensuel équivalent."""
    pct = _to_float(annual_pct, 0.0)
    pct = max(pct, -99.0)  # évite les puissances invalides
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
    }


def _compute_average_income_expenses(
    income_df: pd.DataFrame,
    expense_df: pd.DataFrame,
    months: int = 12,
) -> dict:
    """Calcule les moyennes mensuelles sur les derniers mois ayant des données."""
    if income_df is None:
        income_df = pd.DataFrame(columns=["mois", "income"])
    if expense_df is None:
        expense_df = pd.DataFrame(columns=["mois", "expenses"])

    if income_df.empty and expense_df.empty:
        return {
            "avg_monthly_income": 0.0,
            "avg_monthly_expenses": 0.0,
            "avg_monthly_savings": 0.0,
            "months_used": 0,
        }

    i_df = income_df.rename(columns={"amount": "income"}).copy()
    e_df = expense_df.rename(columns={"amount": "expenses"}).copy()

    if "income" not in i_df.columns:
        i_df["income"] = 0.0
    if "expenses" not in e_df.columns:
        e_df["expenses"] = 0.0

    merged = pd.merge(
        i_df[["mois", "income"]] if "mois" in i_df.columns else pd.DataFrame(columns=["mois", "income"]),
        e_df[["mois", "expenses"]] if "mois" in e_df.columns else pd.DataFrame(columns=["mois", "expenses"]),
        on="mois",
        how="outer",
    )
    merged["income"] = pd.to_numeric(merged["income"], errors="coerce").fillna(0.0)
    merged["expenses"] = pd.to_numeric(merged["expenses"], errors="coerce").fillna(0.0)
    merged["mois_dt"] = pd.to_datetime(merged["mois"], errors="coerce")
    merged = merged.dropna(subset=["mois_dt"])

    if merged.empty:
        return {
            "avg_monthly_income": 0.0,
            "avg_monthly_expenses": 0.0,
            "avg_monthly_savings": 0.0,
            "months_used": 0,
        }

    n_months = max(int(months), 1)
    merged = merged.sort_values("mois_dt", ascending=False).head(n_months)

    avg_income = _to_float(merged["income"].mean())
    avg_expenses = _to_float(merged["expenses"].mean())
    avg_savings = avg_income - avg_expenses

    return {
        "avg_monthly_income": avg_income,
        "avg_monthly_expenses": avg_expenses,
        "avg_monthly_savings": avg_savings,
        "months_used": len(merged),
    }


def get_latest_person_snapshot(conn, person_id: int) -> dict:
    """Retourne la dernière snapshot weekly d'une personne."""
    if person_id is None:
        return {}

    try:
        row = conn.execute(
            """
            SELECT
                week_date,
                patrimoine_net,
                patrimoine_brut,
                liquidites_total,
                bourse_holdings,
                immobilier_value,
                pe_value,
                ent_value,
                credits_remaining
            FROM patrimoine_snapshots_weekly
            WHERE person_id = ?
            ORDER BY week_date DESC, id DESC
            LIMIT 1
            """,
            (int(person_id),),
        ).fetchone()
    except Exception:
        return {}

    if row is None:
        return {}

    return {
        "week_date": _row_get(row, "week_date"),
        "patrimoine_net": _to_float(_row_get(row, "patrimoine_net")),
        "patrimoine_brut": _to_float(_row_get(row, "patrimoine_brut")),
        "liquidites_total": _to_float(_row_get(row, "liquidites_total")),
        "bourse_holdings": _to_float(_row_get(row, "bourse_holdings")),
        "immobilier_value": _to_float(_row_get(row, "immobilier_value")),
        "pe_value": _to_float(_row_get(row, "pe_value")),
        "ent_value": _to_float(_row_get(row, "ent_value")),
        "credits_remaining": _to_float(_row_get(row, "credits_remaining")),
    }


def get_latest_family_snapshot(conn) -> dict:
    """Retourne la dernière snapshot weekly famille."""
    try:
        row = conn.execute(
            """
            SELECT
                week_date,
                patrimoine_net,
                patrimoine_brut,
                liquidites_total,
                bourse_holdings,
                immobilier_value,
                pe_value,
                ent_value,
                credits_remaining
            FROM patrimoine_snapshots_family_weekly
            ORDER BY week_date DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    except Exception:
        return {}

    if row is None:
        return {}

    return {
        "week_date": _row_get(row, "week_date"),
        "patrimoine_net": _to_float(_row_get(row, "patrimoine_net")),
        "patrimoine_brut": _to_float(_row_get(row, "patrimoine_brut")),
        "liquidites_total": _to_float(_row_get(row, "liquidites_total")),
        "bourse_holdings": _to_float(_row_get(row, "bourse_holdings")),
        "immobilier_value": _to_float(_row_get(row, "immobilier_value")),
        "pe_value": _to_float(_row_get(row, "pe_value")),
        "ent_value": _to_float(_row_get(row, "ent_value")),
        "credits_remaining": _to_float(_row_get(row, "credits_remaining")),
    }


def compute_average_income_expenses_for_person(
    conn,
    person_id: int,
    months: int = 12,
) -> dict:
    """Moyennes revenus/dépenses d'une personne (12 derniers mois avec données)."""
    if person_id is None:
        return {
            "avg_monthly_income": 0.0,
            "avg_monthly_expenses": 0.0,
            "avg_monthly_savings": 0.0,
            "months_used": 0,
        }

    try:
        income_df = pd.read_sql_query(
            """
            SELECT mois, SUM(montant) AS amount
            FROM revenus
            WHERE person_id = ?
            GROUP BY mois
            """,
            conn,
            params=(int(person_id),),
        )
    except Exception:
        income_df = pd.DataFrame(columns=["mois", "amount"])

    try:
        expense_df = pd.read_sql_query(
            """
            SELECT mois, SUM(montant) AS amount
            FROM depenses
            WHERE person_id = ?
            GROUP BY mois
            """,
            conn,
            params=(int(person_id),),
        )
    except Exception:
        expense_df = pd.DataFrame(columns=["mois", "amount"])
    return _compute_average_income_expenses(income_df, expense_df, months=months)


def compute_average_income_expenses_for_family(conn, months: int = 12) -> dict:
    """Moyennes revenus/dépenses famille (12 derniers mois avec données)."""
    try:
        income_df = pd.read_sql_query(
            """
            SELECT mois, SUM(montant) AS amount
            FROM revenus
            GROUP BY mois
            """,
            conn,
        )
    except Exception:
        income_df = pd.DataFrame(columns=["mois", "amount"])

    try:
        expense_df = pd.read_sql_query(
            """
            SELECT mois, SUM(montant) AS amount
            FROM depenses
            GROUP BY mois
            """,
            conn,
        )
    except Exception:
        expense_df = pd.DataFrame(columns=["mois", "amount"])
    return _compute_average_income_expenses(income_df, expense_df, months=months)


def _get_person_label(conn, person_id: int) -> str:
    try:
        row = conn.execute(
            "SELECT name FROM people WHERE id = ? LIMIT 1",
            (int(person_id),),
        ).fetchone()
    except Exception:
        return f"Personne #{int(person_id)}"
    if row is None:
        return f"Personne #{int(person_id)}"
    name = _row_get(row, "name")
    return str(name) if name else f"Personne #{int(person_id)}"


def get_projection_base_for_scope(
    conn,
    scope_type: str,
    scope_id: int | None = None,
) -> dict:
    """Construit la base réelle de projection pour `family` ou `person`."""
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

    net_worth = _to_float(snap.get("patrimoine_net"))
    gross_worth = _to_float(snap.get("patrimoine_brut"), net_worth)
    credits = _to_float(snap.get("credits_remaining"))

    # Filet de sécurité: si brut absent, on reconstruit avec net + crédits.
    if gross_worth == 0.0 and (net_worth != 0.0 or credits != 0.0):
        gross_worth = net_worth + credits

    avg_income = _to_float(metrics.get("avg_monthly_income"))
    avg_expenses = _to_float(metrics.get("avg_monthly_expenses"))
    avg_savings = _to_float(metrics.get("avg_monthly_savings"), avg_income - avg_expenses)

    base.update(
        {
            "net_worth": net_worth,
            "gross_worth": gross_worth,
            "liquidities": _to_float(snap.get("liquidites_total")),
            "bourse": _to_float(snap.get("bourse_holdings")),
            "immobilier": _to_float(snap.get("immobilier_value")),
            "private_equity": _to_float(snap.get("pe_value")),
            "entreprises": _to_float(snap.get("ent_value")),
            "credits": credits,
            "avg_monthly_income": avg_income,
            "avg_monthly_expenses": avg_expenses,
            "avg_monthly_savings": avg_savings,
            "fire_annual_expenses_base": avg_expenses * 12.0,
            "snapshot_week_date": snap.get("week_date"),
        }
    )
    return base


def compute_fire_target(monthly_expenses: float, fire_multiple: float) -> float:
    """FIRE target nominal basé sur la dépense mensuelle projetée."""
    monthly = max(_to_float(monthly_expenses), 0.0)
    multiple = max(_to_float(fire_multiple, 25.0), 0.0)
    return monthly * 12.0 * multiple


def run_projection(base: dict, params: ScenarioParams) -> pd.DataFrame:
    """Exécute une projection mensuelle V1 sur l'horizon du scénario."""
    horizon_months = max(int(params.horizon_years), 0) * 12

    monthly_return = _annual_pct_to_monthly_rate(params.expected_return_pct)
    monthly_income_growth = _annual_pct_to_monthly_rate(params.income_growth_pct)
    monthly_expense_growth = _annual_pct_to_monthly_rate(params.expense_growth_pct)
    monthly_inflation_factor = 1.0 + _annual_pct_to_monthly_rate(params.inflation_pct)

    net_worth = _to_float(
        params.initial_net_worth_override
        if params.initial_net_worth_override is not None
        else base.get("net_worth")
    )
    credits = max(_to_float(base.get("credits")), 0.0)
    liquidities = max(_to_float(base.get("liquidities")), 0.0)

    monthly_income = max(_to_float(base.get("avg_monthly_income")), 0.0)
    monthly_expenses = max(_to_float(base.get("avg_monthly_expenses")), 0.0)

    cumulative_growth = 0.0
    cumulative_contributions = 0.0
    inflation_factor = 1.0

    rows = []
    for month_index in range(horizon_months + 1):
        if month_index > 0:
            growth_amount = net_worth * monthly_return
            if params.monthly_savings_override is None:
                monthly_savings = monthly_income - monthly_expenses
            else:
                monthly_savings = _to_float(params.monthly_savings_override)

            net_worth = net_worth + growth_amount + monthly_savings
            cumulative_growth += growth_amount
            cumulative_contributions += monthly_savings

            # Modèle V1: les contributions entrent en liquidités.
            liquidities = max(0.0, (liquidities + monthly_savings) * (1.0 + monthly_return))

            monthly_income = max(0.0, monthly_income * (1.0 + monthly_income_growth))
            monthly_expenses = max(0.0, monthly_expenses * (1.0 + monthly_expense_growth))
            inflation_factor *= monthly_inflation_factor

        gross_worth = net_worth + credits
        if gross_worth >= 0.0:
            projected_liquidities = min(liquidities, gross_worth)
        else:
            projected_liquidities = liquidities

        fire_target = compute_fire_target(monthly_expenses, params.fire_multiple)
        if fire_target <= 0.0:
            fire_progress_pct = 100.0
            is_fire_reached = True
        else:
            fire_progress_pct = (net_worth / fire_target) * 100.0
            is_fire_reached = net_worth >= fire_target

        net_worth_real = net_worth / inflation_factor if inflation_factor > 0 else net_worth

        rows.append(
            {
                "month_index": month_index,
                "year": month_index // 12,
                "projected_net_worth": round(net_worth, 2),
                "projected_net_worth_real": round(net_worth_real, 2),
                "projected_gross_worth": round(gross_worth, 2),
                "projected_liquidities": round(projected_liquidities, 2),
                "projected_growth_component": round(cumulative_growth, 2),
                "projected_contributions_component": round(cumulative_contributions, 2),
                "fire_target": round(fire_target, 2),
                "fire_progress_pct": round(fire_progress_pct, 2),
                "is_fire_reached": bool(is_fire_reached),
            }
        )

    return pd.DataFrame(rows)


def _scaled_savings(base_savings: float, factor: float) -> float:
    """Ajuste l'épargne en conservant le signe (épargne positive ou négative)."""
    return _to_float(base_savings) * _to_float(factor, 1.0)


def build_standard_scenarios(base: dict, horizon_years: int) -> list[ScenarioParams]:
    """Construit les 3 scénarios V1: pessimiste, médian, optimiste."""
    base_savings = _to_float(base.get("avg_monthly_savings"))
    if base_savings >= 0:
        pess_savings = _scaled_savings(base_savings, 0.85)
        opt_savings = _scaled_savings(base_savings, 1.15)
    else:
        # Si l'épargne est négative, pessimiste => déficit plus fort.
        pess_savings = _scaled_savings(base_savings, 1.15)
        opt_savings = _scaled_savings(base_savings, 0.85)

    return [
        ScenarioParams(
            label="Pessimiste",
            horizon_years=int(horizon_years),
            expected_return_pct=3.0,
            inflation_pct=3.0,
            income_growth_pct=0.5,
            expense_growth_pct=2.0,
            monthly_savings_override=pess_savings,
            fire_multiple=27.0,
        ),
        ScenarioParams(
            label="Médian",
            horizon_years=int(horizon_years),
            expected_return_pct=6.0,
            inflation_pct=2.0,
            income_growth_pct=1.0,
            expense_growth_pct=1.0,
            monthly_savings_override=None,  # épargne recalculée dynamiquement
            fire_multiple=25.0,
        ),
        ScenarioParams(
            label="Optimiste",
            horizon_years=int(horizon_years),
            expected_return_pct=8.0,
            inflation_pct=1.5,
            income_growth_pct=2.0,
            expense_growth_pct=0.5,
            monthly_savings_override=opt_savings,
            fire_multiple=25.0,
        ),
    ]


def estimate_fire_reach_date(df_projection: pd.DataFrame) -> dict:
    """Estime la date d'atteinte FIRE depuis un DataFrame de projection."""
    default = {
        "fire_target": 0.0,
        "fire_reached": False,
        "fire_month_index": None,
        "fire_year": None,
        "fire_date_label": None,
    }
    if df_projection is None or df_projection.empty:
        return default

    target_col = "fire_target"
    reach_col = "is_fire_reached"
    month_col = "month_index"
    year_col = "year"

    last_target = _to_float(df_projection.iloc[-1].get(target_col, 0.0))
    reached_df = (
        df_projection[df_projection[reach_col] == True]
        if reach_col in df_projection.columns
        else pd.DataFrame()
    )
    if reached_df.empty:
        default["fire_target"] = last_target
        return default

    first_reached = reached_df.iloc[0]
    month_index = int(_to_float(first_reached.get(month_col, 0)))
    year = int(_to_float(first_reached.get(year_col, month_index // 12)))
    fire_target = _to_float(first_reached.get(target_col, last_target))

    return {
        "fire_target": fire_target,
        "fire_reached": True,
        "fire_month_index": month_index,
        "fire_year": year,
        "fire_date_label": f"M+{month_index} (année {year})",
    }


def _scenario_get(scenario: Any, key: str, default: Any):
    if isinstance(scenario, dict):
        return scenario.get(key, default)
    return getattr(scenario, key, default)


def project_patrimoine(
    patrimoine_initial: dict,
    scenario: ScenarioParams | dict,
    horizon_ans: int = 10,
) -> pd.DataFrame:
    """
    Compatibilité minimale avec l'ancienne API.
    """
    bank = _to_float(patrimoine_initial.get("bank"))
    bourse = _to_float(patrimoine_initial.get("bourse"))
    pe = _to_float(patrimoine_initial.get("pe"))
    ent = _to_float(patrimoine_initial.get("ent"))
    credits = _to_float(patrimoine_initial.get("credits"))

    # Legacy fields prioritaires si présents.
    taux_bourse_annuel = _to_float(
        _scenario_get(
            scenario,
            "taux_bourse_annuel",
            _scenario_get(scenario, "expected_return_pct", 6.0),
        ),
        6.0,
    )
    taux_pe_annuel = _to_float(
        _scenario_get(
            scenario,
            "taux_pe_annuel",
            _scenario_get(scenario, "expected_return_pct", 6.0),
        ),
        6.0,
    )
    inflation_annuelle = _to_float(
        _scenario_get(
            scenario,
            "inflation_annuelle",
            _scenario_get(scenario, "inflation_pct", 2.0),
        ),
        2.0,
    )
    epargne_mensuelle = _scenario_get(scenario, "epargne_mensuelle", None)
    if epargne_mensuelle is None:
        epargne_mensuelle = _scenario_get(scenario, "monthly_savings_override", 0.0)
    epargne_mensuelle = _to_float(epargne_mensuelle, 0.0)
    remboursement_mensuel_credit = _to_float(
        _scenario_get(scenario, "remboursement_mensuel_credit", 0.0),
        0.0,
    )

    r_bourse_m = _annual_pct_to_monthly_rate(taux_bourse_annuel)
    r_pe_m = _annual_pct_to_monthly_rate(taux_pe_annuel)
    defl_m = 1.0 + _annual_pct_to_monthly_rate(inflation_annuelle)

    n_mois = max(int(horizon_ans), 0) * 12
    rows = []
    for m in range(n_mois + 1):
        brut = bank + bourse + pe + ent
        net = brut - credits
        net_reel = net / (defl_m ** m) if defl_m > 0 else net

        rows.append(
            {
                "mois": m,
                "annee": m / 12.0,
                "bank": round(bank, 2),
                "bourse": round(bourse, 2),
                "pe": round(pe, 2),
                "ent": round(ent, 2),
                "credits": round(credits, 2),
                "patrimoine_brut": round(brut, 2),
                "patrimoine_net": round(net, 2),
                "patrimoine_net_reel": round(net_reel, 2),
            }
        )

        if m < n_mois:
            bourse *= 1.0 + r_bourse_m
            pe *= 1.0 + r_pe_m
            bank += epargne_mensuelle
            credits = max(0.0, credits - remboursement_mensuel_credit)

    return pd.DataFrame(rows)


def compute_three_scenarios(
    patrimoine_initial: dict,
    epargne_base: float,
    horizon_ans: int = 10,
    remboursement_mensuel: float = 0.0,
) -> dict[str, pd.DataFrame]:
    """
    Compatibilité minimale avec l'ancienne API 3 scénarios.
    """
    scenarios = [
        {
            "label": "Pessimiste",
            "taux_bourse_annuel": 4.0,
            "taux_pe_annuel": 5.0,
            "epargne_mensuelle": _to_float(epargne_base) * 0.8,
            "inflation_annuelle": 3.0,
            "remboursement_mensuel_credit": _to_float(remboursement_mensuel),
        },
        {
            "label": "Base",
            "taux_bourse_annuel": 7.0,
            "taux_pe_annuel": 10.0,
            "epargne_mensuelle": _to_float(epargne_base),
            "inflation_annuelle": 2.0,
            "remboursement_mensuel_credit": _to_float(remboursement_mensuel),
        },
        {
            "label": "Optimiste",
            "taux_bourse_annuel": 10.0,
            "taux_pe_annuel": 15.0,
            "epargne_mensuelle": _to_float(epargne_base) * 1.2,
            "inflation_annuelle": 1.0,
            "remboursement_mensuel_credit": _to_float(remboursement_mensuel),
        },
    ]
    return {
        str(s["label"]): project_patrimoine(patrimoine_initial, s, horizon_ans)
        for s in scenarios
    }


def summary_table(results: dict[str, pd.DataFrame], horizons: list[int] = None) -> pd.DataFrame:
    """
    Compatibilité minimale du tableau de synthèse.
    """
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
            row[f"{h} an(s)"] = round(_to_float(sub.iloc[0][val_col]), 0) if not sub.empty else None
        rows.append(row)

    return pd.DataFrame(rows)
