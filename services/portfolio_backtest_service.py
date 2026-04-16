"""
Service metier: backtest theorique du portefeuille actuel vs benchmark.

Mode implemente:
- on prend les poids actuels du portefeuille live
- on reconstruit une courbe historique theorique
- on compare au benchmark sur historique commun strict
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from services import bourse_analytics
from services.bourse_advanced_analytics import DEFAULT_BENCHMARK, RISK_FREE_RATE

logger = logging.getLogger(__name__)

SUPPORTED_HORIZONS: dict[str, int | None] = {
    "5y": 5,
    "10y": 10,
    "15y": 15,
    "20y": 20,
    "max": None,
}
MIN_POINTS = 2
DEFAULT_HORIZON = "10y"
DIAG_STRONG_CONTRIBUTION_PCT = 0.5
DIAG_SHARPE_DELTA_STRONG = 0.10
DIAG_RETURN_DELTA_PCT = 0.20
DIAG_DIVERSIFYING_CORR_MAX = 0.60
DIAG_CONCENTRATION_WEIGHT_HIGH = 0.35
DIAG_CONCENTRATION_WEIGHT_MEDIUM = 0.20
DIAG_CORR_CONCENTRATED_MIN = 0.85

IMPROVED_MIN_WEIGHT = 0.02
IMPROVED_MAX_WEIGHT = 0.15
IMPROVED_MAX_ASSETS_BY_MIN = int(1.0 / IMPROVED_MIN_WEIGHT)
IMPROVED_MIN_ASSETS_FOR_MAX = int(math.ceil(1.0 / IMPROVED_MAX_WEIGHT))
IMPROVED_MAX_TURNOVER = 0.25


@dataclass(frozen=True)
class SeriesMetrics:
    cumulative_performance_pct: float | None
    annualized_return_pct: float | None
    annualized_volatility_pct: float | None
    max_drawdown_pct: float | None
    sharpe: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "cumulative_performance_pct": self.cumulative_performance_pct,
            "annualized_return_pct": self.annualized_return_pct,
            "annualized_volatility_pct": self.annualized_volatility_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe": self.sharpe,
        }


@dataclass(frozen=True)
class RelativeMetrics:
    cumulative_excess_performance_pct: float | None
    annualized_excess_return_pct: float | None
    tracking_error_pct: float | None
    information_ratio: float | None
    beta: float | None
    alpha_pct: float | None
    correlation: float | None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "cumulative_excess_performance_pct": self.cumulative_excess_performance_pct,
            "annualized_excess_return_pct": self.annualized_excess_return_pct,
            "tracking_error_pct": self.tracking_error_pct,
            "information_ratio": self.information_ratio,
            "beta": self.beta,
            "alpha_pct": self.alpha_pct,
            "correlation": self.correlation,
        }


def build_current_portfolio_backtest(
    conn,
    person_id: int,
    horizon: str = DEFAULT_HORIZON,
    benchmark_symbol: str = DEFAULT_BENCHMARK,
    risk_free_rate: float = RISK_FREE_RATE,
    ignore_limiting_assets: bool = False,
) -> dict[str, Any]:
    """
    Construit un backtest theorique du portefeuille actuel vs benchmark.

    Retour:
      - series portefeuille/benchmark (base 100)
      - metriques portefeuille, benchmark et relatives
      - metadata pour UI (horizon, historique reel, actifs retenus/ignores, etc.)
    """
    horizon_key, horizon_years = _normalize_horizon(horizon)
    benchmark = (benchmark_symbol or DEFAULT_BENCHMARK).upper().strip()

    logger.info(
        "build_current_portfolio_backtest: person_id=%s horizon=%s benchmark=%s ignore_limiting_assets=%s",
        person_id, horizon_key, benchmark, bool(ignore_limiting_assets),
    )

    weights_df, ignored_assets = _load_current_weights(conn, person_id)
    if weights_df.empty:
        return _error_payload(
            "Aucune position bourse valorisee pour construire le backtest.",
            horizon_key=horizon_key,
            benchmark=benchmark,
        )

    all_symbols = weights_df["symbol"].tolist() + [benchmark]
    prices_df = _load_weekly_prices(conn, all_symbols)

    retained_weights, ignored_history = _filter_assets_with_history(weights_df, prices_df)
    ignored_assets.extend(ignored_history)
    if retained_weights.empty:
        return _error_payload(
            "Aucun actif du portefeuille avec historique weekly exploitable.",
            horizon_key=horizon_key,
            benchmark=benchmark,
            ignored_assets=ignored_assets,
        )

    ignored_limiting_assets: list[str] = []
    if bool(ignore_limiting_assets) and horizon_years is not None:
        retained_weights, ignored_limiting_assets = _drop_limiting_assets_for_horizon(
            retained_weights=retained_weights,
            prices_df=prices_df,
            benchmark_symbol=benchmark,
            horizon_years=int(horizon_years),
        )
        if ignored_limiting_assets:
            logger.info(
                "build_current_portfolio_backtest: ignored limiting assets to extend horizon: %s",
                ",".join(ignored_limiting_assets),
            )
            ignored_assets.extend(
                {
                    "symbol": symbol,
                    "reason": "ignored_limiting_asset_for_horizon",
                }
                for symbol in ignored_limiting_assets
            )
        if retained_weights.empty:
            return _error_payload(
                "Aucun actif restant apres exclusion des actifs limitants.",
                horizon_key=horizon_key,
                benchmark=benchmark,
                ignored_assets=ignored_assets,
            )

    common_frame, history_bounds, error = _build_common_history_frame(
        prices_df=prices_df,
        asset_symbols=retained_weights["symbol"].tolist(),
        benchmark_symbol=benchmark,
    )
    if error is not None:
        return _error_payload(
            error,
            horizon_key=horizon_key,
            benchmark=benchmark,
            assets_retained=retained_weights["symbol"].tolist(),
            ignored_assets=ignored_assets,
        )

    selected_frame = _apply_horizon(common_frame, horizon_years)
    if len(selected_frame) < MIN_POINTS:
        return _error_payload(
            "Historique commun insuffisant pour calculer le backtest.",
            horizon_key=horizon_key,
            benchmark=benchmark,
            assets_retained=retained_weights["symbol"].tolist(),
            ignored_assets=ignored_assets,
        )

    weights = retained_weights.set_index("symbol")["weight"]
    weights = weights / weights.sum()

    portfolio_level = _build_portfolio_level(selected_frame, weights.index.tolist(), weights)
    benchmark_level = _normalize_to_one(selected_frame[benchmark])

    periods_per_year = _infer_periods_per_year(selected_frame.index)
    portfolio_metrics = _compute_series_metrics(
        level_series=portfolio_level,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )
    benchmark_metrics = _compute_series_metrics(
        level_series=benchmark_level,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )
    relative_metrics = _compute_relative_metrics(
        portfolio_level=portfolio_level,
        benchmark_level=benchmark_level,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )
    asset_diagnostics, asset_diagnostic_meta = _build_asset_diagnostics(
        selected_frame=selected_frame,
        weights=weights,
        retained_weights=retained_weights,
        benchmark_symbol=benchmark,
        portfolio_level=portfolio_level,
        benchmark_level=benchmark_level,
        portfolio_metrics=portfolio_metrics,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )
    improved_portfolio = _build_improved_portfolio_payload(
        retained_weights=retained_weights,
        selected_frame=selected_frame,
        benchmark_symbol=benchmark,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
        base_metrics=portfolio_metrics,
        asset_diagnostics=asset_diagnostics,
    )

    history_limits = {
        **_detect_history_limiters(history_bounds),
        "ignore_limiting_assets_enabled": bool(ignore_limiting_assets and horizon_years is not None),
        "ignored_limiting_assets": ignored_limiting_assets,
    }
    effective_years = _compute_period_years(selected_frame.index)
    requested_years = horizon_years

    assets_retained_payload = []
    for _, row in retained_weights.iterrows():
        symbol = str(row["symbol"])
        bounds = history_bounds.get(symbol, {})
        assets_retained_payload.append(
            {
                "symbol": symbol,
                "name": row.get("name"),
                "value_eur": round(float(row["value_eur"]), 2),
                "weight_pct": round(float(row["weight"]) * 100.0, 4),
                "history_start": bounds.get("start"),
                "history_end": bounds.get("end"),
                "history_points": bounds.get("n_points"),
            }
        )

    series_df = pd.DataFrame(
        {
            "date": selected_frame.index,
            "portfolio_norm": (portfolio_level / portfolio_level.iloc[0] * 100.0).values,
            "benchmark_norm": (benchmark_level / benchmark_level.iloc[0] * 100.0).values,
        }
    )

    full_start = common_frame.index.min()
    full_end = common_frame.index.max()
    selected_start = selected_frame.index.min()
    selected_end = selected_frame.index.max()

    summary = {
        "portfolio_beats_benchmark_cumulative": (
            (portfolio_metrics.cumulative_performance_pct or 0.0)
            > (benchmark_metrics.cumulative_performance_pct or 0.0)
        ),
        "history_truncated_vs_requested": bool(
            requested_years is not None and effective_years < float(requested_years) - 0.01
        ),
        "limiting_asset": history_limits.get("limiting_start_asset"),
        "limiting_assets": history_limits.get("limiting_start_assets") or [],
        "ignored_limiting_assets": ignored_limiting_assets,
    }

    payload = {
        "mode": "current_portfolio_weights_projected_into_past",
        "benchmark_symbol": benchmark,
        "benchmark_label": f"MSCI World proxy ({benchmark})",
        "horizon_requested": horizon_key,
        "horizon_requested_years": requested_years,
        "horizon_effective_years": round(effective_years, 2),
        "frequency": "weekly",
        "periods_per_year": round(periods_per_year, 4),
        "dates": {
            "full_common_start": _fmt_date(full_start),
            "full_common_end": _fmt_date(full_end),
            "start_used": _fmt_date(selected_start),
            "end_used": _fmt_date(selected_end),
            "n_points_used": int(len(selected_frame)),
        },
        "history_limits": history_limits,
        "ignore_limiting_assets": bool(ignore_limiting_assets),
        "ignore_limiting_assets_applied": bool(ignored_limiting_assets),
        "ignored_limiting_assets": ignored_limiting_assets,
        "assets_retained": assets_retained_payload,
        "assets_ignored": ignored_assets,
        "series_portfolio": series_df[["date", "portfolio_norm"]].copy(),
        "series_benchmark": series_df[["date", "benchmark_norm"]].copy(),
        "series_comparison": series_df,
        "metrics_portfolio": portfolio_metrics.to_dict(),
        "metrics_benchmark": benchmark_metrics.to_dict(),
        "metrics_relative": relative_metrics.to_dict(),
        "asset_diagnostics": asset_diagnostics,
        "asset_diagnostic_meta": asset_diagnostic_meta,
        "improved_portfolio": improved_portfolio,
        "summary": summary,
    }

    logger.info(
        "build_current_portfolio_backtest: done person_id=%s retained=%d ignored=%d points=%d",
        person_id,
        len(assets_retained_payload),
        len(ignored_assets),
        len(selected_frame),
    )
    return payload


def _normalize_horizon(raw_horizon: str | None) -> tuple[str, int | None]:
    if not raw_horizon:
        return DEFAULT_HORIZON, SUPPORTED_HORIZONS[DEFAULT_HORIZON]
    h = str(raw_horizon).strip().lower()
    aliases = {
        "5": "5y",
        "10": "10y",
        "15": "15y",
        "20": "20y",
        "5ans": "5y",
        "10ans": "10y",
        "15ans": "15y",
        "20ans": "20y",
    }
    h = aliases.get(h, h)
    if h not in SUPPORTED_HORIZONS:
        logger.warning("Horizon inconnu '%s', fallback sur %s.", raw_horizon, DEFAULT_HORIZON)
        h = DEFAULT_HORIZON
    return h, SUPPORTED_HORIZONS[h]


def _load_current_weights(conn, person_id: int) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    positions = bourse_analytics.get_live_bourse_positions(conn, person_id)
    ignored: list[dict[str, Any]] = []

    if positions is None or positions.empty:
        return pd.DataFrame(columns=["symbol", "name", "value_eur", "weight"]), ignored

    df = positions.copy()
    df["symbol"] = df.get("symbol", "").astype(str).str.strip().str.upper()
    df["value"] = pd.to_numeric(df.get("value"), errors="coerce")
    if "name" in df.columns:
        df["name"] = df["name"].astype(str).str.strip()
    else:
        df["name"] = ""

    invalid = df[(df["symbol"] == "") | df["value"].isna() | (df["value"] <= 0)]
    for _, row in invalid.iterrows():
        symbol = str(row.get("symbol") or "").strip().upper()
        ignored.append(
            {
                "symbol": symbol or None,
                "reason": "invalid_live_position_value",
            }
        )

    valid = df[(df["symbol"] != "") & df["value"].notna() & (df["value"] > 0)].copy()
    if valid.empty:
        return pd.DataFrame(columns=["symbol", "name", "value_eur", "weight"]), ignored

    grouped = (
        valid.groupby("symbol", as_index=False)
        .agg(
            value_eur=("value", "sum"),
            name=("name", _first_non_empty),
        )
        .sort_values("value_eur", ascending=False)
        .reset_index(drop=True)
    )
    total_value = float(grouped["value_eur"].sum())
    if total_value <= 0:
        return pd.DataFrame(columns=["symbol", "name", "value_eur", "weight"]), ignored

    grouped["weight"] = grouped["value_eur"] / total_value
    grouped["name"] = grouped["name"].replace("", None)
    return grouped, ignored


def _load_weekly_prices(conn, symbols: list[str]) -> pd.DataFrame:
    symbols = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if not symbols:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(symbols))
    query = (
        "SELECT symbol, week_date, adj_close "
        f"FROM asset_prices_weekly WHERE symbol IN ({placeholders})"
    )
    raw = pd.read_sql_query(query, conn, params=tuple(symbols))
    if raw.empty:
        return pd.DataFrame()

    raw["symbol"] = raw["symbol"].astype(str).str.strip().str.upper()
    raw["week_date"] = pd.to_datetime(raw["week_date"], errors="coerce")
    raw["adj_close"] = pd.to_numeric(raw["adj_close"], errors="coerce")
    raw = raw.dropna(subset=["week_date", "symbol", "adj_close"])
    raw = raw[raw["adj_close"] > 0]
    if raw.empty:
        return pd.DataFrame()

    prices_df = (
        raw.pivot_table(
            index="week_date",
            columns="symbol",
            values="adj_close",
            aggfunc="last",
        )
        .sort_index()
    )
    return prices_df


def _filter_assets_with_history(
    weights_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    ignored: list[dict[str, Any]] = []
    if weights_df.empty:
        return weights_df, ignored

    if prices_df.empty:
        for _, row in weights_df.iterrows():
            ignored.append(
                {
                    "symbol": str(row["symbol"]),
                    "reason": "missing_price_history",
                }
            )
        return pd.DataFrame(columns=weights_df.columns), ignored

    retained_rows = []
    for _, row in weights_df.iterrows():
        symbol = str(row["symbol"])
        if symbol not in prices_df.columns:
            ignored.append({"symbol": symbol, "reason": "missing_price_history"})
            continue
        n_points = int(prices_df[symbol].dropna().shape[0])
        if n_points < MIN_POINTS:
            ignored.append({"symbol": symbol, "reason": "insufficient_price_history"})
            continue
        retained_rows.append(row.to_dict())

    retained = pd.DataFrame(retained_rows)
    if retained.empty:
        return pd.DataFrame(columns=weights_df.columns), ignored

    retained = retained.sort_values("value_eur", ascending=False).reset_index(drop=True)
    retained["weight"] = retained["weight"] / retained["weight"].sum()
    return retained, ignored


def _build_common_history_frame(
    prices_df: pd.DataFrame,
    asset_symbols: list[str],
    benchmark_symbol: str,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], str | None]:
    symbols = [*asset_symbols, benchmark_symbol]
    if prices_df.empty:
        return pd.DataFrame(), {}, "Historique de prix weekly indisponible."

    history_bounds: dict[str, dict[str, Any]] = {}
    series_map: dict[str, pd.Series] = {}
    for symbol in symbols:
        if symbol not in prices_df.columns:
            if symbol == benchmark_symbol:
                return (
                    pd.DataFrame(),
                    {},
                    f"Benchmark '{benchmark_symbol}' indisponible dans asset_prices_weekly.",
                )
            return pd.DataFrame(), {}, f"Actif '{symbol}' sans historique weekly."

        s = prices_df[symbol].dropna()
        s = s[s > 0]
        if len(s) < MIN_POINTS:
            if symbol == benchmark_symbol:
                return (
                    pd.DataFrame(),
                    {},
                    f"Benchmark '{benchmark_symbol}' sans historique suffisant.",
                )
            return pd.DataFrame(), {}, f"Actif '{symbol}' sans historique suffisant."

        series_map[symbol] = s
        history_bounds[symbol] = {
            "start": _fmt_date(s.index.min()),
            "end": _fmt_date(s.index.max()),
            "n_points": int(len(s)),
        }

    common_frame = pd.DataFrame(series_map).dropna().sort_index()
    if len(common_frame) < MIN_POINTS:
        return (
            pd.DataFrame(),
            history_bounds,
            "Historique commun strict insuffisant entre actifs et benchmark.",
        )
    return common_frame, history_bounds, None


def _apply_horizon(common_frame: pd.DataFrame, horizon_years: int | None) -> pd.DataFrame:
    if common_frame.empty or horizon_years is None:
        return common_frame

    end_date = common_frame.index.max()
    cutoff = end_date - pd.DateOffset(years=int(horizon_years))
    sliced = common_frame[common_frame.index >= cutoff]
    if len(sliced) >= MIN_POINTS:
        return sliced
    return common_frame


def _drop_limiting_assets_for_horizon(
    retained_weights: pd.DataFrame,
    prices_df: pd.DataFrame,
    benchmark_symbol: str,
    horizon_years: int,
) -> tuple[pd.DataFrame, list[str]]:
    if retained_weights.empty or horizon_years <= 0:
        return retained_weights, []

    working = retained_weights.copy().reset_index(drop=True)
    ignored: list[str] = []
    max_iterations = max(len(working) - 1, 0)

    for _ in range(max_iterations):
        symbols = working["symbol"].astype(str).tolist()
        common_frame, history_bounds, error = _build_common_history_frame(
            prices_df=prices_df,
            asset_symbols=symbols,
            benchmark_symbol=benchmark_symbol,
        )
        if error is not None or common_frame.empty:
            break

        selected_frame = _apply_horizon(common_frame, horizon_years)
        if len(selected_frame) < MIN_POINTS:
            break

        effective_years = _compute_period_years(selected_frame.index)
        if effective_years >= float(horizon_years) - 0.01:
            break

        history_limits = _detect_history_limiters(history_bounds)
        limiting_assets = [
            str(symbol)
            for symbol in (history_limits.get("limiting_start_assets") or [])
            if str(symbol) and str(symbol) != str(benchmark_symbol)
        ]
        if not limiting_assets:
            break

        before = set(symbols)
        working = working[~working["symbol"].isin(limiting_assets)].copy().reset_index(drop=True)
        removed_symbols = [s for s in limiting_assets if s in before]
        if not removed_symbols:
            break

        for symbol in removed_symbols:
            if symbol not in ignored:
                ignored.append(symbol)

        if working.empty:
            break

    if not working.empty:
        total = float(working["weight"].sum())
        if total > 0:
            working["weight"] = working["weight"] / total
    return working, ignored


def _build_portfolio_level(
    history_frame: pd.DataFrame,
    asset_symbols: list[str],
    weights: pd.Series,
) -> pd.Series:
    assets_prices = history_frame[asset_symbols]
    assets_norm = assets_prices.div(assets_prices.iloc[0])
    ptf = assets_norm.mul(weights, axis=1).sum(axis=1)
    return _normalize_to_one(ptf)


def _normalize_to_one(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return s
    base = float(s.iloc[0])
    if base <= 0:
        return s
    return s / base


def _infer_periods_per_year(index: pd.Index) -> float:
    if len(index) < MIN_POINTS:
        return 52.0
    idx = pd.to_datetime(index, errors="coerce")
    deltas = pd.Series(idx).diff().dt.days.dropna()
    deltas = deltas[deltas > 0]
    if deltas.empty:
        return 52.0
    median_days = float(deltas.median())
    if median_days <= 0:
        return 52.0
    return 365.25 / median_days


def _compute_series_metrics(
    level_series: pd.Series,
    periods_per_year: float,
    risk_free_rate: float,
) -> SeriesMetrics:
    s = pd.to_numeric(level_series, errors="coerce").dropna()
    if len(s) < MIN_POINTS:
        return SeriesMetrics(None, None, None, None, None)

    cumulative = float(s.iloc[-1] / s.iloc[0] - 1.0)
    cagr = _compute_cagr_decimal(s)

    returns = s.pct_change().dropna()
    vol_ann = None
    if len(returns) >= MIN_POINTS:
        vol = float(returns.std(ddof=1))
        if math.isfinite(vol) and vol > 0:
            vol_ann = vol * math.sqrt(periods_per_year)

    max_dd = _compute_max_drawdown_decimal(s)

    sharpe = None
    if cagr is not None and vol_ann is not None and vol_ann > 0:
        sharpe = (cagr - float(risk_free_rate)) / vol_ann

    return SeriesMetrics(
        cumulative_performance_pct=round(cumulative * 100.0, 4),
        annualized_return_pct=round(cagr * 100.0, 4) if cagr is not None else None,
        annualized_volatility_pct=round(vol_ann * 100.0, 4) if vol_ann is not None else None,
        max_drawdown_pct=round(max_dd * 100.0, 4) if max_dd is not None else None,
        sharpe=round(float(sharpe), 4) if sharpe is not None else None,
    )


def _compute_relative_metrics(
    portfolio_level: pd.Series,
    benchmark_level: pd.Series,
    periods_per_year: float,
    risk_free_rate: float,
) -> RelativeMetrics:
    s_port = pd.to_numeric(portfolio_level, errors="coerce").dropna()
    s_bench = pd.to_numeric(benchmark_level, errors="coerce").dropna()
    aligned = pd.DataFrame({"portfolio": s_port, "benchmark": s_bench}).dropna()
    if len(aligned) < MIN_POINTS:
        return RelativeMetrics(None, None, None, None, None, None, None)

    cum_excess = float(
        (aligned["portfolio"].iloc[-1] / aligned["portfolio"].iloc[0])
        - (aligned["benchmark"].iloc[-1] / aligned["benchmark"].iloc[0])
    )

    port_ann = _compute_cagr_decimal(aligned["portfolio"])
    bench_ann = _compute_cagr_decimal(aligned["benchmark"])
    ann_excess = None
    if port_ann is not None and bench_ann is not None:
        ann_excess = port_ann - bench_ann

    returns = aligned.pct_change().dropna()
    tracking_error = None
    information_ratio = None
    beta = None
    alpha = None
    correlation = None

    if len(returns) >= MIN_POINTS:
        active = returns["portfolio"] - returns["benchmark"]
        te = float(active.std(ddof=1))
        if math.isfinite(te) and te > 0:
            tracking_error = te * math.sqrt(periods_per_year)
            if ann_excess is not None:
                information_ratio = ann_excess / tracking_error

        bench_var = float(returns["benchmark"].var(ddof=1))
        if bench_var > 0 and math.isfinite(bench_var):
            cov = float(returns[["portfolio", "benchmark"]].cov().iloc[0, 1])
            beta = cov / bench_var

        corr = float(returns["portfolio"].corr(returns["benchmark"]))
        if math.isfinite(corr):
            correlation = corr

    if beta is not None and port_ann is not None and bench_ann is not None:
        alpha = (port_ann - float(risk_free_rate)) - beta * (bench_ann - float(risk_free_rate))

    return RelativeMetrics(
        cumulative_excess_performance_pct=round(cum_excess * 100.0, 4),
        annualized_excess_return_pct=round(ann_excess * 100.0, 4) if ann_excess is not None else None,
        tracking_error_pct=round(tracking_error * 100.0, 4) if tracking_error is not None else None,
        information_ratio=round(float(information_ratio), 4) if information_ratio is not None else None,
        beta=round(float(beta), 4) if beta is not None else None,
        alpha_pct=round(alpha * 100.0, 4) if alpha is not None else None,
        correlation=round(float(correlation), 4) if correlation is not None else None,
    )


def _compute_max_drawdown_decimal(level_series: pd.Series) -> float | None:
    s = pd.to_numeric(level_series, errors="coerce").dropna()
    if s.empty:
        return None
    running_max = s.cummax()
    drawdowns = s / running_max - 1.0
    return float(drawdowns.min())


def _compute_cagr_decimal(level_series: pd.Series) -> float | None:
    s = pd.to_numeric(level_series, errors="coerce").dropna()
    if len(s) < MIN_POINTS:
        return None
    first = float(s.iloc[0])
    last = float(s.iloc[-1])
    if first <= 0 or last <= 0:
        return None

    idx = pd.to_datetime(s.index, errors="coerce")
    if len(idx) < MIN_POINTS:
        return None
    days = int((idx[-1] - idx[0]).days)
    if days <= 0:
        return None
    years = days / 365.25
    return pow(last / first, 1.0 / years) - 1.0


def _compute_period_years(index: pd.Index) -> float:
    if len(index) < MIN_POINTS:
        return 0.0
    idx = pd.to_datetime(index, errors="coerce")
    days = max(int((idx[-1] - idx[0]).days), 0)
    return days / 365.25


def _build_asset_diagnostics(
    selected_frame: pd.DataFrame,
    weights: pd.Series,
    retained_weights: pd.DataFrame,
    benchmark_symbol: str,
    portfolio_level: pd.Series,
    benchmark_level: pd.Series,
    portfolio_metrics: SeriesMetrics,
    periods_per_year: float,
    risk_free_rate: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    asset_symbols = [str(s) for s in weights.index.tolist()]
    if not asset_symbols:
        return [], _asset_diag_meta()

    assets_prices = selected_frame[asset_symbols]
    assets_norm = assets_prices.div(assets_prices.iloc[0])
    assets_returns = assets_norm.pct_change()
    portfolio_returns = portfolio_level.pct_change().rename("portfolio")
    benchmark_returns = benchmark_level.pct_change().rename("benchmark")

    names_map = {
        str(row["symbol"]): row.get("name")
        for _, row in retained_weights.iterrows()
    }

    diagnostics: list[dict[str, Any]] = []
    for symbol in asset_symbols:
        w = float(weights.loc[symbol])
        asset_level = assets_norm[symbol]
        asset_metrics = _compute_series_metrics(
            level_series=asset_level,
            periods_per_year=periods_per_year,
            risk_free_rate=risk_free_rate,
        )

        contribution_cumulative_pct = float(
            w * (float(asset_level.iloc[-1] / asset_level.iloc[0]) - 1.0) * 100.0
        )
        correlation_to_portfolio = _safe_corr(assets_returns[symbol], portfolio_returns)
        correlation_to_benchmark = _safe_corr(assets_returns[symbol], benchmark_returns)

        without_asset = _build_without_asset_analysis(
            selected_frame=selected_frame,
            base_asset_symbols=asset_symbols,
            weights=weights,
            remove_symbol=symbol,
            periods_per_year=periods_per_year,
            risk_free_rate=risk_free_rate,
            base_metrics=portfolio_metrics,
        )

        status_code, status_label, status_reasons = _classify_asset_status(
            weight=w,
            contribution_cumulative_pct=contribution_cumulative_pct,
            corr_portfolio=correlation_to_portfolio,
            corr_benchmark=correlation_to_benchmark,
            without_asset=without_asset,
        )
        comment = _build_asset_comment(
            symbol=symbol,
            status_label=status_label,
            reasons=status_reasons,
            without_asset=without_asset,
        )

        diagnostics.append(
            {
                "symbol": symbol,
                "name": names_map.get(symbol),
                "weight_pct": round(w * 100.0, 4),
                "contribution_cumulative_pct": round(contribution_cumulative_pct, 4),
                "asset_metrics": asset_metrics.to_dict(),
                "asset_annualized_return_pct": asset_metrics.annualized_return_pct,
                "asset_annualized_volatility_pct": asset_metrics.annualized_volatility_pct,
                "correlation_to_portfolio": round(correlation_to_portfolio, 4)
                if correlation_to_portfolio is not None else None,
                "correlation_to_benchmark": round(correlation_to_benchmark, 4)
                if correlation_to_benchmark is not None else None,
                "concentration_level": _concentration_level(w),
                "diversification_role": _diversification_role(correlation_to_benchmark),
                "status": status_code,
                "status_label": status_label,
                "diagnostic_comment": comment,
                "status_reasons": status_reasons,
                "without_asset": without_asset,
            }
        )

    diagnostics = sorted(
        diagnostics,
        key=lambda d: (
            _status_rank(str(d.get("status") or "")),
            -float(d.get("weight_pct") or 0.0),
        ),
    )
    return diagnostics, _asset_diag_meta()


def _build_without_asset_analysis(
    selected_frame: pd.DataFrame,
    base_asset_symbols: list[str],
    weights: pd.Series,
    remove_symbol: str,
    periods_per_year: float,
    risk_free_rate: float,
    base_metrics: SeriesMetrics,
) -> dict[str, Any]:
    if len(base_asset_symbols) <= 1:
        return {
            "available": False,
            "reason": "mono_asset_portfolio",
            "interpretation": "Analyse sans cet actif indisponible sur un portefeuille mono-actif.",
        }

    other_symbols = [sym for sym in base_asset_symbols if sym != remove_symbol]
    if not other_symbols:
        return {
            "available": False,
            "reason": "no_alternative_assets",
            "interpretation": "Analyse sans cet actif indisponible.",
        }

    weights_without = weights.loc[other_symbols]
    weights_without = weights_without / weights_without.sum()

    level_without = _build_portfolio_level(
        history_frame=selected_frame,
        asset_symbols=other_symbols,
        weights=weights_without,
    )
    metrics_without = _compute_series_metrics(
        level_series=level_without,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )

    deltas = {
        "annualized_return_pct": _delta(metrics_without.annualized_return_pct, base_metrics.annualized_return_pct),
        "annualized_volatility_pct": _delta(
            metrics_without.annualized_volatility_pct,
            base_metrics.annualized_volatility_pct,
        ),
        "max_drawdown_pct": _delta(metrics_without.max_drawdown_pct, base_metrics.max_drawdown_pct),
        "sharpe": _delta(metrics_without.sharpe, base_metrics.sharpe),
        "cumulative_performance_pct": _delta(
            metrics_without.cumulative_performance_pct,
            base_metrics.cumulative_performance_pct,
        ),
    }

    return {
        "available": True,
        "weights_renormalized_on": other_symbols,
        "metrics": metrics_without.to_dict(),
        "deltas": {k: round(v, 4) if v is not None else None for k, v in deltas.items()},
        "interpretation": _interpret_without_asset(deltas),
    }


def _classify_asset_status(
    weight: float,
    contribution_cumulative_pct: float,
    corr_portfolio: float | None,
    corr_benchmark: float | None,
    without_asset: dict[str, Any],
) -> tuple[str, str, list[str]]:
    positive = 0
    negative = 0
    reasons: list[str] = []

    if contribution_cumulative_pct >= DIAG_STRONG_CONTRIBUTION_PCT:
        positive += 1
        reasons.append("Contribution positive marquée sur la performance cumulée.")
    elif contribution_cumulative_pct <= -DIAG_STRONG_CONTRIBUTION_PCT:
        negative += 1
        reasons.append("Contribution négative marquée sur la performance cumulée.")

    deltas = without_asset.get("deltas") if without_asset.get("available") else {}
    delta_sharpe = deltas.get("sharpe") if isinstance(deltas, dict) else None
    delta_return = deltas.get("annualized_return_pct") if isinstance(deltas, dict) else None

    if delta_sharpe is not None:
        if delta_sharpe >= DIAG_SHARPE_DELTA_STRONG:
            negative += 2
            reasons.append("Le Sharpe s'améliore nettement sans cet actif.")
        elif delta_sharpe <= -DIAG_SHARPE_DELTA_STRONG:
            positive += 2
            reasons.append("Le Sharpe se dégrade nettement sans cet actif.")

    if delta_return is not None:
        if delta_return >= DIAG_RETURN_DELTA_PCT:
            negative += 1
            reasons.append("Le rendement annualisé augmente sans cet actif.")
        elif delta_return <= -DIAG_RETURN_DELTA_PCT:
            positive += 1
            reasons.append("Le rendement annualisé baisse sans cet actif.")

    if corr_benchmark is not None and corr_benchmark <= DIAG_DIVERSIFYING_CORR_MAX and weight >= 0.05:
        positive += 1
        reasons.append("Corrélation modérée au benchmark (apport de diversification).")

    if weight >= DIAG_CONCENTRATION_WEIGHT_HIGH and corr_portfolio is not None and corr_portfolio >= DIAG_CORR_CONCENTRATED_MIN:
        negative += 1
        reasons.append("Poids concentré avec corrélation élevée au portefeuille.")

    score = positive - negative
    if score >= 2:
        return "moteur", "Moteur", reasons
    if score <= -2:
        return "penalisant", "Pénalisant", reasons
    if positive > 0 and negative > 0:
        return "a_surveiller", "A surveiller", reasons
    return "neutre", "Neutre", reasons


def _build_asset_comment(
    symbol: str,
    status_label: str,
    reasons: list[str],
    without_asset: dict[str, Any],
) -> str:
    if reasons:
        return reasons[0]
    if without_asset.get("available"):
        return f"Impact historique {status_label.lower()} dans cette analyse."
    return f"Analyse historique limitée pour {symbol}."


def _interpret_without_asset(deltas: dict[str, float | None]) -> str:
    delta_sharpe = deltas.get("sharpe")
    delta_return = deltas.get("annualized_return_pct")
    delta_vol = deltas.get("annualized_volatility_pct")

    if delta_sharpe is not None and delta_sharpe >= DIAG_SHARPE_DELTA_STRONG:
        return "Sans cet actif, le ratio de Sharpe aurait été meilleur dans l'historique analysé."
    if delta_sharpe is not None and delta_sharpe <= -DIAG_SHARPE_DELTA_STRONG:
        return "Sans cet actif, le ratio de Sharpe aurait été moins bon dans l'historique analysé."
    if (
        delta_return is not None and delta_return > 0
        and delta_vol is not None and delta_vol > 0
    ):
        return "Sans cet actif, le rendement aurait été plus élevé mais avec plus de volatilité."
    if (
        delta_return is not None and delta_return < 0
        and delta_vol is not None and delta_vol < 0
    ):
        return "Sans cet actif, le rendement aurait été plus faible mais avec moins de volatilité."
    return "Impact mixte de cet actif sur le couple rendement/risque dans cette analyse."


def _status_rank(status: str) -> int:
    return {
        "penalisant": 0,
        "a_surveiller": 1,
        "neutre": 2,
        "moteur": 3,
    }.get(status, 4)


def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    aligned = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(aligned) < MIN_POINTS:
        return None
    corr = float(aligned["a"].corr(aligned["b"]))
    if not math.isfinite(corr):
        return None
    return corr


def _concentration_level(weight: float) -> str:
    if weight >= DIAG_CONCENTRATION_WEIGHT_HIGH:
        return "elevee"
    if weight >= DIAG_CONCENTRATION_WEIGHT_MEDIUM:
        return "moderee"
    return "faible"


def _diversification_role(corr_benchmark: float | None) -> str:
    if corr_benchmark is None:
        return "indetermine"
    if corr_benchmark <= DIAG_DIVERSIFYING_CORR_MAX:
        return "diversifiant"
    if corr_benchmark < 0.80:
        return "mixte"
    return "tres correle marche"


def _asset_diag_meta() -> dict[str, Any]:
    return {
        "method": "historical_heuristic",
        "delta_definition": "delta = métrique(sans actif) - métrique(portefeuille de base)",
        "status_levels": ["moteur", "neutre", "a_surveiller", "penalisant"],
        "thresholds": {
            "strong_contribution_pct": DIAG_STRONG_CONTRIBUTION_PCT,
            "sharpe_delta_strong": DIAG_SHARPE_DELTA_STRONG,
            "annualized_return_delta_pct": DIAG_RETURN_DELTA_PCT,
            "diversifying_corr_benchmark_max": DIAG_DIVERSIFYING_CORR_MAX,
            "high_concentration_weight": DIAG_CONCENTRATION_WEIGHT_HIGH,
        },
    }


def _build_improved_portfolio_payload(
    retained_weights: pd.DataFrame,
    selected_frame: pd.DataFrame,
    benchmark_symbol: str,
    periods_per_year: float,
    risk_free_rate: float,
    base_metrics: SeriesMetrics,
    asset_diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    weights_series = retained_weights.set_index("symbol")["weight"].astype(float)
    names_map = {
        str(row["symbol"]): row.get("name")
        for _, row in retained_weights.iterrows()
    }

    current_weights_all = {
        str(sym): float(w)
        for sym, w in weights_series.sort_values(ascending=False).items()
    }

    feasibility = _assess_improved_feasibility(len(current_weights_all))
    if not feasibility["feasible"]:
        return {
            "available": False,
            "reason": feasibility["reason"],
            "message": feasibility["message"],
            "constraints": _improved_constraints(),
            "current_portfolio": _format_weight_rows(current_weights_all, names_map),
            "improved_portfolio": [],
            "adjustments": [],
            "metrics_current": base_metrics.to_dict(),
            "metrics_improved": {},
            "metrics_differences": {},
            "summary": "Simulation de portefeuille amélioré indisponible avec le nombre actuel d'actifs.",
            "applied_adjustments": [],
        }

    symbols_sorted = list(weights_series.sort_values(ascending=False).index)
    selected_symbols = symbols_sorted[:IMPROVED_MAX_ASSETS_BY_MIN]
    dropped_symbols = symbols_sorted[IMPROVED_MAX_ASSETS_BY_MIN:]

    current_selected = weights_series.loc[selected_symbols]
    current_selected = current_selected / current_selected.sum()

    diag_by_symbol = {str(row.get("symbol")): row for row in asset_diagnostics}
    target = _build_improved_target_weights(current_selected, diag_by_symbol)

    improved_selected, projection_ok = _project_weights_with_bounds(
        target=target,
        lower_bound=IMPROVED_MIN_WEIGHT,
        upper_bound=IMPROVED_MAX_WEIGHT,
    )
    if not projection_ok:
        return {
            "available": False,
            "reason": "projection_failed",
            "message": "Impossible de construire une version améliorée respectant les contraintes.",
            "constraints": _improved_constraints(),
            "current_portfolio": _format_weight_rows(current_weights_all, names_map),
            "improved_portfolio": [],
            "adjustments": [],
            "metrics_current": base_metrics.to_dict(),
            "metrics_improved": {},
            "metrics_differences": {},
            "summary": "Aucune amélioration crédible n'a été trouvée dans ce cadre.",
            "applied_adjustments": [],
        }

    turnover = _turnover(current_selected, improved_selected)
    if turnover > IMPROVED_MAX_TURNOVER:
        shrink = IMPROVED_MAX_TURNOVER / turnover
        shrunk = current_selected + (improved_selected - current_selected) * shrink
        improved_selected, projection_ok = _project_weights_with_bounds(
            target=shrunk,
            lower_bound=IMPROVED_MIN_WEIGHT,
            upper_bound=IMPROVED_MAX_WEIGHT,
        )
        if projection_ok:
            turnover = _turnover(current_selected, improved_selected)

    improved_all = pd.Series(0.0, index=weights_series.index, dtype=float)
    improved_all.loc[selected_symbols] = improved_selected

    improved_level = _build_portfolio_level(
        history_frame=selected_frame,
        asset_symbols=selected_symbols,
        weights=improved_selected,
    )
    improved_metrics = _compute_series_metrics(
        level_series=improved_level,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )

    metrics_diff = {
        "annualized_return_pct": _delta(
            improved_metrics.annualized_return_pct,
            base_metrics.annualized_return_pct,
        ),
        "annualized_volatility_pct": _delta(
            improved_metrics.annualized_volatility_pct,
            base_metrics.annualized_volatility_pct,
        ),
        "max_drawdown_pct": _delta(
            improved_metrics.max_drawdown_pct,
            base_metrics.max_drawdown_pct,
        ),
        "sharpe": _delta(
            improved_metrics.sharpe,
            base_metrics.sharpe,
        ),
        "cumulative_performance_pct": _delta(
            improved_metrics.cumulative_performance_pct,
            base_metrics.cumulative_performance_pct,
        ),
    }

    adjustments = _build_adjustments_rows(
        current_weights=weights_series,
        improved_weights=improved_all,
        names_map=names_map,
        dropped_symbols=dropped_symbols,
    )
    applied_adjustments = _build_applied_adjustments_flags(
        current_weights=weights_series,
        improved_weights=improved_all,
        dropped_symbols=dropped_symbols,
    )

    summary = _build_improved_summary(metrics_diff)

    return {
        "available": True,
        "reason": None,
        "message": None,
        "constraints": _improved_constraints(),
        "current_portfolio": _format_weight_rows(current_weights_all, names_map),
        "improved_portfolio": _format_weight_rows(improved_all.to_dict(), names_map),
        "adjustments": adjustments,
        "metrics_current": base_metrics.to_dict(),
        "metrics_improved": improved_metrics.to_dict(),
        "metrics_differences": {
            k: round(v, 4) if v is not None else None
            for k, v in metrics_diff.items()
        },
        "summary": summary,
        "applied_adjustments": applied_adjustments,
        "metadata": {
            "benchmark_symbol": benchmark_symbol,
            "turnover_pct": round(turnover * 100.0, 4),
            "active_assets_count": int(len(selected_symbols)),
            "dropped_assets_count": int(len(dropped_symbols)),
        },
        "warning": (
            "Simulation historique indicative, non prédictive et non assimilable à un conseil financier."
        ),
    }


def _assess_improved_feasibility(n_assets: int) -> dict[str, Any]:
    if n_assets <= 0:
        return {
            "feasible": False,
            "reason": "no_assets",
            "message": "Aucun actif disponible pour la simulation améliorée.",
        }
    if n_assets < IMPROVED_MIN_ASSETS_FOR_MAX:
        return {
            "feasible": False,
            "reason": "insufficient_assets_for_max_constraint",
            "message": (
                f"Au moins {IMPROVED_MIN_ASSETS_FOR_MAX} actifs sont nécessaires pour respecter "
                f"le plafond de {int(IMPROVED_MAX_WEIGHT * 100)}% par actif."
            ),
        }
    return {"feasible": True, "reason": None, "message": None}


def _build_improved_target_weights(
    current_weights: pd.Series,
    diag_by_symbol: dict[str, dict[str, Any]],
) -> pd.Series:
    scores = {}
    for symbol, weight in current_weights.items():
        diag = diag_by_symbol.get(str(symbol), {})
        score = _improved_score_for_asset(weight=float(weight), diag=diag)
        scores[str(symbol)] = score

    score_series = pd.Series(scores, dtype=float)
    score_centered = score_series - float(score_series.mean())
    if float(score_centered.abs().sum()) <= 1e-12:
        return current_weights.copy()

    adjustment_strength = 0.03
    scaled = score_centered / float(score_centered.abs().max())
    target = current_weights + scaled * adjustment_strength
    return target


def _improved_score_for_asset(weight: float, diag: dict[str, Any]) -> float:
    status = str(diag.get("status") or "neutre")
    status_score = {
        "moteur": 1.2,
        "neutre": 0.3,
        "a_surveiller": -0.5,
        "penalisant": -1.2,
    }.get(status, 0.0)

    without = diag.get("without_asset") or {}
    deltas = without.get("deltas") or {}
    delta_sharpe = _to_float_or_zero(deltas.get("sharpe"))
    delta_ret = _to_float_or_zero(deltas.get("annualized_return_pct"))
    corr_bench = _to_float_or_zero(diag.get("correlation_to_benchmark"))

    score = status_score
    score -= max(delta_sharpe, 0.0) * 1.5
    score += max(-delta_sharpe, 0.0) * 1.2
    score -= max(delta_ret, 0.0) * 0.15
    score += max(-delta_ret, 0.0) * 0.12

    if corr_bench > 0 and corr_bench <= DIAG_DIVERSIFYING_CORR_MAX:
        score += 0.4
    if weight > DIAG_CONCENTRATION_WEIGHT_HIGH:
        score -= 0.5
    return float(score)


def _project_weights_with_bounds(
    target: pd.Series,
    lower_bound: float,
    upper_bound: float,
    max_iter: int = 50,
) -> tuple[pd.Series, bool]:
    w = target.copy().astype(float)
    n = len(w)
    if n <= 0:
        return w, False
    if n * lower_bound > 1.0 + 1e-9:
        return w, False
    if n * upper_bound < 1.0 - 1e-9:
        return w, False

    w = w.clip(lower=lower_bound, upper=upper_bound)
    for _ in range(max_iter):
        total = float(w.sum())
        diff = 1.0 - total
        if abs(diff) <= 1e-10:
            return w, True

        if diff > 0:
            capacity = (upper_bound - w).clip(lower=0.0)
            cap_sum = float(capacity.sum())
            if cap_sum <= 1e-12:
                return w, False
            w = w + capacity * (diff / cap_sum)
        else:
            reducible = (w - lower_bound).clip(lower=0.0)
            red_sum = float(reducible.sum())
            if red_sum <= 1e-12:
                return w, False
            w = w - reducible * ((-diff) / red_sum)

        w = w.clip(lower=lower_bound, upper=upper_bound)

    return w, abs(float(w.sum()) - 1.0) <= 1e-8


def _turnover(current: pd.Series, improved: pd.Series) -> float:
    aligned = pd.DataFrame({"c": current, "i": improved}).fillna(0.0)
    return float(aligned.eval("abs(c - i)").sum()) / 2.0


def _build_adjustments_rows(
    current_weights: pd.Series,
    improved_weights: pd.Series,
    names_map: dict[str, Any],
    dropped_symbols: list[str],
) -> list[dict[str, Any]]:
    rows = []
    for symbol in current_weights.index.tolist():
        current_w = float(current_weights.get(symbol, 0.0))
        improved_w = float(improved_weights.get(symbol, 0.0))
        delta = improved_w - current_w
        rows.append(
            {
                "symbol": str(symbol),
                "name": names_map.get(str(symbol)),
                "weight_current_pct": round(current_w * 100.0, 4),
                "weight_improved_pct": round(improved_w * 100.0, 4),
                "delta_weight_pct": round(delta * 100.0, 4),
                "action": _weight_action(delta, str(symbol) in dropped_symbols),
            }
        )
    rows.sort(key=lambda x: abs(float(x.get("delta_weight_pct") or 0.0)), reverse=True)
    return rows


def _weight_action(delta: float, dropped: bool) -> str:
    if dropped:
        return "allégé pour respecter les contraintes"
    if delta >= 0.75 / 100:
        return "renforcé"
    if delta <= -0.75 / 100:
        return "allégé"
    return "quasi inchangé"


def _build_applied_adjustments_flags(
    current_weights: pd.Series,
    improved_weights: pd.Series,
    dropped_symbols: list[str],
) -> list[str]:
    flags: list[str] = []
    if dropped_symbols:
        flags.append("univers réduit pour respecter le minimum de 2% par actif")

    overweight_before = int((current_weights > IMPROVED_MAX_WEIGHT + 1e-9).sum())
    if overweight_before > 0:
        flags.append("surpondérations plafonnées à 15%")

    top_current = float(current_weights.max()) if not current_weights.empty else 0.0
    top_improved = float(improved_weights.max()) if not improved_weights.empty else 0.0
    if top_improved + 1e-9 < top_current:
        flags.append("concentration réduite sur la ligne principale")

    turnover = _turnover(current_weights, improved_weights)
    if turnover > 0.01:
        flags.append("réallocation progressive vers une version plus équilibrée")

    if not flags:
        flags.append("ajustements limités pour rester proche du portefeuille actuel")
    return flags


def _build_improved_summary(metrics_diff: dict[str, float | None]) -> str:
    d_sharpe = metrics_diff.get("sharpe")
    d_ret = metrics_diff.get("annualized_return_pct")
    d_vol = metrics_diff.get("annualized_volatility_pct")

    parts = ["Version plus diversifiée du portefeuille actuel, simulée sur le même historique."]
    if d_sharpe is not None:
        if d_sharpe > 0:
            parts.append(f"Sharpe simulé en hausse de {d_sharpe:+.2f}.")
        elif d_sharpe < 0:
            parts.append(f"Sharpe simulé en baisse de {d_sharpe:+.2f}.")

    if d_ret is not None and d_vol is not None:
        parts.append(
            f"Delta rendement {d_ret:+.2f}%/an et delta volatilité {d_vol:+.2f}%."
        )
    return " ".join(parts)


def _format_weight_rows(weights: dict[str, float], names_map: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for symbol, weight in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
        rows.append(
            {
                "symbol": str(symbol),
                "name": names_map.get(str(symbol)),
                "weight_pct": round(float(weight) * 100.0, 4),
            }
        )
    return rows


def _improved_constraints() -> dict[str, Any]:
    return {
        "sum_weights_pct": 100.0,
        "short_allowed": False,
        "leverage_allowed": False,
        "max_weight_pct": round(IMPROVED_MAX_WEIGHT * 100.0, 2),
        "min_weight_if_selected_pct": round(IMPROVED_MIN_WEIGHT * 100.0, 2),
        "max_assets_with_min_constraint": IMPROVED_MAX_ASSETS_BY_MIN,
        "min_assets_required_for_max_constraint": IMPROVED_MIN_ASSETS_FOR_MAX,
        "max_turnover_pct": round(IMPROVED_MAX_TURNOVER * 100.0, 2),
        "asset_universe": "actifs déjà présents dans le portefeuille actuel",
    }


def _to_float_or_zero(value: Any) -> float:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return 0.0


def _delta(new_value: float | None, base_value: float | None) -> float | None:
    if new_value is None or base_value is None:
        return None
    return float(new_value) - float(base_value)


def _first_non_empty(series: pd.Series) -> str:
    for value in series.tolist():
        s = str(value or "").strip()
        if s and s.lower() != "nan":
            return s
    return ""


def _detect_history_limiters(history_bounds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not history_bounds:
        return {
            "limiting_start_asset": None,
            "limiting_start_assets": [],
            "limiting_end_assets": [],
        }

    starts = {
        symbol: pd.to_datetime(bounds.get("start"), errors="coerce")
        for symbol, bounds in history_bounds.items()
    }
    ends = {
        symbol: pd.to_datetime(bounds.get("end"), errors="coerce")
        for symbol, bounds in history_bounds.items()
    }

    valid_starts = {k: v for k, v in starts.items() if pd.notna(v)}
    valid_ends = {k: v for k, v in ends.items() if pd.notna(v)}

    limiting_start_assets: list[str] = []
    limiting_end_assets: list[str] = []
    limiting_start_asset: str | None = None

    if valid_starts:
        max_start = max(valid_starts.values())
        limiting_start_assets = sorted([k for k, v in valid_starts.items() if v == max_start])
        if len(limiting_start_assets) == 1:
            limiting_start_asset = limiting_start_assets[0]

    if valid_ends:
        min_end = min(valid_ends.values())
        limiting_end_assets = sorted([k for k, v in valid_ends.items() if v == min_end])

    return {
        "limiting_start_asset": limiting_start_asset,
        "limiting_start_assets": limiting_start_assets,
        "limiting_end_assets": limiting_end_assets,
    }


def _fmt_date(value: pd.Timestamp | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(pd.Timestamp(value).date())


def _error_payload(message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": message}
    payload.update(extra)
    return payload
