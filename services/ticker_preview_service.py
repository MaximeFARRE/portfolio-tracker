from __future__ import annotations

import time

_PREVIEW_CACHE_TTL_SEC = 20.0
_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}


def _norm_symbol(symbol: str | None) -> str:
    return (symbol or "").strip().upper()


def _safe_price(raw) -> float | None:
    try:
        if raw is None:
            return None
        val = float(raw)
    except Exception:
        return None
    if val <= 0:
        return None
    return val


def _copy_result(result: dict) -> dict:
    return {
        "found": bool(result.get("found")),
        "name": result.get("name"),
        "price": result.get("price"),
        "currency": result.get("currency"),
        "status": result.get("status"),
        "warning": result.get("warning"),
    }


def preview_ticker_live(symbol: str) -> dict:
    """
    Preview live d'un ticker.

    Output:
      found, name, price, currency, status, warning

    Garantie:
      - ne renvoie jamais un faux prix 0
      - price est None si introuvable
    """
    symbol_u = _norm_symbol(symbol)
    if not symbol_u:
        return {
            "found": False,
            "name": None,
            "price": None,
            "currency": None,
            "status": "empty",
            "warning": "Symbole vide.",
        }

    now = time.time()
    cached = _PREVIEW_CACHE.get(symbol_u)
    if cached is not None:
        ts, payload = cached
        if (now - ts) <= _PREVIEW_CACHE_TTL_SEC:
            return _copy_result(payload)

    result = {
        "found": False,
        "name": symbol_u,
        "price": None,
        "currency": None,
        "status": "not_found",
        "warning": "Ticker introuvable.",
    }

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol_u)
        fast = ticker.fast_info or {}

        price = _safe_price(fast.get("last_price"))
        currency = fast.get("currency")

        if price is None:
            try:
                hist = ticker.history(period="5d")
                if hist is not None and not hist.empty:
                    price = _safe_price(hist["Close"].iloc[-1])
            except Exception:
                pass

        name = None
        try:
            search = yf.Search(symbol_u, max_results=1, enable_fuzzy_query=False)
            if getattr(search, "quotes", None):
                q0 = search.quotes[0] or {}
                name = (
                    q0.get("shortname")
                    or q0.get("longname")
                    or q0.get("displayName")
                    or q0.get("symbol")
                )
        except Exception:
            name = None

        result["name"] = str(name or symbol_u)
        result["currency"] = str(currency).upper() if currency else None
        result["price"] = price

        if price is not None:
            result["found"] = True
            result["status"] = "ok"
            result["warning"] = None
        elif name:
            result["found"] = True
            result["status"] = "partial"
            result["warning"] = "Prix live indisponible."
        else:
            result["found"] = False
            result["status"] = "not_found"
            result["warning"] = "Ticker introuvable."

    except Exception as exc:
        result = {
            "found": False,
            "name": symbol_u,
            "price": None,
            "currency": None,
            "status": "error",
            "warning": str(exc),
        }

    _PREVIEW_CACHE[symbol_u] = (now, result)
    return _copy_result(result)
