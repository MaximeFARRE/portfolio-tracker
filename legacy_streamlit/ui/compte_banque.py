import streamlit as st
import pandas as pd

from services import repositories as repo
from utils.cache import reset_cache
from ui.compte_vue import tableau_operations
from ui.compte_saisie import bloc_saisie_operation
from utils.validators import sens_flux
from utils.format_monnaie import money  # adapte si ton helper est ailleurs


SUBTYPES = {
    "courant": "Courant",
    "livret": "Livret",
    "remunere": "Rémunéré",
    "pel": "PEL",
}


def _to_dt(s):
    return pd.to_datetime(s, errors="coerce")


def _solde_tx(tx_df: pd.DataFrame) -> float:
    if tx_df.empty:
        return 0.0
    s = 0.0
    for _, r in tx_df.iterrows():
        s += float(r["amount"]) * sens_flux(str(r["type"]))
    return float(s)


def _interest_12m(tx_df: pd.DataFrame, today: pd.Timestamp) -> float:
    if tx_df.empty:
        return 0.0
    df = tx_df.copy()
    df["date"] = _to_dt(df["date"])
    df = df.dropna(subset=["date"])
    start = today - pd.Timedelta(days=365)
    df = df[(df["date"] >= start) & (df["date"] <= today) & (df["type"] == "INTERETS")]
    return float(df["amount"].sum()) if not df.empty else 0.0


def _month_end_dates_12m(today: pd.Timestamp) -> list[pd.Timestamp]:
    # 12 fins de mois glissantes : M-11 ... M0
    ends = []
    for k in range(11, -1, -1):
        d = (today - pd.DateOffset(months=k))
        end = (d + pd.offsets.MonthEnd(0)).normalize()
        ends.append(end)
    return ends


def _avg_month_end_balance_12m(tx_df: pd.DataFrame, today: pd.Timestamp) -> float:
    """
    V1: capital moyen = moyenne des soldes fin de mois sur les 12 derniers mois.
    """
    if tx_df.empty:
        return 0.0

    df = tx_df.copy()
    df["date"] = _to_dt(df["date"])
    df = df.dropna(subset=["date"]).sort_values("date")

    # flux signé
    df["signed"] = df.apply(lambda r: float(r["amount"]) * sens_flux(str(r["type"])), axis=1)

    month_ends = _month_end_dates_12m(today)

    # solde cumulatif au fil du temps
    df["cum"] = df["signed"].cumsum()

    # pour chaque fin de mois, trouver le dernier cum <= date
    avgs = []
    for end in month_ends:
        mask = df["date"] <= end
        if not mask.any():
            avgs.append(0.0)
        else:
            avgs.append(float(df.loc[mask, "cum"].iloc[-1]))

    return float(sum(avgs) / len(avgs)) if avgs else 0.0


def _fx_rate_today(conn, base_ccy: str, quote_ccy: str) -> float:
    base_ccy = (base_ccy or "EUR").upper()
    quote_ccy = (quote_ccy or "EUR").upper()
    if base_ccy == quote_ccy:
        return 1.0
    row = repo.get_latest_fx_rate(conn, base_ccy, quote_ccy)
    if row and row["rate"]:
        return float(row["rate"])
    st.warning(f"Taux FX manquant {base_ccy}->{quote_ccy} (latest). Conversion ignorée (rate=1).")
    return 1.0


def _fx_rate_12m_ago(conn, base_ccy: str, quote_ccy: str, today: pd.Timestamp) -> float:
    base_ccy = (base_ccy or "EUR").upper()
    quote_ccy = (quote_ccy or "EUR").upper()
    if base_ccy == quote_ccy:
        return 1.0
    asof = (today - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    row = repo.get_fx_rate_asof_or_before(conn, base_ccy, quote_ccy, asof)
    if row and row["rate"]:
        return float(row["rate"])
    # fallback: dernier taux connu (moins juste, mais évite 0)
    row2 = repo.get_latest_fx_rate(conn, base_ccy, quote_ccy)
    if row2 and row2["rate"]:
        return float(row2["rate"])
    st.warning(f"Taux FX manquant {base_ccy}->{quote_ccy} (12M). Conversion ignorée (rate=1).")
    return 1.0


def afficher_compte_banque(conn, person_id: int, bank_account_id: int, key_prefix: str):
    today = pd.Timestamp.today().normalize()

    parent = repo.get_account(conn, bank_account_id)
    parent_ccy = (parent["currency"] if parent and parent["currency"] else "EUR").upper()
    parent_inst = (parent["institution"] if parent else None)

    st.markdown("### Banque — Tableau de bord")
    st.caption("Le compte BANQUE parent est un **container**. Les opérations se font sur les sous-comptes.")

    sub_df = repo.list_bank_subaccounts(conn, bank_account_id)

    # ─────────────────────────────────────────────
    # KPIs améliorés (12 mois)
    # ─────────────────────────────────────────────
    total_balance_parent = 0.0
    total_interest_12m_parent = 0.0
    total_avg_capital_12m_parent = 0.0
    total_fx_pnl_12m_parent = 0.0

    breakdown = []
    ranking = []

    for _, row in sub_df.iterrows():
        sid = int(row["sub_account_id"])
        subtype = str(row["subtype"] or "").lower()
        name = str(row["account_name"])
        ccy = (row["account_currency"] or "EUR").upper()

        tx = repo.list_transactions(conn, account_id=sid, limit=5000)

        bal = _solde_tx(tx)
        interest_12m = _interest_12m(tx, today)
        avg_cap_12m = _avg_month_end_balance_12m(tx, today)
        yield_12m = (interest_12m / avg_cap_12m * 100.0) if avg_cap_12m > 1e-9 else 0.0

        r_today = _fx_rate_today(conn, ccy, parent_ccy)
        r_12m = _fx_rate_12m_ago(conn, ccy, parent_ccy, today)

        bal_parent = bal * r_today
        interest_parent = interest_12m * r_today
        avg_parent = avg_cap_12m * r_today

        # FX P&L 12M (V1) : solde actuel * (rate_today - rate_12m)
        fx_pnl_parent = 0.0
        if ccy != parent_ccy:
            fx_pnl_parent = bal * (r_today - r_12m)

        total_balance_parent += bal_parent
        total_interest_12m_parent += interest_parent
        total_avg_capital_12m_parent += avg_parent
        total_fx_pnl_12m_parent += fx_pnl_parent

        breakdown.append({
            "Sous-compte": name,
            "Subtype": SUBTYPES.get(subtype, subtype),
            "Devise": ccy,
            "Solde": money(bal, ccy),
            f"Solde ({parent_ccy})": money(bal_parent, parent_ccy),
            "Intérêts 12M": money(interest_12m, ccy),
            f"Intérêts 12M ({parent_ccy})": money(interest_parent, parent_ccy),
            "Rendement 12M": f"{yield_12m:.2f} %",
            f"Impact FX 12M ({parent_ccy})": money(fx_pnl_parent, parent_ccy),
        })

        ranking.append({
            "Sous-compte": name,
            "Subtype": SUBTYPES.get(subtype, subtype),
            "Devise": ccy,
            f"Intérêts 12M ({parent_ccy})": interest_parent,
            "Capital moyen 12M (approx)": avg_parent,
            "Rendement 12M (%)": yield_12m,
        })

    # KPI globaux
    global_yield = (total_interest_12m_parent / total_avg_capital_12m_parent * 100.0) if total_avg_capital_12m_parent > 1e-9 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Liquidités totales", money(total_balance_parent, parent_ccy))
    c2.metric("Intérêts perçus (12 mois)", money(total_interest_12m_parent, parent_ccy))
    c3.metric("Rendement global (12 mois)", f"{global_yield:.2f} %")
    c4.metric(f"Impact change (12 mois) ({parent_ccy})", money(total_fx_pnl_12m_parent, parent_ccy))

    # Table synthèse
    if breakdown:
        st.dataframe(pd.DataFrame(breakdown), use_container_width=True, hide_index=True)
    else:
        st.info("Aucun sous-compte lié pour l’instant.")

    st.divider()

    # ─────────────────────────────────────────────
    # Classement rendement (12M)
    # ─────────────────────────────────────────────
    st.markdown("### Classement — Rendement (12 mois)")
    if ranking:
        rk = pd.DataFrame(ranking).sort_values("Rendement 12M (%)", ascending=False).reset_index(drop=True)
        rk["Rendement 12M (%)"] = rk["Rendement 12M (%)"].map(lambda x: f"{float(x):.2f} %")
        rk[f"Intérêts 12M ({parent_ccy})"] = rk[f"Intérêts 12M ({parent_ccy})"].map(lambda x: money(float(x), parent_ccy))
        rk["Capital moyen 12M (approx)"] = rk["Capital moyen 12M (approx)"].map(lambda x: money(float(x), parent_ccy))
        st.dataframe(rk, use_container_width=True, hide_index=True)
    else:
        st.caption("Ajoute des sous-comptes pour avoir un classement.")

    st.divider()

    # ─────────────────────────────────────────────
    # Ajouter / lier un sous-compte
    # ─────────────────────────────────────────────
    with st.expander("➕ Ajouter / lier un sous-compte", expanded=False):
        st.markdown("#### 1) Créer un nouveau sous-compte")
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            new_name = st.text_input("Nom (ex: Revolut - Rémunéré USD)", key=f"{key_prefix}_new_name")
        with col2:
            new_ccy = st.selectbox("Devise", ["EUR", "USD", "CHF"], key=f"{key_prefix}_new_ccy")
        with col3:
            new_subtype = st.selectbox("Subtype", list(SUBTYPES.keys()), format_func=lambda k: SUBTYPES[k], key=f"{key_prefix}_new_subtype")

        if st.button("Créer et lier", use_container_width=True, key=f"{key_prefix}_create_link"):
            if not new_name.strip():
                st.error("Nom obligatoire.")
            else:
                new_id = repo.create_account(
                    conn,
                    person_id=person_id,
                    name=new_name.strip(),
                    account_type="BANQUE",
                    institution=(parent_inst.strip() if parent_inst else None),
                    currency=new_ccy,
                )
                repo.link_subaccount_to_bank(conn, bank_account_id, new_id, new_subtype)
                st.success("Sous-compte créé et lié ✅")
                reset_cache()
                st.rerun()

        st.markdown("---")
        st.markdown("#### 2) Lier un compte existant (BANQUE)")
        all_acc = repo.list_accounts(conn, person_id=person_id)

        linked_ids = set(sub_df["sub_account_id"].tolist()) if not sub_df.empty else set()

        candidates = all_acc[
            (all_acc["account_type"] == "BANQUE")
            & (all_acc["id"] != bank_account_id)
            & (~all_acc["id"].isin(list(linked_ids)))
        ].copy()

        if candidates.empty:
            st.caption("Aucun compte BANQUE disponible à lier.")
        else:
            options = candidates.apply(lambda r: f"{r['name']} ({r['currency']})", axis=1).tolist()
            pick = st.selectbox("Compte à lier", options, key=f"{key_prefix}_pick_existing")
            subtype2 = st.selectbox("Subtype", list(SUBTYPES.keys()), format_func=lambda k: SUBTYPES[k], key=f"{key_prefix}_existing_subtype")

            if st.button("Lier ce compte", use_container_width=True, key=f"{key_prefix}_link_existing"):
                idx = options.index(pick)
                sid = int(candidates.iloc[idx]["id"])
                repo.link_subaccount_to_bank(conn, bank_account_id, sid, subtype2)
                st.success("Compte lié ✅")
                reset_cache()
                st.rerun()

    st.divider()

    # ─────────────────────────────────────────────
    # Détail sous-compte (avec KPIs)
    # ─────────────────────────────────────────────
    st.markdown("### Détail d’un sous-compte")
    if sub_df.empty:
        st.caption("Ajoute un sous-compte pour voir le détail.")
        return

    pick_labels = sub_df.apply(
        lambda r: f"{r['account_name']} — {SUBTYPES.get(str(r['subtype']).lower(), r['subtype'])} ({(r['account_currency'] or 'EUR').upper()})",
        axis=1
    ).tolist()

    pick = st.selectbox("Choisir", pick_labels, key=f"{key_prefix}_pick_sub")
    idx = pick_labels.index(pick)

    sid = int(sub_df.iloc[idx]["sub_account_id"])
    sname = str(sub_df.iloc[idx]["account_name"])
    sccy = (sub_df.iloc[idx]["account_currency"] or "EUR").upper()

    tx_sub = repo.list_transactions(conn, account_id=sid, limit=5000)

    bal_sub = _solde_tx(tx_sub)
    interest_sub_12m = _interest_12m(tx_sub, today)
    avg_sub_12m = _avg_month_end_balance_12m(tx_sub, today)
    yield_sub_12m = (interest_sub_12m / avg_sub_12m * 100.0) if avg_sub_12m > 1e-9 else 0.0

    r_today = _fx_rate_today(conn, sccy, parent_ccy)
    r_12m = _fx_rate_12m_ago(conn, sccy, parent_ccy, today)
    fx_pnl_sub = (bal_sub * (r_today - r_12m)) if sccy != parent_ccy else 0.0

    colA, colB, colC, colD = st.columns(4)
    colA.metric("Solde", money(bal_sub, sccy))
    colB.metric("Intérêts 12M", money(interest_sub_12m, sccy))
    colC.metric("Rendement 12M", f"{yield_sub_12m:.2f} %")
    colD.metric(f"Impact FX 12M ({parent_ccy})", money(fx_pnl_sub, parent_ccy))

    col_g, col_d = st.columns([2, 1], gap="large")
    with col_g:
        st.markdown("#### Historique")
        tableau_operations(tx_sub)

    with col_d:
        st.markdown("#### Ajouter une opération")
        bloc_saisie_operation(
            conn,
            person_id=person_id,
            account_id=sid,
            account_type="BANQUE",
            key_prefix=f"{key_prefix}_sub{sid}",
        )
