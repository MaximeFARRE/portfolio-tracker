from __future__ import annotations
import datetime as dt
from typing import Iterable
from services import market_repository as mrepo


def _row_val(row, key: str, idx: int):
    """Compat sqlite3.Row (accès par clé) et libsql (accès par index tuple)."""
    try:
        return row[key]
    except Exception:
        return row[idx]


def _to_date(d) -> dt.date:
    if isinstance(d, dt.date):
        return d
    return dt.date.fromisoformat(str(d))

def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())  # lundi

def _week_list(start: dt.date, end: dt.date) -> list[str]:
    s = week_start(start)
    e = week_start(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += dt.timedelta(days=7)
    return out

def sync_asset_prices_weekly(conn, symbols: Iterable[str], start_date: str, end_date: str) -> dict:
    symbols = [s.strip() for s in (symbols or []) if str(s).strip()]
    if not symbols:
        return {"did_run": False, "n_rows": 0, "reason": "no_symbols"}

    start = _to_date(start_date)
    end = _to_date(end_date)

    import yfinance as yf

    data = yf.download(
        tickers=" ".join(symbols),
        start=start.isoformat(),
        end=(end + dt.timedelta(days=1)).isoformat(),
        interval="1wk",
        auto_adjust=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )

    n_rows = 0

    # single
    if "Adj Close" in data.columns:
        s = data["Adj Close"].dropna()
        for idx, px in s.items():
            wd = week_start(idx.date()).isoformat()
            mrepo.upsert_asset_price_weekly(conn, symbols[0], wd, float(px))
            n_rows += 1
        conn.commit()
        return {"did_run": True, "n_rows": n_rows}

    # multi
    for sym in symbols:
        try:
            if sym not in data.columns:
                continue
            sub = data[sym]
            if "Adj Close" not in sub.columns:
                continue
            s = sub["Adj Close"].dropna()
            for idx, px in s.items():
                wd = week_start(idx.date()).isoformat()
                mrepo.upsert_asset_price_weekly(conn, sym, wd, float(px))
                n_rows += 1
        except Exception:
            continue

    conn.commit()
    return {"did_run": True, "n_rows": n_rows}

def fx_pair_to_yf_symbol(base_ccy: str, quote_ccy: str) -> str:
    return f"{base_ccy.upper()}{quote_ccy.upper()}=X"

def sync_fx_weekly(conn, pairs: list[tuple[str, str]], start_date: str, end_date: str) -> dict:
    pairs = [(a.upper(), b.upper()) for a, b in (pairs or []) if a and b and a.upper() != b.upper()]
    if not pairs:
        return {"did_run": False, "n_rows": 0, "reason": "no_pairs"}

    symbols = [fx_pair_to_yf_symbol(a, b) for a, b in pairs]
    sync_asset_prices_weekly(conn, symbols, start_date, end_date)

    start = _to_date(start_date)
    end = _to_date(end_date)
    weeks = _week_list(start, end)
    if not weeks:
        return {"did_run": True, "n_rows": 0}

    n_fx = 0
    for base, quote in pairs:
        yf_sym = fx_pair_to_yf_symbol(base, quote)
        rows = conn.execute(
            """
            SELECT week_date, adj_close
            FROM asset_prices_weekly
            WHERE symbol = ? AND week_date >= ? AND week_date <= ?
            """,
            (yf_sym, weeks[0], weeks[-1]),
        ).fetchall()

        for r in rows:
            # compat sqlite3.Row (clé) ET libsql (tuple index)
            week_date = _row_val(r, "week_date", 0)
            adj_close = _row_val(r, "adj_close", 1)
            mrepo.upsert_fx_rate_weekly(conn, base, quote, week_date, float(adj_close))
            n_fx += 1

    conn.commit()
    return {"did_run": True, "n_rows": n_fx}

def get_price_asof(conn, symbol: str, week_date: str) -> float | None:
    row = mrepo.get_asset_price_asof(conn, symbol, week_date)
    if not row:
        return None
    # SELECT symbol(0), week_date(1), adj_close(2), currency(3), source(4)
    return float(_row_val(row, "adj_close", 2))

def get_fx_asof(conn, base_ccy: str, quote_ccy: str, week_date: str) -> float | None:
    base_ccy = base_ccy.upper()
    quote_ccy = quote_ccy.upper()
    if base_ccy == quote_ccy:
        return 1.0

    # SELECT base_ccy(0), quote_ccy(1), week_date(2), rate(3), source(4)
    row = mrepo.get_fx_rate_asof(conn, base_ccy, quote_ccy, week_date)
    if row:
        return float(_row_val(row, "rate", 3))

    inv = mrepo.get_fx_rate_asof(conn, quote_ccy, base_ccy, week_date)
    if inv:
        rate_inv = float(_row_val(inv, "rate", 3))
        if rate_inv != 0:
            return 1.0 / rate_inv

    return None

def convert_weekly(conn, amount: float, from_ccy: str, to_ccy: str, week_date: str) -> float:
    from_ccy = (from_ccy or "EUR").upper()
    to_ccy = (to_ccy or "EUR").upper()
    if from_ccy == to_ccy:
        return float(amount)

    rate = get_fx_asof(conn, from_ccy, to_ccy, week_date)
    if rate is None:
        return float(amount)  # fallback safe
    return float(amount) * float(rate)
