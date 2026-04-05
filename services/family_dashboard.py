from __future__ import annotations

import pandas as pd
from typing import Dict, List, Optional, Tuple

from services import repositories as repo


# ---------- Helpers perf ----------
def _pct(a: float, b: float) -> Optional[float]:
    """Perf % entre a (base) et b (final)."""
    if a is None or b is None:
        return None
    a = float(a)
    b = float(b)
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _safe_window_perf(df: pd.DataFrame, col: str, end_date: pd.Timestamp, days: int, min_base: float = 200.0) -> Optional[float]:
    """
    Perf sur fenêtre glissante: compare valeur à end_date vs valeur <= end_date - days.
    min_base évite des % absurdes si la base est trop petite.
    """
    if df is None or df.empty:
        return None
    d = df.sort_values("week_date").copy()
    d = d.dropna(subset=["week_date"])
    if len(d) < 2:
        return None

    d_end = d[d["week_date"] <= end_date]
    if d_end.empty:
        return None
    v_end = float(d_end.iloc[-1][col])

    cutoff = end_date - pd.Timedelta(days=days)
    d_start = d[d["week_date"] <= cutoff]
    if d_start.empty:
        return None
    v_start = float(d_start.iloc[-1][col])

    if v_start < min_base:
        return None
    return _pct(v_start, v_end)


def _cagr(df: pd.DataFrame, col: str, min_base: float = 200.0) -> Optional[float]:
    """
    CAGR sur la période dispo, à partir du 1er point où col >= min_base.
    """
    if df is None or df.empty or len(df) < 2:
        return None
    d = df.sort_values("week_date").copy()
    d = d[d[col] >= float(min_base)]
    if len(d) < 2:
        return None

    d0 = pd.to_datetime(d.iloc[0]["week_date"])
    d1 = pd.to_datetime(d.iloc[-1]["week_date"])
    days = (d1 - d0).days
    if days < 30:
        return None

    a = float(d.iloc[0][col])
    b = float(d.iloc[-1][col])
    if a <= 0 or b <= 0:
        return None

    years = days / 365.25
    return (pow(b / a, 1.0 / years) - 1.0) * 100.0


# ---------- Data access ----------
def get_people(conn) -> pd.DataFrame:
    p = repo.list_people(conn)
    return p if p is not None else pd.DataFrame()


def get_family_series_from_people_snapshots(conn, person_ids: List[int]) -> pd.DataFrame:
    """
    Agrège directement depuis patrimoine_snapshots_weekly (somme par week_date).
    On ne dépend pas de la table famille si tu veux rester flexible.
    """
    if not person_ids:
        return pd.DataFrame()

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

    if df is None or df.empty:
        return pd.DataFrame()

    df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
    df = df.dropna(subset=["week_date"]).sort_values("week_date")
    return df


def get_last_common_week(conn, person_ids: List[int]) -> Optional[pd.Timestamp]:
    """
    Dernière semaine commune à toutes les personnes.
    (évite biais si quelqu’un n’a pas été rebuild récemment)
    """
    if not person_ids:
        return None

    weeks_sets = []
    for pid in person_ids:
        d = pd.read_sql_query(
            "SELECT week_date FROM patrimoine_snapshots_weekly WHERE person_id=?",
            conn,
            params=(int(pid),),
        )
        if d is None or d.empty:
            return None
        d["week_date"] = pd.to_datetime(d["week_date"], errors="coerce")
        d = d.dropna(subset=["week_date"])
        weeks_sets.append(set(d["week_date"].tolist()))

    common = set.intersection(*weeks_sets) if weeks_sets else set()
    if not common:
        return None
    return max(common)


def get_person_snapshot_at_week(conn, person_id: int, week: pd.Timestamp) -> Optional[Dict]:
    df = pd.read_sql_query(
        """
        SELECT week_date, patrimoine_net, patrimoine_brut, liquidites_total,
               bourse_holdings, pe_value, ent_value, immobilier_value, credits_remaining
        FROM patrimoine_snapshots_weekly
        WHERE person_id=? AND week_date=?
        """,
        conn,
        params=(int(person_id), week.strftime("%Y-%m-%d")),
    )
    if df is None or df.empty:
        return None
    return df.iloc[0].to_dict()


# ---------- Dashboard computations ----------
def compute_family_kpis(df_family: pd.DataFrame) -> Dict:
    if df_family is None or df_family.empty:
        return {}

    last = df_family.iloc[-1]
    end = pd.to_datetime(last["week_date"])

    kpis = {
        "asof": end,
        "patrimoine_net": float(last["patrimoine_net"]),
        "patrimoine_brut": float(last["patrimoine_brut"]),
        "liquidites_total": float(last["liquidites_total"]),
        "credits_remaining": float(last["credits_remaining"]),
        "perf_3m": _safe_window_perf(df_family, "patrimoine_net", end, days=90),
        "perf_12m": _safe_window_perf(df_family, "patrimoine_net", end, days=365),
        "cagr": _cagr(df_family, "patrimoine_net"),
    }
    return kpis


def compute_allocations_family(df_family: pd.DataFrame) -> Dict:
    """
    Allocation par catégories au dernier point.
    """
    if df_family is None or df_family.empty:
        return {}

    last = df_family.iloc[-1]
    alloc = {
        "Liquidités": float(last.get("liquidites_total", 0.0)),
        "Bourse": float(last.get("bourse_holdings", 0.0)),
        "Private Equity": float(last.get("pe_value", 0.0)),
        "Entreprises": float(last.get("ent_value", 0.0)),
        "Immobilier": float(last.get("immobilier_value", 0.0)),
    }
    # Nettoyage (pas de négatifs)
    alloc = {k: max(0.0, float(v)) for k, v in alloc.items()}
    return alloc


def compute_people_table(conn, people: pd.DataFrame, common_week: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        name = str(p["name"])
        snap = get_person_snapshot_at_week(conn, pid, common_week)
        if not snap:
            continue

        net = float(snap.get("patrimoine_net", 0.0))
        brut = float(snap.get("patrimoine_brut", 0.0))
        bourse = float(snap.get("bourse_holdings", 0.0))
        liq = float(snap.get("liquidites_total", 0.0))
        pe = float(snap.get("pe_value", 0.0))
        ent = float(snap.get("ent_value", 0.0))
        immo = float(snap.get("immobilier_value", 0.0))
        cred = float(snap.get("credits_remaining", 0.0))

        expo_bourse = (bourse / net * 100.0) if net > 0 else 0.0

        rows.append({
            "Personne": name,
            "Net (€)": net,
            "Brut (€)": brut,
            "Liquidités (€)": liq,
            "Bourse (€)": bourse,
            "PE (€)": pe,
            "Entreprises (€)": ent,
            "Immobilier (€)": immo,
            "Crédits (€)": cred,
            "% Expo Bourse": round(expo_bourse, 1),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    return df.sort_values("Net (€)", ascending=False).reset_index(drop=True)


def compute_leaderboards(conn, people: pd.DataFrame, person_ids: List[int], common_week: pd.Timestamp) -> Dict:
    """
    Leaderboards:
    - net top
    - perf 3m top
    - perf 12m top
    - exposure bourse top
    """
    # Base table at common week
    df_now = compute_people_table(conn, people, common_week)
    if df_now.empty:
        return {}

    # Perf windows par personne (sur net)
    perf3 = []
    perf12 = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        name = str(p["name"])

        df_p = pd.read_sql_query(
            """
            SELECT week_date, patrimoine_net
            FROM patrimoine_snapshots_weekly
            WHERE person_id=?
            ORDER BY week_date ASC
            """,
            conn,
            params=(pid,),
        )
        if df_p is None or df_p.empty:
            continue
        df_p["week_date"] = pd.to_datetime(df_p["week_date"], errors="coerce")
        df_p = df_p.dropna(subset=["week_date"]).sort_values("week_date")

        # On force end = common_week
        df_p = df_p[df_p["week_date"] <= common_week]
        if len(df_p) < 2:
            continue

        p3 = _safe_window_perf(df_p, "patrimoine_net", common_week, days=90)
        p12 = _safe_window_perf(df_p, "patrimoine_net", common_week, days=365)

        if p3 is not None:
            perf3.append((name, p3))
        if p12 is not None:
            perf12.append((name, p12))

    perf3 = sorted(perf3, key=lambda x: x[1], reverse=True)
    perf12 = sorted(perf12, key=lambda x: x[1], reverse=True)

    expo = df_now[["Personne", "% Expo Bourse"]].sort_values("% Expo Bourse", ascending=False)

    return {
        "top_net": df_now[["Personne", "Net (€)"]].head(3),
        "top_perf_3m": perf3[:3],
        "top_perf_12m": perf12[:3],
        "top_expo_bourse": expo.head(3),
    }


def compute_family_debug(conn, people: pd.DataFrame, common_week: Optional[pd.Timestamp]) -> pd.DataFrame:
    """
    Debug : dernière snapshot par personne, écart vs common week.
    """
    rows = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        name = str(p["name"])

        df = pd.read_sql_query(
            "SELECT MAX(week_date) AS last_week FROM patrimoine_snapshots_weekly WHERE person_id=?",
            conn,
            params=(pid,),
        )
        last_week = None
        if df is not None and not df.empty:
            last_week = pd.to_datetime(df.iloc[0]["last_week"], errors="coerce")

        delta = None
        if common_week is not None and last_week is not None and pd.notna(last_week):
            delta = (common_week - last_week).days

        rows.append({
            "Personne": name,
            "Dernière semaine snapshot": last_week.strftime("%Y-%m-%d") if last_week is not None and pd.notna(last_week) else "—",
            "Écart vs semaine famille (jours)": int(delta) if delta is not None else "—",
        })

    return pd.DataFrame(rows)
