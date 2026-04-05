# ui/liquidites_overview.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt

from services import repositories as repo
from services import pe_cash_repository as pe_cash_repo
from utils.validators import sens_flux
from utils.format_monnaie import money
from services.pe_cash_repository import list_pe_cash_transactions
from utils.validators import sens_flux


def _bank_balance_from_tx(tx_df: pd.DataFrame) -> float:
    if tx_df is None or tx_df.empty:
        return 0.0
    s = 0.0
    for _, r in tx_df.iterrows():
        s += float(r.get("amount", 0.0) or 0.0) * sens_flux(str(r.get("type", "")))
    return float(round(s, 2))

def _compute_liquidites_like_overview(conn, person_id: int):
    """
    Reproduit le calcul de ui/liquidites_overview.py :
    - Banque: somme(amount * sens_flux)
    - Bourse: cash via DEPOT/RETRAIT/ACHAT/VENTE/DIVIDENDE/INTERETS/FRAIS + fees
    - PE: cash plateformes via pe_cash_transactions
    Le tout converti en EUR via _fx_to_eur()
    """
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0, 0.0, 0.0, 0.0  # bank, bourse, pe, total

    # ---- BANQUE
    bank_total_eur = 0.0
    df_banks = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"].copy()
    for _, acc in df_banks.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        try:
            is_container = repo.is_bank_container(conn, acc_id)
        except Exception:
            is_container = False

        total_native = 0.0
        if is_container:
            subs = repo.list_bank_subaccounts(conn, acc_id)
            if subs is not None and not subs.empty:
                for _, s in subs.iterrows():
                    sub_id = int(s["sub_account_id"])  # ✅ comme liquidites_overview.py
                    tx = repo.list_transactions(conn, person_id=person_id, account_id=sub_id, limit=100000)
                    if tx is not None and not tx.empty:
                        for _, r in tx.iterrows():
                            total_native += float(r.get("amount", 0.0) or 0.0) * sens_flux(str(r.get("type", "")))
        else:
            tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
            if tx is not None and not tx.empty:
                for _, r in tx.iterrows():
                    total_native += float(r.get("amount", 0.0) or 0.0) * sens_flux(str(r.get("type", "")))

        bank_total_eur += float(_fx_to_eur(conn, total_native, acc_ccy))

    bank_total_eur = round(float(bank_total_eur), 2)

    # ---- BOURSE (cash uniquement) : uniquement PEA/CTO
    bourse_total_eur = 0.0
    df_bourse = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO"])].copy()
    for _, acc in df_bourse.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
        cash_native = 0.0
        if tx is not None and not tx.empty:
            df = tx.copy()
            df["type"] = df["type"].astype(str)
            df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
            df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

            cash_native += float(df.loc[df["type"] == "DEPOT", "amount"].sum())
            cash_native -= float(df.loc[df["type"] == "RETRAIT", "amount"].sum())
            cash_native -= float(df.loc[df["type"] == "ACHAT", "amount"].sum())
            cash_native += float(df.loc[df["type"] == "VENTE", "amount"].sum())
            cash_native += float(df.loc[df["type"] == "DIVIDENDE", "amount"].sum())
            cash_native += float(df.loc[df["type"] == "INTERETS", "amount"].sum())
            cash_native -= float(df.loc[df["type"] == "FRAIS", "amount"].sum())
            cash_native -= float(df["fees"].sum())

        bourse_total_eur += float(_fx_to_eur(conn, cash_native, acc_ccy))

    bourse_total_eur = round(float(bourse_total_eur), 2)

    # ---- PRIVATE EQUITY cash plateformes
    pe_cash_tx = pe_cash_repo.list_pe_cash_transactions(conn, person_id=person_id)
    pe_total_eur = 0.0
    if pe_cash_tx is not None and not pe_cash_tx.empty:
        df = pe_cash_tx.copy()
        df["tx_type"] = df["tx_type"].astype(str).str.upper()
        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        # on suppose en EUR (comme ton onglet)
        pe_total_eur = float(df.apply(lambda r: float(r["amount"]) if r["tx_type"] == "DEPOSIT" else -float(r["amount"]), axis=1).sum())
    pe_total_eur = round(float(pe_total_eur), 2)

    total = round(float(bank_total_eur + bourse_total_eur + pe_total_eur), 2)
    return bank_total_eur, bourse_total_eur, pe_total_eur, total


def _compute_bank_cash_eur(conn, person_id: int) -> float:
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0

    bank_total_eur = 0.0

    df_banks = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"].copy()
    for _, acc in df_banks.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        try:
            is_container = repo.is_bank_container(conn, acc_id)
        except Exception:
            is_container = False

        if is_container:
            subs = repo.list_bank_subaccounts(conn, acc_id)
            total_native = 0.0
            for _, s in subs.iterrows():
                # ✅ chez toi c'est sub_account_id (pas id)
                sub_id = int(s["sub_account_id"])
                tx = repo.list_transactions(conn, person_id=person_id, account_id=sub_id, limit=100000)
                total_native += _bank_balance_from_tx(tx)
            total_native = float(round(total_native, 2))
        else:
            tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
            total_native = _bank_balance_from_tx(tx)

        bank_total_eur += float(round(_fx_to_eur(conn, total_native, acc_ccy), 2))

    return round(float(bank_total_eur), 2)

def _broker_cash_from_tx(tx: pd.DataFrame) -> float:
    if tx is None or tx.empty:
        return 0.0

    df = tx.copy()
    df["type"] = df["type"].astype(str)
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


def _pe_cash_by_platform(cash_tx: pd.DataFrame) -> pd.DataFrame:
    """Liquidités PE par plateforme à partir de pe_cash_transactions."""
    if cash_tx is None or cash_tx.empty:
        return pd.DataFrame(columns=["platform", "cash"])

    df = cash_tx.copy()
    df["tx_type"] = df["tx_type"].astype(str).str.upper()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)

    def _sign(t: str) -> float:
        if t == "DEPOSIT":
            return 1.0
        if t == "WITHDRAW":
            return -1.0
        # ADJUST : on laisse le signe de l'amount (utile si tu ajustes + ou -)
        return 1.0

    df["signed"] = df.apply(lambda r: float(r["amount"]) * _sign(str(r["tx_type"])), axis=1)
    out = df.groupby("platform", as_index=False)["signed"].sum().rename(columns={"signed": "cash"})
    out["cash"] = out["cash"].astype(float).round(2)
    out = out.sort_values("cash", ascending=False)
    return out


def _fx_to_eur(conn, amount: float, ccy: str) -> float:
    ccy = (ccy or "EUR").upper()
    if ccy == "EUR":
        return float(amount)

    row = repo.get_latest_fx_rate(conn, base_ccy=ccy, quote_ccy="EUR")
    if row is not None:
        rate = float(row["rate"]) if isinstance(row, dict) else float(row[0])
        return float(amount) * rate

    row2 = repo.get_latest_fx_rate(conn, base_ccy="EUR", quote_ccy=ccy)
    if row2 is not None:
        rate = float(row2["rate"]) if isinstance(row2, dict) else float(row2[0])
        if abs(rate) > 1e-12:
            return float(amount) / rate

    return float(amount)


def _kpi_card(title: str, value: str, subtitle: str = "", emoji: str = "", tone: str = "neutral"):
    tones = {
        "primary": ("#111827", "#E5E7EB"),   # fond sombre, texte clair
        "bank": ("#0B3B2E", "#D1FAE5"),      # vert doux
        "broker": ("#1E3A8A", "#DBEAFE"),    # bleu doux
        "pe": ("#4C1D95", "#EDE9FE"),        # violet doux
        "neutral": ("#111827", "#F3F4F6"),
    }
    bg, fg = tones.get(tone, tones["neutral"])

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
                {subtitle}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def afficher_liquidites_overview(conn, person_id: int):
    st.subheader("Liquidités")
    st.caption("Cash disponible : banques + espèces des comptes bourse + liquidités Private Equity.")

    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        st.info("Aucun compte pour cette personne.")
        return

    # ─────────────────────────────────────────────
    # BANQUE (container + comptes simples)
    # ─────────────────────────────────────────────
    bank_rows = []
    bank_total_eur = 0.0

    df_banks = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"].copy()
    for _, acc in df_banks.iterrows():
        acc_id = int(acc["id"])
        acc_name = str(acc["name"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        try:
            is_container = repo.is_bank_container(conn, acc_id)
        except Exception:
            is_container = False

        if is_container:
            subs = repo.list_bank_subaccounts(conn, acc_id)
            total_native = 0.0
            for _, s in subs.iterrows():
                sub_id = int(s["sub_account_id"])
                tx = repo.list_transactions(conn, person_id=person_id, account_id=sub_id, limit=100000)
                total_native += _bank_balance_from_tx(tx)
            total_native = float(round(total_native, 2))
        else:
            tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
            total_native = _bank_balance_from_tx(tx)

        total_eur = float(round(_fx_to_eur(conn, total_native, acc_ccy), 2))
        bank_total_eur += total_eur

        bank_rows.append({
            "type": "Banque",
            "compte": acc_name,
            "currency": acc_ccy,
            "cash_native": total_native,
            "cash_eur": total_eur,
        })

    # ─────────────────────────────────────────────
    # BOURSE (PEA + CTO) = cash "espèces"
    # ─────────────────────────────────────────────
    bourse_rows = []
    bourse_total_eur = 0.0

    df_bourse = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO"])].copy()
    for _, acc in df_bourse.iterrows():
        acc_id = int(acc["id"])
        acc_name = str(acc["name"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
        cash_native = _broker_cash_from_tx(tx)
        cash_eur = float(round(_fx_to_eur(conn, cash_native, acc_ccy), 2))

        bourse_total_eur += cash_eur
        bourse_rows.append({
            "type": "Bourse",
            "compte": acc_name,
            "currency": acc_ccy,
            "cash_native": cash_native,
            "cash_eur": cash_eur,
        })

    # ─────────────────────────────────────────────
    # PRIVATE EQUITY : liquidité plateformes
    # ─────────────────────────────────────────────
    pe_cash_tx = pe_cash_repo.list_pe_cash_transactions(conn, person_id=person_id)
    cash_by_platform = _pe_cash_by_platform(pe_cash_tx)
    pe_total_eur = float(cash_by_platform["cash"].sum()) if not cash_by_platform.empty else 0.0

    # ─────────────────────────────────────────────
    # KPI V2 (cards + %)
    # ─────────────────────────────────────────────
    total_eur = float(round(bank_total_eur + bourse_total_eur + pe_total_eur, 2))
    if abs(total_eur) < 1e-9:
        total_eur = 0.0

    def _pct(x: float) -> float:
        return 0.0 if total_eur == 0 else (x / total_eur) * 100.0

    p_bank = _pct(bank_total_eur)
    p_bourse = _pct(bourse_total_eur)
    p_pe = _pct(pe_total_eur)

    c1, c2, c3, c4 = st.columns([1.6, 1, 1, 1])
    with c1:
        _kpi_card(
            "Liquidités totales",
            money(total_eur, "EUR"),
            f"Répartition : Banque {p_bank:.0f}% • Bourse {p_bourse:.0f}% • PE {p_pe:.0f}%",
            emoji="💧",
            tone="primary",
        )
    with c2:
        _kpi_card("Banques", money(bank_total_eur, "EUR"), f"{p_bank:.0f}% du total", "💳", "bank")
    with c3:
        _kpi_card("Bourse (espèces)", money(bourse_total_eur, "EUR"), f"{p_bourse:.0f}% du total", "📈", "broker")
    with c4:
        _kpi_card("Private Equity", money(pe_total_eur, "EUR"), f"{p_pe:.0f}% du total", "🧪", "pe")

    st.markdown("")  # petite respiration

    # Micro-visualisation (barres de répartition)
    st.caption("Répartition visuelle des liquidités")
    colA, colB, colC = st.columns(3)
    with colA:
        st.write("💳 Banques")
        st.progress(min(max(bank_total_eur / total_eur, 0.0), 1.0) if total_eur else 0.0)
    with colB:
        st.write("📈 Bourse (espèces)")
        st.progress(min(max(bourse_total_eur / total_eur, 0.0), 1.0) if total_eur else 0.0)
    with colC:
        st.write("🧪 Private Equity")
        st.progress(min(max(pe_total_eur / total_eur, 0.0), 1.0) if total_eur else 0.0)

    st.divider()

    # ─────────────────────────────────────────────
    # TOPS + Graphes
    # ─────────────────────────────────────────────
    # Top comptes (banque + bourse) en EUR
    df_all = pd.DataFrame(bank_rows + bourse_rows, columns=["type", "compte", "currency", "cash_native", "cash_eur"])

    if df_all is not None and not df_all.empty:
        df_top = df_all.copy()
        df_top["cash_eur"] = pd.to_numeric(df_top["cash_eur"], errors="coerce").fillna(0.0)
        df_top = df_top.sort_values("cash_eur", ascending=False)

        top1 = df_top.iloc[0]
        st.markdown(f"🏆 **Compte #1 : {top1['compte']}** — {money(float(top1['cash_eur']), 'EUR')}")

        st.caption("Top comptes par liquidités (EUR)")
        df_chart = df_top.head(6)[["compte", "cash_eur"]].set_index("compte")
        st.bar_chart(df_chart)


    st.divider()

    # ─────────────────────────────────────────────
    # Détails
    # ─────────────────────────────────────────────
    rows = bank_rows + bourse_rows
    df_all = pd.DataFrame(rows, columns=["type", "compte", "currency", "cash_native", "cash_eur"])

    with st.expander("Voir le détail banque + bourse", expanded=False):
        if not df_all.empty:
            df_view = df_all.copy()
            df_view["cash_native"] = df_view.apply(lambda r: money(float(r["cash_native"]), str(r["currency"])), axis=1)
            df_view["cash_eur"] = df_view["cash_eur"].map(lambda x: money(float(x), "EUR"))
            st.dataframe(df_view, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune liquidité détectée côté banque / bourse.")

    with st.expander("Voir le détail Private Equity (plateformes)", expanded=False):
        if cash_by_platform.empty:
            st.info("Aucune opération de liquidité Private Equity.")
        else:
            df_pe = cash_by_platform.copy()
            df_pe["cash"] = df_pe["cash"].map(lambda x: money(float(x), "EUR"))
            st.dataframe(df_pe, use_container_width=True, hide_index=True)
