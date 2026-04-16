"""
Service d'analytics avancés pour le portefeuille bourse.

Point d'entrée unique pour les métriques avancées :
- Rendement & risque (Sharpe, volatilité, beta, drawdown)
- Corrélations & diversification
- Contribution au risque
- VaR & Expected Shortfall
- Frontière efficiente
- Comparaison benchmark

Architecture : ce module est consommé par bourse_global_panel.py.
Il s'appuie sur bourse_analytics.py et market_history.py pour les données brutes.
Aucune logique de ce fichier ne doit être dupliquée dans l'UI.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from services import bourse_analytics
from services import efficient_frontier
from services import market_history
from services import repositories as repo
from services.asset_panel_mapping import INVESTMENT_ACCOUNT_TYPES

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
RISK_FREE_RATE = 0.03       # Taux sans risque annuel (3% EUR)
MIN_WEEKS_FOR_RISK = 12     # Minimum de semaines de données pour les calculs de risque
WEEKS_PER_YEAR = 52
DEFAULT_BENCHMARK = "URTH"  # MSCI World ETF
MAX_ASSETS_CORRELATION = 15 # Nombre max d'actifs dans la matrice de corrélation


# ═════════════════════════════════════════════════════════════════════════════
# FONCTIONS INTERNES (données brutes)
# ═════════════════════════════════════════════════════════════════════════════

def _portfolio_weekly_net_flows_eur(
    conn,
    person_id: int,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Flux hebdomadaires vers les holdings bourse (EUR), alignés sur les week_date (lundi).

    Convention de signe:
    - ACHAT  -> flux positif (capital injecté dans les holdings)
    - VENTE  -> flux négatif (capital retiré des holdings)
    """
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=["date", "net_flow"])

    bourse_acc = accounts[
        accounts["account_type"].astype(str).str.upper().isin(INVESTMENT_ACCOUNT_TYPES)
    ].copy()
    if bourse_acc.empty:
        return pd.DataFrame(columns=["date", "net_flow"])

    rows: list[dict[str, Any]] = []
    start_ts = pd.Timestamp(start_date).normalize()
    end_ts = pd.Timestamp(end_date).normalize()

    for _, acc in bourse_acc.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        if tx is None or tx.empty:
            continue

        df = tx.copy()
        df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
        df = df.dropna(subset=["date"])
        df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()
        if df.empty:
            continue

        df["type"] = df.get("type", "").astype(str).str.upper()
        df = df[df["type"].isin(["ACHAT", "VENTE"])].copy()
        if df.empty:
            continue

        # Garde uniquement les ordres sur actifs du panel bourse.
        df = bourse_analytics._filter_tx_buy_sell_to_bourse_assets(conn, df)
        if df.empty:
            continue

        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)
        df["flow_native"] = np.where(
            df["type"] == "ACHAT",
            df["amount"] + df["fees"],
            -(df["amount"] - df["fees"]),
        )

        for _, tr in df.iterrows():
            flow_native = float(tr["flow_native"])
            if not math.isfinite(flow_native) or flow_native == 0.0:
                continue
            date_str = pd.Timestamp(tr["date"]).strftime("%Y-%m-%d")
            flow_eur = (
                flow_native
                if acc_ccy == "EUR"
                else market_history.convert_weekly(conn, flow_native, acc_ccy, "EUR", date_str)
            )
            if flow_eur is None:
                logger.warning(
                    "_portfolio_weekly_net_flows_eur: FX %s→EUR manquant pour tx compte=%s date=%s",
                    acc_ccy, acc_id, date_str,
                )
                continue
            week_date = pd.Timestamp(tr["date"]).to_period("W-MON").end_time.normalize()
            rows.append({"date": week_date, "net_flow": float(flow_eur)})

    if not rows:
        return pd.DataFrame(columns=["date", "net_flow"])

    out = pd.DataFrame(rows)
    out = out.groupby("date", as_index=False)["net_flow"].sum()
    out = out.sort_values("date").reset_index(drop=True)
    return out


def _portfolio_weekly_returns(conn, person_id: int) -> pd.DataFrame:
    """
    Série des rendements log-hebdomadaires cashflow-adjusted du portefeuille.

    Retourne un DataFrame avec colonnes:
    ['date', 'value', 'net_flow', 'simple_return', 'log_return'].
    """
    series = bourse_analytics.get_bourse_weekly_series(conn, person_id)
    if series.empty or len(series) < 2:
        return pd.DataFrame(columns=["date", "value", "net_flow", "simple_return", "log_return"])

    df = series.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["holdings_eur"] > 0].copy()
    if len(df) < 2:
        return pd.DataFrame(columns=["date", "value", "net_flow", "simple_return", "log_return"])

    df["date"] = df["date"].dt.normalize()
    df["value"] = pd.to_numeric(df["holdings_eur"], errors="coerce")
    df = df.dropna(subset=["value"])
    if len(df) < 2:
        return pd.DataFrame(columns=["date", "value", "net_flow", "simple_return", "log_return"])

    flows = _portfolio_weekly_net_flows_eur(
        conn,
        person_id,
        start_date=pd.Timestamp(df["date"].min()),
        end_date=pd.Timestamp(df["date"].max()),
    )
    if flows.empty:
        df["net_flow"] = 0.0
    else:
        df = df.merge(flows, on="date", how="left")
        df["net_flow"] = pd.to_numeric(df["net_flow"], errors="coerce").fillna(0.0)

    prev_value = df["value"].shift(1)
    valid = prev_value > 0
    df["simple_return"] = np.where(
        valid,
        (df["value"] - prev_value - df["net_flow"]) / prev_value,
        np.nan,
    )
    # Rendement log défini uniquement pour (1 + r) > 0.
    df.loc[df["simple_return"] <= -0.999999999, "simple_return"] = np.nan
    df["log_return"] = np.log1p(df["simple_return"])
    df = df.dropna(subset=["log_return"])

    return df[["date", "value", "net_flow", "simple_return", "log_return"]].reset_index(drop=True)


def _get_asset_weekly_returns(
    conn, tickers: list[str], start_date: str, end_date: str
) -> pd.DataFrame:
    """
    Récupère les rendements log-hebdomadaires de chaque ticker.

    Retourne un DataFrame avec une colonne par ticker et l'index = week_date.
    Les tickers sans données sont exclus avec un log warning.
    """
    all_series = {}
    for ticker in tickers:
        rows = conn.execute(
            "SELECT week_date, adj_close FROM asset_prices_weekly "
            "WHERE symbol = ? AND week_date >= ? AND week_date <= ? "
            "ORDER BY week_date ASC",
            (ticker, start_date, end_date),
        ).fetchall()

        if not rows or len(rows) < MIN_WEEKS_FOR_RISK:
            logger.warning(
                "_get_asset_weekly_returns: ticker '%s' — seulement %d points "
                "(min %d requis), exclu des calculs",
                ticker, len(rows) if rows else 0, MIN_WEEKS_FOR_RISK,
            )
            continue

        dates = [r["week_date"] for r in rows]
        prices = [float(r["adj_close"]) for r in rows]
        s = pd.Series(prices, index=pd.to_datetime(dates), name=ticker)
        s = s[s > 0]
        if len(s) < MIN_WEEKS_FOR_RISK:
            continue
        all_series[ticker] = np.log(s / s.shift(1))

    if not all_series:
        return pd.DataFrame()

    df = pd.DataFrame(all_series).dropna(how="all")
    return df


def _safe_covariance_matrix(returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Matrice de covariance nettoyée (NaN remplacés par 0, régularisation diagonale).
    """
    cov = returns_df.cov()
    cov = cov.fillna(0.0)

    # Régularisation légère pour éviter les matrices singulières
    n = len(cov)
    reg = np.eye(n) * 1e-8
    cov_values = cov.values + reg
    return pd.DataFrame(cov_values, index=cov.index, columns=cov.columns)


def _get_positions_weights(conn, person_id: int) -> pd.DataFrame:
    """
    Retourne les positions live avec poids normalisés.

    Colonnes : ['ticker', 'value_eur', 'weight']
    """
    positions = bourse_analytics.get_live_bourse_positions(conn, person_id)
    if positions.empty or "value" not in positions.columns:
        return pd.DataFrame(columns=["ticker", "value_eur", "weight"])

    df = positions[positions["value"] > 0].copy()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "value_eur", "weight"])

    grouped = df.groupby("symbol", as_index=False)["value"].sum()
    grouped = grouped.rename(columns={"symbol": "ticker", "value": "value_eur"})
    total = grouped["value_eur"].sum()
    grouped["weight"] = grouped["value_eur"] / total if total > 0 else 0.0
    grouped = grouped.sort_values("value_eur", ascending=False).reset_index(drop=True)

    return grouped


def _error_payload(message: str) -> dict[str, Any]:
    """Payload d'erreur standardisé."""
    return {"error": message}


# ═════════════════════════════════════════════════════════════════════════════
# 1. RENDEMENT & RISQUE
# ═════════════════════════════════════════════════════════════════════════════

def get_risk_return_payload(conn, person_id: int) -> dict[str, Any]:
    """
    Calcule les métriques rendement/risque du portefeuille.

    Métriques :
    - Rendement moyen annualisé
    - CAGR
    - Volatilité annualisée (σ_weekly × √52)
    - Beta vs benchmark (URTH)
    - Ratio de Sharpe
    - Max drawdown (% + dates + durée de récupération)

    Retourne un dict prêt à consommer par l'UI.
    """
    returns_df = _portfolio_weekly_returns(conn, person_id)
    if returns_df.empty or len(returns_df) < MIN_WEEKS_FOR_RISK:
        n_points = len(returns_df) if not returns_df.empty else 0
        logger.warning(
            "get_risk_return_payload: seulement %d points (min %d requis) "
            "pour person_id=%s",
            n_points, MIN_WEEKS_FOR_RISK, person_id,
        )
        return _error_payload(
            f"Historique insuffisant ({n_points} semaines, minimum {MIN_WEEKS_FOR_RISK})"
        )

    log_returns = returns_df["log_return"].astype(float).values
    dates = returns_df["date"].values

    # Rendement moyen annualisé
    mean_weekly = float(np.mean(log_returns))
    mean_annual = mean_weekly * WEEKS_PER_YEAR * 100.0

    # Volatilité annualisée
    vol_weekly = float(np.std(log_returns, ddof=1))
    vol_annual = vol_weekly * math.sqrt(WEEKS_PER_YEAR) * 100.0

    # CAGR (annualisation du TWR)
    cagr = _compute_cagr_from_log_returns(log_returns, dates)

    # Ratio de Sharpe
    sharpe = _compute_sharpe(mean_weekly, vol_weekly)

    # Max drawdown sur l'indice de performance cashflow-adjusted
    twr_index = np.exp(np.cumsum(log_returns))
    dd_result = _compute_max_drawdown(twr_index, dates)

    # Beta vs benchmark
    beta = _compute_beta(conn, returns_df[["date", "log_return"]])

    period_start = str(pd.Timestamp(dates[0]).date())
    period_end = str(pd.Timestamp(dates[-1]).date())

    return {
        "mean_return_ann_pct": round(mean_annual, 2),
        "cagr_pct": round(cagr, 2) if cagr is not None else None,
        "volatility_ann_pct": round(vol_annual, 2),
        "beta": round(beta, 3) if beta is not None else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown_pct": round(dd_result["max_dd_pct"], 2),
        "drawdown_start": dd_result.get("dd_start"),
        "drawdown_end": dd_result.get("dd_end"),
        "recovery_date": dd_result.get("recovery_date"),
        "recovery_days": dd_result.get("recovery_days"),
        "data_points": len(log_returns),
        "period_start": period_start,
        "period_end": period_end,
    }


def _compute_cagr_from_log_returns(log_returns: np.ndarray, dates: np.ndarray) -> float | None:
    """CAGR annualisé à partir d'une série de rendements log cashflow-adjusted."""
    if len(log_returns) < 2:
        return None

    d0 = pd.Timestamp(dates[0])
    d1 = pd.Timestamp(dates[-1])
    days = (d1 - d0).days
    if days < 30:
        return None

    years = days / 365.25
    cum_log = float(np.sum(log_returns))
    return (math.exp(cum_log / years) - 1.0) * 100.0


def _compute_sharpe(mean_weekly_log: float, vol_weekly: float) -> float | None:
    """Ratio de Sharpe annualisé. Rf = RISK_FREE_RATE."""
    if vol_weekly <= 0:
        return None
    mean_annual = mean_weekly_log * WEEKS_PER_YEAR
    vol_annual = vol_weekly * math.sqrt(WEEKS_PER_YEAR)
    return (mean_annual - RISK_FREE_RATE) / vol_annual


def _compute_max_drawdown(values: np.ndarray, dates: np.ndarray) -> dict:
    """
    Calcule le max drawdown, ses dates et la durée de récupération.
    """
    cummax = np.maximum.accumulate(values)
    drawdowns = (values - cummax) / cummax

    max_dd_idx = int(np.argmin(drawdowns))
    max_dd_pct = float(drawdowns[max_dd_idx]) * 100.0

    result: dict[str, Any] = {"max_dd_pct": max_dd_pct}
    if max_dd_pct >= 0:
        return result

    # Date du pic avant le drawdown
    peak_idx = int(np.argmax(values[:max_dd_idx + 1]))
    result["dd_start"] = str(pd.Timestamp(dates[peak_idx]).date())
    result["dd_end"] = str(pd.Timestamp(dates[max_dd_idx]).date())

    # Chercher la récupération (première date après le trough où valeur >= pic)
    peak_value = values[peak_idx]
    recovery_idx = None
    for i in range(max_dd_idx + 1, len(values)):
        if values[i] >= peak_value:
            recovery_idx = i
            break

    if recovery_idx is not None:
        result["recovery_date"] = str(pd.Timestamp(dates[recovery_idx]).date())
        recovery_days = (pd.Timestamp(dates[recovery_idx]) - pd.Timestamp(dates[max_dd_idx])).days
        result["recovery_days"] = int(recovery_days)
    else:
        result["recovery_date"] = None
        result["recovery_days"] = None

    return result


def _compute_beta(conn, portfolio_returns_df: pd.DataFrame) -> float | None:
    """
    Beta du portefeuille vs benchmark (URTH).

    β = Cov(R_portfolio, R_benchmark) / Var(R_benchmark)
    """
    if portfolio_returns_df is None or portfolio_returns_df.empty:
        return None

    df = portfolio_returns_df.copy()
    if "date" not in df.columns or "log_return" not in df.columns:
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["log_return"] = pd.to_numeric(df["log_return"], errors="coerce")
    df = df.dropna(subset=["date", "log_return"])
    if len(df) < MIN_WEEKS_FOR_RISK:
        return None

    start_date = str(df["date"].min().date())
    end_date = str(df["date"].max().date())

    benchmark_returns = _get_asset_weekly_returns(
        conn, [DEFAULT_BENCHMARK], start_date, end_date
    )
    if benchmark_returns.empty or DEFAULT_BENCHMARK not in benchmark_returns.columns:
        logger.info(
            "_compute_beta: benchmark '%s' non disponible, beta non calculé",
            DEFAULT_BENCHMARK,
        )
        return None

    aligned = pd.DataFrame({
        "portfolio": df.set_index("date")["log_return"],
        "benchmark": benchmark_returns[DEFAULT_BENCHMARK],
    }).dropna()
    if len(aligned) < MIN_WEEKS_FOR_RISK:
        return None

    p_ret = aligned["portfolio"].values
    b_ret = aligned["benchmark"].values

    var_bench = float(np.var(b_ret, ddof=1))
    if var_bench <= 0:
        return None

    cov_pb = float(np.cov(p_ret, b_ret, ddof=1)[0, 1])
    return cov_pb / var_bench


# ═════════════════════════════════════════════════════════════════════════════
# 2. CORRÉLATIONS & DIVERSIFICATION
# ═════════════════════════════════════════════════════════════════════════════

def get_correlation_payload(conn, person_id: int) -> dict[str, Any]:
    """
    Matrice de corrélation des actifs du portefeuille et indicateurs de diversification.

    Limité aux top MAX_ASSETS_CORRELATION actifs par poids pour lisibilité.
    Corrélation de Pearson sur rendements log-weekly.
    """
    weights_df = _get_positions_weights(conn, person_id)
    if weights_df.empty or len(weights_df) < 2:
        return _error_payload("Au moins 2 actifs requis pour la matrice de corrélation")

    top_tickers = weights_df.head(MAX_ASSETS_CORRELATION)["ticker"].tolist()

    # Plage de dates depuis les snapshots
    returns_ptf = _portfolio_weekly_returns(conn, person_id)
    if returns_ptf.empty or len(returns_ptf) < MIN_WEEKS_FOR_RISK:
        return _error_payload("Historique portefeuille insuffisant")

    start_date = str(returns_ptf["date"].min().date())
    end_date = str(returns_ptf["date"].max().date())

    returns_df = _get_asset_weekly_returns(conn, top_tickers, start_date, end_date)
    if returns_df.empty or len(returns_df.columns) < 2:
        return _error_payload(
            f"Données de prix insuffisantes (seul {len(returns_df.columns)} actif(s) avec historique)"
        )

    # Matrice de corrélation
    corr_matrix = returns_df.corr()

    # Top paires les plus corrélées (hors diagonale)
    top_pairs = _extract_top_correlated_pairs(corr_matrix, n=5)

    # Corrélation moyenne (hors diagonale)
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool), k=1)
    avg_corr = float(corr_matrix.values[mask].mean()) if mask.any() else 0.0

    # Ratio de diversification
    div_ratio = _compute_diversification_ratio(conn, returns_df, weights_df)

    return {
        "matrix": corr_matrix,
        "tickers": list(returns_df.columns),
        "top_correlated_pairs": top_pairs,
        "avg_correlation": round(avg_corr, 3),
        "diversification_ratio": round(div_ratio, 3) if div_ratio else None,
        "n_assets": len(returns_df.columns),
    }


def _extract_top_correlated_pairs(
    corr_matrix: pd.DataFrame, n: int = 5
) -> list[tuple[str, str, float]]:
    """Extrait les N paires les plus corrélées (hors diagonale)."""
    pairs = []
    cols = corr_matrix.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = float(corr_matrix.iloc[i, j])
            if not math.isnan(val):
                pairs.append((cols[i], cols[j], round(val, 3)))
    pairs.sort(key=lambda x: abs(x[2]), reverse=True)
    return pairs[:n]


def _compute_diversification_ratio(
    conn, returns_df: pd.DataFrame, weights_df: pd.DataFrame
) -> float | None:
    """
    Ratio de diversification = σ_pondéré / σ_portefeuille.

    σ_pondéré = somme(w_i × σ_i)
    σ_portefeuille = sqrt(w' Σ w)
    Un ratio > 1 indique que la diversification réduit le risque.
    """
    common = list(set(returns_df.columns) & set(weights_df["ticker"].tolist()))
    if len(common) < 2:
        return None

    w_df = weights_df[weights_df["ticker"].isin(common)].copy()
    w_df = w_df.set_index("ticker").loc[common]
    weights = w_df["weight"].values
    weights = weights / weights.sum()  # Renormaliser

    ret = returns_df[common]
    stds = ret.std().values
    cov = ret.cov().values

    weighted_vol = float(np.dot(weights, stds))
    portfolio_var = float(weights @ cov @ weights)
    portfolio_vol = math.sqrt(max(portfolio_var, 0))

    if portfolio_vol <= 0:
        return None
    return weighted_vol / portfolio_vol


# ═════════════════════════════════════════════════════════════════════════════
# 3. CONTRIBUTION AU RISQUE
# ═════════════════════════════════════════════════════════════════════════════

def get_risk_contribution_payload(conn, person_id: int) -> dict[str, Any]:
    """
    Contribution de chaque actif au risque total du portefeuille.

    Risk Contribution_i = w_i × (Σw)_i / σ²_portfolio
    MCTR_i = (Σw)_i / σ_portfolio
    """
    weights_df = _get_positions_weights(conn, person_id)
    if weights_df.empty or len(weights_df) < 2:
        return _error_payload("Au moins 2 actifs requis pour la contribution au risque")

    top_tickers = weights_df.head(MAX_ASSETS_CORRELATION)["ticker"].tolist()

    returns_ptf = _portfolio_weekly_returns(conn, person_id)
    if returns_ptf.empty or len(returns_ptf) < MIN_WEEKS_FOR_RISK:
        return _error_payload("Historique portefeuille insuffisant")

    start_date = str(returns_ptf["date"].min().date())
    end_date = str(returns_ptf["date"].max().date())

    returns_df = _get_asset_weekly_returns(conn, top_tickers, start_date, end_date)
    if returns_df.empty or len(returns_df.columns) < 2:
        return _error_payload("Données de prix insuffisantes pour la contribution au risque")

    common = list(set(returns_df.columns) & set(weights_df["ticker"].tolist()))
    if len(common) < 2:
        return _error_payload("Pas assez d'actifs avec historique commun")

    w_df = weights_df[weights_df["ticker"].isin(common)].copy()
    w_df = w_df.set_index("ticker").loc[common]
    weights = w_df["weight"].values
    weights = weights / weights.sum()

    cov = _safe_covariance_matrix(returns_df[common])
    cov_values = cov.values

    # σ²_portfolio = w' Σ w
    portfolio_var = float(weights @ cov_values @ weights)
    portfolio_vol = math.sqrt(max(portfolio_var, 0))

    if portfolio_var <= 0:
        return _error_payload("Variance du portefeuille nulle")

    # Sigma × w
    sigma_w = cov_values @ weights

    # Risk contribution = w_i × (Σw)_i / σ²_portfolio
    risk_contrib = (weights * sigma_w) / portfolio_var
    # MCTR = (Σw)_i / σ_portfolio
    mctr = sigma_w / portfolio_vol if portfolio_vol > 0 else sigma_w * 0

    rows = []
    for i, ticker in enumerate(common):
        rows.append({
            "ticker": ticker,
            "weight_pct": round(float(weights[i]) * 100, 2),
            "risk_contrib_pct": round(float(risk_contrib[i]) * 100, 2),
            "mctr": round(float(mctr[i]) * 100, 4),
        })

    contrib_df = pd.DataFrame(rows).sort_values("risk_contrib_pct", ascending=False)
    contrib_df["rank"] = range(1, len(contrib_df) + 1)

    return {
        "contributions": contrib_df.reset_index(drop=True),
        "portfolio_vol_weekly_pct": round(portfolio_vol * 100, 4),
        "portfolio_vol_ann_pct": round(portfolio_vol * math.sqrt(WEEKS_PER_YEAR) * 100, 2),
    }


# ═════════════════════════════════════════════════════════════════════════════
# 4. VaR & EXPECTED SHORTFALL
# ═════════════════════════════════════════════════════════════════════════════

def get_var_es_payload(conn, person_id: int) -> dict[str, Any]:
    """
    Value at Risk et Expected Shortfall du portefeuille.

    Méthode primaire : historique (percentile des rendements weekly observés).
    Méthode secondaire : paramétrique (hypothèse normale).

    Les montants en EUR sont basés sur la valeur actuelle du portefeuille.
    """
    returns_df = _portfolio_weekly_returns(conn, person_id)
    if returns_df.empty or len(returns_df) < MIN_WEEKS_FOR_RISK:
        n_pts = len(returns_df) if not returns_df.empty else 0
        return _error_payload(
            f"Historique insuffisant ({n_pts} semaines, minimum {MIN_WEEKS_FOR_RISK})"
        )

    log_returns = returns_df["log_return"].values
    current_value = float(returns_df["value"].iloc[-1])

    # ── Méthode historique ──
    var_95_hist = float(np.percentile(log_returns, 5))
    var_99_hist = float(np.percentile(log_returns, 1))

    # Expected Shortfall (moyenne des pertes au-delà de la VaR)
    es_95_hist = float(np.mean(log_returns[log_returns <= var_95_hist]))
    tail_99 = log_returns[log_returns <= var_99_hist]
    es_99_hist = float(np.mean(tail_99)) if len(tail_99) > 0 else var_99_hist

    # ── Méthode paramétrique (normale) ──
    mu = float(np.mean(log_returns))
    sigma = float(np.std(log_returns, ddof=1))

    from scipy import stats
    var_95_param = mu + stats.norm.ppf(0.05) * sigma
    var_99_param = mu + stats.norm.ppf(0.01) * sigma

    # Annualisation pour l'affichage en EUR (VaR weekly × valeur portfolio)
    var_95_eur = abs(var_95_hist) * current_value
    var_99_eur = abs(var_99_hist) * current_value

    return {
        "var_95_pct": round(abs(var_95_hist) * 100, 2),
        "var_99_pct": round(abs(var_99_hist) * 100, 2),
        "es_95_pct": round(abs(es_95_hist) * 100, 2),
        "es_99_pct": round(abs(es_99_hist) * 100, 2),
        "var_95_eur": round(var_95_eur, 0),
        "var_99_eur": round(var_99_eur, 0),
        "var_95_param_pct": round(abs(float(var_95_param)) * 100, 2),
        "var_99_param_pct": round(abs(float(var_99_param)) * 100, 2),
        "method": "historique",
        "method_secondary": "paramétrique (normale)",
        "n_observations": len(log_returns),
        "portfolio_value_eur": round(current_value, 2),
        "horizon": "1 semaine",
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. FRONTIÈRE EFFICIENTE
# ═════════════════════════════════════════════════════════════════════════════

def get_efficient_frontier_presets_payload() -> dict[str, Any]:
    """Expose les presets de diversification pour l'UI."""
    return {"presets": efficient_frontier.list_frontier_presets()}


def get_efficient_frontier_payload(
    conn,
    person_id: int,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Calcule la frontière efficiente avec contraintes de diversification.

    Retourne :
    - Points de la frontière (vol, ret)
    - Position du portefeuille actuel
    - Portefeuille de variance minimale
    - Portefeuille de Sharpe maximal
    - Métriques de diversification/concentration
    """
    weights_df = _get_positions_weights(conn, person_id)
    if weights_df.empty or len(weights_df) < 2:
        return _error_payload("Au moins 2 actifs requis pour la frontière efficiente")

    top_tickers = weights_df.head(MAX_ASSETS_CORRELATION)["ticker"].tolist()

    returns_ptf = _portfolio_weekly_returns(conn, person_id)
    if returns_ptf.empty or len(returns_ptf) < MIN_WEEKS_FOR_RISK:
        return _error_payload("Historique portefeuille insuffisant")

    start_date = str(returns_ptf["date"].min().date())
    end_date = str(returns_ptf["date"].max().date())

    returns_df = _get_asset_weekly_returns(conn, top_tickers, start_date, end_date)
    if returns_df.empty or len(returns_df.columns) < 2:
        return _error_payload("Données de prix insuffisantes pour la frontière efficiente")

    common = list(set(returns_df.columns) & set(weights_df["ticker"].tolist()))
    if len(common) < 2:
        return _error_payload("Pas assez d'actifs avec historique commun")

    ret_data = returns_df[common].dropna()
    n_assets = len(common)

    if n_assets < 2:
        return _error_payload("Pas assez d'actifs exploitables pour l'optimisation")

    # Rendements et covariance annualisés
    mean_returns = ret_data.mean().values.astype(float) * WEEKS_PER_YEAR
    cov_matrix = ret_data.cov().values.astype(float) * WEEKS_PER_YEAR

    # Poids actuels (renormalisés sur les actifs disponibles)
    w_df = weights_df[weights_df["ticker"].isin(common)].copy()
    w_df = w_df.set_index("ticker").loc[common]
    current_weights = w_df["weight"].values.astype(float)
    current_weights = current_weights / current_weights.sum()

    # Position du portefeuille actuel
    current_ret = float(current_weights @ mean_returns) * 100
    current_vol = float(math.sqrt(current_weights @ cov_matrix @ current_weights)) * 100

    constraints, warnings, errors = efficient_frontier.build_constraints_from_settings(
        settings=settings,
        n_assets=n_assets,
    )
    if errors:
        return _error_payload(" ".join(errors))

    optimized = efficient_frontier.optimize_efficient_frontier(
        mean_returns=mean_returns,
        cov_matrix=cov_matrix,
        tickers=common,
        risk_free_rate=RISK_FREE_RATE,
        constraints=constraints,
        current_weights=current_weights,
    )
    if "error" in optimized:
        return _error_payload(optimized["error"])

    return {
        "frontier_points": optimized.get("frontier_points", []),
        "current_portfolio": {
            "vol": round(current_vol, 2),
            "ret": round(current_ret, 2),
        },
        "min_variance": {
            "vol": optimized["min_variance"]["volatility_ann_pct"],
            "ret": optimized["min_variance"]["return_ann_pct"],
            "sharpe": optimized["min_variance"]["sharpe"],
            "weights": optimized["min_variance"]["weights"],
            "diversification": optimized["min_variance"]["diversification"],
        },
        "max_sharpe": {
            "vol": optimized["max_sharpe"]["volatility_ann_pct"],
            "ret": optimized["max_sharpe"]["return_ann_pct"],
            "sharpe": optimized["max_sharpe"]["sharpe"],
            "weights": optimized["max_sharpe"]["weights"],
            "diversification": optimized["max_sharpe"]["diversification"],
        },
        "constraints_applied": optimized.get("constraints_applied", {}),
        "warnings": warnings + optimized.get("warnings", []),
        "tickers": common,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 6. COMPARAISON BENCHMARK
# ═════════════════════════════════════════════════════════════════════════════

def get_benchmark_comparison_payload(
    conn, person_id: int, benchmark_symbol: str = DEFAULT_BENCHMARK
) -> dict[str, Any]:
    """
    Compare le rendement et la volatilité du portefeuille vs un benchmark.

    Retourne une série normalisée (base 100) et des KPIs comparatifs.
    """
    returns_ptf = _portfolio_weekly_returns(conn, person_id)
    if returns_ptf.empty or len(returns_ptf) < MIN_WEEKS_FOR_RISK:
        return _error_payload("Historique portefeuille insuffisant")

    start_date = str(returns_ptf["date"].min().date())
    end_date = str(returns_ptf["date"].max().date())

    # Récupérer les prix benchmark
    bench_returns = _get_asset_weekly_returns(conn, [benchmark_symbol], start_date, end_date)
    if bench_returns.empty or benchmark_symbol not in bench_returns.columns:
        logger.info(
            "get_benchmark_comparison_payload: benchmark '%s' non disponible en base. "
            "Vérifier que les prix sont synchronisés dans asset_prices_weekly.",
            benchmark_symbol,
        )
        return _error_payload(
            f"Benchmark '{benchmark_symbol}' non disponible. "
            f"Vérifier la synchronisation des prix hebdomadaires."
        )

    # Aligner les deux séries
    ptf_series = returns_ptf.set_index("date")["log_return"]
    bench_series = bench_returns[benchmark_symbol]

    aligned = pd.DataFrame({
        "portfolio": ptf_series,
        "benchmark": bench_series,
    }).dropna()

    if len(aligned) < MIN_WEEKS_FOR_RISK:
        return _error_payload("Période commune insuffisante entre portefeuille et benchmark")

    # Métriques
    ptf_ret_ann = float(aligned["portfolio"].mean()) * WEEKS_PER_YEAR * 100
    bench_ret_ann = float(aligned["benchmark"].mean()) * WEEKS_PER_YEAR * 100
    ptf_vol_ann = float(aligned["portfolio"].std(ddof=1)) * math.sqrt(WEEKS_PER_YEAR) * 100
    bench_vol_ann = float(aligned["benchmark"].std(ddof=1)) * math.sqrt(WEEKS_PER_YEAR) * 100

    # Alpha (excès de rendement vs benchmark)
    alpha = ptf_ret_ann - bench_ret_ann

    # Tracking error (volatilité de la différence)
    diff = aligned["portfolio"] - aligned["benchmark"]
    tracking_error = float(diff.std(ddof=1)) * math.sqrt(WEEKS_PER_YEAR) * 100

    # Série normalisée base 100
    ptf_cumul = np.exp(aligned["portfolio"].cumsum())
    bench_cumul = np.exp(aligned["benchmark"].cumsum())

    norm_series = pd.DataFrame({
        "date": aligned.index,
        "portfolio_norm": (ptf_cumul / ptf_cumul.iloc[0] * 100).round(2).values,
        "benchmark_norm": (bench_cumul / bench_cumul.iloc[0] * 100).round(2).values,
    })

    return {
        "portfolio_return_ann_pct": round(ptf_ret_ann, 2),
        "benchmark_return_ann_pct": round(bench_ret_ann, 2),
        "portfolio_vol_ann_pct": round(ptf_vol_ann, 2),
        "benchmark_vol_ann_pct": round(bench_vol_ann, 2),
        "alpha_pct": round(alpha, 2),
        "tracking_error_pct": round(tracking_error, 2),
        "benchmark_symbol": benchmark_symbol,
        "series": norm_series,
        "n_weeks": len(aligned),
    }
