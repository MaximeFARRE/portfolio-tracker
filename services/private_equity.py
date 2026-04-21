# services/private_equity.py
import pandas as pd
from services import repositories as repo
from services import positions, market_history
from services.asset_panel_mapping import INVESTMENT_ACCOUNT_TYPES, is_asset_type_in_panel

TX_INVEST = "INVEST"
TX_DISTRIB = "DISTRIB"
TX_FEES = "FEES"
TX_VALO = "VALO"
TX_VENTE = "VENTE"

STATUS_EN_COURS = "EN_COURS"
STATUS_SORTI = "SORTI"
STATUS_FAILLITE = "FAILLITE"

def _parse_date(s: str) -> pd.Timestamp:
    return pd.to_datetime(s, errors="coerce")

def build_pe_positions(projects: pd.DataFrame, tx: pd.DataFrame) -> pd.DataFrame:
    """
    Retourne une table 'positions' par projet :
    investi, cash_out, last_valo, pnl, moic, entry_date, exit_date_effective, holding_days...
    """
    if projects.empty:
        return projects.copy()

    if tx.empty:
        # Aucun mouvement : on renvoie les projets avec zéros
        out = projects.copy()
        out["invested"] = 0.0
        out["cash_out"] = 0.0
        out["last_valo"] = 0.0
        out["pnl"] = 0.0
        out["moic"] = None
        out["entry_date"] = None
        out["exit_date_effective"] = out.get("exit_date", None)
        out["holding_days"] = None
        return out

    tx2 = tx.copy()
    tx2["date_dt"] = pd.to_datetime(tx2["date"], errors="coerce")

    # Investi = somme INVEST
    invested = tx2[tx2["tx_type"] == TX_INVEST].groupby("project_id")["amount"].sum()

    # Frais = somme FEES
    fees = tx2[tx2["tx_type"] == TX_FEES].groupby("project_id")["amount"].sum()

    # Cash-out = DISTRIB + VENTE
    cash_out = tx2[tx2["tx_type"].isin([TX_DISTRIB, TX_VENTE])].groupby("project_id")["amount"].sum()

    # Last valo = dernière tx VALO (amount = valeur totale snapshot)
    valo = tx2[tx2["tx_type"] == TX_VALO].sort_values("date_dt").groupby("project_id").tail(1).set_index("project_id")["amount"]

    # Entry date = première INVEST
    entry = tx2[tx2["tx_type"] == TX_INVEST].sort_values("date_dt").groupby("project_id").head(1).set_index("project_id")["date_dt"]

    # Exit effective : si projet sort i -> exit_date si dispo sinon dernière VENTE
    last_sale = tx2[tx2["tx_type"] == TX_VENTE].sort_values("date_dt").groupby("project_id").tail(1).set_index("project_id")["date_dt"]

    out = projects.copy()
    out["invested"] = out["id"].map(invested).fillna(0.0)
    out["fees"] = out["id"].map(fees).fillna(0.0)
    out["cash_out"] = out["id"].map(cash_out).fillna(0.0)
    out["last_valo"] = out["id"].map(valo).fillna(0.0)
    out["has_valo"] = out["id"].map(valo).notna()
    out["value_used"] = out["last_valo"]
    out.loc[~out["has_valo"], "value_used"] = out.loc[~out["has_valo"], "invested"]
    out["entry_date"] = out["id"].map(entry)

    # exit date effective
    exit_date_dt = pd.to_datetime(out["exit_date"], errors="coerce") if "exit_date" in out.columns else pd.NaT
    out["exit_date_effective"] = exit_date_dt
    out.loc[out["exit_date_effective"].isna(), "exit_date_effective"] = out["id"].map(last_sale)

    # holding days (si entry ok)
    today = pd.Timestamp.today().normalize()
    end = out["exit_date_effective"].fillna(today)
    out["holding_days"] = (end - out["entry_date"]).dt.days

    # PNL/MOIC
    # Les frais sont suivis séparément (KPI) et sont déjà inclus dans invested.
    out["pnl"] = (out["cash_out"] + out["value_used"]) - out["invested"]

    den = out["invested"]
    out["moic"] = None
    mask = den > 0
    out.loc[mask, "moic"] = (out.loc[mask, "cash_out"] + out.loc[mask, "value_used"]) / den[mask]


    return out

def compute_pe_kpis(positions: pd.DataFrame) -> dict:
    if positions.empty:
        return {
            "invested": 0.0, "cash_out": 0.0, "value": 0.0, "pnl": 0.0, "moic": None,
            "n_total": 0, "n_en_cours": 0, "n_sortis": 0, "n_faillite": 0,
            "n_en_perte": 0, "n_en_gain": 0,
            "success_rate": None,
            "avg_holding_days": None, "avg_exit_days": None,
        }

    fees = float(positions["fees"].sum()) if "fees" in positions.columns else 0.0

    invested = float(positions["invested"].sum())
    cash_out = float(positions["cash_out"].sum())
    value = float(positions["value_used"].sum())
    # Les frais sont indicatifs uniquement (KPI), déjà inclus dans invested.
    pnl = float((cash_out + value) - invested)
    den = invested
    moic = (cash_out + value) / den if den > 0 else None

    n_total = int(len(positions))
    n_en_cours = int((positions["status"] == "EN_COURS").sum())
    n_sortis = int((positions["status"] == "SORTI").sum())
    n_faillite = int((positions["status"] == "FAILLITE").sum())

    # En gain/perte : nécessite valo ou sortie ; mais on calcule quand même
    n_en_gain = int((positions["pnl"] > 0).sum())
    n_en_perte = int((positions["pnl"] < 0).sum())

    # Taux réussite : parmi les SORTI, combien en gain
    exited = positions[positions["status"] == "SORTI"]
    if len(exited) > 0:
        success_rate = float((exited["pnl"] > 0).mean())
        avg_exit_days = float(exited["holding_days"].dropna().mean()) if exited["holding_days"].notna().any() else None
    else:
        success_rate = None
        avg_exit_days = None

    avg_holding_days = float(positions["holding_days"].dropna().mean()) if positions["holding_days"].notna().any() else None

    return {
        "invested": invested,
        "cash_out": cash_out,
        "value": value,
        "pnl": pnl,
        "fees": fees,
        "moic": moic,
        "n_total": n_total,
        "n_en_cours": n_en_cours,
        "n_sortis": n_sortis,
        "n_faillite": n_faillite,
        "n_en_perte": n_en_perte,
        "n_en_gain": n_en_gain,
        "success_rate": success_rate,
        "avg_holding_days": avg_holding_days,
        "avg_exit_days": avg_exit_days,
    }



def build_pe_monthly_series(tx: pd.DataFrame) -> pd.DataFrame:
    """
    Retourne un DF mensuel avec :
    invest, fees, cash_out et une valeur 'value_proxy' (invest cumulé)
    """
    if tx is None or tx.empty:
        return pd.DataFrame(columns=["month", "invest", "fees", "cash_out", "invest_cum"])

    d = tx.copy()
    d["date_dt"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date_dt"])
    d["month"] = d["date_dt"].dt.to_period("M").dt.to_timestamp()

    invest = d[d["tx_type"] == "INVEST"].groupby("month")["amount"].sum()
    fees = d[d["tx_type"] == "FEES"].groupby("month")["amount"].sum()
    cash_out = d[d["tx_type"].isin(["DISTRIB", "VENTE"])].groupby("month")["amount"].sum()

    out = pd.DataFrame(index=sorted(d["month"].unique()))
    out.index.name = "month"
    out["invest"] = invest.reindex(out.index).fillna(0.0)
    out["fees"] = fees.reindex(out.index).fillna(0.0)
    out["cash_out"] = cash_out.reindex(out.index).fillna(0.0)

    # proxy valeur (fallback) : invest cumulé (sans frais)
    out["invest_cum"] = out["invest"].cumsum()

    return out.reset_index()


def add_portfolio_value(series: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute une colonne 'portfolio_value' :
    valeur du portefeuille = investi cumulé + cash-out cumulés
    (fallback cohérent tant qu'il n'y a pas de VALO intermédiaire)
    """
    if series.empty:
        return series

    s = series.copy()
    s = s.sort_values("month")

    s["cash_out_cum"] = s["cash_out"].cumsum()

    # Valeur portefeuille (fallback)
    s["portfolio_value"] = s["invest_cum"] + s["cash_out_cum"]

    return s


def build_pe_portfolio_value_series(projects: pd.DataFrame, tx: pd.DataFrame) -> pd.DataFrame:
    """
    Série mensuelle de la valeur du portefeuille :
    - si VALO existe avant/à la date -> on prend la dernière VALO
    - sinon -> on prend l'investi cumulé (INVEST) jusqu'à la date
    - si projet SORTI et exit_date <= date -> valeur = 0
    """
    if projects is None or projects.empty:
        return pd.DataFrame(columns=["month", "portfolio_value"])

    if tx is None or tx.empty:
        return pd.DataFrame(columns=["month", "portfolio_value"])

    d = tx.copy()
    d["date_dt"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date_dt"])

    # mois (début de mois)
    d["month"] = d["date_dt"].dt.to_period("M").dt.to_timestamp()
    months = sorted(d["month"].unique())

    # préparations
    projects2 = projects.copy()
    projects2["exit_date_dt"] = pd.to_datetime(projects2.get("exit_date"), errors="coerce")

    rows = []
    for m in months:
        total_value = 0.0

        for _, p in projects2.iterrows():
            pid = int(p["id"])

            # si sorti avant/à ce mois -> valeur = 0
            if p.get("status") == "SORTI" and pd.notna(p["exit_date_dt"]) and p["exit_date_dt"] <= m:
                continue

            tx_p = d[d["project_id"] == pid]
            tx_p = tx_p[tx_p["date_dt"] <= m + pd.offsets.MonthEnd(0)]  # inclure tout le mois

            if tx_p.empty:
                continue

            # dernière VALO <= mois
            valos = tx_p[tx_p["tx_type"] == "VALO"].sort_values("date_dt")
            if not valos.empty:
                value = float(valos.iloc[-1]["amount"])
            else:
                # fallback : investi cumulé <= mois (sans frais)
                invested = float(tx_p[tx_p["tx_type"] == "INVEST"]["amount"].sum())
                value = invested

            total_value += value

        rows.append({"month": m, "portfolio_value": total_value})

    return pd.DataFrame(rows)



def compute_platform_cash(
    pe_tx: pd.DataFrame,
    cash_tx: pd.DataFrame,
) -> pd.DataFrame:
    """
    Retourne une DF:
    platform | cash | last_adjust_date | last_adjust_amount

    Logique:
    - On prend le dernier ADJUST par plateforme (snapshot).
    - Ensuite on applique:
        + DEPOSIT, - WITHDRAW
        + (DISTRIB + VENTE) - (INVEST + FEES)
      uniquement sur les mouvements dont la date >= last_adjust_date (ou tout si aucun ADJUST)
    """

    # Normaliser entrées
    if pe_tx is None:
        pe_tx = pd.DataFrame(columns=["platform", "date", "tx_type", "amount"])
    if cash_tx is None:
        cash_tx = pd.DataFrame(columns=["platform", "date", "tx_type", "amount"])

    if pe_tx.empty and cash_tx.empty:
        return pd.DataFrame(columns=["platform", "cash", "last_adjust_date", "last_adjust_amount"])

    pe = pe_tx.copy()
    if not pe.empty:
        pe["date_dt"] = pd.to_datetime(pe["date"], errors="coerce")
        pe = pe.dropna(subset=["date_dt"])
        pe["platform"] = pe["platform"].fillna("Inconnue")

    c = cash_tx.copy()
    if not c.empty:
        c["date_dt"] = pd.to_datetime(c["date"], errors="coerce")
        c = c.dropna(subset=["date_dt"])
        c["platform"] = c["platform"].fillna("Inconnue")

    platforms = set()
    if not pe.empty:
        platforms |= set(pe["platform"].unique().tolist())
    if not c.empty:
        platforms |= set(c["platform"].unique().tolist())

    rows = []

    for plat in sorted(platforms):
        pe_p = pe[pe["platform"] == plat] if not pe.empty else pe
        c_p = c[c["platform"] == plat] if not c.empty else c

        # Dernier ADJUST (snapshot)
        adjust = None
        if not c_p.empty:
            adj = c_p[c_p["tx_type"] == "ADJUST"].sort_values("date_dt")
            if not adj.empty:
                adjust = adj.iloc[-1]

        if adjust is not None:
            base_cash = float(adjust["amount"])
            base_date = adjust["date_dt"]
            last_adjust_date = adjust["date"]
            last_adjust_amount = float(adjust["amount"])
        else:
            base_cash = 0.0
            base_date = pd.Timestamp.min
            last_adjust_date = None
            last_adjust_amount = None

        # Cash tx manuels après base_date
        cash_after = c_p[c_p["date_dt"] >= base_date] if not c_p.empty else c_p
        deposits = float(cash_after[cash_after["tx_type"] == "DEPOSIT"]["amount"].sum()) if not cash_after.empty else 0.0
        withdraws = float(cash_after[cash_after["tx_type"] == "WITHDRAW"]["amount"].sum()) if not cash_after.empty else 0.0

        # Impact PE après base_date
        pe_after = pe_p[pe_p["date_dt"] >= base_date] if not pe_p.empty else pe_p

        invest = float(pe_after[pe_after["tx_type"] == "INVEST"]["amount"].sum()) if not pe_after.empty else 0.0
        fees = float(pe_after[pe_after["tx_type"] == "FEES"]["amount"].sum()) if not pe_after.empty else 0.0
        cash_in = float(pe_after[pe_after["tx_type"].isin(["DISTRIB", "VENTE"])]["amount"].sum()) if not pe_after.empty else 0.0

        cash = base_cash + deposits - withdraws + cash_in - invest - fees

        rows.append({
            "platform": plat,
            "cash": cash,
            "last_adjust_date": last_adjust_date,
            "last_adjust_amount": last_adjust_amount,
        })

    return pd.DataFrame(rows).sort_values("cash", ascending=False)


def _account_asset_type_by_id(conn, asset_ids: list[int]) -> dict[int, str]:
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


def _get_latest_manual_price_asof(conn, asset_id: int, asof_date: str) -> tuple[float, str | None] | None:
    row = conn.execute(
        """
        SELECT price, currency
        FROM prices
        WHERE asset_id = ?
          AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (int(asset_id), str(asof_date)),
    ).fetchone()
    if not row:
        return None
    try:
        price = float(row["price"])
        ccy = row["currency"]
    except Exception:
        price = float(row[0])
        ccy = row[1] if len(row) > 1 else None
    if price <= 0:
        return None
    return price, (str(ccy).upper() if ccy else None)


def _get_latest_buy_price_asof(
    conn,
    person_id: int,
    asset_id: int,
    asof_date: str,
    account_ids: list[int],
) -> tuple[float, str | None] | None:
    if not account_ids:
        return None
    qmarks = ",".join(["?"] * len(account_ids))
    row = conn.execute(
        f"""
        SELECT
            t.price AS tx_price,
            t.amount AS tx_amount,
            t.quantity AS tx_qty,
            a.currency AS asset_ccy
        FROM transactions t
        LEFT JOIN assets a ON a.id = t.asset_id
        WHERE t.person_id = ?
          AND t.asset_id = ?
          AND t.type = 'ACHAT'
          AND t.date <= ?
          AND t.account_id IN ({qmarks})
        ORDER BY t.date DESC, t.id DESC
        LIMIT 1
        """,
        (int(person_id), int(asset_id), str(asof_date), *[int(x) for x in account_ids]),
    ).fetchone()
    if not row:
        return None

    try:
        px = row["tx_price"]
        amount = row["tx_amount"]
        qty = row["tx_qty"]
        ccy = row["asset_ccy"]
    except Exception:
        px = row[0] if len(row) > 0 else None
        amount = row[1] if len(row) > 1 else None
        qty = row[2] if len(row) > 2 else None
        ccy = row[3] if len(row) > 3 else None

    px_num = pd.to_numeric(pd.Series([px]), errors="coerce").iloc[0]
    if pd.notna(px_num) and float(px_num) > 0:
        return float(px_num), (str(ccy).upper() if ccy else None)

    amt_num = pd.to_numeric(pd.Series([amount]), errors="coerce").iloc[0]
    qty_num = pd.to_numeric(pd.Series([qty]), errors="coerce").iloc[0]
    if pd.notna(amt_num) and pd.notna(qty_num) and float(qty_num) > 0:
        return float(amt_num) / float(qty_num), (str(ccy).upper() if ccy else None)
    return None


def get_account_based_pe_assets_asof(conn, person_id: int, asof_date: str) -> pd.DataFrame:
    """
    Actifs détenus via les comptes d'investissement mappés au panel PE:
    fonds / private_equity / non_cote.
    """
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=[
            "asset_id", "symbol", "asset_type", "quantity", "asset_ccy",
            "last_price", "value_eur", "cost_eur", "pnl_eur", "valuation_status",
        ])
    inv_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(INVESTMENT_ACCOUNT_TYPES)].copy()
    if inv_acc.empty:
        return pd.DataFrame(columns=[
            "asset_id", "symbol", "asset_type", "quantity", "asset_ccy",
            "last_price", "value_eur", "cost_eur", "pnl_eur", "valuation_status",
        ])
    inv_account_ids = [int(x) for x in inv_acc["id"].tolist()]

    pos = positions.compute_positions_asof(
        conn,
        person_id=person_id,
        asof_date=asof_date,
        account_ids=inv_account_ids,
    )
    if pos is None or pos.empty:
        return pd.DataFrame(columns=[
            "asset_id", "symbol", "asset_type", "quantity", "asset_ccy",
            "last_price", "value_eur", "cost_eur", "pnl_eur", "valuation_status",
        ])

    aid_num = pd.to_numeric(pos["asset_id"], errors="coerce")
    asset_ids = aid_num.dropna().astype(int).tolist()
    at_map = _account_asset_type_by_id(conn, asset_ids)
    p = pos.copy()
    p["asset_type"] = aid_num.apply(
        lambda aid: at_map.get(int(aid), "autre") if pd.notna(aid) else "autre"
    )
    p = p[p["asset_type"].apply(lambda at: is_asset_type_in_panel(at, "private_equity"))].copy()
    if p.empty:
        return pd.DataFrame(columns=[
            "asset_id", "symbol", "asset_type", "quantity", "asset_ccy",
            "last_price", "value_eur", "cost_eur", "pnl_eur", "valuation_status",
        ])

    p["quantity"] = pd.to_numeric(p["quantity"], errors="coerce").fillna(0.0)
    p = p[p["quantity"] > 0].copy()
    p["symbol"] = p["symbol"].astype(str).str.strip()
    p["asset_ccy"] = p.get("asset_ccy", "EUR").astype(str).str.upper()

    rows: list[dict] = []
    price_cache: dict[tuple[int, str], tuple[float, str | None, str] | None] = {}
    buy_price_cache: dict[int, tuple[float, str | None] | None] = {}
    fx_cache: dict[str, float | None] = {}
    for _, r in p.iterrows():
        sym = str(r.get("symbol") or "").strip()
        if not sym:
            continue
        qty = float(r["quantity"])
        atype = str(r.get("asset_type") or "autre")
        ccy = str(r.get("asset_ccy") or "EUR").upper()
        aid = int(r["asset_id"])
        cache_key = (aid, sym)
        if cache_key not in price_cache:
            manual = _get_latest_manual_price_asof(conn, aid, asof_date)
            if manual is not None:
                price_cache[cache_key] = (float(manual[0]), manual[1], "ok")
            else:
                weekly = market_history.get_price_and_currency_asof(conn, sym, asof_date)
                if weekly is not None:
                    price_cache[cache_key] = (float(weekly[0]), weekly[1], "ok")
                else:
                    buy_px = _get_latest_buy_price_asof(
                        conn,
                        person_id=person_id,
                        asset_id=aid,
                        asof_date=asof_date,
                        account_ids=inv_account_ids,
                    )
                    if buy_px is not None:
                        price_cache[cache_key] = (float(buy_px[0]), buy_px[1], "fallback_buy_price")
                    else:
                        price_cache[cache_key] = None

        px_data = price_cache[cache_key]
        if px_data is None:
            rows.append({
                "asset_id": aid,
                "symbol": sym,
                "asset_type": atype,
                "quantity": qty,
                "asset_ccy": ccy,
                "last_price": None,
                "value_eur": None,
                "cost_eur": None,
                "pnl_eur": None,
                "valuation_status": "missing_price",
            })
            continue
        px, px_ccy, status = px_data
        used_ccy = ccy or str(px_ccy or "EUR").upper()
        value_native = qty * float(px)

        if aid not in buy_price_cache:
            buy_price_cache[aid] = _get_latest_buy_price_asof(
                conn,
                person_id=person_id,
                asset_id=aid,
                asof_date=asof_date,
                account_ids=inv_account_ids,
            )
        buy_info = buy_price_cache.get(aid)
        buy_px_native = float(buy_info[0]) if (buy_info and buy_info[0] is not None) else None
        buy_ccy = str(buy_info[1] or used_ccy).upper() if buy_info else used_ccy

        if used_ccy == "EUR":
            value_eur = value_native
            if buy_px_native is None:
                cost_eur = None
            elif buy_ccy == "EUR":
                cost_eur = qty * buy_px_native
            else:
                buy_rate = market_history.convert_weekly(conn, 1.0, buy_ccy, "EUR", asof_date)
                cost_eur = (qty * buy_px_native * float(buy_rate)) if buy_rate is not None else None
        else:
            if used_ccy not in fx_cache:
                fx_cache[used_ccy] = market_history.convert_weekly(conn, 1.0, used_ccy, "EUR", asof_date)
            rate = fx_cache.get(used_ccy)
            if rate is None:
                value_eur = None
                cost_eur = None
                status = "missing_fx"
            else:
                value_eur = value_native * float(rate)
                if buy_px_native is None:
                    cost_eur = None
                elif buy_ccy == "EUR":
                    cost_eur = qty * buy_px_native
                elif buy_ccy == used_ccy:
                    cost_eur = qty * buy_px_native * float(rate)
                else:
                    buy_rate = market_history.convert_weekly(conn, 1.0, buy_ccy, "EUR", asof_date)
                    cost_eur = (qty * buy_px_native * float(buy_rate)) if buy_rate is not None else None

        pnl_eur = (float(value_eur) - float(cost_eur)) if (value_eur is not None and cost_eur is not None) else None
        rows.append({
            "asset_id": aid,
            "symbol": sym,
            "asset_type": atype,
            "quantity": qty,
            "asset_ccy": used_ccy,
            "last_price": float(px),
            "value_eur": None if value_eur is None else float(value_eur),
            "cost_eur": None if cost_eur is None else float(cost_eur),
            "pnl_eur": None if pnl_eur is None else float(pnl_eur),
            "valuation_status": status,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values("value_eur", ascending=False, na_position="last").reset_index(drop=True)
    return out


def get_account_based_pe_value_asof(conn, person_id: int, asof_date: str) -> float:
    df = get_account_based_pe_assets_asof(conn, person_id=person_id, asof_date=asof_date)
    if df is None or df.empty:
        return 0.0
    vals = pd.to_numeric(df.get("value_eur"), errors="coerce").dropna()
    if vals.empty:
        return 0.0
    return float(round(float(vals.sum()), 2))
