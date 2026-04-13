from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from services import market_history
from services import repositories as repo
from services.snapshots_compute import compute_weekly_snapshot_person, upsert_weekly_snapshot
from services.snapshots_helpers import (
    _get_last_snapshot_week_ts,
    _list_weeks,
    _sync_person_market_data_for_weeks,
    _today_paris_date,
)


def _build_snapshot_tx_cache(
    conn,
    person_id: int,
    accounts: "pd.DataFrame | None" = None,
) -> dict[int, pd.DataFrame]:
    """
    Précharge les transactions utiles au rebuild weekly.
    Inclut:
    - comptes BANQUE (et sous-comptes)
    - comptes bourse (PEA/CTO/CRYPTO)
    """
    tx_cache: dict[int, pd.DataFrame] = {}
    accounts = accounts if accounts is not None else repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return tx_cache

    account_ids_to_prefetch: set[int] = set()
    bank_accs = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"]
    for _, acc in bank_accs.iterrows():
        acc_id = int(acc["id"])
        try:
            is_container = repo.is_bank_container(conn, acc_id)
        except Exception:
            is_container = False

        if is_container:
            subs = repo.list_bank_subaccounts(conn, acc_id)
            if subs is not None and not subs.empty:
                for _, s in subs.iterrows():
                    account_ids_to_prefetch.add(int(s["sub_account_id"]))
        else:
            account_ids_to_prefetch.add(acc_id)

    bourse_accs = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])]
    for _, acc in bourse_accs.iterrows():
        account_ids_to_prefetch.add(int(acc["id"]))

    for account_id in sorted(account_ids_to_prefetch):
        df = repo.list_transactions(conn, person_id=person_id, account_id=account_id, limit=200000)
        if df is None or df.empty:
            continue
        cached = df.copy()
        cached["date_dt"] = pd.to_datetime(cached.get("date"), errors="coerce")
        cached = cached.dropna(subset=["date_dt"])
        if not cached.empty:
            tx_cache[account_id] = cached

    return tx_cache


def rebuild_snapshots_person(conn, person_id: int, lookback_days: int = 90) -> dict:
    end = market_history.week_start(_today_paris_date())
    start = end - dt.timedelta(days=int(lookback_days))
    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks"}

    _sync_person_market_data_for_weeks(conn, person_id, weeks[0], weeks[-1])
    accounts = repo.list_accounts(conn, person_id=person_id)
    tx_cache = _build_snapshot_tx_cache(conn, person_id, accounts=accounts)

    n_ok = 0
    for wd in weeks:
        payload = compute_weekly_snapshot_person(
            conn,
            person_id,
            wd,
            tx_cache=tx_cache,
            accounts_cache=accounts,
        )
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()
    return {"did_run": True, "n_weeks": len(weeks), "start": weeks[0], "end": weeks[-1], "n_ok": n_ok}


def rebuild_snapshots_person_missing_only(
    conn,
    person_id: int,
    lookback_days: int = 90,
    recalc_days: int = 0,
) -> dict:
    end = market_history.week_start(_today_paris_date())
    start = end - dt.timedelta(days=int(lookback_days))
    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks"}

    df_have = pd.read_sql_query(
        """
        SELECT week_date
        FROM patrimoine_snapshots_weekly
        WHERE person_id = ?
          AND week_date >= ?
          AND week_date <= ?
        """,
        conn,
        params=(int(person_id), str(weeks[0]), str(weeks[-1])),
    )
    have = set()
    if df_have is not None and not df_have.empty:
        have = set(df_have["week_date"].astype(str).tolist())

    missing = [wd for wd in weeks if wd not in have]
    recalc_weeks = []
    if int(recalc_days) > 0:
        recalc_start = end - dt.timedelta(days=int(recalc_days))
        recalc_weeks = _list_weeks(recalc_start, end)

    todo = sorted(set(missing + recalc_weeks))
    if not todo:
        return {"did_run": False, "reason": "nothing_to_do", "n_missing": 0, "n_recalc": 0}

    _sync_person_market_data_for_weeks(conn, person_id, weeks[0], weeks[-1])
    accounts = repo.list_accounts(conn, person_id=person_id)
    tx_cache = _build_snapshot_tx_cache(conn, person_id, accounts=accounts)

    n_ok = 0
    for wd in todo:
        payload = compute_weekly_snapshot_person(
            conn,
            person_id,
            wd,
            tx_cache=tx_cache,
            accounts_cache=accounts,
        )
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()
    return {
        "did_run": True,
        "mode": "MISSING_ONLY",
        "person_id": int(person_id),
        "window_start": weeks[0],
        "window_end": weeks[-1],
        "n_missing": len(missing),
        "n_recalc": len(recalc_weeks),
        "n_done": len(todo),
        "n_ok": n_ok,
    }


def rebuild_snapshots_person_from_last(
    conn,
    person_id: int,
    safety_weeks: int = 4,
    fallback_lookback_days: int = 90,
    cancel_check=None,
) -> dict:
    end = market_history.week_start(_today_paris_date())
    last_week = _get_last_snapshot_week_ts(conn, person_id)

    if last_week is None:
        start = end - dt.timedelta(days=int(fallback_lookback_days))
        start = market_history.week_start(start)
        mode = "FROM_LAST_FALLBACK"
    else:
        start = (last_week.date() - dt.timedelta(days=int(safety_weeks) * 7))
        start = market_history.week_start(start)
        mode = "FROM_LAST"

    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks", "mode": mode}

    _sync_person_market_data_for_weeks(conn, person_id, weeks[0], weeks[-1])
    accounts = repo.list_accounts(conn, person_id=person_id)
    tx_cache = _build_snapshot_tx_cache(conn, person_id, accounts=accounts)

    n_ok = 0
    for wd in weeks:
        if cancel_check and cancel_check():
            logging.getLogger(__name__).info("Rebuild cancelled. Processed %d/%d weeks.", n_ok, len(weeks))
            break
        payload = compute_weekly_snapshot_person(
            conn,
            person_id,
            wd,
            tx_cache=tx_cache,
            accounts_cache=accounts,
        )
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    if not (cancel_check and cancel_check()):
        conn.commit()
        max_row = conn.execute(
            "SELECT MAX(id) AS max_id, MAX(created_at) AS max_created FROM transactions WHERE person_id=?",
            (int(person_id),),
        ).fetchone()
        _set_person_watermark(
            conn,
            person_id,
            (int(max_row[0]) if max_row and max_row[0] is not None else None),
            (str(max_row[1]) if max_row and max_row[1] is not None else None),
        )
    else:
        conn.rollback()

    return {
        "did_run": True,
        "mode": mode,
        "person_id": int(person_id),
        "start": weeks[0],
        "end": weeks[-1],
        "safety_weeks": int(safety_weeks),
        "fallback_lookback_days": int(fallback_lookback_days),
        "n_weeks": len(weeks),
        "n_ok": n_ok,
    }


def has_new_transactions_since_person_watermark(conn, person_id: int) -> bool:
    """
    Indique s'il existe au moins une transaction nouvelle pour la personne
    depuis le dernier watermark enregistré.
    """
    wm = _get_person_watermark(conn, int(person_id))
    last_tx_id = wm.get("last_tx_id")

    if last_tx_id is None:
        row = conn.execute(
            "SELECT 1 FROM transactions WHERE person_id=? LIMIT 1",
            (int(person_id),),
        ).fetchone()
        return row is not None

    row = conn.execute(
        "SELECT 1 FROM transactions WHERE person_id=? AND id>? LIMIT 1",
        (int(person_id), int(last_tx_id)),
    ).fetchone()
    return row is not None


def _ensure_rebuild_watermarks(conn) -> None:
    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS rebuild_watermarks (
      scope TEXT NOT NULL,
      entity_id INTEGER NOT NULL,
      last_tx_id INTEGER,
      last_tx_created_at TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(scope, entity_id)
    );
    """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rw_scope_entity ON rebuild_watermarks(scope, entity_id);")
    conn.commit()


def _get_person_watermark(conn, person_id: int) -> dict:
    _ensure_rebuild_watermarks(conn)
    row = conn.execute(
        "SELECT last_tx_id, last_tx_created_at FROM rebuild_watermarks WHERE scope=? AND entity_id=?",
        ("WEEKLY_PERSON", int(person_id)),
    ).fetchone()
    if not row:
        return {"last_tx_id": None, "last_tx_created_at": None}
    try:
        return {"last_tx_id": row["last_tx_id"], "last_tx_created_at": row["last_tx_created_at"]}
    except (TypeError, KeyError):
        return {"last_tx_id": row[0], "last_tx_created_at": row[1]}


def _set_person_watermark(conn, person_id: int, last_tx_id: int | None, last_tx_created_at: str | None) -> None:
    _ensure_rebuild_watermarks(conn)
    now = pd.Timestamp.now(tz="Europe/Paris").replace(microsecond=0).isoformat()
    conn.execute(
        """
        INSERT INTO rebuild_watermarks(scope, entity_id, last_tx_id, last_tx_created_at, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(scope, entity_id) DO UPDATE SET
          last_tx_id = excluded.last_tx_id,
          last_tx_created_at = excluded.last_tx_created_at,
          updated_at = excluded.updated_at
        """,
        ("WEEKLY_PERSON", int(person_id), last_tx_id, last_tx_created_at, now),
    )
    conn.commit()


def rebuild_snapshots_person_backdated_aware(
    conn,
    person_id: int,
    safety_weeks: int = 4,
    fallback_lookback_days: int = 3650,
) -> dict:
    _ensure_rebuild_watermarks(conn)
    end = market_history.week_start(_today_paris_date())

    wm = _get_person_watermark(conn, person_id)
    last_tx_id = wm.get("last_tx_id")

    if last_tx_id is None:
        df_new = pd.read_sql_query(
            """
            SELECT t.id, t.date, t.created_at, t.asset_id,
                   a.symbol AS asset_symbol
            FROM transactions t
            LEFT JOIN assets a ON a.id = t.asset_id
            WHERE t.person_id=?
            ORDER BY t.id ASC
            """,
            conn,
            params=(int(person_id),),
        )
    else:
        df_new = pd.read_sql_query(
            """
            SELECT t.id, t.date, t.created_at, t.asset_id,
                   a.symbol AS asset_symbol
            FROM transactions t
            LEFT JOIN assets a ON a.id = t.asset_id
            WHERE t.person_id=? AND t.id > ?
            ORDER BY t.id ASC
            """,
            conn,
            params=(int(person_id), int(last_tx_id)),
        )

    if df_new is None or df_new.empty:
        return {"did_run": False, "mode": "BACKDATED_AWARE", "reason": "no_new_transactions", "person_id": int(person_id)}

    df_new["date"] = pd.to_datetime(df_new["date"], errors="coerce")
    df_new = df_new.dropna(subset=["date"])
    if df_new.empty:
        return {"did_run": False, "mode": "BACKDATED_AWARE", "reason": "new_transactions_no_valid_date", "person_id": int(person_id)}

    min_date = df_new["date"].min().date()
    start = market_history.week_start(min_date - dt.timedelta(days=int(safety_weeks) * 7))

    floor = end - dt.timedelta(days=int(fallback_lookback_days))
    floor = market_history.week_start(floor)
    truncated = False
    if start < floor:
        start = floor
        truncated = True

    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "mode": "BACKDATED_AWARE", "reason": "no_weeks", "person_id": int(person_id)}

    _sync_person_market_data_for_weeks(conn, person_id, weeks[0], weeks[-1])
    accounts = repo.list_accounts(conn, person_id=person_id)
    tx_cache = _build_snapshot_tx_cache(conn, person_id, accounts=accounts)

    n_ok = 0
    for wd in weeks:
        payload = compute_weekly_snapshot_person(
            conn,
            person_id,
            wd,
            tx_cache=tx_cache,
            accounts_cache=accounts,
        )
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()

    max_row = conn.execute(
        "SELECT MAX(id) AS max_id, MAX(created_at) AS max_created FROM transactions WHERE person_id=?",
        (int(person_id),),
    ).fetchone()
    _set_person_watermark(
        conn,
        person_id,
        (int(max_row[0]) if max_row and max_row[0] is not None else None),
        (str(max_row[1]) if max_row and max_row[1] is not None else None),
    )

    return {
        "did_run": True,
        "mode": "BACKDATED_AWARE",
        "person_id": int(person_id),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "n_weeks": len(weeks),
        "n_ok": n_ok,
        "truncated": truncated,
    }


def get_first_transaction_date(conn, person_id: int):
    """Retourne la date de la premiere transaction pour une personne, ou None."""
    row = conn.execute(
        "SELECT MIN(date) AS first_date FROM transactions WHERE person_id = ?",
        (int(person_id),),
    ).fetchone()
    if row is None:
        return None
    try:
        raw = row["first_date"]
    except (TypeError, IndexError):
        raw = row[0]
    if raw is None:
        return None
    import datetime as _dt
    try:
        return _dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def rebuild_snapshots_person_full_history(
    conn,
    person_id: int,
    cancel_check=None,
    progress_callback=None,
) -> dict:
    """Reconstruit depuis la premiere transaction. progress_callback(week, year, idx, total)."""
    end = market_history.week_start(_today_paris_date())
    first_tx_date = get_first_transaction_date(conn, person_id)
    if first_tx_date is None:
        return {"did_run": False, "reason": "no_transactions", "mode": "FULL_HISTORY"}
    start = market_history.week_start(first_tx_date)
    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks", "mode": "FULL_HISTORY"}
    _sync_person_market_data_for_weeks(conn, person_id, weeks[0], weeks[-1])
    accounts = repo.list_accounts(conn, person_id=person_id)
    tx_cache = _build_snapshot_tx_cache(conn, person_id, accounts=accounts)
    n_ok = 0
    total_weeks = len(weeks)
    for week_index, wd in enumerate(weeks):
        if cancel_check and cancel_check():
            logging.getLogger(__name__).info(
                "Full-history rebuild cancelled. %d/%d weeks.", n_ok, total_weeks
            )
            break
        if progress_callback is not None:
            current_year = int(str(wd)[:4])
            progress_callback(
                current_week=str(wd),
                current_year=current_year,
                week_index=week_index,
                total_weeks=total_weeks,
            )
        payload = compute_weekly_snapshot_person(
            conn, person_id, wd, tx_cache=tx_cache, accounts_cache=accounts,
        )
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1
    cancelled = bool(cancel_check and cancel_check())
    if not cancelled:
        conn.commit()
        max_row = conn.execute(
            "SELECT MAX(id) AS max_id, MAX(created_at) AS max_created FROM transactions WHERE person_id=?",
            (int(person_id),),
        ).fetchone()
        _set_person_watermark(
            conn, person_id,
            (int(max_row[0]) if max_row and max_row[0] is not None else None),
            (str(max_row[1]) if max_row and max_row[1] is not None else None),
        )
    else:
        conn.rollback()
    return {
        "did_run": True,
        "mode": "FULL_HISTORY",
        "person_id": int(person_id),
        "start": str(weeks[0]),
        "end": str(weeks[-1]),
        "n_weeks": total_weeks,
        "n_ok": n_ok,
        "cancelled": cancelled,
    }
