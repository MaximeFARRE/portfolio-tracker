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
    try:
        rows = conn.execute(
            "SELECT * FROM patrimoine_snapshots_weekly "
            "WHERE person_id = ? ORDER BY week_date",
            (person_id,),
        ).fetchall()
        df_snap = pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: lecture snapshots échouée : %s", exc)
        df_snap = pd.DataFrame()

    if df_snap.empty:
        return m

    # Valeurs courantes par défaut (avant parsing date, pour robustesse).
    last = df_snap.iloc[-1]
    m["net"] = _sf(last.get("patrimoine_net"))
    m["brut"] = _sf(last.get("patrimoine_brut"))
    m["liq"] = _sf(last.get("liquidites_total"))
    m["bourse"] = _sf(last.get("bourse_holdings"))
    m["credits"] = _sf(last.get("credits_remaining"))
    m["pe_value"] = _sf(last.get("pe_value"))
    m["ent_value"] = _sf(last.get("ent_value"))
    m["immo_value"] = _sf(last.get("immobilier_value"))
    m["week_date"] = str(last.get("week_date", "—"))
    m["asof_date"] = m["week_date"]

    # ── 2. Patrimoine net historique ──────────────────────────────────────
    anchor_dt = None
    try:
        df_snap["_dt"] = pd.to_datetime(df_snap["week_date"], errors="coerce")
        df_snap = df_snap.dropna(subset=["_dt"]).sort_values("_dt")
        if df_snap.empty:
            return m

        last = df_snap.iloc[-1]
        anchor_dt = pd.Timestamp(last["_dt"])
        m["net"] = _sf(last.get("patrimoine_net"))
        m["brut"] = _sf(last.get("patrimoine_brut"))
        m["liq"] = _sf(last.get("liquidites_total"))
        m["bourse"] = _sf(last.get("bourse_holdings"))
        m["credits"] = _sf(last.get("credits_remaining"))
        m["pe_value"] = _sf(last.get("pe_value"))
        m["ent_value"] = _sf(last.get("ent_value"))
        m["immo_value"] = _sf(last.get("immobilier_value"))
        m["week_date"] = str(last.get("week_date", "—"))
        m["asof_date"] = anchor_dt.date().isoformat()

        def _hist_net(weeks_back: int) -> float | None:
            target = anchor_dt - pd.Timedelta(weeks=weeks_back)
            past = df_snap[df_snap["_dt"] <= target]
            return _opt(past.iloc[-1]["patrimoine_net"]) if not past.empty else None

        m["net_13w"] = _hist_net(13)
        m["net_52w"] = _hist_net(52)
        m["df_snap"] = df_snap  # pour le graphique ligne dans le panel
    except Exception as exc:
        logger.warning("get_vue_ensemble_metrics: historique net échoué : %s", exc)
        m["net_13w"] = None
        m["net_52w"] = None

    # ── 3. Cashflow mensuel (12 mois) ─────────────────────────────────────
    try:
        from services.revenus_repository import compute_taux_epargne_mensuel
        df_cf = compute_taux_epargne_mensuel(
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
        last12 = df_cf.tail(12)
        m["epargne_12m"]       = float(last12["epargne"].sum())
        m["depenses_moy_12m"]  = float(last12["depenses"].mean())
        m["capacite_epargne_avg"] = float(last12["epargne"].mean())
        rev_sum_12m = float(last12["revenus"].sum())
        m["taux_epargne_avg"] = (
            (m["epargne_12m"] / rev_sum_12m * 100) if rev_sum_12m > 0 else None
        )
    else:
        m["epargne_12m"]          = None
        m["depenses_moy_12m"]     = None
        m["capacite_epargne_avg"] = None
        m["taux_epargne_avg"]     = None

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
