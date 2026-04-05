import streamlit as st
import pandas as pd

from services import family_snapshots as fs
from utils.format_monnaie import money


def afficher_famille_overview(conn, person_ids: list[int], family_id: int = 1):
    st.subheader("👨‍👩‍👧‍👦 Famille — Snapshots weekly")

    c1, c2 = st.columns([1.2, 2.8])
    with c1:
        if st.button("📸 Rebuild Famille (90 jours)", use_container_width=True, key="family_rebuild_90"):
            res = fs.rebuild_family_weekly(conn, person_ids=person_ids, lookback_days=90, family_id=family_id)
            st.success(f"Rebuild Famille terminé ✅ {res}")
            st.rerun()

    with c2:
        st.info("Cette vue agrège les snapshots weekly de chaque personne. Aucun calcul marché dans l’UI.", icon="ℹ️")

    df = fs.list_family_weekly_snapshots(conn, family_id=family_id)
    if df is None or df.empty:
        st.warning("Aucun snapshot famille. Lance un rebuild.")
        return

    df["week_date"] = pd.to_datetime(df["week_date"], errors="coerce")
    df = df.dropna(subset=["week_date"]).sort_values("week_date")

    last = df.iloc[-1]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Patrimoine net", money(float(last["patrimoine_net"])))
    k2.metric("Patrimoine brut", money(float(last["patrimoine_brut"])))
    k3.metric("Liquidités", money(float(last["liquidites_total"])))
    k4.metric("Crédits restants", money(float(last["credits_remaining"])))

    st.markdown("### 📈 Évolution patrimoine net (weekly)")
    st.line_chart(df.set_index("week_date")[["patrimoine_net"]])

    with st.expander("📋 Table snapshots famille", expanded=False):
        st.dataframe(df, use_container_width=True, hide_index=True)
