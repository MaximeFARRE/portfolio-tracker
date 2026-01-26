import streamlit as st
import pandas as pd

from services import diagnostics_global as dg
from services import snapshots as wk_snap
from services import family_snapshots as fs
from services import repositories as repo
from services import snapshots as wk_snap
from services import family_snapshots as fs
from services import repositories as repo


def afficher_data_health(conn):
    st.subheader("🛠️ Diagnostic — Data Health")

    st.markdown("### ✅ Check-up rapide (quotidien)")

    safety_weeks = st.selectbox("Fenêtre sécurité (recalc)", [2, 4, 8], index=1, key="chk_safety_weeks")

    people = repo.list_people(conn)
    person_ids = [int(x) for x in people["id"].tolist()] if people is not None and not people.empty else []

    col1, col2 = st.columns([2.2, 1.2])

    with col1:
        # Résumé statut
        rows = []
        for pid in person_ids:
            name = str(people.loc[people["id"] == pid, "name"].iloc[0])
            stt = dg.person_weekly_status(conn, person_id=pid, safety_weeks=int(safety_weeks))
            rows.append({
                "Personne": name,
                "Dernière semaine": stt.get("last_week") or "—",
                "Cible": stt.get("target_week"),
                "Manquantes (depuis dernière)": stt.get("missing_weeks") if stt.get("missing_weeks") is not None else "—",
                "Statut": "✅ À jour" if stt.get("suggested") == "UP_TO_DATE" else "⚠️ À rebuild",
            })

        df_status = pd.DataFrame(rows)
        if not df_status.empty:
            st.dataframe(df_status, use_container_width=True, hide_index=True)

    with col2:
        if st.button("🚀 Rebuild nécessaire (tout)", use_container_width=True, key="chk_rebuild_all"):
            # 1) rebuild personnes depuis dernière snapshot
            for pid in person_ids:
                wk_snap.rebuild_snapshots_person_from_last(conn, person_id=int(pid), safety_weeks=int(safety_weeks), fallback_lookback_days=90)

            # 2) rebuild famille depuis dernière snapshot (si dispo)
            try:
                fs.rebuild_family_weekly_from_last(conn, person_ids=person_ids, safety_weeks=int(safety_weeks), fallback_lookback_days=90, family_id=1)
            except Exception:
                pass

            st.success("Rebuild quotidien terminé ✅")
            st.rerun()
            
            if st.button("🧠 Backdated-aware (tout)", use_container_width=True, key="chk_backdated_all"):
            # Rebuild backdated-aware pour chaque personne
                for pid in person_ids:
                    wk_snap.rebuild_snapshots_person_backdated_aware(
                        conn,
                        person_id=int(pid),
                        safety_weeks=int(safety_weeks),
                        fallback_lookback_days=365
                    )

                # Rebuild famille backdated-aware
                try:
                    fs.rebuild_family_weekly_backdated_aware(
                        conn,
                        person_ids=person_ids,
                        safety_weeks=int(safety_weeks),
                        fallback_lookback_days=365,
                        family_id=1
                    )
                except Exception:
                    pass

                st.success("Backdated-aware rebuild terminé ✅")
                st.rerun()

    
    # --- Marché
    st.markdown("### 📡 Marché (weekly)")
    dates = dg.last_market_dates(conn)
    c1, c2 = st.columns(2)
    c1.metric("Dernière semaine prix", dates.get("last_price_week") or "—")
    c2.metric("Dernière semaine FX", dates.get("last_fx_week") or "—")

    st.divider()

    # --- Snapshots personnes
    st.markdown("### 👤 Snapshots — Personnes")
    df_last = dg.last_snapshot_week_by_person(conn)
    if df_last.empty:
        st.info("Aucune donnée snapshots personnes.")
    else:
        st.dataframe(df_last, use_container_width=True, hide_index=True)

        # manquants
        with st.expander("📉 Semaines manquantes (90 jours)", expanded=False):
            # petit contrôle fenêtre glissante
            recalc_days = st.selectbox("Fenêtre glissante (recalc)", [0, 30, 90], index=0, key="dbg_recalc_days")
            safety_weeks = st.selectbox("Fenêtre sécurité (recalc)", [2, 4, 8], index=1, key="dbg_safety_weeks")


            for _, row in df_last.iterrows():
                pid = int(row["person_id"])
                name = str(row["person_name"])

                cols_btn = st.columns([1.6, 1.2, 1.2])

                with cols_btn[0]:
                    st.write(f"**{name}**")

                with cols_btn[1]:
                    if st.button("Rebuild missing", key=f"rb_missing_{pid}", use_container_width=True):
                        res = wk_snap.rebuild_snapshots_person_missing_only(conn, person_id=pid, lookback_days=90, recalc_days=0)
                        st.success(f"{name} ✅ {res}")
                        st.rerun()

                with cols_btn[2]:
                    if st.button("Depuis dernière", key=f"rb_last_{pid}", use_container_width=True):
                        res = wk_snap.rebuild_snapshots_person_from_last(conn, person_id=pid, safety_weeks=int(safety_weeks), fallback_lookback_days=90)
                        st.success(f"{name} ✅ {res}")
                        st.rerun()


                df_miss = dg.missing_snapshot_weeks(conn, person_id=pid, lookback_days=90)
                if df_miss.empty:
                    st.success(f"{name} : aucune semaine manquante ✅")
                else:
                    st.warning(f"{name} : {len(df_miss)} semaine(s) manquante(s)")
                    st.dataframe(df_miss, use_container_width=True, hide_index=True)

    st.divider()

    # --- Snapshots famille
    st.markdown("### 👨‍👩‍👧‍👦 Snapshots — Famille")

    people = repo.list_people(conn)
    person_ids = [int(x) for x in people["id"].tolist()] if people is not None and not people.empty else []

    col_f1, col_f2, col_f3 = st.columns([1.8, 1.2, 1.2])

    with col_f1:
        st.write("Rebuild famille : rebuild personnes + agrégation")

    with col_f2:
        if st.button("Famille missing", use_container_width=True, key="rb_family_missing"):
            res = fs.rebuild_family_weekly_missing_only(conn, person_ids=person_ids, lookback_days=90, recalc_days=0, family_id=1)
            st.success(f"Famille ✅ {res}")
            st.rerun()

    with col_f3:
        if st.button("Famille depuis dernière", use_container_width=True, key="rb_family_last"):
            res = fs.rebuild_family_weekly_from_last(conn, person_ids=person_ids, safety_weeks=int(safety_weeks), fallback_lookback_days=90, family_id=1)
            st.success(f"Famille ✅ {res}")
            st.rerun()


    df_fam_miss = dg.family_missing_weeks(conn, lookback_days=90)
    if df_fam_miss.empty:
        st.success("Famille : aucune semaine manquante ✅")
    else:
        st.warning(f"Famille : {len(df_fam_miss)} semaine(s) manquante(s)")
        st.dataframe(df_fam_miss, use_container_width=True, hide_index=True)

    st.divider()

    # --- Tickers sans prix
    st.markdown("### 🧾 Tickers sans prix weekly (base)")
    df_t = dg.tickers_missing_weekly_prices(conn, max_show=30)
    if df_t.empty:
        st.success("Tous les tickers des transactions ont un prix weekly ✅")
    else:
        st.error("Certains tickers n'ont aucun prix weekly en base.")
        st.dataframe(df_t, use_container_width=True, hide_index=True)
        st.caption("Astuce : vérifie le ticker (format yfinance) ou ajoute une règle de mapping.")
