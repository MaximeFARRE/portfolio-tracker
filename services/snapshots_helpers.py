from __future__ import annotations

import datetime as dt
import logging
from datetime import datetime

import pandas as pd
import pytz

from services import market_history
from services import repositories as repo

_logger = logging.getLogger(__name__)


def _now_paris_iso() -> str:
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).replace(microsecond=0).isoformat()


def _today_paris_date() -> dt.date:
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).date()


def _list_weeks(start: dt.date, end: dt.date) -> list[str]:
    s = market_history.week_start(start)
    e = market_history.week_start(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += dt.timedelta(days=7)
    return out


def _collect_person_market_sync_inputs(conn, person_id: int) -> tuple[list[str], list[tuple[str, str]]]:
    """Construit les symboles et paires FX à synchroniser pour une personne."""
    tx = repo.list_transactions(conn, person_id=person_id, limit=300000)
    symbols: list[str] = []
    pairs: set[tuple[str, str]] = set()

    if tx is not None and not tx.empty:
        tx2 = tx[tx["asset_symbol"].notna()].copy()
        symbols = sorted(set([str(s).strip() for s in tx2["asset_symbol"].tolist() if str(s).strip()]))

        asset_ids = sorted(set([int(x) for x in tx2["asset_id"].dropna().astype(int).tolist()]))
        if asset_ids:
            q = ",".join(["?"] * len(asset_ids))
            rows = conn.execute(f"SELECT id, currency FROM assets WHERE id IN ({q})", tuple(asset_ids)).fetchall()
            for r in rows:
                ccy = (r["currency"] or "EUR").upper()
                if ccy != "EUR":
                    pairs.add((ccy, "EUR"))

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is not None and not accounts.empty:
        for _, acc in accounts.iterrows():
            ccy = str(acc.get("currency") or "EUR").upper()
            if ccy != "EUR":
                pairs.add((ccy, "EUR"))

    pairs.add(("USD", "EUR"))
    return symbols, sorted(list(pairs))


def _sync_person_market_data_for_weeks(conn, person_id: int, week_start: str, week_end: str) -> None:
    """Synchronise les historiques marché utiles au rebuild entre deux semaines incluses."""
    symbols, pairs = _collect_person_market_sync_inputs(conn, person_id)
    if symbols:
        market_history.sync_asset_prices_weekly(conn, symbols, week_start, week_end)
    if pairs:
        market_history.sync_fx_weekly(conn, pairs, week_start, week_end)


def _get_last_snapshot_week_ts(conn, person_id: int) -> "pd.Timestamp | None":
    """Retourne la dernière week_date snapshot d'une personne (ou None)."""
    row = conn.execute(
        "SELECT MAX(week_date) AS d FROM patrimoine_snapshots_weekly WHERE person_id=?",
        (int(person_id),),
    ).fetchone()
    if not row:
        return None

    try:
        raw = row["d"]
    except (TypeError, KeyError):
        raw = row[0]

    if not raw:
        return None

    try:
        val = pd.to_datetime(raw, errors="coerce")
        return None if pd.isna(val) else val
    except Exception:
        return None


def _snapshot_row_to_dict(
    row,
    *,
    person_id: int,
    week_str: str | None = None,
    warn_invalid_fields: bool = False,
) -> dict:
    """Convertit une row snapshot SQLite en payload métier normalisé."""

    def _val(key: str) -> float:
        try:
            v = row[key]
            return float(v) if v is not None else 0.0
        except (KeyError, IndexError, TypeError, ValueError):
            if warn_invalid_fields:
                _logger.warning(
                    "get_person_snapshot_at_week: colonne '%s' absente ou invalide "
                    "pour person_id=%s semaine=%s", key, person_id, week_str,
                )
            return 0.0

    return {
        "week_date": str(row["week_date"]) if row["week_date"] else None,
        "patrimoine_net": _val("patrimoine_net"),
        "patrimoine_brut": _val("patrimoine_brut"),
        "liquidites_total": _val("liquidites_total"),
        "bourse_holdings": _val("bourse_holdings"),
        "immobilier_value": _val("immobilier_value"),
        "pe_value": _val("pe_value"),
        "ent_value": _val("ent_value"),
        "credits_remaining": _val("credits_remaining"),
    }

