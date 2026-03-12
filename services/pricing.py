from __future__ import annotations
import datetime as dt
import requests


def today_str() -> str:
    return dt.date.today().isoformat()


def fetch_last_price_auto(symbol: str) -> tuple[float | None, str]:
    """
    Retourne (prix, devise).
    Utilise yfinance (fiable pour AAPL, ETF, etc.)
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None, "EUR"

    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        info = t.fast_info  # + rapide que info
        px = info.get("last_price", None) if info is not None else None
        ccy = info.get("currency", "EUR") if info is not None else "EUR"

        if px is None:
            # fallback
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                px = float(hist["Close"].iloc[-1])

        if px is not None and float(px) > 0:
            return float(px), str(ccy)

    except Exception:
        pass

    return None, "EUR"
