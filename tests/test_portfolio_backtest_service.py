from unittest.mock import patch

import pandas as pd
import pytest

from services.portfolio_backtest_service import build_current_portfolio_backtest
from services.projection_service import ProjectionService


def _insert_weekly_prices(conn, symbol: str, dates: pd.DatetimeIndex, start_price: float, step: float) -> None:
    rows = []
    for i, d in enumerate(dates):
        rows.append((symbol, d.strftime("%Y-%m-%d"), float(start_price + i * step)))
    conn.executemany(
        """
        INSERT INTO asset_prices_weekly(symbol, week_date, adj_close)
        VALUES (?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def test_build_current_portfolio_backtest_nominal(conn):
    _insert_weekly_prices(
        conn,
        "AAA",
        pd.date_range("2010-01-04", periods=220, freq="W-MON"),
        start_price=100.0,
        step=0.5,
    )
    _insert_weekly_prices(
        conn,
        "BBB",
        pd.date_range("2014-01-06", periods=120, freq="W-MON"),
        start_price=50.0,
        step=0.3,
    )
    _insert_weekly_prices(
        conn,
        "URTH",
        pd.date_range("2010-01-04", periods=260, freq="W-MON"),
        start_price=80.0,
        step=0.4,
    )

    live_positions = pd.DataFrame(
        [
            {"symbol": "AAA", "value": 6000.0},
            {"symbol": "BBB", "value": 4000.0},
        ]
    )
    with patch("services.bourse_analytics.get_live_bourse_positions", return_value=live_positions):
        payload = build_current_portfolio_backtest(conn, person_id=1, horizon="10y", benchmark_symbol="URTH")

    assert "error" not in payload
    assert payload["horizon_requested"] == "10y"
    assert payload["dates"]["full_common_start"] == "2014-01-06"
    assert payload["history_limits"]["limiting_start_asset"] == "BBB"
    assert payload["summary"]["history_truncated_vs_requested"] is True

    retained_symbols = {row["symbol"] for row in payload["assets_retained"]}
    assert retained_symbols == {"AAA", "BBB"}
    assert payload["series_comparison"].shape[0] >= 2

    assert payload["metrics_portfolio"]["cumulative_performance_pct"] is not None
    assert payload["metrics_benchmark"]["cumulative_performance_pct"] is not None
    assert payload["metrics_relative"]["annualized_excess_return_pct"] is not None
    assert isinstance(payload.get("asset_diagnostics"), list)
    assert len(payload["asset_diagnostics"]) == 2
    statuses = {row.get("status") for row in payload["asset_diagnostics"]}
    assert statuses.issubset({"moteur", "neutre", "a_surveiller", "penalisant"})
    diag = payload["asset_diagnostics"][0]
    assert "status" in diag
    assert "contribution_cumulative_pct" in diag
    assert "without_asset" in diag
    assert diag["without_asset"]["available"] is True
    assert "asset_diagnostic_meta" in payload
    improved = payload.get("improved_portfolio") or {}
    assert improved.get("available") is False
    assert improved.get("reason") == "insufficient_assets_for_max_constraint"


def test_build_current_portfolio_backtest_ignores_missing_asset_history(conn):
    _insert_weekly_prices(
        conn,
        "AAA",
        pd.date_range("2018-01-01", periods=80, freq="W-MON"),
        start_price=100.0,
        step=0.2,
    )
    _insert_weekly_prices(
        conn,
        "URTH",
        pd.date_range("2018-01-01", periods=90, freq="W-MON"),
        start_price=80.0,
        step=0.1,
    )

    live_positions = pd.DataFrame(
        [
            {"symbol": "AAA", "value": 7000.0},
            {"symbol": "CCC", "value": 3000.0},
        ]
    )
    with patch("services.bourse_analytics.get_live_bourse_positions", return_value=live_positions):
        payload = build_current_portfolio_backtest(conn, person_id=1, horizon="5y")

    assert "error" not in payload
    assert [row["symbol"] for row in payload["assets_retained"]] == ["AAA"]

    ignored = payload["assets_ignored"]
    assert any(row["symbol"] == "CCC" and row["reason"] == "missing_price_history" for row in ignored)
    assert len(payload["asset_diagnostics"]) == 1
    without = payload["asset_diagnostics"][0]["without_asset"]
    assert without["available"] is False
    assert without["reason"] == "mono_asset_portfolio"


def test_build_current_portfolio_backtest_can_ignore_limiting_assets(conn):
    long_dates = pd.date_range("2016-01-04", periods=540, freq="W-MON")
    short_dates = pd.date_range("2024-01-01", periods=60, freq="W-MON")

    _insert_weekly_prices(conn, "AAA", long_dates, start_price=100.0, step=0.4)
    _insert_weekly_prices(conn, "BBB", short_dates, start_price=50.0, step=0.2)
    _insert_weekly_prices(conn, "URTH", long_dates, start_price=80.0, step=0.3)

    live_positions = pd.DataFrame(
        [
            {"symbol": "AAA", "value": 7000.0},
            {"symbol": "BBB", "value": 3000.0},
        ]
    )

    with patch("services.bourse_analytics.get_live_bourse_positions", return_value=live_positions):
        strict_payload = build_current_portfolio_backtest(
            conn,
            person_id=1,
            horizon="5y",
            benchmark_symbol="URTH",
            ignore_limiting_assets=False,
        )
        ignore_payload = build_current_portfolio_backtest(
            conn,
            person_id=1,
            horizon="5y",
            benchmark_symbol="URTH",
            ignore_limiting_assets=True,
        )

    assert "error" not in strict_payload
    assert strict_payload["horizon_effective_years"] < 2.0
    assert strict_payload["history_limits"]["limiting_start_asset"] == "BBB"

    assert "error" not in ignore_payload
    assert ignore_payload["horizon_effective_years"] >= 4.9
    assert ignore_payload["ignore_limiting_assets"] is True
    assert ignore_payload["ignore_limiting_assets_applied"] is True
    assert ignore_payload["ignored_limiting_assets"] == ["BBB"]

    retained_symbols = {row["symbol"] for row in ignore_payload["assets_retained"]}
    assert retained_symbols == {"AAA"}
    ignored_rows = ignore_payload.get("assets_ignored") or []
    assert any(
        row.get("symbol") == "BBB" and row.get("reason") == "ignored_limiting_asset_for_horizon"
        for row in ignored_rows
    )


def test_build_current_portfolio_backtest_improved_portfolio_constraints(conn):
    dates = pd.date_range("2016-01-04", periods=170, freq="W-MON")
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "URTH"]
    for i, symbol in enumerate(symbols):
        _insert_weekly_prices(
            conn,
            symbol,
            dates,
            start_price=90.0 + i * 5.0,
            step=0.12 + i * 0.03,
        )

    live_positions = pd.DataFrame(
        [
            {"symbol": "AAA", "name": "Alpha", "value": 4500.0},
            {"symbol": "BBB", "name": "Beta", "value": 3200.0},
            {"symbol": "CCC", "name": "Gamma", "value": 2500.0},
            {"symbol": "DDD", "name": "Delta", "value": 2100.0},
            {"symbol": "EEE", "name": "Epsilon", "value": 1800.0},
            {"symbol": "FFF", "name": "Phi", "value": 1600.0},
            {"symbol": "GGG", "name": "Giga", "value": 1400.0},
        ]
    )
    with patch("services.bourse_analytics.get_live_bourse_positions", return_value=live_positions):
        payload = build_current_portfolio_backtest(conn, person_id=1, horizon="5y", benchmark_symbol="URTH")

    assert "error" not in payload
    improved = payload.get("improved_portfolio") or {}
    assert improved.get("available") is True

    improved_rows = improved.get("improved_portfolio") or []
    assert len(improved_rows) == 7

    total = sum(float(r.get("weight_pct") or 0.0) for r in improved_rows)
    assert total == pytest.approx(100.0, abs=0.01)

    for row in improved_rows:
        w = float(row["weight_pct"])
        assert w >= 2.0 - 1e-6
        assert w <= 15.0 + 1e-6

    constraints = improved.get("constraints") or {}
    assert constraints.get("short_allowed") is False
    assert constraints.get("leverage_allowed") is False
    assert constraints.get("max_weight_pct") == pytest.approx(15.0)
    assert constraints.get("min_weight_if_selected_pct") == pytest.approx(2.0)

    metrics_improved = improved.get("metrics_improved") or {}
    metrics_diff = improved.get("metrics_differences") or {}
    assert "annualized_return_pct" in metrics_improved
    assert "sharpe" in metrics_improved
    assert "annualized_return_pct" in metrics_diff
    assert "sharpe" in metrics_diff


def test_build_current_portfolio_backtest_errors_when_benchmark_missing(conn):
    _insert_weekly_prices(
        conn,
        "AAA",
        pd.date_range("2020-01-06", periods=60, freq="W-MON"),
        start_price=20.0,
        step=0.1,
    )

    live_positions = pd.DataFrame([{"symbol": "AAA", "value": 1000.0}])
    with patch("services.bourse_analytics.get_live_bourse_positions", return_value=live_positions):
        payload = build_current_portfolio_backtest(conn, person_id=1, horizon="max", benchmark_symbol="URTH")

    assert "error" in payload
    assert "Benchmark 'URTH'" in payload["error"]


def test_projection_service_backtest_facade_calls_dedicated_service():
    expected = {"ok": True}
    with patch(
        "services.portfolio_backtest_service.build_current_portfolio_backtest",
        return_value=expected,
    ) as mocked:
        out = ProjectionService.build_current_portfolio_backtest(
            conn=None,
            person_id=12,
            horizon="5y",
            benchmark_symbol=None,
            ignore_limiting_assets=True,
        )

    assert out is expected
    mocked.assert_called_once_with(
        conn=None,
        person_id=12,
        horizon="5y",
        benchmark_symbol="URTH",
        ignore_limiting_assets=True,
    )
