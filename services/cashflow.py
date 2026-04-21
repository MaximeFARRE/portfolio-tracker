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


def _compute_savings_streak(savings_series: pd.Series) -> int:
    """
    Nombre de mois consécutifs les plus récents avec une épargne strictement positive.
    Itère à rebours et s'arrête au premier mois non positif.
    """
    streak = 0
    for value in savings_series.iloc[::-1]:
        if _to_float(value) > 0:
            streak += 1
        else:
            break
    return streak


def _empty_passive_income_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["mois", "dividendes", "interets", "revenus_passifs"]
    )


def get_passive_income_monthly_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> pd.DataFrame:
    """
    Agrège les revenus passifs bourse (DIVIDENDE, INTERETS) par mois en EUR.

    Colonnes retournées:
        mois (YYYY-MM-01), dividendes, interets, revenus_passifs
    """
    scope = (scope_type or "").strip().lower()
    if scope not in ("family", "person"):
        return _empty_passive_income_df()
    if scope == "person" and scope_id is None:
        return _empty_passive_income_df()

    from services import repositories as repo
    from services.bourse_analytics import compute_passive_income_history

    if scope == "person":
        person_ids = [int(scope_id)]
    else:
        try:
            people = repo.list_people(conn)
            if people is None or people.empty:
                return _empty_passive_income_df()
            person_ids = [int(pid) for pid in people["id"].tolist()]
        except Exception:
            return _empty_passive_income_df()

    all_rows: list[pd.DataFrame] = []
    for person_id in person_ids:
        try:
            df = compute_passive_income_history(conn, person_id)
        except Exception as exc:
            logger.warning(
                "get_passive_income_monthly_for_scope: impossible de charger les revenus passifs "
                "pour person_id=%s: %s",
                person_id,
                exc,
            )
            continue
        if df is None or df.empty:
            continue

        cur = df.copy()
        if "month" in cur.columns:
            cur["mois"] = pd.to_datetime(cur["month"], format="%Y-%m", errors="coerce")
        else:
            cur["mois"] = pd.to_datetime(cur.get("date"), errors="coerce")
        cur["mois"] = cur["mois"].dt.to_period("M").dt.to_timestamp()
        cur = cur.dropna(subset=["mois"]).copy()
        if cur.empty:
            continue

        cur["type"] = cur.get("type", "").astype(str).str.upper()
        cur["amount_eur"] = pd.to_numeric(cur.get("amount_eur"), errors="coerce")
        cur = cur.dropna(subset=["amount_eur"])
        cur = cur[cur["type"].isin(["DIVIDENDE", "INTERETS"])].copy()
        if cur.empty:
            continue
        all_rows.append(cur[["mois", "type", "amount_eur"]])

    if not all_rows:
        return _empty_passive_income_df()

    merged = pd.concat(all_rows, ignore_index=True)
    piv = (
        merged.groupby(["mois", "type"], as_index=False)["amount_eur"]
        .sum()
        .pivot(index="mois", columns="type", values="amount_eur")
        .reset_index()
    )
    piv.columns.name = None
    div_series = (
        pd.to_numeric(piv["DIVIDENDE"], errors="coerce")
        if "DIVIDENDE" in piv.columns
        else pd.Series(0.0, index=piv.index)
    )
    int_series = (
        pd.to_numeric(piv["INTERETS"], errors="coerce")
        if "INTERETS" in piv.columns
        else pd.Series(0.0, index=piv.index)
    )
    piv["dividendes"] = div_series.fillna(0.0)
    piv["interets"] = int_series.fillna(0.0)
    piv["revenus_passifs"] = piv["dividendes"] + piv["interets"]
    piv["mois"] = pd.to_datetime(piv["mois"], errors="coerce").dt.strftime("%Y-%m-01")
    return piv[["mois", "dividendes", "interets", "revenus_passifs"]].sort_values("mois").reset_index(drop=True)



def get_cashflow_for_scope(
    conn,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> pd.DataFrame:
    """
    Récupère l'historique des revenus et dépenses agrégé par mois pour un scope
    (person ou family).
    Revenus = table 'revenus' + revenus passifs bourse (DIVIDENDE/INTERETS).
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
        rows_inc = conn.execute(income_sql.format(where_clause=where_clause), params).fetchall()
        income_df = pd.DataFrame(rows_inc, columns=["mois", "amount"]) if rows_inc else pd.DataFrame(columns=["mois", "amount"])
    except Exception as exc:
        logger.exception("get_cashflow_for_scope: échec requête revenus (scope=%s id=%s)", scope, scope_id, exc_info=exc)
        income_df = pd.DataFrame(columns=["mois", "amount"])

    try:
        rows_exp = conn.execute(expense_sql.format(where_clause=where_clause), params).fetchall()
        expense_df = pd.DataFrame(rows_exp, columns=["mois", "amount"]) if rows_exp else pd.DataFrame(columns=["mois", "amount"])
    except Exception as exc:
        logger.exception("get_cashflow_for_scope: échec requête dépenses (scope=%s id=%s)", scope, scope_id, exc_info=exc)
        expense_df = pd.DataFrame(columns=["mois", "amount"])

    try:
        passive_df = get_passive_income_monthly_for_scope(conn, scope, scope_id)
    except Exception as exc:
        logger.warning("get_cashflow_for_scope: revenus passifs indisponibles: %s", exc)
        passive_df = _empty_passive_income_df()

    income_with_passive = pd.merge(
        income_df.rename(columns={"amount": "income_manual"}),
        passive_df[["mois", "revenus_passifs"]] if not passive_df.empty else pd.DataFrame(columns=["mois", "revenus_passifs"]),
        on="mois",
        how="outer",
    )
    income_manual = (
        pd.to_numeric(income_with_passive["income_manual"], errors="coerce")
        if "income_manual" in income_with_passive.columns
        else pd.Series(0.0, index=income_with_passive.index)
    )
    revenus_passifs = (
        pd.to_numeric(income_with_passive["revenus_passifs"], errors="coerce")
        if "revenus_passifs" in income_with_passive.columns
        else pd.Series(0.0, index=income_with_passive.index)
    )
    income_with_passive["income"] = (
        income_manual.fillna(0.0)
        + revenus_passifs.fillna(0.0)
    )

    merged = pd.merge(
        income_with_passive[["mois", "income"]],
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


def get_person_monthly_savings_series(
    conn,
    person_id: int,
    n_mois: int = 24,
    end_month: str | None = None,
) -> pd.DataFrame:
    """
    Retourne la série mensuelle d'épargne d'une personne.

    Colonnes retournées :
        mois, revenus, depenses, epargne, taux_epargne
    """
    # On utilise get_cashflow_for_scope (dans ce même module) pour éviter
    # toute dépendance circulaire avec revenus_repository.compute_taux_epargne_mensuel.
    try:
        df_raw = get_cashflow_for_scope(conn, "person", int(person_id))
    except Exception as exc:
        logger.warning(
            "get_person_monthly_savings_series: échec calcul série person_id=%s : %s",
            person_id,
            exc,
        )
        return pd.DataFrame(
            columns=["mois", "revenus", "depenses", "epargne", "taux_epargne"]
        )

    if df_raw is None or df_raw.empty:
        return pd.DataFrame(
            columns=["mois", "revenus", "depenses", "epargne", "taux_epargne"]
        )

    n_mois = int(n_mois)
    if n_mois <= 0:
        return pd.DataFrame(
            columns=["mois", "revenus", "depenses", "epargne", "taux_epargne"]
        )

    # Renommage des colonnes SSOT → colonnes attendues
    df = df_raw.rename(
        columns={"income": "revenus", "expenses": "depenses", "savings": "epargne"}
    ).copy()
    df["mois_dt"] = pd.to_datetime(df["mois_dt"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    df = df.dropna(subset=["mois_dt"]).copy()
    if df.empty:
        return pd.DataFrame(
            columns=["mois", "revenus", "depenses", "epargne", "taux_epargne"]
        )

    # Ancre de fin: mois fourni (même si date intra-mois) sinon dernier mois observé.
    end_anchor = pd.to_datetime(end_month, errors="coerce") if end_month else pd.NaT
    if pd.isna(end_anchor):
        end_anchor = df["mois_dt"].max()
    end_anchor = pd.Timestamp(end_anchor).to_period("M").to_timestamp()

    # Fenêtre calendaire explicite avec reindex + remplissage 0 sur les mois manquants.
    df = df[df["mois_dt"] <= end_anchor].copy()
    start_anchor = end_anchor - pd.DateOffset(months=n_mois - 1)
    full_months = pd.date_range(start=start_anchor, end=end_anchor, freq="MS")
    df = (
        df.set_index("mois_dt")
        .reindex(full_months, fill_value=0.0)
        .rename_axis("mois_dt")
        .reset_index()
    )
    for col in ["revenus", "depenses", "epargne"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["epargne"] = df["revenus"] - df["depenses"]
    df["mois"] = pd.to_datetime(df["mois_dt"], errors="coerce").dt.strftime("%Y-%m-01")

    # Taux d'épargne : NA si pas de revenus ce mois-là
    df["taux_epargne"] = df.apply(
        lambda r: round(float(r["epargne"]) / float(r["revenus"]) * 100, 1)
        if _to_float(r["revenus"]) > 0 else pd.NA,
        axis=1,
    )

    return df[["mois", "revenus", "depenses", "epargne", "taux_epargne"]].reset_index(drop=True)

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

    df = get_person_monthly_savings_series(conn, person_id, n_mois=n_mois)

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

    months_with_data = last12[
        (pd.to_numeric(last12["revenus"], errors="coerce").fillna(0.0) != 0.0)
        | (pd.to_numeric(last12["depenses"], errors="coerce").fillna(0.0) != 0.0)
    ].copy()
    base_avg = months_with_data if not months_with_data.empty else last12

    avg_savings_12m = float(base_avg["epargne"].mean()) if not base_avg.empty else 0.0
    avg_income = float(base_avg["revenus"].mean()) if not base_avg.empty else 0.0
    avg_expenses = float(base_avg["depenses"].mean()) if not base_avg.empty else 0.0

    # Streak de mois consécutifs avec épargne positive (depuis le plus récent)
    streak = _compute_savings_streak(df["epargne"])

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
        "has_cashflow": not base_avg.empty,
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
        "has_cashflow": False,
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
            "has_cashflow": False,
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
    # On reconstruit la série sur tous les mois (y compris les mois sans données = 0)
    # avant de calculer le streak, pour ne pas ignorer les trous.
    first_month = monthly_df["mois_dt"].min()
    last_month = monthly_df["mois_dt"].max()
    full_index = pd.date_range(start=first_month, end=last_month, freq="MS")
    full_df = monthly_df.set_index("mois_dt").reindex(full_index, fill_value=0.0)
    full_df["savings"] = full_df["income"] - full_df["expenses"]
    streak = _compute_savings_streak(full_df["savings"])

    return {
        "avg_monthly_income": avg_income,
        "avg_monthly_expenses": avg_expenses,
        "avg_monthly_savings": avg_savings,
        "savings_rate_12m": savings_rate,
        "positive_savings_streak": int(streak),
        "has_cashflow": not with_data.empty,
    }
