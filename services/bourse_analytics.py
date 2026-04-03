from __future__ import annotations

import math
import pandas as pd

from services import repositories as repo
from services import positions
from services import market_history
from services import market_repository as mrepo


def _safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def _broker_cash_asof_native(tx: pd.DataFrame) -> float:
    """
    Cash "native" d'un compte bourse calculé à partir des transactions jusqu'à asof.
    Règles (cohérentes avec snapshots.py):
    - DEPOT : +amount
    - RETRAIT : -amount
    - ACHAT : -amount
    - VENTE : +amount
    - DIVIDENDE : +amount
    - INTERETS : +amount
    - FRAIS : -amount
    - fees : toujours soustraits
    """
    if tx is None or tx.empty:
        return 0.0

    df = tx.copy()
    df["type"] = df.get("type", "").astype(str)
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
    df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

    cash = 0.0
    cash += float(df.loc[df["type"] == "DEPOT", "amount"].sum())
    cash -= float(df.loc[df["type"] == "RETRAIT", "amount"].sum())
    cash -= float(df.loc[df["type"] == "ACHAT", "amount"].sum())
    cash += float(df.loc[df["type"] == "VENTE", "amount"].sum())
    cash += float(df.loc[df["type"] == "DIVIDENDE", "amount"].sum())
    cash += float(df.loc[df["type"] == "INTERETS", "amount"].sum())
    cash -= float(df.loc[df["type"] == "FRAIS", "amount"].sum())
    cash -= float(df["fees"].sum())

    return float(round(cash, 2))


def get_bourse_weekly_series(conn, person_id: int) -> pd.DataFrame:
    """
    Renvoie une série weekly issue des snapshots weekly.
    IMPORTANT: on ne parle pas de cash ici => on utilise bourse_holdings uniquement.
    """
    df = mrepo.list_weekly_snapshots(conn, person_id=person_id)
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "holdings_eur"])

    # compat: la date s'appelle parfois snapshot_date
    date_col = "week_date" if "week_date" in df.columns else "snapshot_date"
    out = df.copy()
    out["date"] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")

    out["holdings_eur"] = pd.to_numeric(out.get("bourse_holdings", 0.0), errors="coerce").fillna(0.0)

    return out[["date", "holdings_eur"]].copy()


def compute_perf(series: pd.Series) -> float:
    """Perf simple en % entre premier et dernier."""
    if series is None or len(series) < 2:
        return 0.0
    a = float(series.iloc[0])
    b = float(series.iloc[-1])
    if a <= 0:
        return 0.0
    return (b / a - 1.0) * 100.0


def compute_cagr(series: pd.Series, dates: pd.Series) -> float:
    """
    Rendement annualisé (CAGR) sur la période dispo.
    """
    if series is None or len(series) < 2:
        return 0.0

    a = float(series.iloc[0])
    b = float(series.iloc[-1])
    if a <= 0 or b <= 0:
        return 0.0

    d0 = pd.to_datetime(dates.iloc[0])
    d1 = pd.to_datetime(dates.iloc[-1])
    # FIX: on vérifie raw_days AVANT le calcul de years (le guard "if years <= 0" après
    # max(...,1) était du code mort — years ne pouvait jamais être <= 0)
    raw_days = (d1 - d0).days
    if raw_days <= 0:
        return 0.0

    years = raw_days / 365.25
    return (pow(b / a, 1.0 / years) - 1.0) * 100.0


def compute_perf_12m(df_series: pd.DataFrame) -> float:
    """
    Perf sur ~12 mois (52 semaines) si dispo, sinon perf sur max dispo.
    """
    if df_series is None or df_series.empty:
        return 0.0
    d = df_series.copy()
    d = d.sort_values("date")
    if len(d) < 2:
        return 0.0

    last_date = d["date"].iloc[-1]
    cutoff = last_date - pd.Timedelta(days=365)

    d12 = d[d["date"] >= cutoff]
    if len(d12) >= 2:
        return compute_perf(d12["holdings_eur"])
    return compute_perf(d["holdings_eur"])


def compute_positions_valued_asof(conn, person_id: int, asof_week_date: str) -> pd.DataFrame:
    """
    Retourne toutes les positions ouvertes (qty>0), valorisées en EUR.
    """
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=["ticker", "account", "ccy", "qty", "px", "value_eur"])

    # comptes bourse: on garde ton périmètre standard
    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
        return pd.DataFrame(columns=["ticker", "account", "ccy", "qty", "px", "value_eur"])

    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=asof_week_date, account_ids=acc_ids)
    if pos is None or pos.empty:
        return pd.DataFrame(columns=["ticker", "account", "ccy", "qty", "px", "value_eur"])

    # map account id -> name
    acc_name = {int(r["id"]): str(r.get("name") or r.get("nom") or f"Compte {int(r['id'])}") for _, r in bourse_acc.iterrows()}

    rows = []
    for _, r in pos.iterrows():
        ticker = str(r.get("symbol") or "").strip()
        qty = _safe_float(r.get("quantity"), 0.0)
        ccy = str(r.get("asset_ccy") or "EUR").upper()
        account_id = int(r.get("account_id"))

        if not ticker or qty <= 0:
            continue

        px = market_history.get_price_asof(conn, ticker, asof_week_date)
        if px is None:
            px = 0.0

        value_native = qty * float(px)
        value_eur = market_history.convert_weekly(conn, value_native, ccy, "EUR", asof_week_date)

        rows.append({
            "ticker": ticker,
            "compte": acc_name.get(account_id, f"Compte {account_id}"),
            "devise": ccy,
            "quantite": qty,
            "prix_weekly": float(px),
            "valeur_eur": float(round(value_eur, 2)),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out = out.sort_values("valeur_eur", ascending=False).reset_index(drop=True)
    total = float(out["valeur_eur"].sum())
    if total > 0:
        out["poids_%"] = (out["valeur_eur"] / total * 100.0).round(2)
    else:
        out["poids_%"] = 0.0

    return out


def top_assets(df_pos: pd.DataFrame, n: int = 5) -> list[tuple[str, float]]:
    if df_pos is None or df_pos.empty:
        return []
    g = df_pos.groupby("ticker", as_index=False)["valeur_eur"].sum().sort_values("valeur_eur", ascending=False)
    g = g.head(int(n))
    return [(str(r["ticker"]), float(r["valeur_eur"])) for _, r in g.iterrows()]

def compute_perf_12m_safe(df_series: pd.DataFrame, min_base_eur: float = 200.0) -> float | None:
    """
    Perf 12m robuste:
    - prend la perf sur la fenêtre 12m si dispo
    - mais refuse si la valeur de départ < min_base_eur (sinon % absurdes)
    """
    if df_series is None or df_series.empty or len(df_series) < 2:
        return None

    d = df_series.sort_values("date").copy()
    last_date = d["date"].iloc[-1]
    cutoff = last_date - pd.Timedelta(days=365)
    w = d[d["date"] >= cutoff].copy()
    if len(w) < 2:
        w = d

    # base = premier point "suffisant"
    w = w[w["holdings_eur"] >= float(min_base_eur)]
    if len(w) < 2:
        return None

    a = float(w["holdings_eur"].iloc[0])
    b = float(w["holdings_eur"].iloc[-1])
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def compute_cagr_safe(df_series: pd.DataFrame, min_base_eur: float = 200.0) -> float | None:
    """
    CAGR robuste:
    - refuse si base < min_base_eur
    - refuse si durée trop courte (< 30 jours)
    """
    if df_series is None or df_series.empty or len(df_series) < 2:
        return None

    d = df_series.sort_values("date").copy()
    d = d[d["holdings_eur"] >= float(min_base_eur)]
    if len(d) < 2:
        return None

    d0 = pd.to_datetime(d["date"].iloc[0])
    d1 = pd.to_datetime(d["date"].iloc[-1])
    days = max((d1 - d0).days, 0)
    if days < 30:
        return None

    a = float(d["holdings_eur"].iloc[0])
    b = float(d["holdings_eur"].iloc[-1])
    if a <= 0 or b <= 0:
        return None

    years = days / 365.25
    return (pow(b / a, 1.0 / years) - 1.0) * 100.0

def compute_accounts_breakdown_asof(conn, person_id: int, asof_week_date: str) -> pd.DataFrame:
    """
    Tableau debug: quels sous-comptes bourse sont utilisés + cash/holdings/total par compte.
    - Cash: calculé via transactions (DEPOT/RETRAIT/ACHAT/VENTE/...)
    - Holdings: valorisés via prix weekly + FX weekly
    """
    import pandas as pd

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=["Compte", "Type", "Devise", "Cash (EUR)", "Holdings (EUR)", "Total (EUR)", "%"])

    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
        return pd.DataFrame(columns=["Compte", "Type", "Devise", "Cash (EUR)", "Holdings (EUR)", "Total (EUR)", "%"])

    # positions as-of par compte
    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=asof_week_date, account_ids=acc_ids)

    # Pré-calc holdings par compte
    holdings_by_acc = {int(aid): 0.0 for aid in acc_ids}
    if pos is not None and not pos.empty:
        for _, r in pos.iterrows():
            aid = int(r["account_id"])
            ticker = str(r.get("symbol") or "").strip()
            qty = _safe_float(r.get("quantity"), 0.0)
            ccy = str(r.get("asset_ccy") or "EUR").upper()
            if not ticker or qty <= 0:
                continue

            px = market_history.get_price_asof(conn, ticker, asof_week_date) or 0.0
            value_native = qty * float(px)
            value_eur = market_history.convert_weekly(conn, value_native, ccy, "EUR", asof_week_date)
            holdings_by_acc[aid] = holdings_by_acc.get(aid, 0.0) + float(value_eur)

    # Cash par compte (en EUR)
    rows = []
    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_name = str(a.get("name") or a.get("nom") or f"Compte {acc_id}")
        acc_type = str(a.get("account_type") or "")
        acc_ccy = str(a.get("currency") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        cash_native = 0.0
        if tx is not None and not tx.empty:
            df = tx.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[df["date"] <= pd.to_datetime(asof_week_date)]
            cash_native = _broker_cash_asof_native(df)

        cash_eur = market_history.convert_weekly(conn, cash_native, acc_ccy, "EUR", asof_week_date)
        hold_eur = float(holdings_by_acc.get(acc_id, 0.0))
        total_eur = float(cash_eur + hold_eur)

        rows.append({
            "Compte": acc_name,
            "Type": acc_type,
            "Devise": acc_ccy,
            "Cash (EUR)": round(float(cash_eur), 2),
            "Holdings (EUR)": round(float(hold_eur), 2),
            "Total (EUR)": round(float(total_eur), 2),
        })

    out = pd.DataFrame(rows).sort_values("Total (EUR)", ascending=False).reset_index(drop=True)
    total = float(out["Total (EUR)"].sum()) if not out.empty else 0.0
    out["%"] = (out["Total (EUR)"] / total * 100.0).round(2) if total > 0 else 0.0
    return out

def compute_invested_amount_eur_asof(conn, person_id: int, asof_week_date: str) -> float:
    """
    Montant investi net (EUR) :
    = Somme ACHAT (amount+fees) - Somme VENTE (amount - fees) sur comptes bourse.
    -> simple, robuste, compréhensible.
    """
    import pandas as pd

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0

    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
        return 0.0

    total_eur = 0.0

    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_ccy = str(a.get("currency") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        if tx is None or tx.empty:
            continue

        df = tx.copy()
        df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
        df = df.dropna(subset=["date"])
        df = df[df["date"] <= pd.to_datetime(asof_week_date)]
        if df.empty:
            continue

        df["type"] = df.get("type", "").astype(str)
        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

        buys = df[df["type"] == "ACHAT"]
        sells = df[df["type"] == "VENTE"]

        invested_native = float(buys["amount"].sum() + buys["fees"].sum()) - float(sells["amount"].sum() - sells["fees"].sum())
        total_eur += market_history.convert_weekly(conn, invested_native, acc_ccy, "EUR", asof_week_date)

    return float(round(total_eur, 2))

def get_start_date_for_perf(df_series: pd.DataFrame, min_base_eur: float = 200.0):
    """
    Date de début utilisée pour les perfs :
    -> première date où holdings >= min_base_eur
    (évite les % débiles quand ça commence à 0 ou 10€).
    """
    if df_series is None or df_series.empty:
        return None
    d = df_series.sort_values("date").copy()
    d = d[d["holdings_eur"] >= float(min_base_eur)]
    if len(d) == 0:
        return None
    return pd.to_datetime(d["date"].iloc[0])


def compute_perf_since_start(df_series: pd.DataFrame, min_base_eur: float = 200.0) -> float | None:
    """
    Perf (%) entre la première valeur "significative" et la dernière.
    """
    if df_series is None or df_series.empty or len(df_series) < 2:
        return None

    d = df_series.sort_values("date").copy()
    d = d[d["holdings_eur"] >= float(min_base_eur)]
    if len(d) < 2:
        return None

    a = float(d["holdings_eur"].iloc[0])
    b = float(d["holdings_eur"].iloc[-1])
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def compute_cagr_since_start(df_series: pd.DataFrame, min_base_eur: float = 200.0) -> float | None:
    """
    CAGR depuis la date de début (même base que compute_perf_since_start).
    """
    if df_series is None or df_series.empty or len(df_series) < 2:
        return None

    d = df_series.sort_values("date").copy()
    d = d[d["holdings_eur"] >= float(min_base_eur)]
    if len(d) < 2:
        return None

    d0 = pd.to_datetime(d["date"].iloc[0])
    d1 = pd.to_datetime(d["date"].iloc[-1])
    days = (d1 - d0).days
    if days < 30:
        return None

    a = float(d["holdings_eur"].iloc[0])
    b = float(d["holdings_eur"].iloc[-1])
    if a <= 0 or b <= 0:
        return None

    years = days / 365.25
    return (pow(b / a, 1.0 / years) - 1.0) * 100.0

def compute_passive_income_history(conn, person_id: int) -> pd.DataFrame:
    """
    Renvoie l'historique des revenus passifs (DIVIDENDE, INTERETS) par mois/année pour la bourse.
    """
    from services import market_history
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=["date", "type", "amount_eur", "month", "year"])
        
    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
         return pd.DataFrame(columns=["date", "type", "amount_eur", "month", "year"])
    
    rows = []
    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_ccy = str(a.get("currency") or "EUR").upper()
        
        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        if tx is None or tx.empty:
            continue
            
        df = tx.copy()
        df = df[df["type"].isin(["DIVIDENDE", "INTERETS"])]
        if df.empty:
            continue
            
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        
        for _, r in df.iterrows():
            amt_native = float(r.get("amount") or 0.0)
            if amt_native <= 0:
                continue
            
            date_str = r["date"].strftime("%Y-%m-%d")
            # Convert API
            amt_eur = market_history.convert_weekly(conn, amt_native, acc_ccy, "EUR", date_str)
            rows.append({
                "date": date_str,
                "month": r["date"].strftime("%Y-%m"),
                "year": r["date"].strftime("%Y"),
                "type": r["type"],
                "amount_eur": round(float(amt_eur), 2),
            })
            
    if not rows:
        return pd.DataFrame(columns=["date", "month", "year", "type", "amount_eur"])
        
    return pd.DataFrame(rows)

def get_bourse_performance_metrics(conn, person_id: int) -> dict:
    """
    Retourne un résumé des métriques boursières globale et YTD ainsi que les DataFrames associées pour l'UI.
    """
    df_snap = repo.list_patrimoine_snapshots(conn, person_id=person_id)
    if df_snap is None or df_snap.empty:
        df_snap = pd.DataFrame(columns=["snapshot_date", "bourse_holdings"])
        
    # We delay load since methods are in this very module
    import datetime as _dt
    invested_eur = compute_invested_amount_eur_asof(conn, person_id, _dt.date.today().isoformat())
    
    df_income = compute_passive_income_history(conn, person_id)
    tot_div = float(df_income[df_income["type"] == "DIVIDENDE"]["amount_eur"].sum()) if not df_income.empty else 0.0
    tot_int = float(df_income[df_income["type"] == "INTERETS"]["amount_eur"].sum()) if not df_income.empty else 0.0

    global_perf = 0.0
    ytd_perf = 0.0
    
    if not df_snap.empty:
        df_snap["date"] = pd.to_datetime(df_snap["snapshot_date"], errors="coerce")
        df_snap = df_snap.dropna(subset=["date"]).sort_values("date")
        
        if len(df_snap) > 0:
            current_value = float(df_snap.iloc[-1]["bourse_holdings"])
            
            if invested_eur > 0:
                global_perf = (current_value / invested_eur - 1.0) * 100.0
                
            current_year = df_snap.iloc[-1]["date"].year
            df_ytd = df_snap[df_snap["date"].dt.year == current_year]
            if len(df_ytd) > 1:
                val_start_ytd = float(df_ytd.iloc[0]["bourse_holdings"])
                val_end_ytd = float(df_ytd.iloc[-1]["bourse_holdings"])
                if val_start_ytd > 0:
                    ytd_perf = (val_end_ytd / val_start_ytd - 1.0) * 100.0

    return {
        "invested_eur": invested_eur,
        "global_perf_pct": global_perf,
        "ytd_perf_pct": ytd_perf,
        "total_dividends": tot_div,
        "total_interests": tot_int,
        "snapshots_df": df_snap,
        "income_df": df_income
    }
