"""
Résolution ISIN → ticker boursier.

Sources (par ordre de priorité) :
  1. Cache SQLite local  (table isin_ticker_cache)
  2. yfinance.Search     (renvoie des tickers Yahoo Finance directement utilisables)
  3. OpenFIGI API        (https://api.openfigi.com — gratuit, 25 req/min sans clé)

Usage :
    from services import isin_resolver
    ticker = isin_resolver.resolve_isin(conn, "IE00B4L5Y983")
    # → "EUNL.DE"  (ou None si non trouvé)

    mapping = isin_resolver.batch_resolve_isins(conn, ["IE00B4L5Y983", "US0378331005"])
    # → {"IE00B4L5Y983": "EUNL.DE", "US0378331005": "AAPL"}
"""
from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_OPENFIGI_HEADERS = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Cache DB
# ---------------------------------------------------------------------------

def _ensure_cache(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS isin_ticker_cache (
            isin        TEXT PRIMARY KEY,
            ticker      TEXT,
            source      TEXT,
            resolved_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _get_cached(conn, isin: str) -> str | None:
    """
    Retourne :
      - str non-vide  → ticker trouvé en cache
      - ""            → ISIN déjà cherché, aucun ticker trouvé
      - None          → pas encore en cache (première fois)
    """
    _ensure_cache(conn)
    row = conn.execute(
        "SELECT ticker FROM isin_ticker_cache WHERE isin = ?", (isin.upper(),)
    ).fetchone()
    if row is None:
        return None
    val = row[0] if not hasattr(row, "keys") else row["ticker"]
    return val if val is not None else ""


def _set_cached(conn, isin: str, ticker: str, source: str) -> None:
    _ensure_cache(conn)
    conn.execute(
        """
        INSERT INTO isin_ticker_cache(isin, ticker, source, resolved_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(isin) DO UPDATE SET
            ticker      = excluded.ticker,
            source      = excluded.source,
            resolved_at = excluded.resolved_at
        """,
        (isin.upper(), ticker, source),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Sources de résolution
# ---------------------------------------------------------------------------

def _via_yfinance(isin: str) -> str | None:
    """
    Résout ISIN via yfinance.Search.
    Retourne un ticker Yahoo Finance (avec suffixe exchange si nécessaire, ex: EUNL.DE).
    Préfère les types EQUITY et ETF.
    """
    try:
        import yfinance as yf
        search = yf.Search(isin, max_results=5, enable_fuzzy_query=False)
        quotes = search.quotes
        if not quotes:
            return None
        # Préférer Equity / ETF
        for q in quotes:
            symbol = q.get("symbol", "")
            qtype = q.get("quoteType", "").upper()
            if symbol and qtype in ("EQUITY", "ETF", "MUTUALFUND"):
                return symbol
        # Fallback : premier résultat
        first = quotes[0].get("symbol")
        return first or None
    except Exception as e:
        logger.debug("yfinance.Search(%s): %s", isin, e)
        return None


def _via_openfigi_single(isin: str) -> str | None:
    """
    Résout ISIN via l'API OpenFIGI (requête individuelle).
    Retourne le ticker OpenFIGI (peut être sans suffixe exchange).
    Respecte la limite de 25 req/min avec un délai de 0.3 s.
    """
    body = [{"idType": "ID_ISIN", "idValue": isin}]
    try:
        resp = requests.post(
            _OPENFIGI_URL, json=body, headers=_OPENFIGI_HEADERS, timeout=10
        )
        time.sleep(0.3)  # rate limit : 25 req/min sans clé API
        if resp.status_code != 200:
            logger.debug("OpenFIGI HTTP %d pour %s", resp.status_code, isin)
            return None
        data = resp.json()
        if not data or "data" not in data[0] or not data[0]["data"]:
            return None
        items = data[0]["data"]
        # Priorité aux résultats Equity
        for item in items:
            t = item.get("ticker", "")
            sector = item.get("marketSector", "")
            if t and sector in ("Equity",):
                return t
        # Fallback : premier ticker disponible
        return items[0].get("ticker") or None
    except Exception as e:
        logger.debug("OpenFIGI single(%s): %s", isin, e)
        return None


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def resolve_isin(conn, isin: str) -> str | None:
    """
    Résout un ISIN en ticker boursier.

    Ordre : cache DB → yfinance.Search → OpenFIGI.
    Retourne None si aucun ticker n'a pu être trouvé.
    Met le résultat en cache (y compris "non trouvé") pour éviter des appels API répétés.
    """
    if not isin or not str(isin).strip():
        return None
    isin = str(isin).strip().upper()

    # 1. Cache DB
    cached = _get_cached(conn, isin)
    if cached is not None:
        return cached or None  # "" → None

    # 2. yfinance Search
    ticker = _via_yfinance(isin)
    if ticker:
        _set_cached(conn, isin, ticker, "yfinance")
        logger.info("ISIN %s → %s  (via yfinance)", isin, ticker)
        return ticker

    # 3. OpenFIGI fallback
    ticker = _via_openfigi_single(isin)
    if ticker:
        _set_cached(conn, isin, ticker, "openfigi")
        logger.info("ISIN %s → %s  (via openfigi)", isin, ticker)
        return ticker

    # Non résolu — on met quand même en cache pour éviter de re-chercher
    _set_cached(conn, isin, "", "not_found")
    logger.warning("ISIN %s : aucun ticker trouvé (yfinance + openfigi)", isin)
    return None


def batch_resolve_isins(conn, isins: list[str]) -> dict[str, str]:
    """
    Résout une liste d'ISINs en tickers (mode batch).

    Stratégie :
      1. Retourne instantanément les ISINs déjà en cache.
      2. Pour les nouveaux : yfinance individuel (résultats Yahoo Finance directs).
      3. Pour ceux non trouvés par yfinance : OpenFIGI batch (25 max par requête).

    Retourne un dict {ISIN_MAJUSCULE: ticker} — seuls les ISINs résolus sont inclus.
    """
    if not isins:
        return {}

    _ensure_cache(conn)
    result: dict[str, str] = {}
    to_fetch: list[str] = []

    # 1. Vérification du cache
    for raw in isins:
        if not raw or not str(raw).strip():
            continue
        isin = str(raw).strip().upper()
        cached = _get_cached(conn, isin)
        if cached is not None:
            if cached:  # non-vide = ticker trouvé
                result[isin] = cached
            # "" = déjà cherché et non trouvé, on n'essaie pas à nouveau
        else:
            to_fetch.append(isin)

    if not to_fetch:
        return result

    # 2. yfinance individuel pour les ISINs non cachés
    openfigi_fallback: list[str] = []
    for isin in to_fetch:
        t = _via_yfinance(isin)
        if t:
            result[isin] = t
            _set_cached(conn, isin, t, "yfinance")
            logger.info("ISIN %s → %s  (via yfinance)", isin, t)
        else:
            openfigi_fallback.append(isin)

    if not openfigi_fallback:
        return result

    # 3. OpenFIGI batch pour ceux que yfinance n'a pas trouvés
    BATCH = 25
    for i in range(0, len(openfigi_fallback), BATCH):
        chunk = openfigi_fallback[i : i + BATCH]
        body = [{"idType": "ID_ISIN", "idValue": isin} for isin in chunk]
        try:
            resp = requests.post(
                _OPENFIGI_URL, json=body, headers=_OPENFIGI_HEADERS, timeout=15
            )
            time.sleep(0.5)

            if resp.status_code == 200:
                data = resp.json()
                for j, isin in enumerate(chunk):
                    entry = data[j] if j < len(data) else {}
                    items = entry.get("data") or []
                    ticker = ""
                    for item in items:
                        t = item.get("ticker", "")
                        if t:
                            ticker = t
                            break
                    if ticker:
                        result[isin] = ticker
                        _set_cached(conn, isin, ticker, "openfigi_batch")
                        logger.info("ISIN %s → %s  (via openfigi_batch)", isin, ticker)
                    else:
                        _set_cached(conn, isin, "", "not_found")
                        logger.warning("ISIN %s : non résolu (openfigi_batch)", isin)

            elif resp.status_code == 429:
                logger.warning(
                    "OpenFIGI rate limit (429) — %d ISIN(s) non résolus : %s",
                    len(chunk), chunk,
                )
                for isin in chunk:
                    _set_cached(conn, isin, "", "rate_limited")

            else:
                logger.warning(
                    "OpenFIGI HTTP %d pour batch — %d ISIN(s) non résolus",
                    resp.status_code, len(chunk),
                )
                for isin in chunk:
                    _set_cached(conn, isin, "", "error")

        except Exception as e:
            logger.warning("OpenFIGI batch error: %s", e)
            for isin in chunk:
                _set_cached(conn, isin, "", "error")

    return result


def clear_cache(conn, isin: str | None = None) -> int:
    """
    Vide le cache ISIN.
    - Si isin fourni : supprime uniquement cet ISIN.
    - Sinon : vide toute la table.
    Retourne le nombre de lignes supprimées.
    """
    _ensure_cache(conn)
    if isin:
        cur = conn.execute(
            "DELETE FROM isin_ticker_cache WHERE isin = ?", (isin.strip().upper(),)
        )
    else:
        cur = conn.execute("DELETE FROM isin_ticker_cache")
    conn.commit()
    return cur.rowcount
