from __future__ import annotations
import datetime as dt
import logging
from datetime import datetime
import pandas as pd
import pytz

from services import repositories as repo
from services import market_history
from services import positions
from services import private_equity_repository as pe_repo
from services import entreprises_repository as ent_repo
from services import immobilier_repository as immo_repo
from services.credits import list_credits_by_person, get_crd_a_date

_logger = logging.getLogger(__name__)

# pe cash tx repo (existe déjà chez toi)
try:
    from services import pe_cash_repository as pe_cash_repo
except Exception:
    pe_cash_repo = None

def _now_paris_iso() -> str:
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).replace(microsecond=0).isoformat()

def _today_paris_date() -> dt.date:
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).date()

def _list_weeks(start: dt.date, end: dt.date) -> list[str]:
    s = market_history.week_start(start)
    e = market_history.week_start(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += dt.timedelta(days=7)
    return out

# --------------------
# CASH BANQUE as-of
# --------------------

# Map vectorisé pour éviter .apply(lambda) ligne à ligne
_SENS_FLUX_MAP: dict[str, int] = {
    "DEPOT": 1, "ENTREE": 1, "CREDIT": 1, "VENTE": 1,
    "DIVIDENDE": 1, "INTERETS": 1, "LOYER": 1, "ABONDEMENT": 1,
    "RETRAIT": -1, "SORTIE": -1, "DEBIT": -1, "ACHAT": -1,
    "DEPENSE": -1, "FRAIS": -1, "IMPOT": -1, "REMBOURSEMENT_CREDIT": -1,
}


def _sum_cash_native(df: pd.DataFrame) -> float:
    """Calcule le solde natif d'un DataFrame de transactions (vectorisé)."""
    if df.empty:
        return 0.0
    amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    sens = df["type"].astype(str).str.strip().str.upper().map(_SENS_FLUX_MAP).fillna(0)
    return float((amount * sens).sum())


def _bank_cash_asof_eur(conn, person_id: int, week_date: str,
                        tx_cache: "dict[int, pd.DataFrame] | None" = None) -> float:
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0

    banks = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"].copy()
    total_eur = 0.0

    def _get_tx(account_id: int) -> pd.DataFrame:
        """Récupère les transactions <= week_date depuis le cache ou la DB."""
        if tx_cache is not None and account_id in tx_cache:
            df = tx_cache[account_id]
            return df[df["date"] <= week_date] if not df.empty else df
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

        total_eur += market_history.convert_weekly(conn, float(total_native), acc_ccy, "EUR", week_date)

    return float(round(total_eur, 2))

# --------------------
# CASH BOURSE as-of
# --------------------
from services.bourse_analytics import _broker_cash_asof_native  # noqa: E402

def _bourse_cash_and_holdings_eur_asof(conn, person_id: int, week_date: str) -> tuple[float, float]:
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0, 0.0

    bourse_acc = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    if bourse_acc.empty:
        return 0.0, 0.0

    acc_ids = [int(x) for x in bourse_acc["id"].tolist()]
    pos = positions.compute_positions_asof(conn, person_id, week_date, account_ids=acc_ids)

    cash_eur = 0.0
    for _, a in bourse_acc.iterrows():
        acc_id = int(a["id"])
        acc_ccy = str(a.get("currency") or "EUR").upper()
        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
        if tx is None or tx.empty:
            continue
        df = tx.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df[df["date"] <= pd.to_datetime(week_date)]
        cash_native = _broker_cash_asof_native(df)
        cash_eur += market_history.convert_weekly(conn, cash_native, acc_ccy, "EUR", week_date)

    holdings_eur = 0.0
    if pos is not None and not pos.empty:
        for _, r in pos.iterrows():
            sym = str(r.get("symbol") or "").strip()
            qty = float(r.get("quantity") or 0.0)
            asset_ccy = str(r.get("asset_ccy") or "EUR").upper()
            if not sym or qty <= 0:
                continue
            px = market_history.get_price_asof(conn, sym, week_date)
            if px is None:
                continue
            value_native = qty * float(px)
            holdings_eur += market_history.convert_weekly(conn, value_native, asset_ccy, "EUR", week_date)

    return float(round(cash_eur, 2)), float(round(holdings_eur, 2))

# --------------------
# PE cash + valo as-of
# --------------------
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
        return 1.0  # ADJUST: laisse le signe de amount

    total = float(d.apply(lambda r: float(r["amount"]) * sign(r["tx_type"]), axis=1).sum())
    return float(round(total, 2))  # supposé EUR

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

# --------------------
# Entreprises as-of
# --------------------
def _enterprise_value_asof_eur(conn, person_id: int, week_date: str) -> float:
    # positions pour la personne (avec pct)
    pos = ent_repo.list_positions_for_person(conn, person_id=person_id)
    if pos is None or pos.empty:
        return 0.0

    total = 0.0
    wd = pd.to_datetime(week_date)

    for _, r in pos.iterrows():
        eid = int(r["enterprise_id"])
        pct = float(r.get("pct") or 0.0) / 100.0

        # dernière ligne d'historique <= week_date (sinon fallback sur enterprises table)
        row = conn.execute(
            """
            SELECT valuation_eur, debt_eur
            FROM enterprise_history
            WHERE enterprise_id = ?
              AND effective_date <= ?
            ORDER BY effective_date DESC, id DESC
            LIMIT 1
            """,
            (eid, wd.strftime("%Y-%m-%d")),
        ).fetchone()

        if row:
            try:
                valuation = float(row["valuation_eur"])
                debt = float(row["debt_eur"])
            except (TypeError, KeyError):
                valuation = float(row[0] or 0.0)
                debt = float(row[1] or 0.0)
        else:
            # fallback "actuel"
            valuation = float(r.get("valuation_eur") or 0.0)
            debt = float(r.get("debt_eur") or 0.0)

        net = max(valuation - debt, 0.0)
        total += pct * net

    return float(round(total, 2))

# --------------------
# Immobilier as-of
# --------------------
def _immobilier_value_asof_eur(conn, person_id: int, week_date: str) -> float:
    # 1. Biens directs
    shares = immo_repo.list_positions_for_person(conn, person_id)
    total_direct = 0.0
    wd = pd.to_datetime(week_date)

    if shares is not None and not shares.empty:
        for _, r in shares.iterrows():
            property_id = int(r["property_id"])
            pct = float(r.get("pct", 100.0)) / 100.0

            # Latest valuation from history <= week_date
            row = conn.execute(
                """
                SELECT valuation_eur
                FROM immobilier_history
                WHERE property_id = ?
                  AND effective_date <= ?
                ORDER BY effective_date DESC, id DESC
                LIMIT 1
                """,
                (property_id, wd.strftime("%Y-%m-%d")),
            ).fetchone()

            if row:
                valo = float(row["valuation_eur"])
            else:
                # Fallback to current valuation from immobiliers table
                valo = float(r.get("valuation_eur") or 0.0)

            total_direct += valo * pct

    # 2. SCPI automatiques (via transactions)
    # On recalcule les positions à la date T
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
        (int(person_id), wd.strftime("%Y-%m-%d")),
    ).fetchall()

    total_scpi = 0.0
    for s in scpi_tx:
        qty = float(s["qty"])
        sym = str(s["symbol"])
        px = market_history.get_price_asof(conn, sym, week_date)
        if px is not None:
            total_scpi += qty * float(px)

    return float(round(total_direct + total_scpi, 2))

# --------------------
# Crédit as-of
# --------------------
def _credits_remaining_asof(conn, person_id: int, week_date: str) -> float:
    df = list_credits_by_person(conn, person_id=person_id, only_active=True)
    if df is None or df.empty:
        return 0.0
    total = 0.0
    for _, c in df.iterrows():
        cid = int(c["id"])
        total += float(get_crd_a_date(conn, credit_id=cid, date_ref=week_date))
    return float(round(total, 2))

# --------------------
# Snapshot write
# --------------------
def upsert_weekly_snapshot(conn, person_id: int, week_date: str, mode: str, payload: dict) -> None:
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

def compute_weekly_snapshot_person(conn, person_id: int, week_date: str,
                                    tx_cache: "dict[int, pd.DataFrame] | None" = None) -> dict:
    bank_cash = _bank_cash_asof_eur(conn, person_id, week_date, tx_cache=tx_cache)
    bourse_cash, bourse_holdings = _bourse_cash_and_holdings_eur_asof(conn, person_id, week_date)
    pe_cash = _pe_cash_asof_eur(conn, person_id, week_date)
    pe_value = _pe_value_asof_eur(conn, person_id, week_date)
    ent_value = _enterprise_value_asof_eur(conn, person_id, week_date)
    immo_value = _immobilier_value_asof_eur(conn, person_id, week_date)
    credits_remaining = _credits_remaining_asof(conn, person_id, week_date)

    liquidites_total = float(round(bank_cash + bourse_cash + pe_cash, 2))
    patrimoine_brut = float(round(liquidites_total + bourse_holdings + pe_value + ent_value + immo_value, 2))
    patrimoine_net = float(round(patrimoine_brut - credits_remaining, 2))

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
        "notes": "Weekly snapshot (as-of) rebuilt",
    }

def rebuild_snapshots_person(conn, person_id: int, lookback_days: int = 90) -> dict:
    end = market_history.week_start(_today_paris_date())
    start = end - dt.timedelta(days=int(lookback_days))
    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks"}

    # tickers + devises depuis assets liés aux transactions
    tx = repo.list_transactions(conn, person_id=person_id, limit=300000)
    symbols = []
    pairs = set()

    if tx is not None and not tx.empty:
        tx2 = tx[tx["asset_symbol"].notna()].copy()
        symbols = sorted(set([str(s).strip() for s in tx2["asset_symbol"].tolist() if str(s).strip()]))

        asset_ids = sorted(set([int(x) for x in tx2["asset_id"].dropna().astype(int).tolist()]))
        if asset_ids:
            q = ",".join(["?"] * len(asset_ids))
            rows = conn.execute(f"SELECT id, currency FROM assets WHERE id IN ({q})", tuple(asset_ids)).fetchall()
            for r in rows:
                ccy = (r["currency"] or "EUR").upper()
                if ccy != "EUR":
                    pairs.add((ccy, "EUR"))

    # AJOUT: On s'assure que les devises des comptes eux-mêmes sont incluses
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is not None and not accounts.empty:
        for _, acc in accounts.iterrows():
            ccy = str(acc.get("currency") or "EUR").upper()
            if ccy != "EUR":
                pairs.add((ccy, "EUR"))

    # AJOUT: Toujours synchroniser l'USD pour permettre le pivot (ex: COP → USD → EUR)
    pairs.add(("USD", "EUR"))

    # Import weekly market data
    if symbols:
        market_history.sync_asset_prices_weekly(conn, symbols, weeks[0], weeks[-1])
    if pairs:
        market_history.sync_fx_weekly(conn, sorted(list(pairs)), weeks[0], weeks[-1])

    # Cache des transactions bancaires par account_id (évite N*W requêtes SQL)
    bank_tx_cache: dict[int, pd.DataFrame] = {}
    if accounts is not None and not accounts.empty:
        bank_accs = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"]
        for _, acc in bank_accs.iterrows():
            acc_id = int(acc["id"])
            try:
                is_container = repo.is_bank_container(conn, acc_id)
            except Exception:
                is_container = False
            if is_container:
                subs = repo.list_bank_subaccounts(conn, acc_id)
                if subs is not None and not subs.empty:
                    for _, s in subs.iterrows():
                        sub_id = int(s["sub_account_id"])
                        df = repo.list_transactions(conn, person_id=person_id, account_id=sub_id, limit=200000)
                        if df is not None and not df.empty:
                            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                            bank_tx_cache[sub_id] = df
            else:
                df = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=200000)
                if df is not None and not df.empty:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                    bank_tx_cache[acc_id] = df

    n_ok = 0
    for wd in weeks:
        payload = compute_weekly_snapshot_person(conn, person_id, wd, tx_cache=bank_tx_cache)
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()
    return {"did_run": True, "n_weeks": len(weeks), "start": weeks[0], "end": weeks[-1], "n_ok": n_ok}


def rebuild_snapshots_person_missing_only(
    conn,
    person_id: int,
    lookback_days: int = 90,
    recalc_days: int = 0,
) -> dict:
    """
    Rebuild intelligent :
    - Crée UNIQUEMENT les snapshots weekly manquantes dans la fenêtre lookback_days
    - Optionnel: recalc les X derniers jours (fenêtre glissante) même si déjà présents
      (recalc_days=0 => pas de recalcul supplémentaire)
    """
    end = market_history.week_start(_today_paris_date())
    start = end - dt.timedelta(days=int(lookback_days))
    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks"}

    # 1) semaines existantes en base
    df_have = pd.read_sql_query(
        """
        SELECT week_date
        FROM patrimoine_snapshots_weekly
        WHERE person_id = ?
          AND week_date >= ?
          AND week_date <= ?
        """,
        conn,
        params=(int(person_id), str(weeks[0]), str(weeks[-1])),
    )
    have = set()
    if df_have is not None and not df_have.empty:
        have = set(df_have["week_date"].astype(str).tolist())

    missing = [wd for wd in weeks if wd not in have]

    # 2) fenêtre glissante optionnelle (recalc)
    recalc_weeks = []
    if int(recalc_days) > 0:
        recalc_start = end - dt.timedelta(days=int(recalc_days))
        recalc_weeks = _list_weeks(recalc_start, end)

    # 3) semaines à traiter = missing + recalc_weeks (unique)
    todo = sorted(set(missing + recalc_weeks))
    if not todo:
        return {"did_run": False, "reason": "nothing_to_do", "n_missing": 0, "n_recalc": 0}

    # --- Même logique que rebuild_snapshots_person pour récupérer tickers + FX
    tx = repo.list_transactions(conn, person_id=person_id, limit=300000)
    symbols = []
    pairs = set()

    if tx is not None and not tx.empty:
        tx2 = tx[tx["asset_symbol"].notna()].copy()
        symbols = sorted(set([str(s).strip() for s in tx2["asset_symbol"].tolist() if str(s).strip()]))

        asset_ids = sorted(set([int(x) for x in tx2["asset_id"].dropna().astype(int).tolist()]))
        if asset_ids:
            q = ",".join(["?"] * len(asset_ids))
            rows = conn.execute(f"SELECT id, currency FROM assets WHERE id IN ({q})", tuple(asset_ids)).fetchall()
            for r in rows:
                ccy = (r["currency"] or "EUR").upper()
                if ccy != "EUR":
                    pairs.add((ccy, "EUR"))

    # AJOUT: ensure account currencies + USD pivot
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is not None and not accounts.empty:
        for _, acc in accounts.iterrows():
            ccy = str(acc.get("currency") or "EUR").upper()
            if ccy != "EUR":
                pairs.add((ccy, "EUR"))
    pairs.add(("USD", "EUR"))

    # Import weekly market data (sur l'intervalle global, simple et safe)
    if symbols:
        market_history.sync_asset_prices_weekly(conn, symbols, weeks[0], weeks[-1])
    if pairs:
        market_history.sync_fx_weekly(conn, sorted(list(pairs)), weeks[0], weeks[-1])

    # 4) upsert uniquement semaines todo
    n_ok = 0
    for wd in todo:
        payload = compute_weekly_snapshot_person(conn, person_id, wd)
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()
    return {
        "did_run": True,
        "mode": "MISSING_ONLY",
        "person_id": int(person_id),
        "window_start": weeks[0],
        "window_end": weeks[-1],
        "n_missing": len(missing),
        "n_recalc": len(recalc_weeks),
        "n_done": len(todo),
        "n_ok": n_ok,
    }

def rebuild_snapshots_person_from_last(
    conn,
    person_id: int,
    safety_weeks: int = 4,
    fallback_lookback_days: int = 90,
) -> dict:
    """
    Rebuild "quotidien" ultra rapide :
    - Cherche la dernière snapshot weekly existante pour la personne
    - Rebuild depuis cette date jusqu'à aujourd'hui
    - + recalcul d'une fenêtre de sécurité (safety_weeks) pour corriger les incohérences récentes
    - Si aucune snapshot n'existe, fallback sur lookback_days (90j)

    ⚠️ Ne casse pas l'existant : fonction additive.
    """
    end = market_history.week_start(_today_paris_date())

    # 1) Dernière snapshot existante
    row = conn.execute(
        "SELECT MAX(week_date) AS d FROM patrimoine_snapshots_weekly WHERE person_id=?",
        (int(person_id),),
    ).fetchone()

    last_week = None
    _d_val = None
    if row:
        try:
            _d_val = row["d"]
        except (TypeError, KeyError):
            _d_val = row[0]
    if row and _d_val:
        try:
            last_week = pd.to_datetime(_d_val, errors="coerce")
            if pd.isna(last_week):
                last_week = None
        except Exception:
            last_week = None

    # 2) Définir start
    if last_week is None:
        # aucun historique => fallback fenêtre 90j
        start = end - dt.timedelta(days=int(fallback_lookback_days))
        start = market_history.week_start(start)
        mode = "FROM_LAST_FALLBACK"
    else:
        # on recule d'une fenêtre de sécurité
        start = (last_week.date() - dt.timedelta(days=int(safety_weeks) * 7))
        start = market_history.week_start(start)
        mode = "FROM_LAST"

    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "reason": "no_weeks", "mode": mode}

    # 3) Import marché (comme rebuild_snapshots_person) sur la période utile
    tx = repo.list_transactions(conn, person_id=person_id, limit=300000)
    symbols = []
    pairs = set()

    if tx is not None and not tx.empty:
        tx2 = tx[tx["asset_symbol"].notna()].copy()
        symbols = sorted(set([str(s).strip() for s in tx2["asset_symbol"].tolist() if str(s).strip()]))

        asset_ids = sorted(set([int(x) for x in tx2["asset_id"].dropna().astype(int).tolist()]))
        if asset_ids:
            q = ",".join(["?"] * len(asset_ids))
            rows = conn.execute(f"SELECT id, currency FROM assets WHERE id IN ({q})", tuple(asset_ids)).fetchall()
            for r in rows:
                ccy = (r["currency"] or "EUR").upper()
                if ccy != "EUR":
                    pairs.add((ccy, "EUR"))

    # AJOUT: ensure account currencies + USD pivot
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is not None and not accounts.empty:
        for _, acc in accounts.iterrows():
            ccy = str(acc.get("currency") or "EUR").upper()
            if ccy != "EUR":
                pairs.add((ccy, "EUR"))
    pairs.add(("USD", "EUR"))

    if symbols:
        market_history.sync_asset_prices_weekly(conn, symbols, weeks[0], weeks[-1])
    if pairs:
        market_history.sync_fx_weekly(conn, sorted(list(pairs)), weeks[0], weeks[-1])

    # 4) Traitement :
    # - Toujours recalculer toutes les semaines dans weeks (petit volume, rapide)
    #   (car on inclut la fenêtre de sécurité)
    n_ok = 0
    for wd in weeks:
        payload = compute_weekly_snapshot_person(conn, person_id, wd)
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()

    return {
        "did_run": True,
        "mode": mode,
        "person_id": int(person_id),
        "start": weeks[0],
        "end": weeks[-1],
        "safety_weeks": int(safety_weeks),
        "fallback_lookback_days": int(fallback_lookback_days),
        "n_weeks": len(weeks),
        "n_ok": n_ok,
    }


def _ensure_rebuild_watermarks(conn) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS rebuild_watermarks (
      scope TEXT NOT NULL,          -- ex: 'WEEKLY_PERSON'
      entity_id INTEGER NOT NULL,   -- person_id
      last_tx_id INTEGER,
      last_tx_created_at TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(scope, entity_id)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rw_scope_entity ON rebuild_watermarks(scope, entity_id);")
    conn.commit()


def _get_person_watermark(conn, person_id: int) -> dict:
    _ensure_rebuild_watermarks(conn)
    row = conn.execute(
        "SELECT last_tx_id, last_tx_created_at FROM rebuild_watermarks WHERE scope=? AND entity_id=?",
        ("WEEKLY_PERSON", int(person_id)),
    ).fetchone()
    if not row:
        return {"last_tx_id": None, "last_tx_created_at": None}
    try:
        return {"last_tx_id": row["last_tx_id"], "last_tx_created_at": row["last_tx_created_at"]}
    except (TypeError, KeyError):
        return {"last_tx_id": row[0], "last_tx_created_at": row[1]}


def _set_person_watermark(conn, person_id: int, last_tx_id: int | None, last_tx_created_at: str | None) -> None:
    _ensure_rebuild_watermarks(conn)
    now = pd.Timestamp.now(tz="Europe/Paris").replace(microsecond=0).isoformat()
    conn.execute(
        """
        INSERT INTO rebuild_watermarks(scope, entity_id, last_tx_id, last_tx_created_at, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(scope, entity_id) DO UPDATE SET
          last_tx_id = excluded.last_tx_id,
          last_tx_created_at = excluded.last_tx_created_at,
          updated_at = excluded.updated_at
        """,
        ("WEEKLY_PERSON", int(person_id), last_tx_id, last_tx_created_at, now),
    )
    conn.commit()


def rebuild_snapshots_person_backdated_aware(
    conn,
    person_id: int,
    safety_weeks: int = 4,
    fallback_lookback_days: int = 3650,
) -> dict:
    """
    B4: Rebuild backdated-aware (transactions ajoutées récemment mais avec date ancienne)
    - Detecte les NOUVELLES transactions depuis le dernier run (via id/created_at)
    - Trouve la date métier la plus ancienne parmi ces nouvelles transactions
    - Rebuild de la semaine correspondante (moins safety_weeks) jusqu'à aujourd'hui
    - Met à jour un watermark (last_tx_id / last_tx_created_at)

    Limite: si tu EDITES une transaction existante, on ne la détecte pas (pas d'updated_at).
    """
    _ensure_rebuild_watermarks(conn)

    # Seuil "aujourd'hui" en weekly
    end = market_history.week_start(_today_paris_date())

    # 1) watermark actuel
    wm = _get_person_watermark(conn, person_id)
    last_tx_id = wm.get("last_tx_id")

    # 2) récupérer les transactions "nouvelles"
    #    V1: basé sur ID (simple et fiable si tu n'update pas les IDs)
    if last_tx_id is None:
        df_new = pd.read_sql_query(
            """
            SELECT t.id, t.date, t.created_at, t.asset_id,
                   a.symbol AS asset_symbol
            FROM transactions t
            LEFT JOIN assets a ON a.id = t.asset_id
            WHERE t.person_id=?
            ORDER BY t.id ASC
            """,
            conn,
            params=(int(person_id),),
        )
    else:
        df_new = pd.read_sql_query(
            """
            SELECT t.id, t.date, t.created_at, t.asset_id,
                   a.symbol AS asset_symbol
            FROM transactions t
            LEFT JOIN assets a ON a.id = t.asset_id
            WHERE t.person_id=? AND t.id > ?
            ORDER BY t.id ASC
            """,
            conn,
            params=(int(person_id), int(last_tx_id)),
        )

    if df_new is None or df_new.empty:
        # Rien de nouveau => à jour
        return {"did_run": False, "mode": "BACKDATED_AWARE", "reason": "no_new_transactions", "person_id": int(person_id)}

    # 3) date métier la plus ancienne parmi les nouvelles tx
    df_new["date"] = pd.to_datetime(df_new["date"], errors="coerce")
    df_new = df_new.dropna(subset=["date"])
    if df_new.empty:
        return {"did_run": False, "mode": "BACKDATED_AWARE", "reason": "new_transactions_no_valid_date", "person_id": int(person_id)}

    min_date = df_new["date"].min().date()

    # 4) start = semaine(min_date) - safety_weeks
    start = market_history.week_start(min_date - dt.timedelta(days=int(safety_weeks) * 7))

    # garde-fou : si ça remonte trop loin, on limite (mais on te le dit)
    floor = end - dt.timedelta(days=int(fallback_lookback_days))
    floor = market_history.week_start(floor)
    truncated = False
    if start < floor:
        start = floor
        truncated = True

    weeks = _list_weeks(start, end)
    if not weeks:
        return {"did_run": False, "mode": "BACKDATED_AWARE", "reason": "no_weeks", "person_id": int(person_id)}

    # 5) Import marché sur l'intervalle utile (même logique que tes autres rebuild)
    tx_all = repo.list_transactions(conn, person_id=person_id, limit=300000)
    symbols = []
    pairs = set()

    if tx_all is not None and not tx_all.empty:
        tx2 = tx_all[tx_all["asset_symbol"].notna()].copy()
        symbols = sorted(set([str(s).strip() for s in tx2["asset_symbol"].tolist() if str(s).strip()]))

        asset_ids = sorted(set([int(x) for x in tx2["asset_id"].dropna().astype(int).tolist()]))
        if asset_ids:
            q = ",".join(["?"] * len(asset_ids))
            rows = conn.execute(f"SELECT id, currency FROM assets WHERE id IN ({q})", tuple(asset_ids)).fetchall()
            for r in rows:
                ccy = (r["currency"] or "EUR").upper()
                if ccy != "EUR":
                    pairs.add((ccy, "EUR"))

    # AJOUT: ensure account currencies + USD pivot
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is not None and not accounts.empty:
        for _, acc in accounts.iterrows():
            ccy = str(acc.get("currency") or "EUR").upper()
            if ccy != "EUR":
                pairs.add((ccy, "EUR"))
    pairs.add(("USD", "EUR"))

    if symbols:
        market_history.sync_asset_prices_weekly(conn, symbols, weeks[0], weeks[-1])
    if pairs:
        market_history.sync_fx_weekly(conn, sorted(list(pairs)), weeks[0], weeks[-1])

    # 6) Recalc weeks
    n_ok = 0
    for wd in weeks:
        payload = compute_weekly_snapshot_person(conn, person_id, wd)
        upsert_weekly_snapshot(conn, person_id, wd, mode="REBUILD", payload=payload)
        n_ok += 1

    conn.commit()

    # 7) Update watermark vers le MAX ID existant
    max_row = conn.execute(
        "SELECT MAX(id) AS max_id, MAX(created_at) AS max_created FROM transactions WHERE person_id=?",
        (int(person_id),),
    ).fetchone()
    _set_person_watermark(
        conn,
        person_id,
        (int(max_row[0]) if max_row and max_row[0] is not None else None),
        (str(max_row[1]) if max_row and max_row[1] is not None else None),
    )

    return {
        "did_run": True,
        "mode": "BACKDATED_AWARE",
        "person_id": int(person_id),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "n_weeks": len(weeks),
        "n_ok": n_ok,
        "truncated": truncated
    }
