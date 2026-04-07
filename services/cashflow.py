import logging
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)


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

def compute_savings_metrics(conn_or_df, person_id: Optional[int] = None,
                            n_mois: int = 24) -> dict:
    """
    Point d'entrée unique (SSOT) pour toutes les métriques d'épargne.

    Deux modes d'appel :

    1) Appel complet (recommandé — mode SSOT) :
       compute_savings_metrics(conn, person_id, n_mois=24)
       → retourne les KPIs agrégés ET la série mensuelle complète.

    2) Appel legacy (rétrocompatible) :
       compute_savings_metrics(monthly_df)
       → comportement historique, retourne uniquement les KPIs agrégés
         à partir d'un DataFrame cashflow déjà chargé.

    Clés retournées (mode complet) :
        avg_monthly_income      float
        avg_monthly_expenses    float
        avg_monthly_savings     float
        savings_rate_12m        float  (% moyen sur les 12 derniers mois avec données)
        positive_savings_streak int
        monthly_series          DataFrame[mois, revenus, depenses, epargne, taux_epargne]
        avg_rate_12m            float  (taux moyen 12 mois, arrondi 1 décimale)
        avg_savings_12m         float  (épargne mensuelle moyenne 12 mois)
    """
    # ── Détection du mode d'appel ────────────────────────────────────────
    if isinstance(conn_or_df, pd.DataFrame):
        return _compute_savings_kpis_from_cashflow(conn_or_df)

    # ── Mode complet : conn + person_id ──────────────────────────────────
    conn = conn_or_df
    if person_id is None:
        logger.warning("compute_savings_metrics: person_id manquant")
        return _empty_savings_result()

    from services.revenus_repository import compute_taux_epargne_mensuel

    df = compute_taux_epargne_mensuel(conn, person_id, n_mois=n_mois)

    if df is None or df.empty:
        logger.info(
            "compute_savings_metrics: aucune donnée revenus/dépenses "
            "pour person_id=%s (n_mois=%s)", person_id, n_mois,
        )
        return _empty_savings_result()

    # ── KPIs agrégés sur les 12 derniers mois ────────────────────────────
    last12 = df.tail(12)

    valid_rates = last12["taux_epargne"].dropna()
    if not valid_rates.empty:
        avg_rate_12m = round(float(valid_rates.mean()), 1)
    else:
        avg_rate_12m = 0.0
        logger.debug(
            "compute_savings_metrics: aucun mois avec revenus > 0 "
            "sur les 12 derniers mois (person_id=%s)", person_id,
        )

    avg_savings_12m = float(last12["epargne"].mean()) if not last12.empty else 0.0

    avg_income = float(last12["revenus"].mean()) if not last12.empty else 0.0
    avg_expenses = float(last12["depenses"].mean()) if not last12.empty else 0.0

    # Streak de mois consécutifs avec épargne positive (depuis le plus récent)
    streak = 0
    for ep in df["epargne"].iloc[::-1]:
        if _to_float(ep) > 0:
            streak += 1
        else:
            break

    return {
        # KPIs agrégés (rétrocompatibles)
        "avg_monthly_income": avg_income,
        "avg_monthly_expenses": avg_expenses,
        "avg_monthly_savings": avg_savings_12m,
        "savings_rate_12m": avg_rate_12m,
        "positive_savings_streak": int(streak),
        # Données enrichies (mode complet)
        "monthly_series": df,
        "avg_rate_12m": avg_rate_12m,
        "avg_savings_12m": avg_savings_12m,
    }


def _empty_savings_result() -> dict:
    """Résultat vide pour compute_savings_metrics."""
    return {
        "avg_monthly_income": 0.0,
        "avg_monthly_expenses": 0.0,
        "avg_monthly_savings": 0.0,
        "savings_rate_12m": 0.0,
        "positive_savings_streak": 0,
        "monthly_series": pd.DataFrame(
            columns=["mois", "revenus", "depenses", "epargne", "taux_epargne"]
        ),
        "avg_rate_12m": 0.0,
        "avg_savings_12m": 0.0,
    }


def get_family_flux_summary(
    conn,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict:
    """
    Résumé des flux famille basé sur la table ``transactions``.

    Ce point d'entrée encapsule les calculs autrefois dispersés dans
    ``FluxPanel`` (famille_page.py) : solde global, cashflow du mois,
    ventilation par personne et par compte, dernières opérations.

    Paramètres
    ----------
    year, month : int ou None
        Année et mois du cashflow mensuel affiché.
        Si None, utilise le mois courant.

    Retourne un dictionnaire :
        solde_total          float   — solde global famille (toutes tx)
        cashflow_mois        float   — flux net du mois year/month
        n_operations         int     — nombre total de transactions chargées
        par_personne         DataFrame[Personne, Solde (flux), Opérations]
        par_compte           DataFrame[Personne, Compte, Solde (flux), Opérations]
        dernieres_operations DataFrame — 50 dernières opérations (colonnes dispo)
    """
    from services import repositories as repo
    from services import calculations as calc

    today = pd.Timestamp.today()
    yr = int(year) if year is not None else int(today.year)
    mo = int(month) if month is not None else int(today.month)

    # ── Chargement des données ────────────────────────────────────────────
    people = repo.list_people(conn)
    if people is None or people.empty:
        logger.warning("get_family_flux_summary: aucune personne en base")
        return _empty_flux_result()

    accounts = repo.list_accounts(conn)
    tx_all = repo.list_transactions(conn, limit=20000)

    if tx_all is None or tx_all.empty:
        logger.info("get_family_flux_summary: aucune transaction disponible")
        return _empty_flux_result()

    # ── KPIs globaux ─────────────────────────────────────────────────────
    solde_total = calc.solde_compte(tx_all)
    cashflow_du_mois = calc.cashflow_mois(tx_all, yr, mo)
    n_ops = len(tx_all)

    # ── Ventilation par personne ──────────────────────────────────────────
    lignes_p = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        tx_p = tx_all[tx_all["person_id"] == pid].copy()
        lignes_p.append({
            "Personne": str(p["name"]),
            "Solde (flux)": calc.solde_compte(tx_p),
            "Opérations": len(tx_p),
        })
    df_par_personne = (
        pd.DataFrame(lignes_p)
        .sort_values("Solde (flux)", ascending=False)
        .reset_index(drop=True)
    )

    # ── Ventilation par compte ────────────────────────────────────────────
    df_par_compte = pd.DataFrame()
    if accounts is not None and not accounts.empty:
        lignes_c = []
        for _, a in accounts.iterrows():
            acc_id = int(a["id"])
            pid = int(a["person_id"])
            person_name = (
                str(people.loc[people["id"] == pid, "name"].iloc[0])
                if pid in people["id"].values
                else "?"
            )
            tx_c = tx_all[tx_all["account_id"] == acc_id].copy()
            lignes_c.append({
                "Personne": person_name,
                "Compte": str(a["name"]),
                "Solde (flux)": calc.solde_compte(tx_c),
                "Opérations": len(tx_c),
            })
        df_par_compte = (
            pd.DataFrame(lignes_c)
            .sort_values("Solde (flux)", ascending=False)
            .reset_index(drop=True)
        )

    # ── Dernières opérations ──────────────────────────────────────────────
    cols_last = ["date", "person_name", "account_name", "type",
                 "asset_symbol", "amount", "fees", "category", "note"]
    cols_present = [c for c in cols_last if c in tx_all.columns]
    df_dernieres = tx_all[cols_present].head(50).copy() if cols_present else pd.DataFrame()

    return {
        "solde_total":           solde_total,
        "cashflow_mois":         cashflow_du_mois,
        "n_operations":          n_ops,
        "par_personne":          df_par_personne,
        "par_compte":            df_par_compte,
        "dernieres_operations":  df_dernieres,
    }


def _empty_flux_result() -> dict:
    """Résultat vide retourné par get_family_flux_summary en cas d'erreur."""
    return {
        "solde_total":          0.0,
        "cashflow_mois":        0.0,
        "n_operations":         0,
        "par_personne":         pd.DataFrame(columns=["Personne", "Solde (flux)", "Opérations"]),
        "par_compte":           pd.DataFrame(columns=["Personne", "Compte", "Solde (flux)", "Opérations"]),
        "dernieres_operations": pd.DataFrame(),
    }


def _compute_savings_kpis_from_cashflow(monthly_df: pd.DataFrame) -> dict:
    """
    Calcule les KPIs agrégés à partir d'un DataFrame cashflow
    (colonnes mois_dt, income, expenses, savings).

    Chemin legacy utilisé par native_milestones et projections.
    """
    if monthly_df is None or monthly_df.empty:
        return {
            "avg_monthly_income": 0.0,
            "avg_monthly_expenses": 0.0,
            "avg_monthly_savings": 0.0,
            "savings_rate_12m": 0.0,
            "positive_savings_streak": 0,
        }

    with_data = monthly_df[
        (monthly_df["income"] != 0.0) | (monthly_df["expenses"] != 0.0)
    ].copy()
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
        monthly_rates = (
            recent.loc[recent["income"] > 0, "savings"]
            / recent.loc[recent["income"] > 0, "income"]
            * 100.0
        )
        savings_rate = _to_float(monthly_rates.mean()) if not monthly_rates.empty else 0.0

    # Streak : série continue de mois avec épargne positive.
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
