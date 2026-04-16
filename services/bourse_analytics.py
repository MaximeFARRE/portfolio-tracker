from __future__ import annotations

import logging
import math
import pandas as pd

from services import repositories as repo
from services import positions
from services import market_history
from services.asset_panel_mapping import INVESTMENT_ACCOUNT_TYPES, is_asset_type_in_panel
from services.common_utils import safe_float

logger = logging.getLogger(__name__)


def _investment_accounts_df(accounts: pd.DataFrame) -> pd.DataFrame:
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=[])
    return accounts[
        accounts["account_type"].astype(str).str.upper().isin(INVESTMENT_ACCOUNT_TYPES)
    ].copy()


def _asset_type_by_id(conn, asset_ids: list[int]) -> dict[int, str]:
    if not asset_ids:
        return {}
    ids = sorted({int(aid) for aid in asset_ids if aid is not None})
    if not ids:
        return {}
    qmarks = ",".join(["?"] * len(ids))
    rows = conn.execute(
        f"SELECT id, asset_type FROM assets WHERE id IN ({qmarks})",
        tuple(ids),
    ).fetchall()
    out: dict[int, str] = {}
    for row in rows:
        try:
            rid = int(row["id"])
            at = str(row["asset_type"] or "autre")
        except Exception:
            rid = int(row[0])
            at = str(row[1] or "autre")
        out[rid] = at
    return out


def _filter_positions_to_bourse_assets(conn, df_pos: pd.DataFrame) -> pd.DataFrame:
    if df_pos is None or df_pos.empty:
        return pd.DataFrame(columns=df_pos.columns if df_pos is not None else [])
    out = df_pos.copy()
    if "asset_id" not in out.columns:
        return out

    aid_num = pd.to_numeric(out["asset_id"], errors="coerce")
    asset_ids = aid_num.dropna().astype(int).tolist()
    at_map = _asset_type_by_id(conn, asset_ids)
    out["asset_type"] = aid_num.apply(
        lambda aid: at_map.get(int(aid), "autre") if pd.notna(aid) else "autre"
    )
    keep = out["asset_type"].apply(lambda at: is_asset_type_in_panel(at, "bourse"))
    return out[keep].copy()


def _filter_tx_buy_sell_to_bourse_assets(conn, tx_df: pd.DataFrame) -> pd.DataFrame:
    """
    Garde uniquement les achats/ventes portant sur des actifs mappés au panel bourse.
    """
    if tx_df is None or tx_df.empty:
        return pd.DataFrame(columns=tx_df.columns if tx_df is not None else [])
    if "asset_id" not in tx_df.columns:
        # Fallback legacy: si asset_id est absent, on conserve le comportement
        # historique (ACHAT/VENTE tous actifs confondus) plutôt que renvoyer 0.
        df = tx_df.copy()
        df["type"] = df.get("type", "").astype(str).str.upper()
        return df[df["type"].isin(["ACHAT", "VENTE"])].copy()

    df = tx_df.copy()
    df["type"] = df.get("type", "").astype(str).str.upper()
    df = df[df["type"].isin(["ACHAT", "VENTE"])].copy()
    if df.empty:
        return df

    aid_num = pd.to_numeric(df["asset_id"], errors="coerce")
    if aid_num.notna().sum() == 0:
        # Même fallback: pas de mapping possible sans asset_id exploitable.
        return df

    df = df[aid_num.notna()].copy()
    aid_num = pd.to_numeric(df["asset_id"], errors="coerce")
    asset_ids = aid_num.dropna().astype(int).tolist()
    at_map = _asset_type_by_id(conn, asset_ids)
    df["asset_type"] = aid_num.apply(
        lambda aid: at_map.get(int(aid), "autre") if pd.notna(aid) else "autre"
    )
    df = df[df["asset_type"].apply(lambda at: is_asset_type_in_panel(at, "bourse"))].copy()
    return df


def _apply_missing_price_fallback_to_pru_for_pe_assets(pos_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fallback d'affichage pour actifs PE/non-cotés sur tableau de bord compte:
    - si prix manquant, utiliser le PRU courant comme dernier prix connu.
    - évite un vide total en attendant un prix manuel explicite.
    """
    if pos_df is None or pos_df.empty:
        return pd.DataFrame(columns=pos_df.columns if pos_df is not None else [])
    needed = {"asset_type", "last_price", "pru", "quantity"}
    if not needed.issubset(set(pos_df.columns)):
        return pos_df

    out = pos_df.copy()
    last = pd.to_numeric(out["last_price"], errors="coerce")
    pru = pd.to_numeric(out["pru"], errors="coerce")
    qty = pd.to_numeric(out["quantity"], errors="coerce")

    is_pe_asset = out["asset_type"].apply(lambda at: is_asset_type_in_panel(at, "private_equity"))
    missing_price = (last.isna() | (last <= 0))
    can_fallback = missing_price & is_pe_asset & pru.notna() & (pru > 0) & qty.notna() & (qty > 0)
    if not can_fallback.any():
        return out

    out.loc[can_fallback, "last_price"] = pru.loc[can_fallback]
    if "value" in out.columns:
        out.loc[can_fallback, "value"] = qty.loc[can_fallback] * pru.loc[can_fallback]
    if "pnl_latent" in out.columns:
        out.loc[can_fallback, "pnl_latent"] = 0.0
    if "valuation_status" in out.columns:
        out.loc[can_fallback, "valuation_status"] = "fallback_buy_price"
    if "fx_breakdown_status" in out.columns:
        out.loc[can_fallback, "fx_breakdown_status"] = "fallback_buy_price"
    return out


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
    from services.snapshots import get_person_weekly_series
    df = get_person_weekly_series(conn, person_id)
    if df.empty:
        return pd.DataFrame(columns=["date", "holdings_eur"])

    out = df[["week_date", "bourse_holdings"]].copy()
    out = out.rename(columns={"week_date": "date", "bourse_holdings": "holdings_eur"})
    return out


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

    # Comptes d'investissement multi-supports (PEA/PEA_PME/CTO/CRYPTO/AV/PER/PEE).
    bourse_acc = _investment_accounts_df(accounts)
    if bourse_acc.empty:
        return pd.DataFrame(columns=["ticker", "account", "ccy", "qty", "px", "value_eur"])

    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=asof_week_date, account_ids=acc_ids)
    pos = _filter_positions_to_bourse_assets(conn, pos)
    if pos is None or pos.empty:
        return pd.DataFrame(columns=["ticker", "account", "ccy", "qty", "px", "value_eur"])

    # map account id -> name
    acc_name = {int(r["id"]): str(r.get("name") or r.get("nom") or f"Compte {int(r['id'])}") for _, r in bourse_acc.iterrows()}

    price_cache: dict[str, float | None] = {}
    fx_cache: dict[str, float | None] = {}

    def _to_eur(amount_native: float, ccy: str) -> float | None:
        c = str(ccy or "EUR").upper()
        if c == "EUR":
            return float(amount_native)
        if c not in fx_cache:
            fx_cache[c] = market_history.convert_weekly(conn, 1.0, c, "EUR", asof_week_date)
        rate = fx_cache[c]
        if rate is None:
            return None
        return float(amount_native) * float(rate)

    rows = []
    for _, r in pos.iterrows():
        ticker = str(r.get("symbol") or "").strip()
        qty = safe_float(r.get("quantity"), 0.0)
        ccy = str(r.get("asset_ccy") or "EUR").upper()
        account_id = int(r.get("account_id"))

        if not ticker or qty <= 0:
            continue

        if ticker not in price_cache:
            price_cache[ticker] = market_history.get_price_asof(conn, ticker, asof_week_date)
        px = price_cache[ticker]
        if px is None:
            px = 0.0

        value_native = qty * float(px)
        value_eur = _to_eur(value_native, ccy)
        if value_eur is None:
            logger.warning(
                "compute_positions_valued_asof: FX %s→EUR manquant pour %s @ %s, position ignorée.",
                ccy, ticker, asof_week_date,
            )
            continue

        rows.append({
            "ticker": ticker,
            "compte": acc_name.get(account_id, f"Compte {account_id}"),
            "devise": ccy,
            "quantite": qty,
            "prix_weekly": float(px),
            "valeur_eur": round(float(value_eur), 2),
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

    bourse_acc = _investment_accounts_df(accounts)
    if bourse_acc.empty:
        return pd.DataFrame(columns=["Compte", "Type", "Devise", "Cash (EUR)", "Holdings (EUR)", "Total (EUR)", "%"])

    # positions as-of par compte
    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=asof_week_date, account_ids=acc_ids)
    pos = _filter_positions_to_bourse_assets(conn, pos)

    price_cache: dict[str, float] = {}
    fx_cache: dict[str, float | None] = {}

    def _to_eur(amount_native: float, ccy: str) -> float | None:
        c = str(ccy or "EUR").upper()
        if c == "EUR":
            return float(amount_native)
        if c not in fx_cache:
            fx_cache[c] = market_history.convert_weekly(conn, 1.0, c, "EUR", asof_week_date)
        rate = fx_cache[c]
        if rate is None:
            return None
        return float(amount_native) * float(rate)

    # Pré-calc holdings par compte
    holdings_by_acc = {int(aid): 0.0 for aid in acc_ids}
    if pos is not None and not pos.empty:
        for _, r in pos.iterrows():
            aid = int(r["account_id"])
            ticker = str(r.get("symbol") or "").strip()
            qty = safe_float(r.get("quantity"), 0.0)
            ccy = str(r.get("asset_ccy") or "EUR").upper()
            if not ticker or qty <= 0:
                continue

            if ticker not in price_cache:
                price_cache[ticker] = float(market_history.get_price_asof(conn, ticker, asof_week_date) or 0.0)
            px = price_cache[ticker]
            value_native = qty * float(px)
            value_eur = _to_eur(value_native, ccy)
            if value_eur is None:
                logger.warning(
                    "compute_accounts_breakdown_asof: FX %s→EUR manquant pour %s @ %s, ignoré des holdings.",
                    ccy, ticker, asof_week_date,
                )
                continue
            holdings_by_acc[aid] = holdings_by_acc.get(aid, 0.0) + float(value_eur)

    # Cash par compte (en EUR)
    rows = []
    tx_by_account: dict[int, pd.DataFrame] = {}
    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_name = str(a.get("name") or a.get("nom") or f"Compte {acc_id}")
        acc_type = str(a.get("account_type") or "")
        acc_ccy = str(a.get("currency") or "EUR").upper()

        if acc_id not in tx_by_account:
            tx_by_account[acc_id] = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        tx = tx_by_account[acc_id]
        cash_native = 0.0
        if tx is not None and not tx.empty:
            df = tx.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df[df["date"] <= pd.to_datetime(asof_week_date)]
            cash_native = _broker_cash_asof_native(df)

        cash_eur = _to_eur(cash_native, acc_ccy)
        if cash_eur is None:
            logger.warning(
                "compute_accounts_breakdown_asof: FX %s→EUR manquant pour cash du compte %s @ %s, ignoré.",
                acc_ccy, acc_name, asof_week_date,
            )
            continue
        hold_eur = float(holdings_by_acc.get(acc_id, 0.0))
        total_eur = float(cash_eur) + hold_eur

        rows.append({
            "Compte": acc_name,
            "Type": acc_type,
            "Devise": acc_ccy,
            "Cash (EUR)": round(float(cash_eur), 2),
            "Holdings (EUR)": round(hold_eur, 2),
            "Total (EUR)": round(total_eur, 2),
        })

    if not rows:
        return pd.DataFrame(columns=["Compte", "Type", "Devise", "Cash (EUR)", "Holdings (EUR)", "Total (EUR)", "%"])

    out = pd.DataFrame(rows).sort_values("Total (EUR)", ascending=False).reset_index(drop=True)
    total = float(out["Total (EUR)"].sum()) if not out.empty else 0.0
    out["%"] = (out["Total (EUR)"] / total * 100.0).round(2) if total > 0 else 0.0
    return out

def compute_invested_amount_eur_asof(conn, person_id: int, asof_week_date: str) -> float:
    """
    Montant investi net (EUR) :
    = Somme ACHAT (amount+fees) - Somme VENTE (amount - fees) sur comptes d'investissement.
    -> simple, robuste, compréhensible.
    """
    import pandas as pd

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0

    bourse_acc = _investment_accounts_df(accounts)
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

        df_bs = _filter_tx_buy_sell_to_bourse_assets(conn, df)
        buys = df_bs[df_bs["type"] == "ACHAT"]
        sells = df_bs[df_bs["type"] == "VENTE"]

        invested_native = float(buys["amount"].sum() + buys["fees"].sum()) - float(sells["amount"].sum() - sells["fees"].sum())
        converted = market_history.convert_weekly(conn, invested_native, acc_ccy, "EUR", asof_week_date)
        if converted is None:
            logger.warning(
                "compute_invested_amount_eur_asof: FX %s→EUR manquant pour compte %s @ %s, ignoré.",
                acc_ccy, acc_id, asof_week_date,
            )
            continue
        total_eur += converted

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
        
    bourse_acc = _investment_accounts_df(accounts)
    if bourse_acc.empty:
         return pd.DataFrame(columns=["date", "type", "amount_eur", "month", "year"])
    
    rows = []
    missing_fx: list[dict] = []
    fx_cache: dict[tuple[str, str], float | None] = {}
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
            if acc_ccy == "EUR":
                amt_eur = amt_native
            else:
                key = (acc_ccy, date_str)
                if key not in fx_cache:
                    fx_cache[key] = market_history.convert_weekly(conn, 1.0, acc_ccy, "EUR", date_str)
                rate = fx_cache[key]
                amt_eur = None if rate is None else float(amt_native) * float(rate)
            if amt_eur is None:
                logger.warning(
                    "compute_passive_income_history: FX %s→EUR manquant pour %s @ %s, ignoré.",
                    acc_ccy, r["type"], date_str,
                )
                missing_fx.append({
                    "account_id": acc_id,
                    "currency": acc_ccy,
                    "date": date_str,
                    "type": str(r["type"]),
                    "amount_native": round(float(amt_native), 2),
                })
                continue
            rows.append({
                "date": date_str,
                "month": r["date"].strftime("%Y-%m"),
                "year": r["date"].strftime("%Y"),
                "type": r["type"],
                "amount_eur": round(float(amt_eur), 2),
            })
            
    if not rows:
        out = pd.DataFrame(columns=["date", "month", "year", "type", "amount_eur"])
    else:
        out = pd.DataFrame(rows)
    out.attrs["missing_fx"] = missing_fx
    out.attrs["quality_status"] = "partial" if missing_fx else "ok"
    return out

def compute_invested_series(conn, person_id: int) -> pd.DataFrame:
    """
    Retourne la série temporelle cumulée du montant net investi (EUR).
    Utilisée pour tracer la courbe "montant investi" sur le graphe d'évolution.
    Conversion FX au taux actuel (approximation acceptable pour l'affichage).
    """
    from services import fx

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=["date", "invested_eur"])

    bourse_acc = _investment_accounts_df(accounts)
    if bourse_acc.empty:
        return pd.DataFrame(columns=["date", "invested_eur"])

    all_rows = []
    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_ccy = str(a.get("currency") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        if tx is None or tx.empty:
            continue

        df = tx.copy()
        df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
        df = df.dropna(subset=["date"])
        df["type"] = df.get("type", "").astype(str)
        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

        df_bs = _filter_tx_buy_sell_to_bourse_assets(conn, df)
        buys = df_bs[df_bs["type"] == "ACHAT"].copy()
        sells = df_bs[df_bs["type"] == "VENTE"].copy()
        buys["net_native"] = buys["amount"] + buys["fees"]
        sells["net_native"] = -(sells["amount"] - sells["fees"])

        combined = pd.concat([buys[["date", "net_native"]], sells[["date", "net_native"]]])

        if acc_ccy != "EUR":
            rate = fx.ensure_fx_rate(conn, acc_ccy, "EUR")
            if rate is None:
                logger.warning(
                    "compute_invested_series: FX %s→EUR introuvable pour compte %s, ignoré de la série.",
                    acc_ccy, acc_id,
                )
                continue
            combined["net_eur"] = combined["net_native"] * float(rate)
        else:
            combined["net_eur"] = combined["net_native"]

        all_rows.append(combined[["date", "net_eur"]])

    if not all_rows:
        return pd.DataFrame(columns=["date", "invested_eur"])

    all_tx = pd.concat(all_rows, ignore_index=True).sort_values("date")
    all_tx["invested_eur"] = all_tx["net_eur"].cumsum()
    return all_tx[["date", "invested_eur"]].reset_index(drop=True)


def compute_fx_pnl_summary(df_positions: pd.DataFrame) -> dict:
    """
    Calcule l'effet de change (FX) agrégé en EUR.

    Paramètre:
        df_positions: DataFrame retourné par get_live_bourse_positions.
                      Colonnes attendues: asset_ccy + fx_gain_eur (fallback pnl_fx).

    Retourne:
        {
            "total_fx_pnl": float,             # Effet FX total en EUR
            "by_currency": dict[str, float],   # Effet FX agrégé par devise
            "by_account": dict[str, float],    # Effet FX agrégé par compte (si colonne dispo)
            "missing_breakdown_count": int,    # Nb positions étrangères sans décomposition exploitable
            "fx_column": str | None,           # Colonne utilisée (fx_gain_eur ou pnl_fx)
        }
    """
    empty = {
        "total_fx_pnl": 0.0,
        "by_currency": {},
        "by_account": {},
        "missing_breakdown_count": 0,
        "fx_column": None,
    }
    if df_positions is None or df_positions.empty:
        return empty
    if "asset_ccy" not in df_positions.columns:
        return empty

    foreign = df_positions[df_positions["asset_ccy"] != "EUR"].copy()
    if foreign.empty:
        return empty

    fx_col = "fx_gain_eur" if "fx_gain_eur" in foreign.columns else ("pnl_fx" if "pnl_fx" in foreign.columns else None)
    if fx_col is None:
        return empty

    pnl_series = pd.to_numeric(foreign[fx_col], errors="coerce")
    total_fx_pnl = float(pnl_series.dropna().sum())
    missing_breakdown_count = int(pnl_series.isna().sum())

    by_currency = (
        foreign.assign(_fx_val=pnl_series)
        .groupby("asset_ccy")["_fx_val"]
        .sum()
    )
    by_account: dict[str, float] = {}
    if "compte" in foreign.columns:
        grouped = (
            foreign.assign(_fx_val=pnl_series)
            .groupby("compte")["_fx_val"]
            .sum()
        )
        by_account = {str(k): float(v) for k, v in grouped.items()}
    return {
        "total_fx_pnl": total_fx_pnl,
        "by_currency": {str(k): float(v) for k, v in by_currency.items()},
        "by_account": by_account,
        "missing_breakdown_count": missing_breakdown_count,
        "fx_column": fx_col,
    }


def get_bourse_performance_metrics(conn, person_id: int, current_live_value: float | None = None) -> dict:
    """
    Retourne un résumé des métriques boursières globale et YTD ainsi que les DataFrames associées pour l'UI.

    current_live_value : si fourni, utilisé à la place du dernier snapshot pour le calcul de
                         global_perf et comme point final du graphe (évite le décalage snapshot/live).
    """
    from services.snapshots import get_person_weekly_series
    df_raw = get_person_weekly_series(conn, person_id)
    if df_raw.empty:
        df_snap = pd.DataFrame(columns=["date", "bourse_holdings"])
    else:
        df_snap = df_raw[["week_date", "bourse_holdings"]].copy()
        df_snap = df_snap.rename(columns={"week_date": "date"})

    import datetime as _dt
    invested_eur = compute_invested_amount_eur_asof(conn, person_id, _dt.date.today().isoformat())

    df_income = compute_passive_income_history(conn, person_id)
    tot_div = float(df_income[df_income["type"] == "DIVIDENDE"]["amount_eur"].sum()) if not df_income.empty else 0.0
    tot_int = float(df_income[df_income["type"] == "INTERETS"]["amount_eur"].sum()) if not df_income.empty else 0.0

    global_perf = None
    ytd_perf = None
    perf_warnings: list[str] = []

    if not df_snap.empty:
        # Injecter le point live aujourd'hui si le dernier snapshot a plus de 3 jours
        today = pd.Timestamp(_dt.date.today())
        if current_live_value is not None:
            last_snap_date = df_snap["date"].max() if not df_snap.empty else pd.NaT
            if pd.isna(last_snap_date) or (today - last_snap_date).days > 3:
                today_row = pd.DataFrame([{
                    "date": today,
                    "bourse_holdings": float(current_live_value),
                }])
                df_snap = pd.concat([df_snap, today_row], ignore_index=True).sort_values("date")

        if len(df_snap) > 0:
            # Perf globale : on préfère la valeur live si disponible
            current_value = float(current_live_value) if current_live_value is not None else float(df_snap.iloc[-1]["bourse_holdings"])
            if invested_eur > 0:
                global_perf = (current_value / invested_eur - 1.0) * 100.0
            else:
                perf_warnings.append("montant investi non calculable")

            # Perf YTD : toujours basée sur les snapshots (historique intra-année)
            current_year = today.year
            df_ytd = df_snap[df_snap["date"].dt.year == current_year]
            if len(df_ytd) > 1:
                val_start_ytd = float(df_ytd.iloc[0]["bourse_holdings"])
                val_end_ytd = float(df_ytd.iloc[-1]["bourse_holdings"])
                if val_start_ytd > 0:
                    ytd_perf = (val_end_ytd / val_start_ytd - 1.0) * 100.0
                else:
                    perf_warnings.append("base YTD nulle")
            else:
                perf_warnings.append("historique YTD insuffisant")
    else:
        perf_warnings.append("historique bourse absent")

    return {
        "invested_eur": invested_eur,
        "global_perf_pct": global_perf,
        "ytd_perf_pct": ytd_perf,
        "total_dividends": tot_div,
        "total_interests": tot_int,
        "snapshots_df": df_snap,
        "income_df": df_income,
        "quality_status": "partial" if df_income.attrs.get("missing_fx") or perf_warnings else "ok",
        "missing_income_fx": df_income.attrs.get("missing_fx", []),
        "perf_warnings": perf_warnings,
    }

def get_tickers_diagnostic_df(conn, person_id: int) -> pd.DataFrame:
    """
    Retourne un diagnostic de l'état des tickers possédés par une personne.
    - Prix live (table prices)
    - Prix hebdo (table asset_prices_weekly)
    - Statut visuel
    """
    import datetime as _dt
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame()

    bourse_acc = _investment_accounts_df(accounts)
    if bourse_acc.empty:
        return pd.DataFrame()

    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    # Utilise positions.compute_positions_asof avec asof=today pour avoir le live
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=_dt.date.today().isoformat(), account_ids=acc_ids)
    pos = _filter_positions_to_bourse_assets(conn, pos)
    if pos is None or pos.empty:
        return pd.DataFrame()

    # Garde uniquement les positions ouvertes
    pos = pos[pos["quantity"] > 0].copy()
    if pos.empty:
        return pd.DataFrame()

    rows = []
    today = _dt.date.today()

    for _, r in pos.iterrows():
        sym = str(r.get("symbol") or "").strip()
        name = str(r.get("name") or "Inconnu")
        asset_id = r.get("asset_id")
        
        if not sym: continue

        # 1) Dernier prix live (table 'prices')
        # On ne passe pas d'asset_id à repo.get_latest_prices (qui attend une liste),
        # On va faire simple: une requête directe ou via repo si dispo
        row_live = conn.execute(
            "SELECT price, date, currency FROM prices WHERE asset_id = ? ORDER BY date DESC LIMIT 1",
            (asset_id,)
        ).fetchone()

        # 2) Dernier prix hebdo (table 'asset_prices_weekly')
        row_weekly = conn.execute(
            "SELECT adj_close, week_date FROM asset_prices_weekly WHERE symbol = ? ORDER BY week_date DESC LIMIT 1",
            (sym,)
        ).fetchone()

        live_val = f"{row_live['price']:.2f} {row_live['currency']}" if row_live else "—"
        live_date = row_live["date"] if row_live else "—"
        
        weekly_date = row_weekly["week_date"] if row_weekly else "—"

        # Determination du statut
        statut = "✅ OK"
        if not row_live:
            statut = "❌ Pas de prix"
        elif (today - _dt.date.fromisoformat(row_live["date"])).days > 3:
            statut = "⚠️ Ancien (>3j)"
        
        if not row_weekly:
            statut += " (No Hebdo)"

        rows.append({
            "Ticker": sym,
            "Nom": name,
            "Dernier Prix": live_val,
            "MàJ Live": live_date,
            "MàJ Hebdo": weekly_date,
            "Statut": statut
        })

    return pd.DataFrame(rows)


def get_live_bourse_positions(conn, person_id: int) -> pd.DataFrame:
    """
    Point d'entrée unique pour obtenir les positions bourse live consolidées
    d'une personne, tous comptes d'investissement confondus.

    Encapsule :
    - la récupération des comptes bourse
    - l'appel à portfolio.compute_positions_v2_fx pour chaque compte
    - l'agrégation des positions de tous les comptes

    Colonnes retournées :
        asset_id, symbol, name, asset_type, quantity, pru, last_price,
        value, pnl_latent, asset_ccy, compte, type

    Retourne un DataFrame vide (avec les colonnes) si aucune position.
    """
    from services import portfolio

    empty_cols = [
        "asset_id", "symbol", "name", "asset_type", "quantity", "pru",
        "last_price", "value", "pnl_latent",
        "total_gain_eur", "market_gain_eur", "fx_gain_eur", "pnl_fx",
        "asset_ccy", "valuation_status", "fx_breakdown_status", "compte", "type",
    ]

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        logger.info("get_live_bourse_positions: aucun compte pour person_id=%s", person_id)
        return pd.DataFrame(columns=empty_cols)

    df_b = _investment_accounts_df(accounts)
    if df_b.empty:
        logger.info("get_live_bourse_positions: aucun compte bourse pour person_id=%s", person_id)
        return pd.DataFrame(columns=empty_cols)

    all_pos = []
    for _, row in df_b.iterrows():
        account_id = int(row["id"])
        acc_name = str(row.get("name") or row.get("nom") or f"Compte {account_id}")
        acc_type = str(row.get("account_type") or "")
        acc_ccy = str(row.get("currency") or "EUR").upper()

        asset_ids = repo.list_account_asset_ids(conn, account_id=account_id)
        if not asset_ids:
            logger.debug(
                "get_live_bourse_positions: aucun actif lié au compte '%s' (id=%s)",
                acc_name, account_id,
            )
            continue

        tx_acc = repo.list_transactions(conn, account_id=account_id, limit=10000)
        prices = repo.get_latest_prices(conn, asset_ids)

        # Vue globale: toutes les valorisations sont consolidées en EUR.
        pos = portfolio.compute_positions_v2_fx(conn, tx_acc, prices, "EUR")
        if pos is not None and not pos.empty and "asset_type" in pos.columns:
            pos = pos[pos["asset_type"].apply(lambda at: is_asset_type_in_panel(at, "bourse"))].copy()

        if pos.empty:
            logger.debug(
                "get_live_bourse_positions: aucune position pour compte '%s' (id=%s)",
                acc_name, account_id,
            )
            continue

        # Vérifier les prix manquants
        if "last_price" in pos.columns:
            missing_px = pos[pos["last_price"].isna() | (pos["last_price"] <= 0)]
            for _, mp in missing_px.iterrows():
                logger.warning(
                    "get_live_bourse_positions: prix live absent pour %s (compte '%s')",
                    mp.get("symbol", "?"), acc_name,
                )

        pos["compte"] = acc_name
        pos["type"] = acc_type
        all_pos.append(pos)

    if not all_pos:
        logger.info("get_live_bourse_positions: aucune position ouverte pour person_id=%s", person_id)
        return pd.DataFrame(columns=empty_cols)

    df_all = pd.concat(all_pos, ignore_index=True)
    return df_all


def get_live_bourse_positions_for_account(conn, account_id: int) -> pd.DataFrame:
    """
    Retourne les positions live d'un seul compte d'investissement.

    Encapsule l'appel à portfolio.compute_positions_v2_fx pour un
    account_id donné, sans que l'UI ait à manipuler transactions,
    prix ou le moteur de calcul directement.

    Colonnes retournées :
        asset_id, symbol, name, asset_type, quantity, pru, last_price,
        value, pnl_latent, asset_ccy
    """
    from services import portfolio

    empty_cols = [
        "asset_id", "symbol", "name", "asset_type", "quantity", "pru",
        "last_price", "value", "pnl_latent",
        "total_gain_eur", "market_gain_eur", "fx_gain_eur", "pnl_fx",
        "asset_ccy", "valuation_status", "fx_breakdown_status",
    ]

    # Devise du compte
    acc_row = repo.get_account(conn, account_id)
    if acc_row is None:
        logger.warning(
            "get_live_bourse_positions_for_account: compte introuvable (id=%s)", account_id,
        )
        return pd.DataFrame(columns=empty_cols)

    acc_ccy = str(acc_row.get("currency") or "EUR").upper()

    asset_ids = repo.list_account_asset_ids(conn, account_id=account_id)
    if not asset_ids:
        logger.debug(
            "get_live_bourse_positions_for_account: aucun actif lié au compte id=%s",
            account_id,
        )
        return pd.DataFrame(columns=empty_cols)

    tx_acc = repo.list_transactions(conn, account_id=account_id, limit=10000)
    prices = repo.get_latest_prices(conn, asset_ids)

    pos = portfolio.compute_positions_v2_fx(conn, tx_acc, prices, acc_ccy)
    pos = _apply_missing_price_fallback_to_pru_for_pe_assets(pos)

    if pos.empty:
        logger.debug(
            "get_live_bourse_positions_for_account: aucune position pour compte id=%s",
            account_id,
        )
        return pd.DataFrame(columns=empty_cols)

    # Log des prix manquants
    if "last_price" in pos.columns:
        missing_px = pos[pos["last_price"].isna() | (pos["last_price"] <= 0)]
        for _, mp in missing_px.iterrows():
            logger.warning(
                "get_live_bourse_positions_for_account: prix live absent pour %s (compte id=%s)",
                mp.get("symbol", "?"), account_id,
            )

    return pos


def get_bourse_state_asof(conn, person_id: int, asof_date: str) -> dict:
    """
    Ressort l'état complet du portefeuille (KPIs + Positions) à une date passée.
    Servira au debug/historique sur la page Bourse Globale.
    """
    import datetime as _dt
    from services.market_history import get_price_asof, get_fx_asof

    # 1) Liste des comptes bourse
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return {"quality_status": "no_accounts", "missing_prices": [], "missing_fx": []}
    bourse_acc = _investment_accounts_df(accounts)
    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]

    # 2) Positions à cette date
    pos = positions.compute_positions_asof(conn, person_id=person_id, asof_date=asof_date, account_ids=acc_ids)
    pos = _filter_positions_to_bourse_assets(conn, pos)
    if pos is None or pos.empty:
        return {
            "total_val": None,
            "total_invested": None,
            "total_pnl": None,
            "df": pd.DataFrame(),
            "quality_status": "no_positions",
            "missing_prices": [],
            "missing_fx": [],
        }

    # Map account info
    acc_map = {int(r["id"]): {"name": str(r["name"]), "ccy": str(r["currency"] or "EUR").upper()} for _, r in bourse_acc.iterrows()}

    price_cache: dict[str, float | None] = {}
    fx_cache: dict[str, float | None] = {}
    rows = []
    total_val_eur = 0.0
    missing_prices: list[str] = []
    missing_fx: list[dict] = []

    for _, r in pos.iterrows():
        aid = int(r["account_id"])
        sym = str(r.get("symbol") or "").strip()
        qty = float(r.get("quantity") or 0.0)
        asset_ccy = str(r.get("asset_ccy") or "EUR").upper()
        
        if not sym or qty <= 0: continue

        # Prix à la date (weekly fallback ou exact)
        if sym not in price_cache:
            price_cache[sym] = get_price_asof(conn, sym, asof_date)
        px = price_cache[sym]
        valuation_status = "ok"
        val_native = None
        if px is None:
            valuation_status = "missing_price"
            if sym not in missing_prices:
                missing_prices.append(sym)
        else:
            val_native = qty * float(px)
        
        # Taux de change (asset_ccy -> EUR)
        fx_rate = 1.0 if asset_ccy == "EUR" else None
        if valuation_status == "ok" and asset_ccy != "EUR":
            if asset_ccy not in fx_cache:
                fx_cache[asset_ccy] = get_fx_asof(conn, asset_ccy, "EUR", asof_date)
            if fx_cache[asset_ccy] is None:
                valuation_status = "missing_fx"
                missing_fx.append({"symbol": sym, "currency": asset_ccy, "date": asof_date})
            else:
                fx_rate = float(fx_cache[asset_ccy])
        
        val_eur = None
        if valuation_status == "ok" and val_native is not None and fx_rate is not None:
            val_eur = val_native * fx_rate
            total_val_eur += val_eur

        rows.append({
            "symbol": sym,
            "name": sym, # fallback
            "quantity": qty,
            "last_price": px,
            "currency": asset_ccy,
            "fx_rate": fx_rate,
            "value": val_eur,
            "valuation_status": valuation_status,
            "compte": acc_map.get(aid, {}).get("name", "Inconnu"),
        })

    # 3) Montant investi à cette date
    invested_eur = compute_invested_amount_eur_asof(conn, person_id, asof_date)

    has_rows = bool(rows)
    has_valued_rows = any(r.get("value") is not None for r in rows)
    total_val = total_val_eur if has_valued_rows else None
    return {
        "total_val": total_val,
        "total_invested": invested_eur,
        "total_pnl": (total_val - invested_eur) if total_val is not None and invested_eur > 0 else None,
        "df": pd.DataFrame(rows).sort_values("value", ascending=False, na_position="last"),
        "quality_status": "partial" if (missing_prices or missing_fx) else ("ok" if has_rows else "no_positions"),
        "missing_prices": missing_prices,
        "missing_fx": missing_fx,
    }
