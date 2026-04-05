import streamlit as st
import pandas as pd
import plotly.express as px

from utils.format_monnaie import money
from services import family_dashboard as fd
from services import family_snapshots as fs  # si tu l’as déjà (rebuild famille)
from services import diagnostics as diag     # pour dates prix/FX si tu l’as


def afficher_famille_dashboard(conn):
    people = fd.get_people(conn)
    if people.empty:
        st.error("Aucune personne en base.")
        return

    person_ids = [int(x) for x in people["id"].tolist()]

    # --- Header
    h1, h2 = st.columns([1.2, 2.8])
    with h1:
        if st.button("📸 Rebuild Famille (90j)", use_container_width=True, key="fam_dash_rebuild"):
            res = fs.rebuild_family_weekly(conn, person_ids=person_ids, lookback_days=90, family_id=1)
            st.success(f"Rebuild Famille terminé ✅ {res}")
            st.rerun()

    with h2:
        st.caption("Vue Famille = somme des snapshots weekly des personnes + comparaisons (gamified).")

    # --- Série famille (agrégation directe depuis snapshots personnes)
    df_family = fd.get_family_series_from_people_snapshots(conn, person_ids)
    if df_family.empty:
        st.warning("Aucune donnée weekly. Lance un rebuild (personnes + famille).")
        return

    # --- Semaine commune (pour comparer les personnes proprement)
    common_week = fd.get_last_common_week(conn, person_ids)
    if common_week is None:
        st.warning("Impossible de trouver une semaine commune à toutes les personnes (rebuild nécessaire).")
        return

    kpis = fd.compute_family_kpis(df_family)
    asof = kpis.get("asof")
    asof_txt = asof.strftime("%Y-%m-%d") if asof is not None else "—"

    st.markdown(f"### 👨‍👩‍👧‍👦 Famille — Semaine : **{asof_txt}**")

    # --- KPI Cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimoine net", money(kpis.get("patrimoine_net", 0.0)))
    c2.metric("Patrimoine brut", money(kpis.get("patrimoine_brut", 0.0)))
    c3.metric("Liquidités", money(kpis.get("liquidites_total", 0.0)))
    c4.metric("Crédits restants", money(kpis.get("credits_remaining", 0.0)))

    # Perf bloc (lisible)
    p1, p2, p3 = st.columns(3)
    p3m = kpis.get("perf_3m")
    p12m = kpis.get("perf_12m")
    cagr = kpis.get("cagr")
    p1.metric("Évolution 3 mois", f"{p3m:.1f}%" if p3m is not None else "—")
    p2.metric("Évolution 12 mois", f"{p12m:.1f}%" if p12m is not None else "—")
    p3.metric("Rendement annualisé", f"{cagr:.1f}%" if cagr is not None else "—")

    st.divider()

    # --- Courbe
    st.markdown("### 📈 Évolution — Patrimoine net (weekly)")
    st.line_chart(df_family.set_index("week_date")[["patrimoine_net"]])

    st.divider()

    # --- Répartition (2 charts)
    left, right = st.columns([1.1, 1.1])

    with left:
        st.markdown("### 🥧 Répartition par catégories")
        alloc = fd.compute_allocations_family(df_family)
        alloc_df = pd.DataFrame([{"Catégorie": k, "Valeur": v} for k, v in alloc.items() if v > 0])
        if alloc_df.empty:
            st.info("Pas assez de données pour l’allocation.")
        else:
            fig = px.pie(alloc_df, names="Catégorie", values="Valeur", hole=0.45)
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("### 🥧 Répartition par personne (Net)")
        df_people = fd.compute_people_table(conn, people, common_week)
        if df_people.empty:
            st.info("Pas de snapshots au format attendu.")
        else:
            person_alloc = df_people[["Personne", "Net (€)"]].copy()
            person_alloc = person_alloc[person_alloc["Net (€)"] > 0]
            if person_alloc.empty:
                st.info("Net nul / non disponible.")
            else:
                fig2 = px.pie(person_alloc, names="Personne", values="Net (€)", hole=0.45)
                fig2.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # --- Leaderboards (Gamification)
    st.markdown("### 🏆 Classements (famille)")
    boards = fd.compute_leaderboards(conn, people, person_ids, common_week)

    a, b = st.columns(2)
    with a:
        st.markdown("#### 🥇 Patrimoine net (Top 3)")
        top_net = boards.get("top_net")
        if top_net is None or len(top_net) == 0:
            st.write("—")
        else:
            for i, row in top_net.iterrows():
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "•"
                st.write(f"{medal} **{row['Personne']}** — {money(float(row['Net (€)']))}")

        st.markdown("#### 🎯 Exposition bourse (Top 3)")
        top_expo = boards.get("top_expo_bourse")
        if top_expo is None or len(top_expo) == 0:
            st.write("—")
        else:
            for i, row in top_expo.iterrows():
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "•"
                st.write(f"{medal} **{row['Personne']}** — {float(row['% Expo Bourse']):.1f}%")

    with b:
        st.markdown("#### 🚀 Progression 3 mois (Top 3)")
        top3 = boards.get("top_perf_3m", [])
        if not top3:
            st.write("—")
        else:
            for i, (name, val) in enumerate(top3):
                medal = ["🥇", "🥈", "🥉"][i]
                st.write(f"{medal} **{name}** — {val:.1f}%")

        st.markdown("#### 📈 Progression 12 mois (Top 3)")
        top12 = boards.get("top_perf_12m", [])
        if not top12:
            st.write("—")
        else:
            for i, (name, val) in enumerate(top12):
                medal = ["🥇", "🥈", "🥉"][i]
                st.write(f"{medal} **{name}** — {val:.1f}%")

    st.divider()

    # --- Table “profil personne” (super utile + lisible)
    st.markdown("### 🧾 Détails par personne (semaine commune)")
    df_people = fd.compute_people_table(conn, people, common_week)
    if df_people is not None and not df_people.empty:
        st.dataframe(df_people, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune donnée personne à afficher.")

    # --- Debug expander
    with st.expander("🛠️ Diagnostic (famille)", expanded=False):
        dbg = fd.compute_family_debug(conn, people, common_week)
        st.dataframe(dbg, use_container_width=True, hide_index=True)

        # Dates prix/FX si dispo
        try:
            dates = diag.last_market_dates(conn)
            st.write("**Dernières données marché en base**")
            st.write(f"- Prix weekly : {dates.get('last_price_week')}")
            st.write(f"- FX weekly   : {dates.get('last_fx_week')}")
        except Exception:
            st.caption("Diagnostic marché non disponible (services/diagnostics.py absent).")
