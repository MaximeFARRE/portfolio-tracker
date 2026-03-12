from __future__ import annotations
import pandas as pd
from services import repositories as repo
from services import market_history
from services import positions


def diagnose_bourse_asof(conn, person_id: int, asof_week_date: str) -> dict:
    """
    Diagnostic des données nécessaires à la bourse :
    - tickers sans prix weekly as-of
    - devises sans fx as-of
    - positions count
    """
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return {"ok": False, "reason": "no_accounts"}

    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
        return {"ok": False, "reason": "no_bourse_accounts"}

    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=asof_week_date, account_ids=acc_ids)
    if pos is None or pos.empty:
        return {"ok": True, "positions": 0, "missing_prices": [], "missing_fx": []}

    missing_prices = []
    missing_fx = set()

    for _, r in pos.iterrows():
        ticker = str(r.get("symbol") or "").strip()
        qty = float(r.get("quantity") or 0.0)
        ccy = str(r.get("asset_ccy") or "EUR").upper()
        if not ticker or qty <= 0:
            continue

        px = market_history.get_price_asof(conn, ticker, asof_week_date)
        if px is None:
            missing_prices.append(ticker)

        if ccy != "EUR":
            fx = market_history.get_fx_asof(conn, ccy, "EUR", asof_week_date)
            if fx is None:
                missing_fx.add((ccy, "EUR"))

    return {
        "ok": True,
        "positions": int(len(pos)),
        "missing_prices": sorted(list(set(missing_prices))),
        "missing_fx": sorted(list(missing_fx)),
    }


def last_market_dates(conn) -> dict:
    """
    Dernières dates en base pour prix et fx (utile debug)
    """
    def _get_d(row):
        if not row:
            return None
        try:
            return row["d"]
        except Exception:
            try:
                return row[0]
            except Exception:
                return None

    row_p = conn.execute("SELECT MAX(week_date) AS d FROM asset_prices_weekly").fetchone()
    row_f = conn.execute("SELECT MAX(week_date) AS d FROM fx_rates_weekly").fetchone()
    return {
        "last_price_week": _get_d(row_p),
        "last_fx_week": _get_d(row_f),
    }
