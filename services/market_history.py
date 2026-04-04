from __future__ import annotations
import datetime as dt
import logging
from typing import Iterable
from services import market_repository as mrepo

_logger = logging.getLogger(__name__)

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
    """
    Synchronise les taux de change hebdomadaires pour chaque paire (base, quote).

    Pour chaque paire, on essaie d'abord le symbole direct (ex: COPEUR=X).
    Si yfinance ne retourne rien (paire exotique absente), on essaie la paire
    inverse (ex: EURCOP=X) et on la stocke sous (quote, base) — get_fx_asof
    sait déjà inverser automatiquement pour retrouver (base, quote).
    """
    pairs = [(a.upper(), b.upper()) for a, b in (pairs or []) if a and b and a.upper() != b.upper()]
    if not pairs:
        return {"did_run": False, "n_rows": 0, "reason": "no_pairs"}

    # Télécharger direct ET inverse pour maximiser la couverture yfinance
    all_symbols = list({
        sym
        for base, quote in pairs
        for sym in (fx_pair_to_yf_symbol(base, quote), fx_pair_to_yf_symbol(quote, base))
    })
    sync_asset_prices_weekly(conn, all_symbols, start_date, end_date)

    start = _to_date(start_date)
    end = _to_date(end_date)
    weeks = _week_list(start, end)
    if not weeks:
        return {"did_run": True, "n_rows": 0}

    n_fx = 0
    for base, quote in pairs:
        direct_sym  = fx_pair_to_yf_symbol(base, quote)   # ex: COPEUR=X
        inverse_sym = fx_pair_to_yf_symbol(quote, base)   # ex: EURCOP=X

        rows = conn.execute(
            "SELECT week_date, adj_close FROM asset_prices_weekly "
            "WHERE symbol = ? AND week_date >= ? AND week_date <= ?",
            (direct_sym, weeks[0], weeks[-1]),
        ).fetchall()

        if rows:
            # Paire directe disponible → stocker (base, quote, rate)
            for r in rows:
                mrepo.upsert_fx_rate_weekly(conn, base, quote, r["week_date"], float(r["adj_close"]))
                n_fx += 1
        else:
            # Paire directe absente → essayer l'inverse et stocker (quote, base, rate)
            # get_fx_asof inversera automatiquement pour retrouver base→quote
            inv_rows = conn.execute(
                "SELECT week_date, adj_close FROM asset_prices_weekly "
                "WHERE symbol = ? AND week_date >= ? AND week_date <= ?",
                (inverse_sym, weeks[0], weeks[-1]),
            ).fetchall()
            if inv_rows:
                _logger.info(
                    "sync_fx_weekly: paire %s absente sur yfinance, "
                    "stockage de l'inverse %s (get_fx_asof inversera à la lecture).",
                    direct_sym, inverse_sym,
                )
            for r in inv_rows:
                mrepo.upsert_fx_rate_weekly(conn, quote, base, r["week_date"], float(r["adj_close"]))
                n_fx += 1

    conn.commit()
    return {"did_run": True, "n_rows": n_fx}

def get_price_asof(conn, symbol: str, week_date: str) -> float | None:
    row = mrepo.get_asset_price_asof(conn, symbol, week_date)
    return float(row["adj_close"]) if row else None

def get_fx_asof(conn, base_ccy: str, quote_ccy: str, week_date: str) -> float | None:
    base_ccy = base_ccy.upper()
    quote_ccy = quote_ccy.upper()
    if base_ccy == quote_ccy:
        return 1.0

    row = mrepo.get_fx_rate_asof(conn, base_ccy, quote_ccy, week_date)
    if row:
        return float(row["rate"])

    inv = mrepo.get_fx_rate_asof(conn, quote_ccy, base_ccy, week_date)
    if inv and float(inv["rate"]) != 0:
        return 1.0 / float(inv["rate"])

    return None

def convert_weekly(conn, amount: float, from_ccy: str, to_ccy: str, week_date: str) -> float:
    from_ccy = (from_ccy or "EUR").upper()
    to_ccy = (to_ccy or "EUR").upper()
    if from_ccy == to_ccy:
        return float(amount)

    rate = get_fx_asof(conn, from_ccy, to_ccy, week_date)
    if rate is None:
        # FIX: on loggue explicitement — retourner le montant sans conversion peut fausser
        # les snapshots (ex: un actif USD serait compté 1-pour-1 en EUR)
        _logger.warning(
            "convert_weekly: taux %s→%s introuvable pour la semaine %s. "
            "Montant %.4f retourné SANS conversion — vérifier la table fx_rates_weekly.",
            from_ccy, to_ccy, week_date, amount,
        )
        return float(amount)  # fallback: montant brut sans conversion (taux manquant)
    return float(amount) * float(rate)
