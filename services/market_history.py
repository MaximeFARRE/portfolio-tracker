from __future__ import annotations
import datetime as dt
import logging
import threading
from typing import Iterable
from services import market_repository as mrepo

_logger = logging.getLogger(__name__)

# ── Tracker de taux FX manquants ────────────────────────────────────────────
_missing_fx_lock: threading.Lock = threading.Lock()
_missing_fx_pairs: set[tuple[str, str]] = set()


def get_and_clear_missing_fx() -> set[tuple[str, str]]:
    """Retourne les paires FX manquantes depuis le dernier appel, puis remet à zéro."""
    global _missing_fx_pairs
    with _missing_fx_lock:
        result = set(_missing_fx_pairs)
        _missing_fx_pairs.clear()
    return result


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

    import pandas as pd
    
    # yfinance peut retourner un DataFrame vide si aucune donnée n'est trouvée
    if data is None or data.empty:
        return {"did_run": True, "n_rows": 0, "reason": "yfinance_empty"}

    for sym in symbols:
        try:
            # On cherche une colonne de prix dans le DataFrame
            # On gère le cas MultiIndex (plusieurs tickers) et SingleIndex (un seul)
            if isinstance(data.columns, pd.MultiIndex):
                # On essaie de trouver le sous-dataframe pour ce symbole
                # yf peut mettre le symbole en level 0 ou level 1
                if sym in data.columns.get_level_values(0):
                    sub = data[sym]
                elif sym in data.columns.get_level_values(1):
                    # Cas où le prix est en level 0 (ex: 'Close') et le ticker en level 1
                    sub = data.xs(sym, axis=1, level=1, drop_level=True)
                else:
                    continue
            else:
                # Index simple : un seul ticker a été demandé
                sub = data

            # Choix de la colonne (Adj Close en priorité)
            col_to_use = None
            for candidate in ["Adj Close", "Close"]:
                if candidate in sub.columns:
                    col_to_use = candidate
                    break
            
            if col_to_use:
                s = sub[col_to_use].dropna()
                for idx, px in s.items():
                    wd = week_start(idx.date()).isoformat()
                    mrepo.upsert_asset_price_weekly(conn, sym, wd, float(px))
                    n_rows += 1
        except Exception as e:
            _logger.debug("Erreur lors du traitement de %s : %s", sym, e)

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
    pivot_pairs_extra: set[tuple[str, str]] = set()

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
            # Paire directe absente → essayer l'inverse
            inv_rows = conn.execute(
                "SELECT week_date, adj_close FROM asset_prices_weekly "
                "WHERE symbol = ? AND week_date >= ? AND week_date <= ?",
                (inverse_sym, weeks[0], weeks[-1]),
            ).fetchall()
            if inv_rows:
                _logger.info(
                    "sync_fx_weekly: paire %s absente sur yfinance, "
                    "stockage de l'inverse %s.",
                    direct_sym, inverse_sym,
                )
                for r in inv_rows:
                    mrepo.upsert_fx_rate_weekly(conn, quote, base, r["week_date"], float(r["adj_close"]))
                    n_fx += 1
            else:
                # Direct et inverse absents → paire exotique, ajouter les paires
                # pivot via USD pour permettre le cross-rate dans get_fx_asof
                _PIVOT = "USD"
                if base != _PIVOT and quote != _PIVOT:
                    _logger.info(
                        "sync_fx_weekly: ni %s ni %s disponibles sur yfinance. "
                        "Ajout des paires pivot %s↔%s et %s↔%s pour cross-rate via USD.",
                        direct_sym, inverse_sym,
                        base, _PIVOT, _PIVOT, quote,
                    )
                    pivot_pairs_extra.add((base,  _PIVOT))
                    pivot_pairs_extra.add((_PIVOT, quote))

    # Synchroniser les paires pivot USD collectées pour les devises exotiques
    if pivot_pairs_extra:
        extra_syms = list({
            sym
            for b, q in pivot_pairs_extra
            for sym in (fx_pair_to_yf_symbol(b, q), fx_pair_to_yf_symbol(q, b))
        })
        sync_asset_prices_weekly(conn, extra_syms, start_date, end_date)
        for b, q in pivot_pairs_extra:
            direct_sym  = fx_pair_to_yf_symbol(b, q)
            inverse_sym = fx_pair_to_yf_symbol(q, b)
            for sym, store_b, store_q in [(direct_sym, b, q), (inverse_sym, q, b)]:
                rows = conn.execute(
                    "SELECT week_date, adj_close FROM asset_prices_weekly "
                    "WHERE symbol = ? AND week_date >= ? AND week_date <= ?",
                    (sym, weeks[0], weeks[-1]),
                ).fetchall()
                for r in rows:
                    mrepo.upsert_fx_rate_weekly(conn, store_b, store_q, r["week_date"], float(r["adj_close"]))
                    n_fx += 1

    conn.commit()
    return {"did_run": True, "n_rows": n_fx}

def get_price_asof(conn, symbol: str, week_date: str) -> float | None:
    row = mrepo.get_asset_price_asof(conn, symbol, week_date)
    if not row:
        return None
    # SELECT symbol(0), week_date(1), adj_close(2), currency(3), source(4)
    return float(_row_val(row, "adj_close", 2))

def get_fx_asof(conn, base_ccy: str, quote_ccy: str, week_date: str,
                _depth: int = 0) -> float | None:
    """
    Retourne le taux base→quote à la semaine donnée.

    Stratégie (dans l'ordre) :
      1. Paire directe  (base, quote) dans fx_rates_weekly
      2. Paire inverse  (quote, base) → 1/rate
      3. Cross-rate via USD : base→USD→quote  (pour devises exotiques comme COP)
    """
    base_ccy  = base_ccy.upper()
    quote_ccy = quote_ccy.upper()
    if base_ccy == quote_ccy:
        return 1.0

# 1. Paire directe
    row = mrepo.get_fx_rate_asof(conn, base_ccy, quote_ccy, week_date)
    if row:
        return float(_row_val(row, "rate", 3))

    # 2. Paire inverse
    inv = mrepo.get_fx_rate_asof(conn, quote_ccy, base_ccy, week_date)
    if inv:
        rate_inv = float(_row_val(inv, "rate", 3))
        if rate_inv != 0:
            return 1.0 / rate_inv

    # 3. Cross-rate via USD (évite la récursion infinie via _depth)
    _PIVOT = "USD"
    if _depth == 0 and base_ccy != _PIVOT and quote_ccy != _PIVOT:
        r_base_usd = get_fx_asof(conn, base_ccy,  _PIVOT,    week_date, _depth=1)
        r_usd_quote = get_fx_asof(conn, _PIVOT,   quote_ccy, week_date, _depth=1)
        if r_base_usd is not None and r_usd_quote is not None:
            return float(r_base_usd) * float(r_usd_quote)

    return None

def convert_weekly(conn, amount: float, from_ccy: str, to_ccy: str, week_date: str) -> float:
    from_ccy = (from_ccy or "EUR").upper()
    to_ccy = (to_ccy or "EUR").upper()
    if from_ccy == to_ccy:
        return float(amount)

    rate = get_fx_asof(conn, from_ccy, to_ccy, week_date)
    if rate is None:
        _logger.error(
            "convert_weekly: taux %s→%s introuvable pour la semaine %s. "
            "VALEUR ANNULÉE (0.0) pour éviter une valorisation erronée — vérifier fx_rates_weekly.",
            from_ccy, to_ccy, week_date
        )
        with _missing_fx_lock:
            _missing_fx_pairs.add((from_ccy, to_ccy))
        return 0.0  # Sécurité : on préfère 0 que des milliards imaginaires (ex: COP counted as EUR)
    return float(amount) * float(rate)
