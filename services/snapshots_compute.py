from __future__ import annotations

import logging

import pandas as pd

from services import entreprises_repository as ent_repo
from services import immobilier_repository as immo_repo
from services import market_history
from services import positions
from services import private_equity_repository as pe_repo
from services import repositories as repo
from services.credits import get_crd_a_date, list_credits_by_person
from services.snapshots_helpers import _now_paris_iso

_logger = logging.getLogger(__name__)

try:
    from services import pe_cash_repository as pe_cash_repo
except Exception:
    pe_cash_repo = None


_SENS_FLUX_MAP: dict[str, int] = {
    "DEPOT": 1, "ENTREE": 1, "CREDIT": 1, "VENTE": 1,
    "DIVIDENDE": 1, "INTERETS": 1, "LOYER": 1, "ABONDEMENT": 1,
    "RETRAIT": -1, "SORTIE": -1, "DEBIT": -1, "ACHAT": -1,
    "DEPENSE": -1, "FRAIS": -1, "IMPOT": -1, "REMBOURSEMENT_CREDIT": -1,
}


def _sum_cash_native(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    sens = df["type"].astype(str).str.strip().str.upper().map(_SENS_FLUX_MAP).fillna(0)
    return float((amount * sens).sum())


def _bank_cash_asof_eur(
    conn,
    person_id: int,
    week_date: str,
    tx_cache: "dict[int, pd.DataFrame] | None" = None,
    accounts_cache: "pd.DataFrame | None" = None,
    _tracker: "dict | None" = None,
) -> float:
    accounts = accounts_cache if accounts_cache is not None else repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0

    banks = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"].copy()
    total_eur = 0.0
    week_ts = pd.to_datetime(week_date, errors="coerce")

    def _get_tx(account_id: int) -> pd.DataFrame:
        if tx_cache is not None and account_id in tx_cache:
            df = tx_cache[account_id]
            if df is None or df.empty:
                return df
            if "date_dt" in df.columns and pd.notna(week_ts):
                return df[df["date_dt"] <= week_ts]
            return df[df["date"] <= week_date] if "date" in df.columns else df
        return repo.list_transactions(
            conn, person_id=person_id, account_id=account_id,
            limit=200000, date_asof=week_date,
        )

    for _, acc in banks.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency") or "EUR").upper()

        try:
            is_container = repo.is_bank_container(conn, acc_id)
        except Exception:
            is_container = False

        total_native = 0.0
        if is_container:
            subs = repo.list_bank_subaccounts(conn, acc_id)
            if subs is not None and not subs.empty:
                for _, s in subs.iterrows():
                    sub_id = int(s["sub_account_id"])
                    df = _get_tx(sub_id)
                    if df is not None and not df.empty:
                        total_native += _sum_cash_native(df)
        else:
            df = _get_tx(acc_id)
            if df is not None and not df.empty:
                total_native += _sum_cash_native(df)

        converted = market_history.convert_weekly(conn, float(total_native), acc_ccy, "EUR", week_date)
        if converted is None:
            _logger.warning(
                "_bank_cash_asof_eur: taux %s→EUR introuvable pour week=%s "
                "(compte %s exclu du snapshot — snapshot potentiellement incomplet)",
                acc_ccy, week_date, acc_id,
            )
            if _tracker is not None:
                _tracker["fx_missing"] = _tracker.get("fx_missing", 0) + 1
            continue
        total_eur += converted

    return float(round(total_eur, 2))


from services.bourse_analytics import _broker_cash_asof_native  # noqa: E402


def _bourse_cash_and_holdings_eur_asof(
    conn,
    person_id: int,
    week_date: str,
    tx_cache: "dict[int, pd.DataFrame] | None" = None,
    accounts_cache: "pd.DataFrame | None" = None,
    _tracker: "dict | None" = None,
) -> tuple[float, float]:
    accounts = accounts_cache if accounts_cache is not None else repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0, 0.0

    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
        return 0.0, 0.0

    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id, week_date, account_ids=acc_ids)
    week_ts = pd.to_datetime(week_date, errors="coerce")

    def _get_tx_asof(account_id: int) -> pd.DataFrame:
        if tx_cache is not None and account_id in tx_cache:
            df = tx_cache[account_id]
            if df is None or df.empty:
                return df
            if "date_dt" in df.columns and pd.notna(week_ts):
                return df[df["date_dt"] <= week_ts]
            return df[df["date"] <= week_date] if "date" in df.columns else df
        return repo.list_transactions(
            conn,
            person_id=person_id,
            account_id=account_id,
            limit=200000,
            date_asof=week_date,
        )

    fx_rate_cache: dict[str, float | None] = {}

    def _convert_to_eur(amount_native: float, from_ccy: str) -> float | None:
        ccy = str(from_ccy or "EUR").upper()
        if ccy == "EUR":
            return float(amount_native)
        if ccy not in fx_rate_cache:
            fx_rate_cache[ccy] = market_history.convert_weekly(conn, 1.0, ccy, "EUR", week_date)
        rate = fx_rate_cache[ccy]
        if rate is None:
            return None
        return float(amount_native) * float(rate)

    cash_eur = 0.0
    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_ccy = str(a.get("currency") or "EUR").upper()
        tx = _get_tx_asof(acc_id)
        if tx is None or tx.empty:
            continue
        cash_native = _broker_cash_asof_native(tx)
        converted_cash = _convert_to_eur(cash_native, acc_ccy)
        if converted_cash is None:
            _logger.warning(
                "_bourse_cash_and_holdings_eur_asof: taux %s→EUR introuvable pour week=%s "
                "(cash compte %s exclu du snapshot — snapshot potentiellement incomplet)",
                acc_ccy, week_date, acc_id,
            )
            if _tracker is not None:
                _tracker["fx_missing"] = _tracker.get("fx_missing", 0) + 1
            continue
        cash_eur += converted_cash

    holdings_eur = 0.0
    if pos is not None and not pos.empty:
        pos2 = pos.copy()
        if {"symbol", "quantity"}.issubset(set(pos2.columns)):
            if "asset_ccy" not in pos2.columns:
                pos2["asset_ccy"] = "EUR"
            pos2["symbol"] = pos2["symbol"].astype(str).str.strip()
            pos2["asset_ccy"] = pos2["asset_ccy"].astype(str).str.upper()
            pos2["quantity"] = pd.to_numeric(pos2["quantity"], errors="coerce").fillna(0.0)
            pos2 = pos2[(pos2["symbol"] != "") & (pos2["quantity"] > 0)]
        else:
            pos2 = pd.DataFrame()
        if not pos2.empty:
            grouped = pos2.groupby(["symbol", "asset_ccy"], as_index=False)["quantity"].sum()
            price_cache: dict[str, float | None] = {}
            for _, r in grouped.iterrows():
                sym = str(r["symbol"])
                qty = float(r["quantity"])
                asset_ccy = str(r["asset_ccy"] or "EUR").upper()

                if sym not in price_cache:
                    price_cache[sym] = market_history.get_price_asof(conn, sym, week_date)
                px = price_cache[sym]
                if px is None:
                    if _tracker is not None:
                        _tracker["price_missing"] = _tracker.get("price_missing", 0) + 1
                    continue

                value_native = qty * float(px)
                converted_holding = _convert_to_eur(value_native, asset_ccy)
                if converted_holding is None:
                    _logger.warning(
                        "_bourse_cash_and_holdings_eur_asof: taux %s→EUR introuvable pour week=%s "
                        "(actif %s exclu du snapshot — snapshot potentiellement incomplet)",
                        asset_ccy, week_date, sym,
                    )
                    if _tracker is not None:
                        _tracker["fx_missing"] = _tracker.get("fx_missing", 0) + 1
                    continue
                holdings_eur += converted_holding

    return float(round(cash_eur, 2)), float(round(holdings_eur, 2))


def _pe_cash_asof_eur(conn, person_id: int, week_date: str) -> float:
    if pe_cash_repo is None:
        return 0.0
    df = pe_cash_repo.list_pe_cash_transactions(conn, person_id=person_id)
    if df is None or df.empty:
        return 0.0
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"] if "date" in d.columns else None, errors="coerce")
    d = d.dropna(subset=["date"])
    d = d[d["date"] <= pd.to_datetime(week_date)]
    if d.empty:
        return 0.0
    d["tx_type"] = d["tx_type"].astype(str).str.upper()
    d["amount"] = pd.to_numeric(d["amount"] if "amount" in d.columns else 0.0, errors="coerce").fillna(0.0)

    def sign(t: str) -> float:
        if t == "DEPOSIT":
            return 1.0
        if t == "WITHDRAW":
            return -1.0
        return 1.0

    total = float(d.apply(lambda r: float(r["amount"]) * sign(r["tx_type"]), axis=1).sum())
    return float(round(total, 2))


def _pe_value_asof_eur(conn, person_id: int, week_date: str) -> float:
    projects = pe_repo.list_pe_projects(conn, person_id=person_id)
    tx = pe_repo.list_pe_transactions(conn, person_id=person_id)
    if projects is None or projects.empty or tx is None or tx.empty:
        return 0.0

    d = tx.copy()
    d["date_dt"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date_dt"])
    d = d[d["date_dt"] <= pd.to_datetime(week_date)]

    p = projects.copy()
    p["exit_date_dt"] = pd.to_datetime(p.get("exit_date"), errors="coerce")

    total = 0.0
    for _, pr in p.iterrows():
        pid = int(pr["id"])
        status = str(pr.get("status") or "").upper()

        if status == "SORTI" and pd.notna(pr["exit_date_dt"]) and pr["exit_date_dt"] <= pd.to_datetime(week_date):
            continue

        dpr = d[d["project_id"] == pid].sort_values("date_dt")
        if dpr.empty:
            continue

        valos = dpr[dpr["tx_type"].astype(str).str.upper() == "VALO"]
        if not valos.empty:
            total += float(valos.iloc[-1]["amount"])
        else:
            invests = dpr[dpr["tx_type"].astype(str).str.upper() == "INVEST"]
            total += float(pd.to_numeric(invests["amount"], errors="coerce").fillna(0.0).sum())

    return float(round(total, 2))


def _enterprise_value_asof_eur(conn, person_id: int, week_date: str) -> float:
    pos = ent_repo.list_positions_for_person(conn, person_id=person_id)
    if pos is None or pos.empty:
        return 0.0

    total = 0.0
    wd = pd.to_datetime(week_date).strftime("%Y-%m-%d")
    eids = [int(eid) for eid in pos["enterprise_id"].unique()]
    if not eids:
        return 0.0

    placeholders = ",".join(["?"] * len(eids))
    q = f"""
        SELECT enterprise_id, valuation_eur, debt_eur
        FROM (
            SELECT enterprise_id, valuation_eur, debt_eur,
                   ROW_NUMBER() OVER(PARTITION BY enterprise_id ORDER BY effective_date DESC, id DESC) as rn
            FROM enterprise_history
            WHERE enterprise_id IN ({placeholders})
              AND effective_date <= ?
        )
        WHERE rn = 1
    """
    params = tuple(eids) + (wd,)
    rows = conn.execute(q, params).fetchall()
    hist_map = {}
    for r in rows:
        hist_map[int(r["enterprise_id"])] = (float(r["valuation_eur"] or 0.0), float(r["debt_eur"] or 0.0))

    for _, r in pos.iterrows():
        eid = int(r["enterprise_id"])
        pct = float(r.get("pct") or 0.0) / 100.0

        if eid in hist_map:
            valuation, debt = hist_map[eid]
        else:
            valuation = float(r.get("valuation_eur") or 0.0)
            debt = float(r.get("debt_eur") or 0.0)

        net = max(valuation - debt, 0.0)
        total += pct * net

    return float(round(total, 2))


def _immobilier_value_asof_eur(conn, person_id: int, week_date: str) -> float:
    shares = immo_repo.list_positions_for_person(conn, person_id)
    total_direct = 0.0
    wd = pd.to_datetime(week_date).strftime("%Y-%m-%d")

    if shares is not None and not shares.empty:
        pids = [int(pid) for pid in shares["property_id"].unique()]
        if pids:
            placeholders = ",".join(["?"] * len(pids))
            q = f"""
                SELECT property_id, valuation_eur
                FROM (
                    SELECT property_id, valuation_eur,
                           ROW_NUMBER() OVER(PARTITION BY property_id ORDER BY effective_date DESC, id DESC) as rn
                    FROM immobilier_history
                    WHERE property_id IN ({placeholders})
                      AND effective_date <= ?
                )
                WHERE rn = 1
            """
            params = tuple(pids) + (wd,)
            rows = conn.execute(q, params).fetchall()
            hist_map = {int(r["property_id"]): float(r["valuation_eur"] or 0.0) for r in rows}

            for _, r in shares.iterrows():
                property_id = int(r["property_id"])
                pct = float(r.get("pct", 100.0)) / 100.0
                if property_id in hist_map:
                    valo = hist_map[property_id]
                else:
                    valo = float(r.get("valuation_eur") or 0.0)
                total_direct += valo * pct

    scpi_tx = conn.execute(
        """
        SELECT
            a.id     AS asset_id,
            a.symbol,
            SUM(CASE
                WHEN t.type = 'ACHAT' THEN  t.quantity
                WHEN t.type = 'VENTE' THEN -t.quantity
                ELSE 0
            END) AS qty
        FROM transactions t
        JOIN assets a ON a.id = t.asset_id
        WHERE t.person_id = ?
          AND a.asset_type = 'scpi'
          AND t.date <= ?
        GROUP BY a.id
        HAVING qty > 0.0001
        """,
        (int(person_id), wd),
    ).fetchall()

    total_scpi = 0.0
    for s in scpi_tx:
        qty = float(s["qty"])
        sym = str(s["symbol"])
        px = market_history.get_price_asof(conn, sym, week_date)
        if px is not None:
            total_scpi += qty * float(px)

    return float(round(total_direct + total_scpi, 2))


def _credits_remaining_asof(conn, person_id: int, week_date: str) -> float:
    df = list_credits_by_person(conn, person_id=person_id, only_active=True)
    if df is None or df.empty:
        return 0.0
    total = 0.0
    for _, c in df.iterrows():
        cid = int(c["id"])
        total += float(get_crd_a_date(conn, credit_id=cid, date_ref=week_date))
    return float(round(total, 2))


def upsert_weekly_snapshot(conn, person_id: int, week_date: str, mode: str, payload: dict) -> None:
    import math

    pn = float(payload.get("patrimoine_net", 0.0))
    if math.isnan(pn):
        logging.getLogger(__name__).warning(
            "Snapshot for person %s on %s has missing prices (NaN). Skipping insert.", person_id, week_date
        )
        return

    conn.execute(
        """
        INSERT INTO patrimoine_snapshots_weekly(
            person_id, week_date, created_at, mode,
            patrimoine_net, patrimoine_brut,
            liquidites_total, bank_cash, bourse_cash, pe_cash,
            bourse_holdings, pe_value, ent_value, immobilier_value,
            credits_remaining, notes
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(person_id, week_date) DO UPDATE SET
            created_at = excluded.created_at,
            mode = excluded.mode,
            patrimoine_net = excluded.patrimoine_net,
            patrimoine_brut = excluded.patrimoine_brut,
            liquidites_total = excluded.liquidites_total,
            bank_cash = excluded.bank_cash,
            bourse_cash = excluded.bourse_cash,
            pe_cash = excluded.pe_cash,
            bourse_holdings = excluded.bourse_holdings,
            pe_value = excluded.pe_value,
            ent_value = excluded.ent_value,
            immobilier_value = excluded.immobilier_value,
            credits_remaining = excluded.credits_remaining,
            notes = excluded.notes
        """,
        (
            int(person_id),
            str(week_date),
            _now_paris_iso(),
            str(mode),
            float(payload.get("patrimoine_net", 0.0)),
            float(payload.get("patrimoine_brut", 0.0)),
            float(payload.get("liquidites_total", 0.0)),
            float(payload.get("bank_cash", 0.0)),
            float(payload.get("bourse_cash", 0.0)),
            float(payload.get("pe_cash", 0.0)),
            float(payload.get("bourse_holdings", 0.0)),
            float(payload.get("pe_value", 0.0)),
            float(payload.get("ent_value", 0.0)),
            float(payload.get("immobilier_value", 0.0)),
            float(payload.get("credits_remaining", 0.0)),
            payload.get("notes"),
        ),
    )


def compute_weekly_snapshot_person(
    conn,
    person_id: int,
    week_date: str,
    tx_cache: "dict[int, pd.DataFrame] | None" = None,
    accounts_cache: "pd.DataFrame | None" = None,
) -> dict:
    accounts = accounts_cache if accounts_cache is not None else repo.list_accounts(conn, person_id=person_id)
    _tracker: dict = {"fx_missing": 0, "price_missing": 0}
    bank_cash = _bank_cash_asof_eur(
        conn, person_id, week_date,
        tx_cache=tx_cache, accounts_cache=accounts, _tracker=_tracker,
    )
    bourse_cash, bourse_holdings = _bourse_cash_and_holdings_eur_asof(
        conn,
        person_id,
        week_date,
        tx_cache=tx_cache,
        accounts_cache=accounts,
        _tracker=_tracker,
    )
    pe_cash = _pe_cash_asof_eur(conn, person_id, week_date)
    pe_value = _pe_value_asof_eur(conn, person_id, week_date)
    ent_value = _enterprise_value_asof_eur(conn, person_id, week_date)
    immo_value = _immobilier_value_asof_eur(conn, person_id, week_date)
    credits_remaining = _credits_remaining_asof(conn, person_id, week_date)

    liquidites_total = float(round(bank_cash + bourse_cash + pe_cash, 2))
    patrimoine_brut = float(round(liquidites_total + bourse_holdings + pe_value + ent_value + immo_value, 2))
    patrimoine_net = float(round(patrimoine_brut - credits_remaining, 2))

    n_fx = _tracker.get("fx_missing", 0)
    n_price = _tracker.get("price_missing", 0)
    if n_fx > 0 and n_price > 0:
        notes = f"partial_fx:{n_fx},partial_price:{n_price}"
    elif n_fx > 0:
        notes = f"partial_fx:{n_fx}"
    elif n_price > 0:
        notes = f"partial_price:{n_price}"
    else:
        notes = "complete"

    return {
        "bank_cash": bank_cash,
        "bourse_cash": bourse_cash,
        "pe_cash": pe_cash,
        "liquidites_total": liquidites_total,
        "bourse_holdings": bourse_holdings,
        "pe_value": pe_value,
        "ent_value": ent_value,
        "immobilier_value": immo_value,
        "credits_remaining": credits_remaining,
        "patrimoine_brut": patrimoine_brut,
        "patrimoine_net": patrimoine_net,
        "notes": notes,
    }
