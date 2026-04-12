"""
services/family_snapshots.py

Source canonique (SSOT) des données brutes du patrimoine famille.

Ce module est le seul autorisé à :
- lire et écrire dans `patrimoine_snapshots_family_weekly`,
- agréger les snapshots hebdomadaires par personne pour construire la série famille,
- rebuilder la série famille depuis les snapshots individuels.

Frontière : ce module NE contient PAS de KPI dérivés, de métriques de performance
ou de logique de présentation. Ces responsabilités appartiennent à `family_dashboard.py`.
"""
from __future__ import annotations
import pandas as pd
from datetime import datetime
import pytz

FAMILY_WEEKLY_COLUMNS = [
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

# _now_paris_iso existe aussi dans snapshots.py — on l'importe pour éviter la duplication.
from services.snapshots import _now_paris_iso



def list_family_weekly_snapshots(conn, family_id: int = 1) -> pd.DataFrame:
    _COLS = [
        "week_date", "created_at", "mode",
        "patrimoine_net", "patrimoine_brut", "liquidites_total",
        "bourse_holdings", "pe_value", "ent_value", "immobilier_value", "credits_remaining",
    ]
    rows = conn.execute(
        """
        SELECT week_date, created_at, mode,
               patrimoine_net, patrimoine_brut, liquidites_total,
               bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining
        FROM patrimoine_snapshots_family_weekly
        WHERE family_id = ?
        ORDER BY week_date ASC
        """,
        (int(family_id),),
    ).fetchall()
    return pd.DataFrame(rows, columns=_COLS) if rows else pd.DataFrame(columns=_COLS)


def _normalize_family_weekly_series(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=FAMILY_WEEKLY_COLUMNS)

    out = df.copy()
    out["week_date"] = pd.to_datetime(out["week_date"], errors="coerce")
    out = out.dropna(subset=["week_date"]).sort_values("week_date")

    for col in FAMILY_WEEKLY_COLUMNS:
        if col == "week_date":
            continue
        if col not in out.columns:
            out[col] = 0.0

    return out[FAMILY_WEEKLY_COLUMNS].reset_index(drop=True)


def get_family_weekly_series(conn, family_id: int = 1, fallback_person_ids: list[int] | None = None) -> pd.DataFrame:
    """
    Source canonique de la série famille :
    1) table famille weekly
    2) fallback (si table vide) via agrégation snapshots personnes
    """
    df_family = list_family_weekly_snapshots(conn, family_id=family_id)
    df_family = _normalize_family_weekly_series(df_family)
    if not df_family.empty:
        return df_family

    if not fallback_person_ids:
        return df_family

    _AGG_COLS = ["week_date", "patrimoine_net", "patrimoine_brut", "liquidites_total",
                 "bourse_holdings", "pe_value", "ent_value", "immobilier_value", "credits_remaining"]
    q = ",".join(["?"] * len(fallback_person_ids))
    rows = conn.execute(
        f"""
        SELECT week_date,
               SUM(patrimoine_net) AS patrimoine_net,
               SUM(patrimoine_brut) AS patrimoine_brut,
               SUM(liquidites_total) AS liquidites_total,
               SUM(bourse_holdings) AS bourse_holdings,
               SUM(pe_value) AS pe_value,
               SUM(ent_value) AS ent_value,
               SUM(immobilier_value) AS immobilier_value,
               SUM(credits_remaining) AS credits_remaining
        FROM patrimoine_snapshots_weekly
        WHERE person_id IN ({q})
        GROUP BY week_date
        ORDER BY week_date ASC
        """,
        tuple([int(x) for x in fallback_person_ids]),
    ).fetchall()
    df_people = pd.DataFrame(rows, columns=_AGG_COLS) if rows else pd.DataFrame(columns=_AGG_COLS)
    return _normalize_family_weekly_series(df_people)


def _aggregate_person_snapshots_by_week(conn, person_ids: list[int]) -> pd.DataFrame:
    """
    Agrège les snapshots hebdomadaires de plusieurs personnes par semaine (SUM).
    Helper interne mutualisé — évite la répétition de cette requête SQL dans chaque rebuild famille.
    """
    _AGG_COLS = ["week_date", "patrimoine_net", "patrimoine_brut", "liquidites_total",
                 "bourse_holdings", "pe_value", "ent_value", "immobilier_value", "credits_remaining"]
    q = ",".join(["?"] * len(person_ids))
    rows = conn.execute(
        f"""
        SELECT week_date,
               SUM(patrimoine_net)      AS patrimoine_net,
               SUM(patrimoine_brut)     AS patrimoine_brut,
               SUM(liquidites_total)    AS liquidites_total,
               SUM(bourse_holdings)     AS bourse_holdings,
               SUM(pe_value)            AS pe_value,
               SUM(ent_value)           AS ent_value,
               SUM(immobilier_value)    AS immobilier_value,
               SUM(credits_remaining)   AS credits_remaining
        FROM patrimoine_snapshots_weekly
        WHERE person_id IN ({q})
        GROUP BY week_date
        ORDER BY week_date ASC
        """,
        tuple([int(x) for x in person_ids]),
    ).fetchall()
    return pd.DataFrame(rows, columns=_AGG_COLS) if rows else pd.DataFrame(columns=_AGG_COLS)


def upsert_family_snapshot(conn, family_id: int, week_date: str, mode: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_family_weekly(
            family_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut, liquidites_total,
            bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining,
            notes
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(family_id, week_date) DO UPDATE SET
            created_at = excluded.created_at,
            mode = excluded.mode,
            patrimoine_net = excluded.patrimoine_net,
            patrimoine_brut = excluded.patrimoine_brut,
            liquidites_total = excluded.liquidites_total,
            bourse_holdings = excluded.bourse_holdings,
            pe_value = excluded.pe_value,
            ent_value = excluded.ent_value,
            immobilier_value = excluded.immobilier_value,
            credits_remaining = excluded.credits_remaining,
            notes = excluded.notes
        """,
        (
            int(family_id),
            str(week_date),
            _now_paris_iso(),
            str(mode),
            float(payload.get("patrimoine_net", 0.0)),
            float(payload.get("patrimoine_brut", 0.0)),
            float(payload.get("liquidites_total", 0.0)),
            float(payload.get("bourse_holdings", 0.0)),
            float(payload.get("pe_value", 0.0)),
            float(payload.get("ent_value", 0.0)),
            float(payload.get("immobilier_value", 0.0)),
            float(payload.get("credits_remaining", 0.0)),
            payload.get("notes"),
        ),
    )


def rebuild_family_weekly(conn, person_ids: list[int], lookback_days: int = 90, family_id: int = 1) -> dict:
    if not person_ids:
        return {"did_run": False, "reason": "no_person_ids"}

    from services import snapshots as wk_snap

    # 1) rebuild chaque personne
    for pid in person_ids:
        wk_snap.rebuild_snapshots_person(conn, person_id=int(pid), lookback_days=int(lookback_days))

    # 2) agrégation via le helper mutualisé
    df = _aggregate_person_snapshots_by_week(conn, person_ids)


    if df.empty:
        return {"did_run": False, "reason": "no_weekly_person_snapshots"}

    # 3) upsert
    n = 0
    for _, r in df.iterrows():
        payload = dict(r)
        payload["notes"] = f"Agrégé sur {len(person_ids)} personnes"
        upsert_family_snapshot(conn, family_id=family_id, week_date=str(r["week_date"]), mode="REBUILD", payload=payload)
        n += 1

    conn.commit()
    return {"did_run": True, "family_id": family_id, "n_weeks": int(n), "n_people": len(person_ids)}

def rebuild_family_weekly_missing_only(conn, person_ids: list[int], lookback_days: int = 90, recalc_days: int = 0, family_id: int = 1) -> dict:
    """
    Rebuild famille intelligent :
    - rebuild missing-only par personne
    - puis agrégation weekly => upsert famille
    """
    if not person_ids:
        return {"did_run": False, "reason": "no_person_ids"}

    # 1) rebuild missing-only chaque personne
    from services import snapshots as wk_snap
    for pid in person_ids:
        wk_snap.rebuild_snapshots_person_missing_only(conn, person_id=int(pid), lookback_days=int(lookback_days), recalc_days=int(recalc_days))

    # 2) agrégation via le helper mutualisé
    df = _aggregate_person_snapshots_by_week(conn, person_ids)


    if df.empty:
        return {"did_run": False, "reason": "no_weekly_person_snapshots"}

    n = 0
    for _, r in df.iterrows():
        payload = dict(r)
        payload["notes"] = f"Agrégé sur {len(person_ids)} personnes"
        upsert_family_snapshot(conn, family_id=family_id, week_date=str(r["week_date"]), mode="REBUILD", payload=payload)
        n += 1

    conn.commit()
    return {"did_run": True, "family_id": family_id, "n_weeks": int(n), "n_people": len(person_ids), "mode": "MISSING_ONLY"}

def rebuild_family_weekly_from_last(
    conn,
    person_ids: list[int],
    safety_weeks: int = 4,
    fallback_lookback_days: int = 90,
    family_id: int = 1,
) -> dict:
    """
    Rebuild famille depuis les dernières snapshots :
    - rebuild chaque personne depuis sa dernière snapshot (+ safety weeks)
    - puis agrégation et upsert dans la table famille
    """
    if not person_ids:
        return {"did_run": False, "reason": "no_person_ids"}

    from services import snapshots as wk_snap

    # 1) rebuild rapide par personne
    for pid in person_ids:
        wk_snap.rebuild_snapshots_person_from_last(
            conn,
            person_id=int(pid),
            safety_weeks=int(safety_weeks),
            fallback_lookback_days=int(fallback_lookback_days),
        )

    # 2) agrégation via le helper mutualisé
    df = _aggregate_person_snapshots_by_week(conn, person_ids)


    if df.empty:
        return {"did_run": False, "reason": "no_weekly_person_snapshots"}

    n = 0
    for _, r in df.iterrows():
        payload = dict(r)
        payload["notes"] = f"Agrégé sur {len(person_ids)} personnes"
        upsert_family_snapshot(conn, family_id=family_id, week_date=str(r["week_date"]), mode="REBUILD", payload=payload)
        n += 1

    conn.commit()
    return {"did_run": True, "family_id": family_id, "n_weeks": int(n), "n_people": len(person_ids), "mode": "FROM_LAST"}


def rebuild_family_weekly_backdated_aware(
    conn,
    person_ids: list[int],
    safety_weeks: int = 4,
    fallback_lookback_days: int = 365,
    family_id: int = 1,
) -> dict:
    """
    B4 famille :
    - rebuild backdated-aware pour chaque personne
    - puis agrégation famille
    """
    if not person_ids:
        return {"did_run": False, "reason": "no_person_ids"}

    from services import snapshots as wk_snap

    # rebuild personnes
    res_people = []
    for pid in person_ids:
        res_people.append(
            wk_snap.rebuild_snapshots_person_backdated_aware(
                conn,
                person_id=int(pid),
                safety_weeks=int(safety_weeks),
                fallback_lookback_days=int(fallback_lookback_days),
            )
        )

    # agrégation famille via le helper mutualisé
    df = _aggregate_person_snapshots_by_week(conn, person_ids)


    if df.empty:
        return {"did_run": False, "reason": "no_weekly_person_snapshots", "people": res_people}

    n = 0
    for _, r in df.iterrows():
        payload = dict(r)
        payload["notes"] = f"Agrégé sur {len(person_ids)} personnes"
        upsert_family_snapshot(conn, family_id=family_id, week_date=str(r["week_date"]), mode="REBUILD", payload=payload)
        n += 1

    conn.commit()
    return {"did_run": True, "mode": "FAMILY_BACKDATED_AWARE", "n_weeks": int(n), "people": res_people}
