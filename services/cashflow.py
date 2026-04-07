import pandas as pd
from typing import Optional

def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def get_cashflow_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> pd.DataFrame:
    """
    Récupère l'historique des revenus et dépenses agrégé par mois pour un scope
    (person ou family). Source de vérité = tables 'revenus' et 'depenses'.
    """
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

def compute_savings_metrics(monthly_df: pd.DataFrame) -> dict:
    """
    Génère les KPIs à partir du DataFrame cashflow:
    - avg_monthly_income
    - avg_monthly_expenses 
    - avg_monthly_savings
    - savings_rate_12m
    - positive_savings_streak
    """
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
