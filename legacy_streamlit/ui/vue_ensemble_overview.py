import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import html
from datetime import datetime
import pytz
from services import pricing
from services import fx
from ui.liquidites_overview import _compute_liquidites_like_overview

from services import repositories as repo
from services import snapshots as wk_snap
from services import market_repository as mrepo

# Dépenses / revenus
from services.depenses_repository import depenses_par_mois
from services.revenus_repository import revenus_par_mois

# Crédit
from services.credits import list_credits_by_person, get_crd_a_date, get_credit_dates

# Private Equity
from services import private_equity_repository as pe_repo
from services import private_equity as pe
from services import pe_cash_repository as pe_cash_repo

# Entreprises
from services import entreprises_repository as ent_repo


def _now_paris_date():
    return datetime.now(pytz.timezone("Europe/Paris")).date()

def _now_paris_iso_dt() -> str:
    tz = pytz.timezone("Europe/Paris")
    return datetime.now(tz).replace(microsecond=0).isoformat()


def _refresh_all_bourse_prices(conn) -> tuple[int, int]:
    """
    Refresh les prix pour tous les actifs détenus dans tous les comptes BOURSE.
    Retourne (n_ok, n_fail). Ne lève pas d'exception bloquante.
    """
    try:
        df_acc = repo.list_accounts(conn)
        if df_acc is None or df_acc.empty:
            return (0, 0)
        df_b = df_acc[df_acc["account_type"].astype(str).str.upper() == "BOURSE"]
        if df_b.empty:
            return (0, 0)

        n_ok, n_fail = 0, 0
        for _, r in df_b.iterrows():
            account_id = int(r["id"])
            account_ccy = str(r.get("currency") or "EUR").upper()

            asset_ids = repo.list_account_asset_ids(conn, account_id=account_id)
            for aid in asset_ids:
                a = conn.execute("SELECT * FROM assets WHERE id = ?;", (aid,)).fetchone()
                if not a:
                    continue
                sym = a["symbol"]
                px, ccy = pricing.fetch_last_price_auto(sym)
                if px is None:
                    n_fail += 1
                    continue

                repo.upsert_price(conn, asset_id=aid, date=pricing.today_str(), price=px, currency=ccy, source="AUTO")

                if ccy:
                    ccy = str(ccy).upper()
                    repo.update_asset_currency(conn, aid, ccy)
                    if ccy != account_ccy:
                        fx.ensure_fx_rate(conn, ccy, account_ccy)

                n_ok += 1

        return (n_ok, n_fail)
    except Exception:
        return (0, 0)


def _compute_patrimoine_components_for_snapshot(conn, person_id: int) -> dict:
    """
    Calcule tout ce qu'on stocke en snapshot pour UNE personne.
    """
    bank_cash, bourse_cash, pe_cash, liquidites_total = _compute_liquidites_like_overview(conn, person_id)

    # holdings bourse
    _cash, bourse_holdings, _total = _compute_bourse_value_eur(conn, person_id)

    # PE / entreprises / crédits
    pe_value, _ = _compute_pe(conn, person_id)
    ent_value = _compute_enterprises_value(conn, person_id)
    credits_remaining = _compute_credits_remaining(conn, person_id)

    patrimoine_brut = float(liquidites_total) + float(bourse_holdings) + float(pe_value) + float(ent_value)
    patrimoine_net = float(patrimoine_brut) - float(credits_remaining)

    return {
        "bank_cash": float(bank_cash),
        "bourse_cash": float(bourse_cash),
        "pe_cash": float(pe_cash),
        "liquidites_total": float(liquidites_total),
        "bourse_holdings": float(bourse_holdings),
        "pe_value": float(pe_value),
        "ent_value": float(ent_value),
        "credits_remaining": float(credits_remaining),
        "patrimoine_brut": float(patrimoine_brut),
        "patrimoine_net": float(patrimoine_net),
    }


def ensure_daily_snapshots_for_all_people(conn, mode: str = "AUTO", force_refresh_prices: bool = True) -> dict:
    """
    Crée (ou upsert) la snapshot du jour pour toutes les personnes.
    - Si la snapshot du jour existe déjà pour tout le monde -> ne fait rien (sauf si mode=MANUAL + on veut forcer).
    Retourne un dict de stats.
    """
    today = _now_paris_date().isoformat()
    created_at = _now_paris_iso_dt()

    people = repo.list_people(conn)
    if people is None or people.empty:
        return {"did_run": False, "reason": "no_people", "n_ok": 0, "n_fail": 0}

    # Si déjà fait aujourd'hui pour tout le monde, on skip en AUTO.
    n_existing = repo.count_snapshots_for_date(conn, today)
    if mode == "AUTO" and n_existing >= len(people):
        return {"did_run": False, "reason": "already_done_today", "n_ok": 0, "n_fail": 0}

    # Refresh prix (comme comptes bourse)
    price_ok, price_fail = (0, 0)
    if force_refresh_prices:
        price_ok, price_fail = _refresh_all_bourse_prices(conn)

    n_ok, n_fail = 0, 0
    for _, pr in people.iterrows():
        pid = int(pr["id"])
        try:
            comp = _compute_patrimoine_components_for_snapshot(conn, pid)
            repo.upsert_patrimoine_snapshot(
                conn,
                person_id=pid,
                snapshot_date=today,
                created_at=created_at,
                mode=mode,
                patrimoine_net=comp["patrimoine_net"],
                patrimoine_brut=comp["patrimoine_brut"],
                liquidites_total=comp["liquidites_total"],
                bank_cash=comp["bank_cash"],
                bourse_cash=comp["bourse_cash"],
                pe_cash=comp["pe_cash"],
                bourse_holdings=comp["bourse_holdings"],
                pe_value=comp["pe_value"],
                ent_value=comp["ent_value"],
                credits_remaining=comp["credits_remaining"],
                notes=None,
            )
            n_ok += 1
        except Exception:
            n_fail += 1

    return {
        "did_run": True,
        "reason": "ok",
        "price_ok": price_ok,
        "price_fail": price_fail,
        "n_ok": n_ok,
        "n_fail": n_fail,
    }


def _milestone_status(value: float, milestones: list[tuple[float, str]]):
    """Retourne (current_label, next_label, next_target, progress_0_1)."""
    if not milestones:
        return "", "", 0.0, 0.0

    v = float(value or 0.0)
    ms = sorted([(float(a), str(b)) for a, b in milestones], key=lambda x: x[0])

    current_amt, current_label = ms[0]
    next_amt, next_label = ms[-1]

    for i, (amt, label) in enumerate(ms):
        if v >= amt:
            current_amt, current_label = amt, label
            if i + 1 < len(ms):
                next_amt, next_label = ms[i + 1]
            else:
                next_amt, next_label = amt, label
        else:
            break

    if next_amt <= current_amt:
        prog = 1.0
    else:
        prog = (v - current_amt) / (next_amt - current_amt)
        prog = max(0.0, min(1.0, float(prog)))

    return current_label, next_label, next_amt, prog


def _loan_principal_from_monthly_payment(monthly_payment: float, annual_rate_pct: float, duration_years: int) -> float:
    """Capacité d’emprunt simple via annuité : P = M * (1 - (1+r)^-n) / r."""
    m = float(monthly_payment or 0.0)
    if m <= 0:
        return 0.0

    years = int(duration_years or 0)
    n = max(0, years) * 12
    if n <= 0:
        return 0.0

    r = (float(annual_rate_pct or 0.0) / 100.0) / 12.0
    if abs(r) < 1e-9:
        return m * n
    return m * (1.0 - (1.0 + r) ** (-n)) / r


def _fmt_eur(x: float) -> str:
    try:
        return f"{float(x):,.2f} €".replace(",", " ")
    except Exception:
        return "0,00 €"

def _row_id(row) -> int:
    """
    Récupère un identifiant d'une row pandas même si la colonne n'est pas 'id'.
    Cherche d'abord des clés classiques, puis toute colonne contenant 'id'.
    """
    # cas classiques
    for k in ["id", "account_id", "subaccount_id", "sub_account_id", "bank_subaccount_id", "sub_id"]:
        if k in row and pd.notna(row[k]):
            return int(row[k])

    # fallback : première colonne qui contient "id"
    for col in row.index:
        if "id" in str(col).lower() and pd.notna(row[col]):
            try:
                return int(row[col])
            except Exception:
                pass

    raise KeyError("Impossible de trouver une colonne identifiant dans cette row.")

def _sum_first_existing_col(df: pd.DataFrame, candidates: list[str]) -> float:
    """
    Somme la première colonne existante parmi candidates.
    Si aucune n'existe, tente une heuristique sur les colonnes contenant 'value' ou 'valo'.
    """
    if df is None or df.empty:
        return 0.0

    cols = list(df.columns)

    # 1) candidats explicites
    for c in candidates:
        if c in cols:
            s = pd.to_numeric(df[c], errors="coerce").fillna(0.0).sum()
            return float(s)

    # 2) heuristique : colonnes qui ressemblent à une valeur
    heuristics = []
    for col in cols:
        low = str(col).lower()
        if any(k in low for k in ["value", "valo", "valuation", "net"]) and not any(k in low for k in ["pct", "percent", "ratio"]):
            heuristics.append(col)

    for col in heuristics:
        try:
            s = pd.to_numeric(df[col], errors="coerce").fillna(0.0).sum()
            # si ça ressemble bien à des montants (pas juste 0)
            return float(s)
        except Exception:
            pass

    return 0.0


def _kpi_card(title: str, value: str, subtitle: str = "", emoji: str = "", tone: str = "neutral"):
    tones = {
        "primary": ("#111827", "#E5E7EB"),
        "blue": ("#1E3A8A", "#DBEAFE"),
        "green": ("#0B3B2E", "#D1FAE5"),
        "purple": ("#4C1D95", "#EDE9FE"),
        "neutral": ("#111827", "#F3F4F6"),
        "red": ("#7F1D1D", "#FEE2E2"),
    }
    bg, fg = tones.get(tone, tones["neutral"])

    title = html.escape(str(title))
    value = html.escape(str(value))
    subtitle = html.escape(str(subtitle))
    emoji = html.escape(str(emoji))

    st.markdown(
        f"""
        <div style="
            background:{bg};
            color:{fg};
            border-radius:16px;
            padding:14px 16px;
            box-shadow:0 6px 18px rgba(0,0,0,0.08);
            min-height:96px;
        ">
            <div style="font-size:14px; opacity:0.9; font-weight:600;">
                {emoji} {title}
            </div>
            <div style="font-size:26px; font-weight:800; margin-top:6px;">
                {value}
            </div>
            <div style="font-size:13px; opacity:0.85; margin-top:4px;">
                {subtitle if subtitle else "&nbsp;"}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def _fx_to_eur(conn, amount: float, ccy: str) -> float:
    ccy = (ccy or "EUR").upper()
    if ccy == "EUR":
        return float(amount)

    # 1) base -> EUR
    row = repo.get_latest_fx_rate(conn, base_ccy=ccy, quote_ccy="EUR")
    if row is not None:
        rate = float(row["rate"]) if isinstance(row, dict) else float(row[0])
        return float(amount) * rate

    # 2) fallback inverse : EUR -> base
    row2 = repo.get_latest_fx_rate(conn, base_ccy="EUR", quote_ccy=ccy)
    if row2 is not None:
        rate = float(row2["rate"]) if isinstance(row2, dict) else float(row2[0])
        if abs(rate) > 1e-12:
            return float(amount) / rate

    # 3) dernier recours
    return float(amount)



def _compute_cash_from_tx(df_tx: pd.DataFrame) -> float:
    """
    Cash (devise du compte) depuis transactions type:
    ACHAT, VENTE, DIVIDENDE, INTERETS, FRAIS + fees
    (même logique que compte_bourse / liquidités)
    """
    if df_tx is None or df_tx.empty:
        return 0.0

    df = df_tx.copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

    cash = 0.0
    cash -= float(df.loc[df["type"] == "ACHAT", "amount"].sum())
    cash += float(df.loc[df["type"] == "VENTE", "amount"].sum())
    cash += float(df.loc[df["type"] == "DIVIDENDE", "amount"].sum())
    cash += float(df.loc[df["type"] == "INTERETS", "amount"].sum())
    cash -= float(df.loc[df["type"] == "FRAIS", "amount"].sum())
    cash -= float(df["fees"].sum())
    return round(float(cash), 2)


def _positions_from_transactions(df_tx: pd.DataFrame) -> pd.DataFrame:
    """
    Construit positions simples (qty) par asset_id à partir des tx.
    ACHAT -> +quantity ; VENTE -> -quantity
    """
    if df_tx is None or df_tx.empty:
        return pd.DataFrame(columns=["asset_id", "qty"])

    df = df_tx.copy()
    df = df[df["type"].isin(["ACHAT", "VENTE"])].copy()
    if df.empty:
        return pd.DataFrame(columns=["asset_id", "qty"])

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["asset_id"] = pd.to_numeric(df["asset_id"], errors="coerce")

    df = df.dropna(subset=["asset_id"])
    df["asset_id"] = df["asset_id"].astype(int)

    df["signed_qty"] = np.where(df["type"] == "ACHAT", df["quantity"], -df["quantity"])
    pos = df.groupby("asset_id", as_index=False)["signed_qty"].sum()
    pos = pos.rename(columns={"signed_qty": "qty"})
    pos = pos[pos["qty"].abs() > 1e-9]
    return pos


def _compute_bourse_value_eur(conn, person_id: int):
    """
    Retourne (cash_eur, holdings_eur, total_eur) pour les comptes bourse (PEA/CTO/... non-banque, non-crédit).
    Hypothèse: account_type contient "PEA", "CTO", "BROKER", etc. -> on filtre par NOT banque container et NOT CREDIT.
    """
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0, 0.0, 0.0

    # On exclut crédits + comptes banque container
    def _is_bourse_row(r):
        t = str(r.get("type", "")).upper()
        if t == "CREDIT":
            return False
        try:
            if repo.is_bank_container(conn, int(r["id"])):
                return False
        except Exception:
            pass
        # heuristique : tout ce qui n'est pas banque container et pas crédit = bourse/autres
        return True

    bourse_acc = accounts[accounts.apply(_is_bourse_row, axis=1)].copy()
    if bourse_acc.empty:
        return 0.0, 0.0, 0.0

    cash_eur_total = 0.0
    holdings_eur_total = 0.0

    for _, a in bourse_acc.iterrows():
        acc_id = _row_id(a)
        acc_ccy = str(a.get("currency", "EUR")).upper()

        tx = repo.list_transactions(conn, account_id=acc_id, limit=100000)
        cash_native = _compute_cash_from_tx(tx)
        cash_eur_total += _fx_to_eur(conn, cash_native, acc_ccy)

        # holdings
        pos = _positions_from_transactions(tx)
        if pos.empty:
            continue

        asset_ids = pos["asset_id"].tolist()
        prices = repo.get_latest_prices(conn, asset_ids)
        if prices.empty:
            continue

        merged = pos.merge(prices, on="asset_id", how="left")
        merged["price"] = pd.to_numeric(merged["price"], errors="coerce").fillna(0.0)
        merged["qty"] = pd.to_numeric(merged["qty"], errors="coerce").fillna(0.0)
        merged["ccy_price"] = merged["currency"].fillna(acc_ccy).astype(str).str.upper()
        merged["value_native"] = merged["qty"] * merged["price"]

        # conversion en EUR par currency du prix
        val_eur = 0.0
        for _, row in merged.iterrows():
            val_eur += _fx_to_eur(conn, float(row["value_native"]), str(row["ccy_price"]))
        holdings_eur_total += val_eur

    total = float(cash_eur_total + holdings_eur_total)
    return round(cash_eur_total, 2), round(holdings_eur_total, 2), round(total, 2)


def _compute_bank_cash_eur(conn, person_id: int) -> float:
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0

    bank_containers = []
    for _, r in accounts.iterrows():
        try:
            if repo.is_bank_container(conn, _row_id(r)):
                bank_containers.append(_row_id(r))
        except Exception:
            pass

    total = 0.0
    for bank_id in bank_containers:
        subs = repo.list_bank_subaccounts(conn, bank_id)
        if subs is None or subs.empty:
            continue

        for _, s in subs.iterrows():
            sub_id = _row_id(s)
            ccy = str(s.get("currency", "EUR")).upper()
            tx = repo.list_transactions(conn, account_id=sub_id, limit=100000)
            cash_native = _compute_cash_from_tx(tx)
            total += _fx_to_eur(conn, cash_native, ccy)

    return round(float(total), 2)


def _compute_pe(conn, person_id: int):
    # --- Valeur PE (projets)
    projects = pe_repo.list_pe_projects(conn, person_id)
    tx = pe_repo.list_pe_transactions(conn, person_id)
    positions = pe.build_pe_positions(projects, tx)
    k = pe.compute_pe_kpis(positions)  # dict
    pe_value = float(k.get("value", 0.0) or 0.0)

    # --- Cash plateformes (PE)
    cash_tx = pe_cash_repo.list_pe_cash_transactions(conn, person_id=person_id)
    cash_by_platform = pe.compute_platform_cash(pe_tx=tx, cash_tx=cash_tx)
    pe_cash = float(cash_by_platform["cash"].sum()) if cash_by_platform is not None and not cash_by_platform.empty else 0.0

    return round(pe_value, 2), round(pe_cash, 2)



def _compute_enterprises_value(conn, person_id: int) -> float:
    positions = ent_repo.list_positions_for_person(conn, person_id)
    if positions is None or positions.empty:
        return 0.0

    # on privilégie la valeur "de marché" si dispo, sinon valeur nette perso, sinon valeur nette globale…
    total = _sum_first_existing_col(
        positions,
        candidates=[
            "value_now",
            "my_value",
            "my_net",
            "net",
            "value",
            "valo",
            "valuation",
        ],
    )
    return round(float(total), 2)

def _compute_credits_remaining(conn, person_id: int) -> float:
    credits = list_credits_by_person(conn, person_id)
    if credits is None or credits.empty:
        return 0.0

    today = _now_paris_date()
    total = 0.0

    for _, c in credits.iterrows():
        credit_id = int(c["id"])
        capital_init = float(c.get("capital_emprunte") or 0.0)

        # ✅ Gestion différé : si on est avant le début de remboursement -> CRD = capital emprunté
        try:
            dates = get_credit_dates(conn, credit_id=credit_id)
            date_debut_remb = dates.get("date_debut_remboursement")
            if date_debut_remb is not None and today < date_debut_remb:
                total += capital_init
                continue
        except Exception:
            # si on ne peut pas récupérer les dates, on continue sur la méthode CRD
            pass

        # ✅ Appel correct : date_ref= (comme dans tes fichiers crédit)
        try:
            crd_today = float(get_crd_a_date(conn, credit_id=credit_id, date_ref=str(today)))
        except Exception:
            crd_today = 0.0

        # fallback si jamais CRD renvoie 0 alors qu'on a un capital
        if crd_today <= 0 and capital_init > 0:
            crd_today = capital_init

        total += crd_today

    return round(float(total), 2)



def _get_cashflow_last12(conn, person_id: int):
    # Revenus par mois
    df_r = revenus_par_mois(conn, person_id).copy()
    df_d = depenses_par_mois(conn, person_id).copy()

    if df_r.empty and df_d.empty:
        return pd.DataFrame(columns=["mois", "revenus", "depenses", "solde"])

    # normalise
    if not df_r.empty:
        df_r["mois"] = pd.to_datetime(df_r["mois"])
        df_r["total"] = pd.to_numeric(df_r["total"], errors="coerce").fillna(0.0)
        df_r = df_r.sort_values("mois")
        df_r = df_r.rename(columns={"total": "revenus"})
    else:
        df_r = pd.DataFrame(columns=["mois", "revenus"])

    if not df_d.empty:
        df_d["mois"] = pd.to_datetime(df_d["mois"])
        df_d["total"] = pd.to_numeric(df_d["total"], errors="coerce").fillna(0.0)
        df_d = df_d.sort_values("mois")
        df_d = df_d.rename(columns={"total": "depenses"})
    else:
        df_d = pd.DataFrame(columns=["mois", "depenses"])

    df = pd.merge(df_r[["mois", "revenus"]], df_d[["mois", "depenses"]], on="mois", how="outer").fillna(0.0)
    df = df.sort_values("mois").tail(12).copy()
    df["solde"] = df["revenus"] - df["depenses"]
    df["mois_str"] = df["mois"].dt.strftime("%Y-%m")
    return df


def afficher_vue_ensemble_overview(conn, person_id: int):
    st.subheader("Vue d’ensemble")

    # ─────────────────────────────────────────────
    # Agrégations
    # ─────────────────────────────────────────────
    # Liquidités : même logique que l’onglet « Liquidités »
    bank_cash, bourse_cash, pe_cash, liquidites_total = _compute_liquidites_like_overview(conn, person_id)

    # Bourse : on garde la valo titres (holdings)
    _, bourse_holdings, _ = _compute_bourse_value_eur(conn, person_id)

    # PE : on garde la valo projets
    pe_value, _ = _compute_pe(conn, person_id)

    ent_value = _compute_enterprises_value(conn, person_id)
    credits_remaining = _compute_credits_remaining(conn, person_id)

    patrimoine_brut = liquidites_total + bourse_holdings + pe_value + ent_value
    patrimoine_net = patrimoine_brut - credits_remaining


    invested_total = bourse_holdings + pe_value + ent_value

    def _pct(part, total):
        return 0.0 if total <= 0 else (part / total) * 100.0

    pct_cash = _pct(liquidites_total, patrimoine_brut)
    pct_invest = _pct(invested_total, patrimoine_brut)
    
    with st.expander("📸 Snapshot / Rebuild (weekly)", expanded=False):
        if st.button("📸 Snapshot / Rebuild (90 jours)", use_container_width=True):
            res = wk_snap.rebuild_snapshots_person(conn, person_id=person_id, lookback_days=90)
            st.success(f"Weekly rebuild terminé ✅ {res}")
            st.rerun()



    # ─────────────────────────────────────────────
    # KPI Cards (haut de page)
    # ─────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns([1.6, 1, 1, 1, 1])
    with c1:
        _kpi_card(
            "Patrimoine net",
            _fmt_eur(patrimoine_net),
            f"Brut {_fmt_eur(patrimoine_brut)} • Dettes {_fmt_eur(credits_remaining)}",
            "📌",
            "primary",
        )
    with c2:
        _kpi_card("Liquidités", _fmt_eur(liquidites_total), f"{pct_cash:.0f}% du brut", "💧", "blue")
    with c3:
        _kpi_card("Investissements", _fmt_eur(invested_total), f"{pct_invest:.0f}% du brut", "📈", "green")
    with c4:
        _kpi_card("Bourse (valeurs)", _fmt_eur(bourse_holdings), "hors cash", "🧾", "purple")
    with c5:
        _kpi_card("Dettes (CRD)", _fmt_eur(credits_remaining), "crédits", "⚓", "red")

    st.divider()

    # ─────────────────────────────────────────────
    # Section ludique : progression (paliers) + capacité d'emprunt
    # ─────────────────────────────────────────────
    st.markdown("### 🎯 Progression")

    milestones_net = [
        (0, "Zéro mais réveillé"),
        (10_000, "Fondations posées"),
        (25_000, "Épargnant sérieux"),
        (50_000, "Classe moyenne patrimoniale"),
        (100_000, "Capital crédible"),
        (250_000, "Rentier en gestation"),
        (500_000, "Patrimoine solide"),
        (1_000_000, "Family Office junior"),
        (2_500_000, "Indépendance (presque) insolente"),
    ]

    cur_label, next_label, next_target, prog = _milestone_status(patrimoine_net, milestones_net)
    pct = int(round(prog * 100))

    st.write(f"**Niveau actuel :** {cur_label}")
    if next_target and patrimoine_net < next_target:
        st.write(
            f"Prochain palier : **{next_label}** ({_fmt_eur(next_target)}) • "
            f"encore **{_fmt_eur(max(0.0, next_target - patrimoine_net))}**"
        )
    else:
        st.write("✅ Dernier palier atteint. À toi d'inventer le prochain boss final 😄")

    st.progress(prog)
    st.caption(f"Progression vers le prochain palier : **{pct}%**")

    st.divider()


    # ─────────────────────────────────────────────
    # Performance & croissance (NET vs BRUT) — basé sur SNAPSHOTS
    # ─────────────────────────────────────────────
    st.markdown("### 📈 Performance & croissance")

    df_snap = None
    try:
        df_snap = mrepo.list_weekly_snapshots(conn, person_id=person_id)
    except Exception:
        df_snap = None


    if df_snap is None or df_snap.empty:
        st.info("Aucune snapshot enregistrée pour le moment. Fais une snapshot (bouton) puis reviens ici.")
        return

    # On attend au minimum snapshot_date, patrimoine_net, patrimoine_brut
    required_cols = {"snapshot_date", "patrimoine_net", "patrimoine_brut"}
    if not required_cols.issubset(set(df_snap.columns)):
        st.warning(f"Snapshots trouvées mais colonnes manquantes : {required_cols - set(df_snap.columns)}")
        return

    df_h = df_snap.copy()
    df_h["snapshot_date"] = pd.to_datetime(df_h["snapshot_date"], errors="coerce")
    df_h = df_h.dropna(subset=["snapshot_date"]).sort_values("snapshot_date")

    # Affichage en mois si tu veux une granularité quotidienne : utilise "%Y-%m-%d"
    df_h["x"] = df_h["snapshot_date"].dt.strftime("%Y-%m-%d")

    # Métriques période
    first = df_h.iloc[0]
    last = df_h.iloc[-1]

    first_net = float(first["patrimoine_net"])
    last_net = float(last["patrimoine_net"])
    delta_net = last_net - first_net
    pct_net = 0.0 if abs(first_net) < 1e-9 else (delta_net / first_net) * 100.0

    first_brut = float(first["patrimoine_brut"])
    last_brut = float(last["patrimoine_brut"])
    delta_brut = last_brut - first_brut
    pct_brut = 0.0 if abs(first_brut) < 1e-9 else (delta_brut / first_brut) * 100.0

    m1, m2 = st.columns(2)
    with m1:
        st.metric("Patrimoine net (période)", _fmt_eur(last_net), f"{_fmt_eur(delta_net)} ({pct_net:+.1f}%)")
    with m2:
        st.metric("Patrimoine brut (période)", _fmt_eur(last_brut), f"{_fmt_eur(delta_brut)} ({pct_brut:+.1f}%)")

    # Si une seule snapshot -> tu n’auras qu’un point, c’est normal
    if len(df_h) < 2:
        st.info("Tu n’as qu’une seule snapshot : le graphe affiche un point. Dès demain (ou après plusieurs snapshots), tu auras une courbe.")
        return

    # Graphe
    df_plot = df_h[["x", "patrimoine_net", "patrimoine_brut"]].copy()
    df_plot = df_plot.rename(columns={"patrimoine_net": "net", "patrimoine_brut": "brut"})
    df_long = df_plot.melt(id_vars=["x"], value_vars=["brut", "net"], var_name="type", value_name="val")

    chart = (
        alt.Chart(df_long)
        .mark_line(point=True)
        .encode(
            x=alt.X("x:N", title=""),
            y=alt.Y("val:Q", title="€"),
            color=alt.Color("type:N", title=""),
            tooltip=[
                alt.Tooltip("x:N", title="Date"),
                alt.Tooltip("type:N", title="Série"),
                alt.Tooltip("val:Q", title="Montant", format=",.2f"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, use_container_width=True)


    # ─────────────────────────────────────────────
    # Allocation donut
    # ─────────────────────────────────────────────
    st.markdown("### Répartition du patrimoine (brut)")

    alloc = pd.DataFrame([
        {"poste": "Liquidités", "valeur": max(liquidites_total, 0.0)},
        {"poste": "Bourse (valeurs)", "valeur": max(bourse_holdings, 0.0)},
        {"poste": "Private Equity", "valeur": max(pe_value, 0.0)},
        {"poste": "Entreprises", "valeur": max(ent_value, 0.0)},
    ])
    alloc = alloc[alloc["valeur"] > 0].copy()

    if alloc.empty:
        st.info("Pas assez de données pour afficher une répartition.")
    else:
        alloc["pct"] = alloc["valeur"] / alloc["valeur"].sum() * 100.0
        donut = (
            alt.Chart(alloc)
            .mark_arc(innerRadius=55)
            .encode(
                theta=alt.Theta("valeur:Q"),
                color=alt.Color("poste:N", legend=None),
                tooltip=[
                    alt.Tooltip("poste:N", title="Poste"),
                    alt.Tooltip("valeur:Q", title="Montant", format=",.2f"),
                    alt.Tooltip("pct:Q", title="Part", format=".1f"),
                ],
            )
            .properties(height=260)
        )

        colA, colB = st.columns([1.1, 1])
        with colA:
            st.altair_chart(donut, use_container_width=True)
        with colB:
            st.caption("Détails")
            st.write(f"- Liquidités : **{_fmt_eur(liquidites_total)}**")
            st.write(f"- Bourse (valeurs) : **{_fmt_eur(bourse_holdings)}**")
            st.write(f"- Private Equity : **{_fmt_eur(pe_value)}**")
            st.write(f"- Entreprises : **{_fmt_eur(ent_value)}**")

    st.divider()

    # ─────────────────────────────────────────────
    # Cashflow (12 derniers mois) : revenus vs dépenses + solde
    # ─────────────────────────────────────────────
    st.markdown("### Cashflow (12 derniers mois)")

    df_cf = _get_cashflow_last12(conn, person_id)
    if df_cf.empty:
        st.info("Pas assez de données revenus/dépenses.")
        return

    df_long = df_cf.melt(
        id_vars=["mois_str"],
        value_vars=["revenus", "depenses"],
        var_name="type",
        value_name="montant",
    )

    chart_cf = (
        alt.Chart(df_long)
        .mark_bar(opacity=0.85)
        .encode(
            x=alt.X("mois_str:N", title="", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("montant:Q", title="€"),
            color=alt.Color("type:N", legend=None),
            tooltip=[
                alt.Tooltip("mois_str:N", title="Mois"),
                alt.Tooltip("type:N", title="Type"),
                alt.Tooltip("montant:Q", title="Montant", format=",.2f"),
            ],
        )
        .properties(height=260)
    )

    # Solde en ligne
    chart_solde = (
        alt.Chart(df_cf)
        .mark_line(point=True)
        .encode(
            x=alt.X("mois_str:N", title=""),
            y=alt.Y("solde:Q", title=""),
            tooltip=[
                alt.Tooltip("mois_str:N", title="Mois"),
                alt.Tooltip("solde:Q", title="Solde", format=",.2f"),
            ],
        )
    )

    st.altair_chart(chart_cf + chart_solde, use_container_width=True)

    # KPIs cashflow
    avg_solde = float(df_cf["solde"].mean())
    col1, col2, col3 = st.columns(3)
    col1.metric("Solde moyen / mois", _fmt_eur(avg_solde))
    col2.metric("Revenus (12 mois)", _fmt_eur(float(df_cf["revenus"].sum())))
    col3.metric("Dépenses (12 mois)", _fmt_eur(float(df_cf["depenses"].sum())))

    st.divider()

    # ─────────────────────────────────────────────
    # Mini détail liquidités (sans refaire l’onglet dédié)
    # ─────────────────────────────────────────────
    st.markdown("### Résumé liquidités")
    a, b, c = st.columns(3)
    a.metric("Banque", _fmt_eur(bank_cash))
    b.metric("Bourse (cash)", _fmt_eur(bourse_cash))
    c.metric("PE (cash)", _fmt_eur(pe_cash))
