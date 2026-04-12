from __future__ import annotations
import logging
import pandas as pd
from datetime import datetime
import pytz
from services import snapshots

_logger = logging.getLogger(__name__)


def _paris_today() -> pd.Timestamp:
    tz = pytz.timezone("Europe/Paris")
    return pd.Timestamp(datetime.now(tz).date())


def _week_monday(d: pd.Timestamp) -> pd.Timestamp:
    d = pd.to_datetime(d)
    return (d - pd.Timedelta(days=int(d.weekday()))).normalize()


def list_people(conn) -> pd.DataFrame:
    try:
        rows = conn.execute("SELECT id, name FROM people ORDER BY id").fetchall()
        return pd.DataFrame(rows, columns=["id", "name"]) if rows else pd.DataFrame(columns=["id", "name"])
    except Exception:
        return pd.DataFrame(columns=["id", "name"])


def last_market_dates(conn) -> dict:
    """
    Dernières dates en base pour prix & FX weekly.
    """
    out = {"last_price_week": None, "last_fx_week": None}
    try:
        r = conn.execute("SELECT MAX(week_date) AS d FROM asset_prices_weekly").fetchone()
        out["last_price_week"] = r["d"] if r else None
    except Exception:
        pass
    try:
        r = conn.execute("SELECT MAX(week_date) AS d FROM fx_rates_weekly").fetchone()
        out["last_fx_week"] = r["d"] if r else None
    except Exception:
        pass
    return out


def last_snapshot_week_by_person(conn) -> pd.DataFrame:
    """
    Dernière semaine snapshot par personne.
    """
    try:
        people = list_people(conn)
    except Exception:
        _logger.error("last_snapshot_week_by_person: erreur lecture people", exc_info=True)
        return pd.DataFrame(columns=["person_id", "person_name", "last_week"])

    if people is None or people.empty:
        return pd.DataFrame(columns=["person_id", "person_name", "last_week"])

    rows = []
    for _, p in people.iterrows():
        person_id = int(p["id"])
        person_name = p.get("name")
        snap = snapshots.get_latest_person_snapshot(conn, person_id)

        last_week = None
        if snap is None:
            _logger.info(
                "last_snapshot_week_by_person: aucun snapshot pour person_id=%s",
                person_id,
            )
        else:
            week_date = snap.get("week_date")
            if not week_date:
                _logger.warning(
                    "last_snapshot_week_by_person: date absente pour person_id=%s",
                    person_id,
                )
            else:
                week_ts = pd.to_datetime(week_date, errors="coerce")
                if pd.isna(week_ts):
                    _logger.warning(
                        "last_snapshot_week_by_person: date incohérente pour "
                        "person_id=%s week_date=%r",
                        person_id, week_date,
                    )
                else:
                    last_week = week_ts.strftime("%Y-%m-%d")

        rows.append(
            {
                "person_id": person_id,
                "person_name": person_name,
                "last_week": last_week,
            }
        )

    try:
        return pd.DataFrame(rows, columns=["person_id", "person_name", "last_week"])
    except Exception:
        _logger.error(
            "last_snapshot_week_by_person: erreur construction dataframe",
            exc_info=True,
        )
        return pd.DataFrame(columns=["person_id", "person_name", "last_week"])


def missing_snapshot_weeks(conn, person_id: int, lookback_days: int = 90) -> pd.DataFrame:
    """
    Liste des semaines manquantes (W-MON) pour une personne sur une fenêtre.
    """
    end = _week_monday(_paris_today())
    start = _week_monday(end - pd.Timedelta(days=int(lookback_days)))

    all_weeks = pd.date_range(start=start, end=end, freq="W-MON")
    try:
        df = snapshots.get_person_weekly_series(conn, int(person_id))
        if df is None or df.empty:
            _logger.info(
                "missing_snapshot_weeks: aucun snapshot disponible pour person_id=%s",
                person_id,
            )
            have = set()
        elif "week_date" not in df.columns:
            _logger.warning(
                "missing_snapshot_weeks: colonne week_date absente, diagnostic ignoré "
                "pour person_id=%s",
                person_id,
            )
            have = set()
        else:
            week_dates = pd.to_datetime(df["week_date"], errors="coerce")
            invalid_count = int(week_dates.isna().sum())
            if invalid_count > 0:
                _logger.warning(
                    "missing_snapshot_weeks: %s date(s) incohérente(s) ignorée(s) "
                    "pour person_id=%s",
                    invalid_count,
                    person_id,
                )
            have = set(week_dates.dropna().dt.normalize().tolist())
    except Exception:
        _logger.error(
            "missing_snapshot_weeks: erreur lecture snapshots pour person_id=%s",
            person_id,
            exc_info=True,
        )
        have = set()

    missing = [w for w in all_weeks if w.normalize() not in have]
    return pd.DataFrame({"missing_week": [x.strftime("%Y-%m-%d") for x in missing]})


def family_missing_weeks(conn, lookback_days: int = 90) -> pd.DataFrame:
    """
    Semaines manquantes côté famille (table famille weekly) si tu l'as.
    """
    end = _week_monday(_paris_today())
    start = _week_monday(end - pd.Timedelta(days=int(lookback_days)))
    all_weeks = pd.date_range(start=start, end=end, freq="W-MON")

    have = set()
    try:
        df = pd.read_sql_query("SELECT week_date FROM patrimoine_snapshots_family_weekly", conn)
        df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
        have = set(df.dropna(subset=["week_date"])["week_date"].dt.normalize().tolist())
    except Exception:
        have = set()

    missing = [w for w in all_weeks if w.normalize() not in have]
    return pd.DataFrame({"missing_week": [x.strftime("%Y-%m-%d") for x in missing]})


def tickers_missing_weekly_prices(conn, max_show: int = 30) -> pd.DataFrame:
    """
    Diagnostic simple : tickers vus dans transactions (ACHAT/VENTE)
    qui n'ont AUCUN prix weekly en base.
    (V1 : facile, utile, pas parfait mais efficace)
    """
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT asset_symbol AS ticker
            FROM transactions
            WHERE asset_symbol IS NOT NULL
              AND TRIM(asset_symbol) <> ''
              AND type IN ('ACHAT','VENTE')
            """
        ).fetchall()
        tx = pd.DataFrame(rows, columns=["ticker"]) if rows else pd.DataFrame(columns=["ticker"])
    except Exception:
        return pd.DataFrame(columns=["ticker", "has_price"])

    if tx.empty:
        return pd.DataFrame(columns=["ticker", "has_price"])

    tickers = tx["ticker"].astype(str).str.strip().unique().tolist()

    rows = []
    for t in tickers:
        try:
            r = conn.execute(
                "SELECT 1 FROM asset_prices_weekly WHERE symbol=? LIMIT 1",
                (t,),
            ).fetchone()
            has = True if r else False
        except Exception:
            has = False
        if not has:
            rows.append({"ticker": t, "has_price": False})

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.head(int(max_show))


def person_weekly_status(conn, person_id: int, safety_weeks: int = 4) -> dict:
    """
    Retourne un statut simple :
    - last_week_in_db
    - target_week (semaine courante)
    - missing_weeks_count (depuis last_week -> target_week)
    - suggested_action
    """
    end = _week_monday(_paris_today())
    snap = snapshots.get_latest_person_snapshot(conn, int(person_id))

    last = None
    if snap is None:
        _logger.info(
            "person_weekly_status: aucun snapshot disponible pour person_id=%s",
            person_id,
        )
    else:
        d_val = snap.get("week_date")
        if not d_val:
            _logger.warning(
                "person_weekly_status: date absente pour person_id=%s",
                person_id,
            )
        else:
            last = pd.to_datetime(d_val, errors="coerce")
            if pd.isna(last):
                _logger.warning(
                    "person_weekly_status: date incohérente pour person_id=%s "
                    "week_date=%r (diagnostic ignoré)",
                    person_id,
                    d_val,
                )
                last = None

    if last is None:
        return {
            "ok": False,
            "reason": "no_snapshot",
            "last_week": None,
            "target_week": end.strftime("%Y-%m-%d"),
            "missing_weeks": None,
            "suggested": "FROM_LAST_FALLBACK",
        }

    # semaines manquantes strictes depuis last -> end
    # (si last == end => 0)
    missing = pd.date_range(start=last, end=end, freq="W-MON")
    missing_count = max(0, len(missing) - 1)

    # si tu as des trous anciens, ce statut ne les voit pas : c'est voulu (B3 = quotidien)
    return {
        "ok": True,
        "reason": "ok",
        "last_week": last.strftime("%Y-%m-%d"),
        "target_week": end.strftime("%Y-%m-%d"),
        "missing_weeks": int(missing_count),
        "suggested": "UP_TO_DATE" if missing_count == 0 else "FROM_LAST",
        "safety_weeks": int(safety_weeks),
    }


def get_family_health_summary(conn, safety_weeks: int = 4) -> dict:
    """
    Résumé de santé des données famille, prêt pour l'affichage dans le
    tableau de diagnostic.

    Encapsule l'assemblage autrefois fait directement dans ``DataHealthPanel`` :
    lecture des personnes, appel à ``person_weekly_status`` pour chacune,
    construction du DataFrame de statuts.

    Paramètres
    ----------
    safety_weeks : int
        Nombre de semaines de tolérance passé à ``person_weekly_status``.

    Retourne un dictionnaire :
        status_df   DataFrame[Personne, Dernière semaine, Cible, Statut]
                    — prêt pour l'affichage (libellés et indicateurs inclus)
        person_ids  list[int]
                    — liste des person_id détectés (utile pour les rebuilds)
    """
    _EMPTY_STATUS_DF = pd.DataFrame(
        columns=["Personne", "Dernière semaine", "Cible", "Statut"]
    )

    people = list_people(conn)
    if people is None or people.empty:
        _logger.warning("get_family_health_summary: aucune personne en base")
        return {"status_df": _EMPTY_STATUS_DF, "person_ids": []}

    person_ids = [int(x) for x in people["id"].tolist()]
    rows = []
    for pid in person_ids:
        name_series = people.loc[people["id"] == pid, "name"]
        if name_series.empty:
            _logger.warning(
                "get_family_health_summary: person_id=%s introuvable dans people",
                pid,
            )
            continue
        name = str(name_series.iloc[0])
        stt = person_weekly_status(conn, person_id=pid, safety_weeks=safety_weeks)
        statut = "✅ À jour" if stt.get("suggested") == "UP_TO_DATE" else "⚠️ À rebuild"
        rows.append({
            "Personne":          name,
            "Dernière semaine":  stt.get("last_week") or "—",
            "Cible":             stt.get("target_week") or "—",
            "Statut":            statut,
        })

    if not rows:
        _logger.info(
            "get_family_health_summary: aucune ligne de diagnostic disponible "
            "(safety_weeks=%s)", safety_weeks,
        )
        return {"status_df": _EMPTY_STATUS_DF, "person_ids": person_ids}

    return {
        "status_df":  pd.DataFrame(rows),
        "person_ids": person_ids,
    }


def family_weekly_status(conn, safety_weeks: int = 4) -> dict:
    """
    Statut famille basé sur la table famille weekly si elle existe.
    """
    end = _week_monday(_paris_today())
    last = None
    try:
        row = conn.execute("SELECT MAX(week_date) AS d FROM patrimoine_snapshots_family_weekly").fetchone()
        if row and row["d"]:
            last = pd.to_datetime(row["d"], errors="coerce")
            if pd.isna(last):
                last = None
    except Exception:
        last = None

    if last is None:
        return {
            "ok": False,
            "reason": "no_family_snapshot",
            "last_week": None,
            "target_week": end.strftime("%Y-%m-%d"),
            "missing_weeks": None,
            "suggested": "FAMILY_FROM_LAST_FALLBACK",
        }

    missing = pd.date_range(start=last, end=end, freq="W-MON")
    missing_count = max(0, len(missing) - 1)

    return {
        "ok": True,
        "reason": "ok",
        "last_week": last.strftime("%Y-%m-%d"),
        "target_week": end.strftime("%Y-%m-%d"),
        "missing_weeks": int(missing_count),
        "suggested": "UP_TO_DATE" if missing_count == 0 else "FAMILY_FROM_LAST",
        "safety_weeks": int(safety_weeks),
    }
