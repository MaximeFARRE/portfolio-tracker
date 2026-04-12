from __future__ import annotations

import logging

import pandas as pd

from services.snapshots_helpers import _snapshot_row_to_dict

_logger = logging.getLogger(__name__)


PERSON_WEEKLY_COLUMNS = [
    "week_date",
    "patrimoine_net",
    "patrimoine_brut",
    "liquidites_total",
    "bourse_holdings",
    "pe_value",
    "ent_value",
    "immobilier_value",
    "credits_remaining",
]


def get_person_weekly_series(conn, person_id: int) -> pd.DataFrame:
    empty = pd.DataFrame(columns=PERSON_WEEKLY_COLUMNS)

    try:
        rows = conn.execute(
            """
            SELECT week_date,
                   patrimoine_net,
                   patrimoine_brut,
                   liquidites_total,
                   bourse_holdings,
                   pe_value,
                   ent_value,
                   immobilier_value,
                   credits_remaining
            FROM patrimoine_snapshots_weekly
            WHERE person_id = ?
            ORDER BY week_date ASC
            """,
            (int(person_id),),
        ).fetchall()
        df = pd.DataFrame(rows, columns=PERSON_WEEKLY_COLUMNS) if rows else pd.DataFrame(columns=PERSON_WEEKLY_COLUMNS)
    except Exception:
        _logger.error(
            "get_person_weekly_series: erreur lecture snapshots pour person_id=%s",
            person_id, exc_info=True,
        )
        return empty

    if df is None or df.empty:
        _logger.info("get_person_weekly_series: aucun snapshot pour person_id=%s", person_id)
        return empty

    df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
    n_before = len(df)
    df = df.dropna(subset=["week_date"]).sort_values("week_date")
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        _logger.warning(
            "get_person_weekly_series: %d ligne(s) ignorée(s) (date invalide) "
            "pour person_id=%s", n_dropped, person_id,
        )

    for col in PERSON_WEEKLY_COLUMNS:
        if col == "week_date":
            continue
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df[PERSON_WEEKLY_COLUMNS].reset_index(drop=True)


def get_latest_person_snapshot(conn, person_id: int) -> dict | None:
    if person_id is None:
        _logger.warning("get_latest_person_snapshot: person_id est None")
        return None

    try:
        row = conn.execute(
            """
            SELECT week_date, patrimoine_net, patrimoine_brut,
                   liquidites_total, bourse_holdings, immobilier_value,
                   pe_value, ent_value, credits_remaining
            FROM patrimoine_snapshots_weekly
            WHERE person_id = ?
            ORDER BY week_date DESC, id DESC
            LIMIT 1
            """,
            (int(person_id),),
        ).fetchone()
    except Exception:
        _logger.error(
            "get_latest_person_snapshot: erreur lecture pour person_id=%s",
            person_id, exc_info=True,
        )
        return None

    if row is None:
        _logger.info("get_latest_person_snapshot: aucun snapshot pour person_id=%s", person_id)
        return None

    return _snapshot_row_to_dict(row, person_id=int(person_id))


def get_latest_snapshot_notes(conn, person_id: int) -> str | None:
    """
    Retourne le champ ``notes`` du snapshot le plus récent d'une personne.

    Valeurs typiques: ``"complete"``, ``"partial_fx:2"``, ``"partial_price:1"``.
    Retourne None si aucun snapshot n'existe ou si la colonne est absente.
    """
    if person_id is None:
        return None
    try:
        row = conn.execute(
            "SELECT notes FROM patrimoine_snapshots_weekly WHERE person_id=? "
            "ORDER BY week_date DESC, id DESC LIMIT 1",
            (int(person_id),),
        ).fetchone()
        if row is None:
            return None
        return row["notes"] if "notes" in row.keys() else None
    except Exception:
        _logger.warning(
            "get_latest_snapshot_notes: erreur lecture pour person_id=%s",
            person_id, exc_info=True,
        )
        return None


def get_person_snapshot_at_week(
    conn,
    person_id: int,
    week_date: "pd.Timestamp | str",
) -> "dict | None":
    if person_id is None:
        _logger.warning("get_person_snapshot_at_week: person_id est None")
        return None

    try:
        if isinstance(week_date, str):
            week_str = week_date
        else:
            week_str = pd.Timestamp(week_date).strftime("%Y-%m-%d")
    except Exception:
        _logger.warning(
            "get_person_snapshot_at_week: week_date invalide (%r) pour person_id=%s",
            week_date, person_id,
        )
        return None

    try:
        row = conn.execute(
            """
            SELECT week_date, patrimoine_net, patrimoine_brut,
                   liquidites_total, bourse_holdings, immobilier_value,
                   pe_value, ent_value, credits_remaining
            FROM patrimoine_snapshots_weekly
            WHERE person_id = ? AND week_date = ?
            LIMIT 1
            """,
            (int(person_id), week_str),
        ).fetchone()
    except Exception:
        _logger.error(
            "get_person_snapshot_at_week: erreur lecture pour person_id=%s week_date=%s",
            person_id, week_str, exc_info=True,
        )
        return None

    if row is None:
        _logger.info(
            "get_person_snapshot_at_week: aucun snapshot pour person_id=%s semaine=%s",
            person_id, week_str,
        )
        return None

    return _snapshot_row_to_dict(
        row,
        person_id=int(person_id),
        week_str=week_str,
        warn_invalid_fields=True,
    )

