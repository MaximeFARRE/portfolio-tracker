from __future__ import annotations
import pandas as pd
from datetime import datetime
import pytz

from services import snapshots as wk_snap


def _now_paris_iso() -> str:
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).replace(microsecond=0).isoformat()


def list_family_weekly_snapshots(conn, family_id: int = 1) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT week_date, created_at, mode,
               patrimoine_net, patrimoine_brut, liquidites_total,
               bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining
        FROM patrimoine_snapshots_family_weekly
        WHERE family_id = ?
        ORDER BY week_date ASC
        """,
        conn,
        params=(int(family_id),),
    )


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

    # 1) rebuild chaque personne
    for pid in person_ids:
        wk_snap.rebuild_snapshots_person(conn, person_id=int(pid), lookback_days=int(lookback_days))

    # 2) agrégation
    q = ",".join(["?"] * len(person_ids))
    df = pd.read_sql_query(
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
        conn,
        params=tuple([int(x) for x in person_ids]),
    )

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

    # 2) agrégation (identique à ton rebuild_family_weekly)
    q = ",".join(["?"] * len(person_ids))
    df = pd.read_sql_query(
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
        conn,
        params=tuple([int(x) for x in person_ids]),
    )

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

    # 2) agrégation (identique à rebuild_family_weekly)
    q = ",".join(["?"] * len(person_ids))
    df = pd.read_sql_query(
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
        conn,
        params=tuple([int(x) for x in person_ids]),
    )

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

    # agrégation famille (comme tes autres rebuild)
    q = ",".join(["?"] * len(person_ids))
    df = pd.read_sql_query(
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
        conn,
        params=tuple([int(x) for x in person_ids]),
    )

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
