"""
Métriques agrégées pour le dashboard Vue d'ensemble.
Appel unique: get_vue_ensemble_metrics(conn, person_id) → dict
"""
from __future__ import annotations
import math
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def _sf(v, default: float = 0.0) -> float:
    """safe float — retourne default si None / NaN / non-numérique."""
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _opt(v) -> float | None:
    """Comme _sf mais retourne None plutôt qu'un défaut."""
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# business metrics
def get_vue_ensemble_metrics(conn, person_id: int) -> dict:
    """
    Calcule et retourne toutes les métriques du dashboard patrimoine.

    Clés retournées (les KPI peuvent être None si données insuffisantes) :
        Snapshot courant :
            net, brut, liq, bourse, credits, pe_value, ent_value, immo_value,
            week_date, asof_date
        Historiques :
            net_13w, net_52w
        Performance :
            perf_3m_pct, perf_12m_pct, cagr_pct
        Santé patrimoniale :
            taux_endettement, part_liquide, exposition_marches, actifs_illiquides
        Progression réelle :
            gain_3m, gain_12m, epargne_12m, effet_valorisation_12m
        Pilotage :
            taux_epargne_avg, capacite_epargne_avg, reserve_securite
        Cashflow brut (pour les graphiques) :
            df_cashflow  (DataFrame: mois, revenus, depenses, epargne, taux_epargne)
    """
    m: dict = {}

    # ── 1. Snapshots hebdomadaires ────────────────────────────────────────
    from services.snapshots import get_person_weekly_series
    try:
        df_snap = get_person_weekly_series(conn, person_id)
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: lecture snapshots échouée : %s", exc)
        df_snap = pd.DataFrame()

    if df_snap.empty:
        return m

    # week_date est déjà datetime (via get_person_weekly_series)
    last = df_snap.iloc[-1]
    m["net"] = _sf(last.get("patrimoine_net"))
    m["brut"] = _sf(last.get("patrimoine_brut"))
    m["liq"] = _sf(last.get("liquidites_total"))
    m["bourse"] = _sf(last.get("bourse_holdings"))
    m["credits"] = _sf(last.get("credits_remaining"))
    m["pe_value"] = _sf(last.get("pe_value"))
    m["ent_value"] = _sf(last.get("ent_value"))
    m["immo_value"] = _sf(last.get("immobilier_value"))
    m["week_date"] = pd.Timestamp(last["week_date"]).strftime("%Y-%m-%d")
    m["asof_date"] = m["week_date"]

    # ── Qualité du snapshot stocké (DQ-02) ────────────────────────────────
    try:
        from services.snapshots_read import get_latest_snapshot_notes
        m["snapshot_notes"] = get_latest_snapshot_notes(conn, person_id)
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: snapshot_notes indisponible : %s", exc)
        m["snapshot_notes"] = None

    # ── 2. Patrimoine net historique ──────────────────────────────────────
    anchor_dt = None
    try:
        anchor_dt = pd.Timestamp(last["week_date"])
        m["asof_date"] = anchor_dt.date().isoformat()

        def _hist_net(weeks_back: int) -> float | None:
            target = anchor_dt - pd.Timedelta(weeks=weeks_back)
            past = df_snap[df_snap["week_date"] <= target]
            return _opt(past.iloc[-1]["patrimoine_net"]) if not past.empty else None

        m["net_13w"] = _hist_net(13)
        m["net_52w"] = _hist_net(52)
        # _dt : alias pour rétrocompatibilité avec vue_ensemble_panel (graphique)
        df_snap = df_snap.copy()
        df_snap["_dt"] = df_snap["week_date"]
        m["df_snap"] = df_snap  # pour le graphique ligne dans le panel
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: historique net échoué : %s", exc)
        m["net_13w"] = None
        m["net_52w"] = None

    # ── 3. Cashflow mensuel (12 mois) ─────────────────────────────────────
    try:
        from services.cashflow import get_person_monthly_savings_series
        df_cf = get_person_monthly_savings_series(
            conn,
            person_id,
            n_mois=24,
            end_month=(anchor_dt.date().isoformat() if anchor_dt is not None else None),
        )
        m["df_cashflow"] = df_cf if (df_cf is not None and not df_cf.empty) else pd.DataFrame()
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: cashflow échoué : %s", exc)
        m["df_cashflow"] = pd.DataFrame()

    df_cf = m.get("df_cashflow", pd.DataFrame())
    if not df_cf.empty:
        # Sécurise les KPI sur 12 mois calendaires complets (mois manquants = 0).
        df_kpi = df_cf.copy()
        df_kpi["_mois_dt"] = pd.to_datetime(df_kpi["mois"], errors="coerce").dt.to_period("M").dt.to_timestamp()
        df_kpi = df_kpi.dropna(subset=["_mois_dt"]).copy()
        if not df_kpi.empty:
            last_m = df_kpi["_mois_dt"].max()
            idx = pd.date_range(start=last_m - pd.DateOffset(months=11), end=last_m, freq="MS")
            last12 = (
                df_kpi.set_index("_mois_dt")
                .reindex(idx, fill_value=0.0)
                .reset_index(drop=True)
            )
            for col in ["revenus", "depenses", "epargne"]:
                last12[col] = pd.to_numeric(last12[col], errors="coerce").fillna(0.0)
        else:
            last12 = pd.DataFrame(columns=["revenus", "depenses", "epargne"])

        m["epargne_12m"]       = float(last12["epargne"].sum())
        m["depenses_moy_12m"]  = float(last12["depenses"].mean())
        m["capacite_epargne_avg"] = float(last12["epargne"].mean())
        rev_sum_12m = float(last12["revenus"].sum())
        m["taux_epargne_avg"] = (
            (m["epargne_12m"] / rev_sum_12m * 100) if rev_sum_12m > 0 else None
        )
        # Couverture cashflow (DQ-07): nombre de mois avec au moins revenus ou dépenses non nuls
        m["cashflow_coverage_months_12"] = int((
            (last12["revenus"] != 0.0) | (last12["depenses"] != 0.0)
        ).sum())
    else:
        m["epargne_12m"]                   = None
        m["depenses_moy_12m"]              = None
        m["capacite_epargne_avg"]          = None
        m["taux_epargne_avg"]              = None
        m["cashflow_coverage_months_12"]   = 0

    # ── 4. Santé patrimoniale ─────────────────────────────────────────────
    brut = m["brut"]
    if brut > 0:
        m["taux_endettement"]  = m["credits"] / brut * 100
        m["part_liquide"]       = m["liq"] / brut * 100
        m["exposition_marches"] = (m["bourse"] + m["pe_value"]) / brut * 100
        m["actifs_illiquides"]  = (m["ent_value"] + m["pe_value"] + m["immo_value"]) / brut * 100
    else:
        m["taux_endettement"]   = None
        m["part_liquide"]       = None
        m["exposition_marches"] = None
        m["actifs_illiquides"]  = None

    # ── 5. Progression réelle ─────────────────────────────────────────────
    net     = m.get("net")
    net_13w = m.get("net_13w")
    net_52w = m.get("net_52w")
    m["gain_3m"]  = (net - net_13w) if (net is not None and net_13w is not None) else None
    m["gain_12m"] = (net - net_52w) if (net is not None and net_52w is not None) else None
    m["perf_3m_pct"] = (
        ((net - net_13w) / abs(net_13w) * 100)
        if (net is not None and net_13w is not None and abs(net_13w) >= 1)
        else None
    )
    m["perf_12m_pct"] = (
        ((net - net_52w) / abs(net_52w) * 100)
        if (net is not None and net_52w is not None and abs(net_52w) >= 1)
        else None
    )

    m["cagr_pct"] = None
    try:
        if anchor_dt is not None and len(df_snap) >= 2 and net is not None:
            val_first = _opt(df_snap.iloc[0]["patrimoine_net"])
            first_dt = pd.Timestamp(df_snap.iloc[0]["_dt"])
            n_years = (anchor_dt - first_dt).days / 365.25
            if (
                val_first is not None
                and abs(val_first) > 1
                and n_years > 0.1
                and (net / val_first) > 0
            ):
                m["cagr_pct"] = ((net / val_first) ** (1 / n_years) - 1) * 100
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: cagr échoué : %s", exc)

    gain_12m    = m.get("gain_12m")
    epargne_12m = m.get("epargne_12m")
    m["effet_valorisation_12m"] = (
        gain_12m - epargne_12m
        if (gain_12m is not None and epargne_12m is not None)
        else None
    )

    # ── 6. Réserve de sécurité ────────────────────────────────────────────
    dep_moy = m.get("depenses_moy_12m")
    m["reserve_securite"] = (m["liq"] / dep_moy) if (dep_moy and dep_moy > 0) else None

    return m


# presentation helpers
_ALLOC_COLUMNS = ["Catégorie", "Valeur"]
_CASHFLOW_COLUMNS = ["mois", "revenus", "depenses", "epargne", "taux_epargne"]
_EPARGNE_COLUMNS = [*_CASHFLOW_COLUMNS, "mois_label"]


def _empty_alloc_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_ALLOC_COLUMNS)


def _empty_cashflow_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_CASHFLOW_COLUMNS)


def _empty_epargne_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_EPARGNE_COLUMNS)


def _normalize_cashflow_for_panel(df_cashflow: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise la série cashflow pour les usages graphiques de vue_ensemble_panel.
    """
    if df_cashflow is None or df_cashflow.empty:
        logger.info("_normalize_cashflow_for_panel: série cashflow vide")
        return _empty_cashflow_df()

    df = df_cashflow.copy()
    if "mois" not in df.columns:
        if "mois_dt" in df.columns:
            df["mois"] = pd.to_datetime(df["mois_dt"], errors="coerce").dt.strftime("%Y-%m-01")
        else:
            logger.warning(
                "_normalize_cashflow_for_panel: colonnes 'mois' et 'mois_dt' absentes"
            )
            return _empty_cashflow_df()

    for col in ["revenus", "depenses", "epargne"]:
        if col not in df.columns:
            logger.warning(
                "_normalize_cashflow_for_panel: colonne '%s' absente, remplacée par 0",
                col,
            )
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "taux_epargne" not in df.columns:
        logger.warning(
            "_normalize_cashflow_for_panel: colonne 'taux_epargne' absente, remplacée par NaN"
        )
        df["taux_epargne"] = pd.NA
    df["taux_epargne"] = pd.to_numeric(df["taux_epargne"], errors="coerce")

    return df[_CASHFLOW_COLUMNS].reset_index(drop=True)


def prepare_vue_ensemble_alloc_pie_data(metrics: dict) -> pd.DataFrame:
    """
    Prépare les données d'allocation pour le pie chart du panel Vue d'ensemble.
    """
    if not metrics:
        logger.info("prepare_vue_ensemble_alloc_pie_data: métriques absentes")
        return _empty_alloc_df()

    alloc_data = [
        {"Catégorie": "Liquidités", "Valeur": max(0.0, _sf(metrics.get("liq")))},
        {"Catégorie": "Holdings bourse", "Valeur": max(0.0, _sf(metrics.get("bourse")))},
        {"Catégorie": "Immobilier", "Valeur": max(0.0, _sf(metrics.get("immo_value")))},
        {"Catégorie": "PE", "Valeur": max(0.0, _sf(metrics.get("pe_value")))},
        {"Catégorie": "Entreprises", "Valeur": max(0.0, _sf(metrics.get("ent_value")))},
    ]
    df = pd.DataFrame([row for row in alloc_data if row["Valeur"] > 0])
    if df.empty:
        logger.info("prepare_vue_ensemble_alloc_pie_data: aucune allocation positive")
        return _empty_alloc_df()
    return df.reset_index(drop=True)


def prepare_vue_ensemble_cashflow_bar_data(
    df_cashflow: pd.DataFrame,
    months: int = 12,
) -> pd.DataFrame:
    """
    Prépare la série des barres Revenus/Dépenses sur les N derniers mois.
    """
    df = _normalize_cashflow_for_panel(df_cashflow)
    if df.empty:
        logger.info("prepare_vue_ensemble_cashflow_bar_data: série vide")
        return _empty_cashflow_df()
    return df.tail(int(months)).reset_index(drop=True)


def prepare_vue_ensemble_epargne_chart_data(df_cashflow: pd.DataFrame) -> pd.DataFrame:
    """
    Prépare la série complète pour le graphique taux d'épargne du panel.
    """
    df = _normalize_cashflow_for_panel(df_cashflow)
    if df.empty:
        logger.info("prepare_vue_ensemble_epargne_chart_data: série vide")
        return _empty_epargne_df()

    df = df.copy()
    df["mois_label"] = pd.to_datetime(df["mois"], errors="coerce").dt.strftime("%b %Y")
    return df[_EPARGNE_COLUMNS].reset_index(drop=True)


def pop_missing_fx_pairs() -> set[tuple[str, str]]:
    """
    Retourne puis purge les paires FX manquantes collectées lors des calculs marché.
    """
    from services import market_history

    missing_fx = market_history.get_and_clear_missing_fx()
    if missing_fx:
        logger.warning(
            "pop_missing_fx_pairs: %d paire(s) FX manquante(s)", len(missing_fx)
        )
    return missing_fx


def get_vue_ensemble_panel_payload(conn, person_id: int) -> dict:
    """
    Assemble le payload métier consommé par ``qt_ui/panels/vue_ensemble_panel.py``.
    """
    metrics = get_vue_ensemble_metrics(conn, person_id)
    if not metrics:
        logger.info(
            "get_vue_ensemble_panel_payload: métriques indisponibles pour person_id=%s",
            person_id,
        )
        return {}

    df_cashflow = metrics.get("df_cashflow", pd.DataFrame())
    payload = {
        "metrics": metrics,
        "alloc_df": prepare_vue_ensemble_alloc_pie_data(metrics),
        "cashflow_12m_df": prepare_vue_ensemble_cashflow_bar_data(df_cashflow, months=12),
        "epargne_df": prepare_vue_ensemble_epargne_chart_data(df_cashflow),
        "missing_fx_pairs": pop_missing_fx_pairs(),
    }
    return payload
