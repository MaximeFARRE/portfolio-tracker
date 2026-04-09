from __future__ import annotations

import logging
import pandas as pd
from typing import Dict, List, Optional, Tuple

from services import repositories as repo

_logger = logging.getLogger(__name__)

# Mapping stable catégorie → colonne SSOT (famille weekly).
# Utilisé par prepare_family_area_chart_data et prepare_family_alloc_pie_data.
ALLOC_CATEGORY_MAP: Dict[str, str] = {
    "Liquidités":     "liquidites_total",
    "Bourse":         "bourse_holdings",
    "Private Equity": "pe_value",
    "Entreprises":    "ent_value",
    "Immobilier":     "immobilier_value",
}


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
    from services import family_snapshots as fs
    return fs.get_family_weekly_series(conn, family_id=1, fallback_person_ids=person_ids)


def get_family_series(conn, person_ids: Optional[List[int]] = None, family_id: int = 1) -> pd.DataFrame:
    """
    Source de vérité famille:
    - priorité: table patrimoine_snapshots_family_weekly
    - fallback: agrégation des snapshots weekly personnes
    """
    from services import family_snapshots as fs
    return fs.get_family_weekly_series(conn, family_id=family_id, fallback_person_ids=person_ids or [])


def get_last_common_week(conn, person_ids: List[int]) -> Optional[pd.Timestamp]:
    """
    Dernière semaine commune à toutes les personnes.
    (évite biais si quelqu’un n’a pas été rebuild récemment)
    """
    if not person_ids:
        return None

    from services import snapshots as wk_snap

    weeks_sets = []
    for pid in person_ids:
        df_p = wk_snap.get_person_weekly_series(conn, person_id=pid)
        if df_p.empty:
            return None
        weeks_sets.append(set(df_p["week_date"].tolist()))

    common = set.intersection(*weeks_sets) if weeks_sets else set()
    if not common:
        return None
    return max(common)


def get_person_snapshot_at_week(conn, person_id: int, week: pd.Timestamp) -> Optional[Dict]:
    """
    Snapshot d'une personne à une semaine précise.
    Délègue à la source officielle ``snapshots.get_person_snapshot_at_week``.
    """
    from services import snapshots as wk_snap
    return wk_snap.get_person_snapshot_at_week(conn, person_id=person_id, week_date=week)


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
    from services import snapshots as wk_snap

    perf3 = []
    perf12 = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        name = str(p["name"])

        df_p = wk_snap.get_person_weekly_series(conn, person_id=pid)
        if df_p.empty:
            continue

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
    from services import snapshots as wk_snap

    rows = []
    for _, p in people.iterrows():
        pid = int(p["id"])
        name = str(p["name"])

        df_p = wk_snap.get_person_weekly_series(conn, person_id=pid)
        last_week = df_p["week_date"].max() if not df_p.empty else None
        if last_week is not None and pd.isna(last_week):
            last_week = None

        delta = None
        if common_week is not None and last_week is not None and pd.notna(last_week):
            delta = (common_week - last_week).days

        rows.append({
            "Personne": name,
            "Dernière semaine snapshot": last_week.strftime("%Y-%m-%d") if last_week is not None and pd.notna(last_week) else "—",
            "Écart vs semaine famille (jours)": int(delta) if delta is not None else "—",
        })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# Préparation de données pour les graphiques famille
# ──────────────────────────────────────────────────────────────────────────────

def prepare_family_area_chart_data(df_family: pd.DataFrame) -> pd.DataFrame:
    """
    Prépare les données du graphique stacked-area d'allocation patrimoniale.

    Transforme la série famille hebdomadaire en format long (melt) et enrichit
    chaque ligne avec la part du total hebdomadaire et la variation par rapport
    à la semaine précédente — logique autrefois inline dans ``_build_allocation_area_chart``.

    Paramètres
    ----------
    df_family : DataFrame retourné par ``get_family_weekly_series`` ou ``get_family_series``.

    Retourne un DataFrame en format long avec les colonnes :
        week_date   datetime64
        Catégorie   str   (Liquidités / Bourse / Private Equity / Entreprises / Immobilier)
        Valeur      float (≥ 0)
        part_pct    float (% du total de la semaine)
        var_pct     float (variation % vs semaine précédente, NaN si première semaine)

    Retourne un DataFrame vide (avec les colonnes) si l'entrée est vide ou invalide.
    """
    empty = pd.DataFrame(columns=["week_date", "Catégorie", "Valeur", "part_pct", "var_pct"])

    if df_family is None or df_family.empty:
        _logger.info("prepare_family_area_chart_data: série famille vide")
        return empty

    df = df_family.copy()
    df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
    df = df.dropna(subset=["week_date"]).sort_values("week_date")

    if df.empty:
        _logger.warning("prepare_family_area_chart_data: aucune date valide après nettoyage")
        return empty

    # Colonnes manquantes → 0.0 (défensif)
    for col in ALLOC_CATEGORY_MAP.values():
        if col not in df.columns:
            _logger.warning(
                "prepare_family_area_chart_data: colonne '%s' absente, remplacée par 0", col
            )
            df[col] = 0.0

    # Pivot wide → long avec renommage catégories
    melt = (
        df[["week_date", *ALLOC_CATEGORY_MAP.values()]]
        .rename(columns={v: k for k, v in ALLOC_CATEGORY_MAP.items()})
        .melt(id_vars="week_date", var_name="Catégorie", value_name="Valeur")
    )
    melt["Valeur"] = melt["Valeur"].fillna(0.0).clip(lower=0.0)
    melt = melt.sort_values(["Catégorie", "week_date"]).reset_index(drop=True)

    # Part de chaque catégorie dans le total de la semaine
    totals = melt.groupby("week_date")["Valeur"].transform("sum")
    melt["part_pct"] = (melt["Valeur"] / totals * 100.0).where(totals > 0, 0.0)

    # Variation hebdomadaire par catégorie (NaN pour la première semaine)
    melt["var_pct"] = melt.groupby("Catégorie")["Valeur"].pct_change() * 100.0

    return melt.reset_index(drop=True)


def prepare_family_alloc_pie_data(
    df_family: pd.DataFrame,
    alloc: Dict[str, float],
) -> pd.DataFrame:
    """
    Prépare les données du pie chart d'allocation patrimoniale par catégorie.

    Calcule pour chaque catégorie : la part dans le total courant et la variation
    par rapport à la semaine précédente — logique autrefois inline dans ``_build_alloc_chart``.

    Paramètres
    ----------
    df_family : DataFrame retourné par ``get_family_weekly_series``.
    alloc     : dict {catégorie: valeur} retourné par ``compute_allocations_family``.

    Retourne un DataFrame avec les colonnes :
        Catégorie   str
        Valeur      float (valeur courante, > 0)
        part_pct    float (% du total)
        var_pct     float ou None (variation % vs semaine précédente)

    Retourne un DataFrame vide (avec les colonnes) si alloc est vide ou invalide.
    """
    _COLS = ["Catégorie", "Valeur", "part_pct", "var_pct"]
    empty = pd.DataFrame(columns=_COLS)

    if not alloc:
        _logger.info("prepare_family_alloc_pie_data: allocation vide")
        return empty

    # Valeurs de la semaine précédente pour le calcul de variation
    prev_values: Dict[str, float] = {}
    if df_family is not None and len(df_family) >= 2:
        prev_row = df_family.iloc[-2]
        for cat, col in ALLOC_CATEGORY_MAP.items():
            prev_values[cat] = float(prev_row.get(col, 0.0) or 0.0)

    rows = []
    for category, value in alloc.items():
        amount = float(value or 0.0)
        if amount <= 0:
            continue
        prev_amount = prev_values.get(category, 0.0)
        # _pct(base, final) → variation %
        var_pct = _pct(prev_amount, amount)
        rows.append({"Catégorie": category, "Valeur": amount, "var_pct": var_pct})

    if not rows:
        _logger.info("prepare_family_alloc_pie_data: aucune catégorie avec valeur positive")
        return empty

    df = pd.DataFrame(rows)
    total = float(df["Valeur"].sum())
    df["part_pct"] = (df["Valeur"] / total * 100.0).round(2) if total > 0 else 0.0

    return df[_COLS].reset_index(drop=True)


# Mapping catégorie → colonne dans df_people (sortie de compute_people_table).
# Distinct de ALLOC_CATEGORY_MAP qui pointe sur les colonnes de la série famille.
_TREEMAP_CATEGORY_COLS: Dict[str, str] = {
    "Liquidités":     "Liquidités (€)",
    "Bourse":         "Bourse (€)",
    "Private Equity": "PE (€)",
    "Entreprises":    "Entreprises (€)",
    "Immobilier":     "Immobilier (€)",
}


def prepare_family_treemap_data(
    df_people: pd.DataFrame,
    df_people_prev: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Prépare le DataFrame pour le treemap d'allocation détaillée par personne
    et catégorie.

    Transforme les données de la table personnes (sortie de ``compute_people_table``)
    en format plat prêt pour ``px.treemap`` — logique autrefois inline dans
    ``_build_allocation_treemap``.

    Paramètres
    ----------
    df_people      : DataFrame courant (semaine de référence).
    df_people_prev : DataFrame semaine précédente (optionnel, pour les variations).

    Retourne un DataFrame avec les colonnes :
        Portefeuille        str   (toujours « Famille »)
        Personne            str
        Catégorie           str
        Valeur              float (> 0)
        Part personne (%)   float
        Part famille (%)    float
        var_pct             float ou None (variation vs semaine précédente)

    Retourne un DataFrame vide (avec les colonnes) si l'entrée est vide ou invalide.
    """
    _COLS = [
        "Portefeuille", "Personne", "Catégorie",
        "Valeur", "Part personne (%)", "Part famille (%)", "var_pct",
    ]
    empty = pd.DataFrame(columns=_COLS)

    if df_people is None or df_people.empty:
        _logger.info("prepare_family_treemap_data: df_people vide")
        return empty

    # Vérification défensive des colonnes attendues
    missing_cols = [col for col in _TREEMAP_CATEGORY_COLS.values() if col not in df_people.columns]
    if missing_cols:
        _logger.warning(
            "prepare_family_treemap_data: colonnes absentes dans df_people : %s",
            missing_cols,
        )

    # Construction du prev_map : (personne, catégorie) → valeur semaine précédente
    prev_map: Dict[tuple, float] = {}
    if df_people_prev is not None and not df_people_prev.empty:
        for _, row in df_people_prev.iterrows():
            name = str(row.get("Personne", ""))
            for category, col in _TREEMAP_CATEGORY_COLS.items():
                prev_map[(name, category)] = float(row.get(col, 0.0) or 0.0)

    # Construction des lignes du treemap
    rows = []
    for _, row in df_people.iterrows():
        person = str(row.get("Personne", ""))

        # Agrégation par catégorie pour cette personne
        values: Dict[str, float] = {}
        person_total = 0.0
        for category, col in _TREEMAP_CATEGORY_COLS.items():
            value = max(0.0, float(row.get(col, 0.0) or 0.0))
            values[category] = value
            person_total += value

        if person_total <= 0:
            _logger.debug(
                "prepare_family_treemap_data: personne '%s' ignorée (total = 0)", person
            )
            continue

        for category, value in values.items():
            if value <= 0:
                continue
            prev_val = prev_map.get((person, category))
            var_pct = _pct(prev_val, value) if prev_val is not None else None
            rows.append({
                "Portefeuille":      "Famille",
                "Personne":          person,
                "Catégorie":         category,
                "Valeur":            value,
                "Part personne (%)": round(value / person_total * 100.0, 2),
                "var_pct":           var_pct,
            })

    if not rows:
        _logger.info("prepare_family_treemap_data: aucune ligne générée (données vides ?)")
        return empty

    tree_df = pd.DataFrame(rows)
    total = float(tree_df["Valeur"].sum())
    tree_df["Part famille (%)"] = (
        tree_df["Valeur"] / total * 100.0
    ).round(2) if total > 0 else 0.0

    return tree_df[_COLS].reset_index(drop=True)
