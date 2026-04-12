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
from services import market_history

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

def _portfolio_weekly_returns(conn, person_id: int) -> pd.DataFrame:
    """
    Série des rendements log-hebdomadaires du portefeuille.

    Retourne un DataFrame avec colonnes ['date', 'value', 'log_return'].
    Source : snapshots weekly (bourse_holdings).
    """
    series = bourse_analytics.get_bourse_weekly_series(conn, person_id)
    if series.empty or len(series) < 2:
        return pd.DataFrame(columns=["date", "value", "log_return"])

    df = series.sort_values("date").copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["holdings_eur"] > 0].copy()
    if len(df) < 2:
        return pd.DataFrame(columns=["date", "value", "log_return"])

    df["value"] = df["holdings_eur"].astype(float)
    df["log_return"] = np.log(df["value"] / df["value"].shift(1))
    df = df.dropna(subset=["log_return"])

    return df[["date", "value", "log_return"]].reset_index(drop=True)


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

    log_returns = returns_df["log_return"].values
    values = returns_df["value"].values
    dates = returns_df["date"].values

    # Rendement moyen annualisé
    mean_weekly = float(np.mean(log_returns))
    mean_annual = mean_weekly * WEEKS_PER_YEAR * 100.0

    # Volatilité annualisée
    vol_weekly = float(np.std(log_returns, ddof=1))
    vol_annual = vol_weekly * math.sqrt(WEEKS_PER_YEAR) * 100.0

    # CAGR
    cagr = _compute_cagr_from_series(values, dates)

    # Ratio de Sharpe
    sharpe = _compute_sharpe(mean_weekly, vol_weekly)

    # Max drawdown
    dd_result = _compute_max_drawdown(values, dates)

    # Beta vs benchmark
    beta = _compute_beta(conn, log_returns, dates)

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


def _compute_cagr_from_series(values: np.ndarray, dates: np.ndarray) -> float | None:
    """CAGR à partir de valeurs et dates numpy."""
    if len(values) < 2:
        return None
    first_val = float(values[0])
    last_val = float(values[-1])
    if first_val <= 0 or last_val <= 0:
        return None

    d0 = pd.Timestamp(dates[0])
    d1 = pd.Timestamp(dates[-1])
    days = (d1 - d0).days
    if days < 30:
        return None

    years = days / 365.25
    return (pow(last_val / first_val, 1.0 / years) - 1.0) * 100.0


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


def _compute_beta(
    conn, portfolio_returns: np.ndarray, dates: np.ndarray
) -> float | None:
    """
    Beta du portefeuille vs benchmark (URTH).

    β = Cov(R_portfolio, R_benchmark) / Var(R_benchmark)
    """
    if len(dates) < MIN_WEEKS_FOR_RISK:
        return None

    start_date = str(pd.Timestamp(dates[0]).date())
    end_date = str(pd.Timestamp(dates[-1]).date())

    benchmark_returns = _get_asset_weekly_returns(
        conn, [DEFAULT_BENCHMARK], start_date, end_date
    )
    if benchmark_returns.empty or DEFAULT_BENCHMARK not in benchmark_returns.columns:
        logger.info(
            "_compute_beta: benchmark '%s' non disponible, beta non calculé",
            DEFAULT_BENCHMARK,
        )
        return None

    bench_ret = benchmark_returns[DEFAULT_BENCHMARK].dropna().values

    # Aligner les longueurs
    min_len = min(len(portfolio_returns), len(bench_ret))
    if min_len < MIN_WEEKS_FOR_RISK:
        return None

    p_ret = portfolio_returns[-min_len:]
    b_ret = bench_ret[-min_len:]

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

def get_efficient_frontier_payload(conn, person_id: int) -> dict[str, Any]:
    """
    Calcule la frontière efficiente via optimisation scipy (SLSQP).

    Retourne :
    - Points de la frontière (vol, ret)
    - Position du portefeuille actuel
    - Portefeuille de variance minimale
    - Portefeuille de Sharpe maximal
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

    # Rendements et covariance annualisés
    mean_returns = ret_data.mean().values * WEEKS_PER_YEAR
    cov_matrix = ret_data.cov().values * WEEKS_PER_YEAR

    # Poids actuels (renormalisés sur les actifs disponibles)
    w_df = weights_df[weights_df["ticker"].isin(common)].copy()
    w_df = w_df.set_index("ticker").loc[common]
    current_weights = w_df["weight"].values
    current_weights = current_weights / current_weights.sum()

    # Position du portefeuille actuel
    current_ret = float(current_weights @ mean_returns) * 100
    current_vol = float(math.sqrt(current_weights @ cov_matrix @ current_weights)) * 100

    # Optimisation via scipy
    from scipy.optimize import minimize

    # Contraintes : somme des poids = 1
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    # Bornes : long-only (pas de vente à découvert)
    bounds = [(0.0, 1.0)] * n_assets
    initial_weights = np.ones(n_assets) / n_assets

    # Portefeuille de variance minimale
    min_var_result = minimize(
        lambda w: float(w @ cov_matrix @ w),
        initial_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )
    min_var_weights = min_var_result.x if min_var_result.success else initial_weights
    min_var_ret = float(min_var_weights @ mean_returns) * 100
    min_var_vol = float(math.sqrt(min_var_weights @ cov_matrix @ min_var_weights)) * 100

    # Portefeuille de Sharpe maximal (tangent portfolio)
    def neg_sharpe(w):
        ret_ann = float(w @ mean_returns)
        vol_ann = float(math.sqrt(w @ cov_matrix @ w))
        if vol_ann <= 0:
            return 1e6
        return -(ret_ann - RISK_FREE_RATE) / vol_ann

    max_sharpe_result = minimize(
        neg_sharpe,
        initial_weights,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )
    max_sharpe_weights = max_sharpe_result.x if max_sharpe_result.success else initial_weights
    max_sharpe_ret = float(max_sharpe_weights @ mean_returns) * 100
    max_sharpe_vol = float(math.sqrt(max_sharpe_weights @ cov_matrix @ max_sharpe_weights)) * 100

    # Points de la frontière (optimisation pour chaque niveau de rendement cible)
    frontier_points = _compute_frontier_points(
        mean_returns, cov_matrix, n_assets, bounds, n_points=40
    )

    return {
        "frontier_points": frontier_points,
        "current_portfolio": {
            "vol": round(current_vol, 2),
            "ret": round(current_ret, 2),
        },
        "min_variance": {
            "vol": round(min_var_vol, 2),
            "ret": round(min_var_ret, 2),
            "weights": {common[i]: round(float(min_var_weights[i]) * 100, 1) for i in range(n_assets)},
        },
        "max_sharpe": {
            "vol": round(max_sharpe_vol, 2),
            "ret": round(max_sharpe_ret, 2),
            "weights": {common[i]: round(float(max_sharpe_weights[i]) * 100, 1) for i in range(n_assets)},
        },
        "tickers": common,
    }


def _compute_frontier_points(
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    n_assets: int,
    bounds: list[tuple[float, float]],
    n_points: int = 40,
) -> list[dict[str, float]]:
    """
    Calcule les points de la frontière efficiente par optimisation.

    Pour chaque rendement cible entre min et max, on minimise la variance
    sous contrainte de rendement = cible et somme des poids = 1.
    """
    from scipy.optimize import minimize

    min_ret = float(np.min(mean_returns))
    max_ret = float(np.max(mean_returns))
    target_returns = np.linspace(min_ret, max_ret, n_points)

    points = []
    initial_weights = np.ones(n_assets) / n_assets

    for target_ret in target_returns:
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "eq", "fun": lambda w, tr=target_ret: float(w @ mean_returns) - tr},
        ]
        result = minimize(
            lambda w: float(w @ cov_matrix @ w),
            initial_weights,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
        )
        if result.success:
            vol = float(math.sqrt(result.x @ cov_matrix @ result.x)) * 100
            ret = float(result.x @ mean_returns) * 100
            points.append({"vol": round(vol, 2), "ret": round(ret, 2)})

    return points


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
