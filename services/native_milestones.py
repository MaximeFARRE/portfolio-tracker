"""
Jalons natifs (gamification) calculés dynamiquement par scope.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from services.projections import compute_fire_target, get_projection_base_for_scope
from utils.format_monnaie import money

NATIVE_MILESTONE_DEFINITIONS = [
    {
        "category_key": "net_worth",
        "category_label": "Patrimoine net",
        "metric_key": "net_worth",
        "unit": "EUR",
        "thresholds": [
            1000, 2500, 5000, 7500, 10000, 15000, 20000, 30000, 40000, 50000,
            60000, 75000, 100000, 125000, 150000, 200000, 250000, 300000,
            400000, 500000, 600000, 750000, 1000000, 1250000, 1500000, 2000000,
            3000000, 5000000, 7500000, 10000000,
        ],
    },
    {
        "category_key": "liquidities",
        "category_label": "Liquidités",
        "metric_key": "liquidities",
        "unit": "EUR",
        "thresholds": [500, 1000, 2000, 3000, 5000, 7500, 10000, 15000, 20000, 50000],
    },
    {
        "category_key": "stocks",
        "category_label": "Bourse",
        "metric_key": "stocks",
        "unit": "EUR",
        "thresholds": [
            500, 1000, 2500, 5000, 7500, 10000, 15000, 20000, 30000, 40000,
            50000, 75000, 100000, 150000, 200000, 300000, 500000, 750000,
            1000000, 2000000,
        ],
    },
    {
        "category_key": "savings_rate_12m",
        "category_label": "Taux d'épargne moyen (12m)",
        "metric_key": "savings_rate_12m",
        "unit": "PCT",
        "thresholds": [5, 10, 15, 20, 25, 30, 35, 40, 50, 60],
    },
    {
        "category_key": "monthly_savings_capacity",
        "category_label": "Capacité d'épargne mensuelle",
        "metric_key": "monthly_savings_capacity",
        "unit": "EUR",
        "thresholds": [100, 250, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000],
    },
    {
        "category_key": "fire_progress",
        "category_label": "Progression FIRE",
        "metric_key": "fire_progress",
        "unit": "PCT",
        "thresholds": [5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 90, 100],
    },
    {
        "category_key": "real_estate_value",
        "category_label": "Immobilier",
        "metric_key": "real_estate_value",
        "unit": "EUR",
        "thresholds": [25000, 50000, 75000, 100000, 150000, 200000, 300000, 500000, 750000, 1000000],
    },
]


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _load_monthly_income_expenses_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> pd.DataFrame:
    scope = (scope_type or "").strip().lower()
    if scope not in ("family", "person"):
        return pd.DataFrame(columns=["mois_dt", "income", "expenses", "savings"])

    if scope == "person" and scope_id is None:
        return pd.DataFrame(columns=["mois_dt", "income", "expenses", "savings"])

    income_sql = """
        SELECT mois, SUM(montant) AS amount
        FROM revenus
        {where_clause}
        GROUP BY mois
    """
    expense_sql = """
        SELECT mois, SUM(montant) AS amount
        FROM depenses
        {where_clause}
        GROUP BY mois
    """
    where_clause = ""
    params: tuple = ()
    if scope == "person":
        where_clause = "WHERE person_id = ?"
        params = (int(scope_id),)

    try:
        income_df = pd.read_sql_query(income_sql.format(where_clause=where_clause), conn, params=params)
    except Exception:
        income_df = pd.DataFrame(columns=["mois", "amount"])

    try:
        expense_df = pd.read_sql_query(expense_sql.format(where_clause=where_clause), conn, params=params)
    except Exception:
        expense_df = pd.DataFrame(columns=["mois", "amount"])

    merged = pd.merge(
        income_df.rename(columns={"amount": "income"}),
        expense_df.rename(columns={"amount": "expenses"}),
        on="mois",
        how="outer",
    )
    if merged.empty:
        return pd.DataFrame(columns=["mois_dt", "income", "expenses", "savings"])

    merged["income"] = pd.to_numeric(merged.get("income"), errors="coerce").fillna(0.0)
    merged["expenses"] = pd.to_numeric(merged.get("expenses"), errors="coerce").fillna(0.0)
    merged["mois_dt"] = pd.to_datetime(merged["mois"], errors="coerce")
    merged = merged.dropna(subset=["mois_dt"]).copy()
    if merged.empty:
        return pd.DataFrame(columns=["mois_dt", "income", "expenses", "savings"])

    merged["mois_dt"] = merged["mois_dt"].dt.to_period("M").dt.to_timestamp()
    merged = (
        merged.groupby("mois_dt", as_index=False)[["income", "expenses"]]
        .sum()
        .sort_values("mois_dt")
        .reset_index(drop=True)
    )
    merged["savings"] = merged["income"] - merged["expenses"]
    return merged


def _compute_savings_metrics(monthly_df: pd.DataFrame) -> dict:
    if monthly_df is None or monthly_df.empty:
        return {
            "avg_monthly_income": 0.0,
            "avg_monthly_expenses": 0.0,
            "avg_monthly_savings": 0.0,
            "savings_rate_12m": 0.0,
            "positive_savings_streak": 0,
        }

    with_data = monthly_df[(monthly_df["income"] != 0.0) | (monthly_df["expenses"] != 0.0)].copy()
    recent = with_data.sort_values("mois_dt", ascending=False).head(12)

    if recent.empty:
        avg_income = 0.0
        avg_expenses = 0.0
        avg_savings = 0.0
        savings_rate = 0.0
    else:
        avg_income = _to_float(recent["income"].mean())
        avg_expenses = _to_float(recent["expenses"].mean())
        avg_savings = avg_income - avg_expenses
        monthly_rates = recent.loc[recent["income"] > 0, "savings"] / recent.loc[recent["income"] > 0, "income"] * 100.0
        savings_rate = _to_float(monthly_rates.mean()) if not monthly_rates.empty else 0.0

    # Série continue pour mesurer la régularité récente (streak).
    first_month = monthly_df["mois_dt"].min()
    last_month = monthly_df["mois_dt"].max()
    idx = pd.date_range(start=first_month, end=last_month, freq="MS")
    full_df = monthly_df.set_index("mois_dt").reindex(idx, fill_value=0.0)
    full_df["savings"] = full_df["income"] - full_df["expenses"]

    streak = 0
    for value in full_df["savings"].iloc[::-1]:
        if _to_float(value) > 0:
            streak += 1
        else:
            break

    return {
        "avg_monthly_income": avg_income,
        "avg_monthly_expenses": avg_expenses,
        "avg_monthly_savings": avg_savings,
        "savings_rate_12m": savings_rate,
        "positive_savings_streak": int(streak),
    }


def get_scope_milestone_metrics(conn, scope_type: str, scope_id: Optional[int] = None) -> dict:
    """
    Retourne les métriques nécessaires au calcul des jalons natifs.
    """
    base = get_projection_base_for_scope(conn, scope_type, scope_id)
    monthly_df = _load_monthly_income_expenses_for_scope(conn, scope_type, scope_id)
    savings_metrics = _compute_savings_metrics(monthly_df)

    avg_expenses = _to_float(savings_metrics["avg_monthly_expenses"])
    fire_target = compute_fire_target(avg_expenses, 25.0)
    if fire_target <= 0:
        fire_progress = 0.0
    else:
        fire_progress = max(0.0, min((_to_float(base.get("net_worth")) / fire_target) * 100.0, 100.0))

    return {
        "scope_type": str(base.get("scope_type") or scope_type),
        "scope_id": base.get("scope_id", scope_id),
        "scope_label": base.get("scope_label"),
        "net_worth": _to_float(base.get("net_worth")),
        "liquidities": _to_float(base.get("liquidities")),
        "stocks": _to_float(base.get("bourse")),
        "real_estate_value": _to_float(base.get("immobilier")),
        "avg_monthly_income": _to_float(savings_metrics["avg_monthly_income"]),
        "avg_monthly_expenses": avg_expenses,
        "avg_monthly_savings": _to_float(savings_metrics["avg_monthly_savings"]),
        "monthly_savings_capacity": _to_float(savings_metrics["avg_monthly_savings"]),
        "savings_rate_12m": _to_float(savings_metrics["savings_rate_12m"]),
        "positive_savings_streak": int(savings_metrics["positive_savings_streak"]),
        "fire_progress": _to_float(fire_progress),
    }


def compute_current_milestone(current_value, thresholds: list[float]) -> dict:
    """
    Calcule le niveau courant et la progression entre le palier atteint et le suivant.
    """
    value = _to_float(current_value)
    levels = sorted(float(x) for x in thresholds or [])
    if not levels:
        return {
            "current_level_index": -1,
            "current_level_value": 0.0,
            "next_level_index": None,
            "next_level_value": None,
            "progress_pct": 0.0,
            "is_max_level": True,
        }

    first_level = levels[0]
    last_level = levels[-1]

    if value < first_level:
        progress = 0.0 if first_level <= 0 else max(0.0, min((value / first_level) * 100.0, 100.0))
        return {
            "current_level_index": -1,
            "current_level_value": 0.0,
            "next_level_index": 0,
            "next_level_value": first_level,
            "progress_pct": progress,
            "is_max_level": False,
        }

    if value >= last_level:
        return {
            "current_level_index": len(levels) - 1,
            "current_level_value": last_level,
            "next_level_index": None,
            "next_level_value": None,
            "progress_pct": 100.0,
            "is_max_level": True,
        }

    current_idx = 0
    for idx, threshold in enumerate(levels):
        if value >= threshold:
            current_idx = idx
        else:
            break

    current_threshold = levels[current_idx]
    next_idx = current_idx + 1
    next_threshold = levels[next_idx]
    step = max(next_threshold - current_threshold, 1e-9)
    progress = max(0.0, min(((value - current_threshold) / step) * 100.0, 100.0))

    return {
        "current_level_index": current_idx,
        "current_level_value": current_threshold,
        "next_level_index": next_idx,
        "next_level_value": next_threshold,
        "progress_pct": progress,
        "is_max_level": False,
    }


def _format_value(value: float, unit: str) -> str:
    if unit == "EUR":
        return money(value)
    return f"{_to_float(value):.1f} %"


def build_native_milestones_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
    metrics: Optional[dict] = None,
) -> list[dict]:
    """
    Génère la liste des jalons natifs affichables pour le scope actif.
    """
    metrics = metrics or get_scope_milestone_metrics(conn, scope_type, scope_id)
    results = []

    for definition in NATIVE_MILESTONE_DEFINITIONS:
        metric_key = definition["metric_key"]
        current_value = _to_float(metrics.get(metric_key, 0.0))
        level = compute_current_milestone(current_value, definition["thresholds"])
        level_number = max(int(level["current_level_index"]) + 1, 0)
        current_threshold = _to_float(level["current_level_value"])
        next_threshold = level["next_level_value"]
        progress_pct = _to_float(level["progress_pct"])
        is_max_level = bool(level["is_max_level"])

        if is_max_level:
            status = "MAX_LEVEL"
            subtitle = "Niveau maximal atteint."
        elif level_number == 0 and current_value <= 0:
            status = "NOT_STARTED"
            subtitle = f"Prochain palier : {_format_value(_to_float(next_threshold), definition['unit'])}"
        else:
            status = "IN_PROGRESS"
            subtitle = f"Prochain palier : {_format_value(_to_float(next_threshold), definition['unit'])}"

        results.append(
            {
                "category_key": definition["category_key"],
                "category_label": definition["category_label"],
                "current_value": current_value,
                "display_value": _format_value(current_value, definition["unit"]),
                "unit": definition["unit"],
                "level_number": level_number,
                "current_threshold": current_threshold,
                "next_threshold": _to_float(next_threshold) if next_threshold is not None else None,
                "progress_pct": progress_pct,
                "is_max_level": is_max_level,
                "status": status,
                "title": f"Niveau {level_number} — {definition['category_label']}",
                "subtitle": subtitle,
            }
        )

    return results


def get_featured_milestone_for_category(milestones: list[dict], category_key: str) -> Optional[dict]:
    """
    Retourne un jalon précis depuis la liste générée.
    """
    for milestone in milestones or []:
        if str(milestone.get("category_key")) == str(category_key):
            return milestone
    return None
