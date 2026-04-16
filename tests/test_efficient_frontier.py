import numpy as np

from services.efficient_frontier import (
    FrontierConstraints,
    build_constraints_from_settings,
    optimize_efficient_frontier,
)


def _make_cov(stds: list[float], corr: float = 0.25) -> np.ndarray:
    sig = np.asarray(stds, dtype=float)
    cov = np.outer(sig, sig) * corr
    np.fill_diagonal(cov, np.square(sig))
    return cov


def test_few_assets_portfolio_is_supported_when_constraints_are_feasible():
    tickers = ["A", "B", "C"]
    mean = np.array([0.08, 0.06, 0.05], dtype=float)
    cov = _make_cov([0.18, 0.16, 0.14], corr=0.2)
    constraints = FrontierConstraints(
        max_weight_per_asset=0.70,
        min_assets=2,
        min_active_weight=0.02,
        max_assets=3,
        allow_tiny_residuals=False,
    )

    payload = optimize_efficient_frontier(
        mean_returns=mean,
        cov_matrix=cov,
        tickers=tickers,
        risk_free_rate=0.03,
        constraints=constraints,
    )
    assert "error" not in payload
    assert payload["max_sharpe"]["diversification"]["n_assets"] >= 2


def test_many_assets_portfolio_respects_diversification_constraints():
    tickers = [f"A{i}" for i in range(12)]
    mean = np.array([0.085, 0.08, 0.075, 0.07, 0.068, 0.066, 0.064, 0.062, 0.061, 0.06, 0.059, 0.058])
    cov = _make_cov([0.22, 0.21, 0.20, 0.19, 0.18, 0.17, 0.17, 0.16, 0.16, 0.15, 0.15, 0.14], corr=0.25)
    constraints = FrontierConstraints(
        max_weight_per_asset=0.15,
        min_assets=8,
        min_active_weight=0.01,
        max_assets=10,
        allow_tiny_residuals=False,
    )

    payload = optimize_efficient_frontier(
        mean_returns=mean,
        cov_matrix=cov,
        tickers=tickers,
        risk_free_rate=0.03,
        constraints=constraints,
    )
    assert "error" not in payload
    div = payload["max_sharpe"]["diversification"]
    assert div["n_assets"] >= 8
    assert div["largest_position_pct"] <= 15.1


def test_constraints_too_strict_return_clear_error():
    tickers = ["A", "B", "C", "D"]
    mean = np.array([0.08, 0.07, 0.06, 0.05], dtype=float)
    cov = _make_cov([0.20, 0.20, 0.18, 0.18], corr=0.3)
    constraints = FrontierConstraints(
        max_weight_per_asset=0.20,  # 4 x 20% = 80% < 100% -> impossible
        min_assets=4,
        min_active_weight=0.01,
        max_assets=4,
        allow_tiny_residuals=False,
    )

    payload = optimize_efficient_frontier(
        mean_returns=mean,
        cov_matrix=cov,
        tickers=tickers,
        risk_free_rate=0.03,
        constraints=constraints,
    )
    assert "error" in payload
    assert "contraintes" in payload["error"].lower()


def test_close_returns_case_remains_stable():
    tickers = [f"T{i}" for i in range(8)]
    mean = np.array([0.060, 0.0605, 0.0598, 0.0602, 0.0601, 0.0599, 0.0603, 0.0604], dtype=float)
    cov = _make_cov([0.14, 0.145, 0.138, 0.142, 0.141, 0.139, 0.143, 0.140], corr=0.35)
    constraints = FrontierConstraints(
        max_weight_per_asset=0.25,
        min_assets=5,
        min_active_weight=0.01,
        max_assets=8,
        allow_tiny_residuals=True,
    )

    payload = optimize_efficient_frontier(
        mean_returns=mean,
        cov_matrix=cov,
        tickers=tickers,
        risk_free_rate=0.03,
        constraints=constraints,
    )
    assert "error" not in payload
    assert len(payload["frontier_points"]) >= 1


def test_diversification_constraints_reduce_concentration_vs_free_mode():
    tickers = [f"X{i}" for i in range(9)]
    # Actif X0 dominant en rendement -> mode libre tend vers concentration.
    mean = np.array([0.16, 0.085, 0.082, 0.08, 0.078, 0.076, 0.074, 0.072, 0.07], dtype=float)
    cov = _make_cov([0.20, 0.18, 0.18, 0.17, 0.17, 0.16, 0.16, 0.15, 0.15], corr=0.2)

    free_constraints = FrontierConstraints(
        max_weight_per_asset=1.0,
        min_assets=2,
        min_active_weight=0.0,
        max_assets=None,
        allow_tiny_residuals=True,
    )
    diversified_constraints = FrontierConstraints(
        max_weight_per_asset=0.25,
        min_assets=5,
        min_active_weight=0.01,
        max_assets=7,
        allow_tiny_residuals=False,
    )

    free_payload = optimize_efficient_frontier(
        mean_returns=mean,
        cov_matrix=cov,
        tickers=tickers,
        risk_free_rate=0.03,
        constraints=free_constraints,
    )
    div_payload = optimize_efficient_frontier(
        mean_returns=mean,
        cov_matrix=cov,
        tickers=tickers,
        risk_free_rate=0.03,
        constraints=diversified_constraints,
    )
    assert "error" not in free_payload
    assert "error" not in div_payload

    free_largest = free_payload["max_sharpe"]["diversification"]["largest_position_pct"]
    div_largest = div_payload["max_sharpe"]["diversification"]["largest_position_pct"]
    assert div_largest < free_largest


def test_validation_catches_too_many_min_assets():
    constraints, warnings, errors = build_constraints_from_settings(
        {
            "preset": "free",
            "advanced": {
                "min_assets": 10,
                "max_weight_per_asset": 0.5,
            },
        },
        n_assets=6,
    )
    assert isinstance(constraints, FrontierConstraints)
    assert isinstance(warnings, list)
    assert errors
    assert "dépasse" in " ".join(errors).lower()
