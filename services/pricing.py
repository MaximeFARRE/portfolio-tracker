from __future__ import annotations
import datetime as dt
import time
import requests

_PRICE_CACHE_TTL_SEC = 15
_PRICE_CACHE: dict[str, tuple[float, tuple[float | None, str]]] = {}


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

    now_ts = time.time()
    cached = _PRICE_CACHE.get(symbol)
    if cached is not None:
        ts, payload = cached
        if (now_ts - ts) <= _PRICE_CACHE_TTL_SEC:
            return payload

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
            payload = (float(px), str(ccy))
            _PRICE_CACHE[symbol] = (now_ts, payload)
            return payload

    except Exception:
        pass

    _PRICE_CACHE[symbol] = (now_ts, (None, "EUR"))
    return None, "EUR"
