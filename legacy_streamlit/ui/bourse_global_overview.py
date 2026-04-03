import streamlit as st
import pandas as pd
import plotly.express as px

from utils.format_monnaie import money
from services import snapshots as wk_snap
from services import bourse_analytics as ba
from services import diagnostics as diag


def afficher_bourse_global_overview(conn, person_id: int):
    st.subheader("📊 Bourse (GLOBAL)")
    st.caption("Données issues des snapshots weekly — calculées as-of avec transactions + prix weekly + FX weekly.")

    st.markdown("""
    <style>
    .bg-grid {display:flex; gap:14px; align-items:stretch;}
    .bg-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 14px 16px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.25);
    }
    .bg-card h4 {margin:0 0 6px 0; font-size: 13px; opacity: .85; font-weight: 600;}
    .bg-card .big {font-size: 30px; font-weight: 800; margin:0; line-height:1.0;}
    .bg-card .sub {margin-top:6px; font-size: 12px; opacity: .75;}
    .bg-pill {
    display:inline-block; padding: 4px 10px; border-radius: 999px;
    font-size: 12px; font-weight: 700; margin-top: 8px;
    }
    .bg-blue   {background: linear-gradient(135deg, rgba(30,64,175,0.45), rgba(59,130,246,0.18)); border-color: rgba(59,130,246,0.35);}
    .bg-green  {background: linear-gradient(135deg, rgba(6,95,70,0.45), rgba(16,185,129,0.15)); border-color: rgba(16,185,129,0.35);}
    .bg-purple {background: linear-gradient(135deg, rgba(88,28,135,0.45), rgba(168,85,247,0.14)); border-color: rgba(168,85,247,0.35);}
    .bg-amber  {background: linear-gradient(135deg, rgba(120,53,15,0.42), rgba(245,158,11,0.14)); border-color: rgba(245,158,11,0.35);}

    .bg-pill-green {background: rgba(16,185,129,0.18); border: 1px solid rgba(16,185,129,0.35); color: rgb(167,243,208);}
    .bg-pill-red   {background: rgba(239,68,68,0.18); border: 1px solid rgba(239,68,68,0.35); color: rgb(254,202,202);}
    .bg-pill-gray  {background: rgba(148,163,184,0.12); border: 1px solid rgba(148,163,184,0.25); color: rgb(226,232,240);}
    </style>
    """, unsafe_allow_html=True)

    # --- Actions compactes (haut)
    a1, a2, a3 = st.columns([1.2, 2.4, 1.4])
    with a1:
        if st.button("📸 Rebuild 90j", use_container_width=True, key=f"bg_rebuild_{person_id}"):
            res = wk_snap.rebuild_snapshots_person(conn, person_id=person_id, lookback_days=90)
            st.success(f"Rebuild weekly terminé ✅ {res}")
            st.rerun()

    with a2:
        st.markdown("**On suit uniquement l’investi (holdings)** — le cash est ignoré (déjà traité ailleurs).")

    with a3:
        # petit rappel de date (dernière semaine)
        st.markdown("<div style='text-align:right; opacity:.75; font-size:12px;'>Dernière semaine snapshot</div>", unsafe_allow_html=True)


    # --- Série weekly
    # --- Série weekly
    df = ba.get_bourse_weekly_series(conn, person_id=person_id)
    if df.empty:
        st.warning("Aucun snapshot weekly pour la bourse. Lance un rebuild.")
        return

    # date as-of
    asof_date = df["date"].iloc[-1].strftime("%Y-%m-%d")

    # Valeur investie = holdings
    val_investie = float(df["holdings_eur"].iloc[-1])

    # Valeur portefeuille bourse = holdings + cash bourse (as-of)
    # On prend le cash depuis le snapshot weekly si dispo, sinon 0
    # (Le snapshot weekly contient bourse_cash: cash bourse en EUR)
    try:
        # récup via snapshots weekly (mrepo) si tu l'as encore dans df snapshots, sinon 0
        # Ici df est la série holdings only, donc on récup cash via snapshot full:
        from services import market_repository as mrepo
        df_snap = mrepo.list_weekly_snapshots(conn, person_id=person_id)
        date_col = "week_date" if "week_date" in df_snap.columns else "snapshot_date"
        df_snap = df_snap.sort_values(date_col)
        bourse_cash = float(df_snap["bourse_cash"].iloc[-1]) if "bourse_cash" in df_snap.columns else 0.0
    except Exception:
        bourse_cash = 0.0

    val_portefeuille = float(val_investie + bourse_cash)

    # positions (pour top actif + allocation + tableau)
    df_pos = ba.compute_positions_valued_asof(conn, person_id=person_id, asof_week_date=asof_date)

    last_value = float(df["holdings_eur"].iloc[-1])

    # ---- KPI cards "compréhensibles"
    from services import market_repository as mrepo  # si pas déjà importé

    # cash bourse depuis dernier snapshot weekly (si dispo)
    bourse_cash = 0.0
    try:
        df_snap = mrepo.list_weekly_snapshots(conn, person_id=person_id)
        if df_snap is not None and not df_snap.empty and "bourse_cash" in df_snap.columns:
            bourse_cash = float(df_snap["bourse_cash"].iloc[-1])
    except Exception:
        bourse_cash = 0.0

    val_actifs = float(val_investie)  # holdings = valeur des actifs
    val_portefeuille = float(val_actifs + bourse_cash)

    montant_investi = ba.compute_invested_amount_eur_asof(conn, person_id=person_id, asof_week_date=asof_date)

    # perf 12 mois fiable (sinon None)
    perf_12m = ba.compute_perf_12m_safe(df, min_base_eur=200.0)

    # top actif
    tops = ba.top_assets(df_pos, n=1)
    top_label = tops[0][0] if tops else "—"
    top_val   = tops[0][1] if tops else 0.0

    perf_debut = ba.compute_perf_since_start(df, min_base_eur=200.0)
    cagr_debut = ba.compute_cagr_since_start(df, min_base_eur=200.0)
    start_dt = ba.get_start_date_for_perf(df, min_base_eur=200.0)
    start_txt = start_dt.strftime("%d/%m/%Y") if start_dt is not None else "—"

    def _pill_simple(pct):
        if pct is None:
            return ("—", "bg-pill-gray")
        if pct >= 0:
            return (f"+{pct:.1f}%", "bg-pill-green")
        return (f"{pct:.1f}%", "bg-pill-red")

    pstart_txt, pstart_cls = _pill_simple(perf_debut)
    cagr_txt, cagr_cls = _pill_simple(cagr_debut)


    p12_txt, p12_cls = _pill_simple(perf_12m)

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.markdown(f"""
        <div class="bg-card bg-blue">
        <h4>Performance depuis début</h4>
        <p class="big">{pstart_txt if perf_debut is not None else "—"}</p>
        <span class="bg-pill {pstart_cls}">{pstart_txt}</span>
        <div class="sub">Annualisé : <b>{cagr_txt if cagr_debut is not None else "—"}</b> • Début : <b>{start_txt}</b></div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="bg-card bg-purple">
        <h4>Valeur des actifs</h4>
        <p class="big">{money(val_actifs)}</p>
        <div class="sub">Valorisation actuelle</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="bg-card bg-amber">
        <h4>Montant investi</h4>
        <p class="big">{money(montant_investi)}</p>
        <div class="sub">Achats – ventes (net)</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        st.markdown(f"""
        <div class="bg-card bg-green">
        <h4>Performance 12 mois</h4>
        <p class="big">{p12_txt if perf_12m is not None else "—"}</p>
        <span class="bg-pill {p12_cls}">{p12_txt}</span>
        <div class="sub">Évolution sur 12 mois</div>
        </div>
        """, unsafe_allow_html=True)

    with c5:
        st.markdown(f"""
        <div class="bg-card bg-blue">
        <h4>Top actif</h4>
        <p class="big">{top_label}</p>
        <span class="bg-pill bg-pill-gray">{money(top_val) if tops else "—"}</span>
        <div class="sub">Plus grosse position</div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # --- Courbe principale (ludique + lisible)
    st.markdown("### 📈 Évolution weekly — Valeur investie (holdings)")
    d = df.copy()
    d = d.sort_values("date")
    st.line_chart(d.set_index("date")[["holdings_eur"]])


    st.divider()

    # --- Allocation (Pie chart)
    st.markdown("### 🥧 Allocation par actif")
    if df_pos.empty:
        st.info("Aucune position ouverte à la dernière semaine.")
    else:
        alloc = df_pos.groupby("ticker", as_index=False)["valeur_eur"].sum().sort_values("valeur_eur", ascending=False)
        # Top 10 + Autres pour un pie lisible
        if len(alloc) > 10:
            top = alloc.head(10).copy()
            other = pd.DataFrame([{"ticker": "Autres", "valeur_eur": float(alloc.iloc[10:]["valeur_eur"].sum())}])
            alloc = pd.concat([top, other], ignore_index=True)

        fig = px.pie(
            alloc,
            names="ticker",
            values="valeur_eur",
            hole=0.45,
        )
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Tableau positions (toutes les positions)
    st.markdown("### 🧾 Positions consolidées")
    st.caption("Toutes les positions ouvertes (qty > 0) — valorisées en EUR (prix weekly + FX weekly).")

    if df_pos.empty:
        st.info("Aucune position ouverte.")
        return

    # petits filtres ludiques, mais simples
    f1, f2, f3 = st.columns([1.2, 1.2, 1.6])
    with f1:
        min_value = st.number_input("Valeur min (€)", min_value=0.0, value=0.0, step=100.0)
    with f2:
        devises = ["Toutes"] + sorted(df_pos["devise"].astype(str).unique().tolist())
        ccy = st.selectbox("Devise", devises, index=0)
    with f3:
        tri = st.selectbox("Tri", ["Valeur décroissante", "Ticker A→Z", "Poids décroissant"], index=0)

    dpos = df_pos.copy()
    dpos = dpos[dpos["valeur_eur"] >= float(min_value)]
    if ccy != "Toutes":
        dpos = dpos[dpos["devise"] == ccy]

    if tri == "Ticker A→Z":
        dpos = dpos.sort_values("ticker", ascending=True)
    elif tri == "Poids décroissant":
        dpos = dpos.sort_values("poids_%", ascending=False)
    else:
        dpos = dpos.sort_values("valeur_eur", ascending=False)

    # format colonnes (sans casser le dataframe)
    dpos_display = dpos.rename(columns={
        "ticker": "Ticker",
        "compte": "Compte",
        "devise": "Devise",
        "quantite": "Qté",
        "prix_weekly": "Prix weekly",
        "valeur_eur": "Valeur EUR",
        "poids_%": "Poids %",
    }).copy()

    st.dataframe(dpos_display, use_container_width=True, hide_index=True)

    # --- bloc "Top actifs" (ludique)
    st.markdown("### 🔥 Top actifs")
    tops5 = ba.top_assets(df_pos, n=5)
    if not tops5:
        st.write("—")
    else:
        cols = st.columns(len(tops5))
        for i, (t, v) in enumerate(tops5):
            cols[i].metric(t, money(v))

    st.markdown("### 🧩 Sous-comptes utilisés (debug)")
    st.caption("Répartition et vérification des comptes inclus dans le calcul GLOBAL.")

    df_break = ba.compute_accounts_breakdown_asof(conn, person_id=person_id, asof_week_date=asof_date)

    if df_break.empty:
        st.info("Aucun sous-compte bourse détecté.")
    else:
        st.dataframe(df_break, use_container_width=True, hide_index=True)


    with st.expander("🛠️ Diagnostic (qualité des données)", expanded=False):
        info_dates = diag.last_market_dates(conn)
        st.write("**Dernières données en base**")
        st.write(f"- Prix weekly : {info_dates.get('last_price_week')}")
        st.write(f"- FX weekly   : {info_dates.get('last_fx_week')}")

        d = diag.diagnose_bourse_asof(conn, person_id=person_id, asof_week_date=asof_date)
        if not d.get("ok"):
            st.warning(f"Diagnostic impossible: {d.get('reason')}")
        else:
            st.write(f"**Positions détectées : {d.get('positions', 0)}**")

            mp = d.get("missing_prices", [])
            mf = d.get("missing_fx", [])

            if mp:
                st.error(f"Tickers sans prix weekly (as-of {asof_date}) : {', '.join(mp[:25])}" + (" ..." if len(mp) > 25 else ""))
            else:
                st.success("Tous les tickers ont un prix weekly ✅")

            if mf:
                st.error("FX manquants : " + ", ".join([f"{a}/{b}" for a,b in mf]))
            else:
                st.success("FX OK ✅")
