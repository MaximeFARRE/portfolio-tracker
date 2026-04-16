from unittest.mock import patch

import numpy as np
import pandas as pd

from services import bourse_advanced_analytics as baa


def test_portfolio_weekly_returns_are_cashflow_adjusted():
    weekly = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-08", "2024-01-15"]),
            "holdings_eur": [100.0, 150.0, 165.0],
        }
    )
    flows = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-08", "2024-01-15"]),
            "net_flow": [50.0, 0.0],
        }
    )

    with patch("services.bourse_advanced_analytics.bourse_analytics.get_bourse_weekly_series", return_value=weekly), patch(
        "services.bourse_advanced_analytics._portfolio_weekly_net_flows_eur", return_value=flows
    ):
        out = baa._portfolio_weekly_returns(conn=None, person_id=1)

    assert len(out) == 2
    # 100 -> 150 avec +50 de flux => performance nulle.
    assert abs(float(out.iloc[0]["simple_return"])) < 1e-12
    # 150 -> 165 sans flux => +10%.
    assert abs(float(out.iloc[1]["simple_return"]) - 0.10) < 1e-12
    assert abs(float(out.iloc[1]["log_return"]) - np.log1p(0.10)) < 1e-12


def test_risk_return_cagr_is_driven_by_adjusted_returns_not_raw_value():
    dates = pd.date_range("2024-01-01", periods=13, freq="W-MON")
    adjusted = pd.DataFrame(
        {
            "date": dates,
            # Valorisation en hausse (simule des apports), mais performance ajustée nulle.
            "value": np.linspace(100.0, 220.0, len(dates)),
            "net_flow": np.full(len(dates), 10.0),
            "simple_return": np.zeros(len(dates)),
            "log_return": np.zeros(len(dates)),
        }
    )

    with patch("services.bourse_advanced_analytics._portfolio_weekly_returns", return_value=adjusted), patch(
        "services.bourse_advanced_analytics._compute_beta", return_value=None
    ):
        payload = baa.get_risk_return_payload(conn=None, person_id=1)

    assert "error" not in payload
    assert payload["mean_return_ann_pct"] == 0.0
    assert payload["cagr_pct"] == 0.0
