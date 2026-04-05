import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import altair as alt
from datetime import datetime
from services.credits import get_credit_dates

import pytz
from services.credits import (
    get_credit_by_account, get_credit_kpis, cout_reel_mois_via_bankin,
    cout_reel_mois_credit_via_bankin, get_crd_a_date,
    build_amortissement, CreditParams, replace_amortissement,
)


def afficher_dashboard_credit(conn, person_id: int, account_id: int):
    credit = get_credit_by_account(conn, account_id)

    if not credit:
        st.info("Aucune fiche crédit trouvée. Va dans Import → Crédit pour la créer.")
        return

    k = get_credit_kpis(conn, credit_id=int(credit["id"]))

    # --- KPIs ---
    # --- Graphes ---
    st.markdown("### Évolution")
    courbe = k["courbe_crd"]
    if courbe.empty:
        st.info("Aucun amortissement importé. Va dans Import → Crédit pour importer le CSV.")
        return

    courbe_plot = courbe.copy()
    courbe_plot["date_echeance"] = pd.to_datetime(courbe_plot["date_echeance"], errors="coerce")
    courbe_plot = courbe_plot.dropna(subset=["date_echeance"])
    
    today = pd.Timestamp.today()
    mois_courant = f"{today.year:04d}-{today.month:02d}-01"
    today = pd.Timestamp.today()
    mois_courant = f"{today.year:04d}-{today.month:02d}-01"
    cout_reel = cout_reel_mois_credit_via_bankin(conn, credit_id=int(credit["id"]), mois_yyyy_mm_01=mois_courant)
    capital_init = float(credit.get("capital_emprunte") or 0.0)
    today = pd.Timestamp.today().normalize()
    crd_today = get_crd_a_date(conn, credit_id=int(credit["id"]), date_ref=str(today.date()))
    capital_rembourse = max(0.0, capital_init - crd_today)
    # Date de fin (dernière échéance du tableau)
    date_fin = courbe_plot["date_echeance"].max()
    date_debut = courbe_plot["date_echeance"].min()

    # Mois restants estimés (arrondi vers le haut)
    if pd.isna(date_fin):
        mois_restants = None
    else:
        # différence en mois (approx fiable)
        mois_restants = max(0, (date_fin.year - today.year) * 12 + (date_fin.month - today.month))
        # si on est en début de mois et qu'il reste une échéance ce mois, tu peux +1 (optionnel)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("CRD estimé (tableau)", f"{k['crd_estime']:,.2f} €".replace(",", " "))
    c2.metric("Capital remboursé", f"{capital_rembourse:,.2f} €".replace(",", " "))
    c3.metric("Intérêts restants (estim.)", f"{k['interets_restants']:,.2f} €".replace(",", " "))
    c4.metric("Assurance restante (estim.)", f"{k['assurance_restante']:,.2f} €".replace(",", " "))
    c5.metric("Coût réel du mois (Bankin)", f"{cout_reel:,.2f} €".replace(",", " "))
    c6.metric("Mois restants (estim.)", str(mois_restants) if mois_restants is not None else "N/A")
    
    st.divider()
    capital_init = float(credit.get("capital_emprunte") or 0.0)

    df_crd = k.get("courbe_crd")
    crd_last = float(k.get("crd_estime") or 0.0)

    # fallback : si crd_last==0 mais le crédit vient d'être créé, on prend le 1er crd > 0
    crd_start = None
    if df_crd is not None and not df_crd.empty:
        # on cherche le 1er crd strictement positif
        tmp = df_crd.copy()
        tmp["crd"] = pd.to_numeric(tmp["crd"], errors="coerce").fillna(0.0)
        positives = tmp[tmp["crd"] > 0]["crd"]
        if len(positives) > 0:
            crd_start = float(positives.iloc[0])

    # Si on a crd_start, on "cap" la progression
    today = pd.Timestamp.today()
    capital_init = float(credit.get("capital_emprunte") or 0.0)

    # CRD estimé à la date du jour (et pas le dernier CRD du tableau)
    crd_today = get_crd_a_date(conn, credit_id=int(credit["id"]), date_ref=str(today.date()))

    if capital_init > 0:
        prog = max(0.0, min(1.0, (capital_init - crd_today) / capital_init))
        st.progress(prog, text=f"Remboursé : {prog*100:.1f}%")


    st.divider()
    dates = get_credit_dates(conn, credit_id=int(credit["id"]))
    debut_remb = dates["date_debut_remboursement"]
    fin = dates["date_fin"]

    cA, cB = st.columns(2)
    cA.metric("Début remboursement", debut_remb.isoformat() if debut_remb else "—")
    cB.metric("Fin estimée", fin.isoformat() if fin else "—")

    # --- Fiche contrat ---
    st.markdown("### Fiche crédit")
    colA, colB, colC = st.columns(3)

    with colA:
        st.write(f"**Nom** : {credit.get('nom','')}")
        st.write(f"**Banque** : {credit.get('banque','')}")
        st.write(f"**Type** : {credit.get('type_credit','')}")

    with colB:
        st.write(f"**Capital emprunté** : {float(credit.get('capital_emprunte') or 0):,.2f} €".replace(",", " "))
        st.write(f"**Mensualité théorique** : {float(credit.get('mensualite_theorique') or 0):,.2f} €".replace(",", " "))
        st.write(f"**Assurance mensuelle** : {float(credit.get('assurance_mensuelle_theorique') or 0):,.2f} €".replace(",", " "))

    with colC:
        st.write(f"**Taux nominal** : {float(credit.get('taux_nominal') or 0):.2f} %")
        st.write(f"**TAEG** : {float(credit.get('taeg') or 0):.2f} %")
        st.write(f"**Durée** : {int(credit.get('duree_mois') or 0)} mois")

    st.divider()

    # --- Graphes ---
    # courbe_plot doit contenir: date_echeance (datetime) et crd (float)
    df_line = courbe_plot[["date_echeance", "crd"]].copy()
    df_line = df_line.sort_values("date_echeance")

    today = datetime.now(pytz.timezone("Europe/Paris")).date()
    crd_today = get_crd_a_date(conn, credit_id=int(credit["id"]), date_ref=str(today))

    df_point = pd.DataFrame({
        "date_echeance": [pd.to_datetime(today)],
        "crd": [crd_today],
    })

    line = alt.Chart(df_line).mark_line().encode(
        x=alt.X("date_echeance:T", title="Date"),
        y=alt.Y("crd:Q", title="Capital restant dû (CRD)"),
    )

    point = alt.Chart(df_point).mark_point(size=80, color="red").encode(
        x="date_echeance:T",
        y="crd:Q",
    )

    chart = (line + point).properties(height=260)

    st.altair_chart(chart, use_container_width=True)



    st.markdown("### Totaux annuels")
    tot = k["totaux_annuels"]
    if tot.empty:
        st.info("Pas de totaux annuels (colonne annee manquante ?).")
    else:
        tot_plot = tot.set_index("annee")[["capital_amorti", "interets", "assurance"]]
        st.bar_chart(tot_plot)

    st.divider()

    # --- Génération automatique du tableau d'amortissement ---
    st.markdown("### ⚙️ Générer le tableau d'amortissement automatiquement")
    credit_id = int(credit["id"])
    preview_key = f"amort_preview_{credit_id}"

    capital = float(credit.get("capital_emprunte") or 0.0)
    taux = float(credit.get("taux_nominal") or 0.0)
    duree = int(credit.get("duree_mois") or 0)
    date_debut = str(credit.get("date_debut") or "")
    assurance = float(credit.get("assurance_mensuelle_theorique") or 0.0)

    params_ok = capital > 0 and duree > 0 and date_debut

    if not params_ok:
        st.info("Renseigne le capital, la durée et la date de début dans la fiche crédit pour générer automatiquement.")
    else:
        if st.button("⚙️ Calculer l'amortissement", key=f"gen_amort_{credit_id}"):
            params = CreditParams(
                capital=capital,
                taux_annuel=taux,
                duree_mois=duree,
                date_debut=date_debut,
                assurance_mensuelle=assurance,
            )
            st.session_state[preview_key] = build_amortissement(params)

        if preview_key in st.session_state:
            rows = st.session_state[preview_key]
            df_preview = pd.DataFrame(rows)
            mensualite = float(df_preview["mensualite"].iloc[0]) if len(df_preview) > 0 else 0.0
            cout_total = float(df_preview["mensualite"].sum())
            cout_interets = float(df_preview["interets"].sum())

            c1, c2, c3 = st.columns(3)
            c1.metric("Mensualité calculée", f"{mensualite:,.2f} €".replace(",", " "))
            c2.metric("Coût total estimé", f"{cout_total:,.2f} €".replace(",", " "))
            c3.metric("Coût des intérêts", f"{cout_interets:,.2f} €".replace(",", " "))

            st.caption(f"Aperçu des 5 premières lignes sur {len(df_preview)} échéances :")
            st.dataframe(df_preview.head(5), use_container_width=True)

            if st.button("✅ Confirmer et sauvegarder", key=f"save_amort_{credit_id}"):
                replace_amortissement(conn, credit_id, rows)
                del st.session_state[preview_key]
                st.success("Tableau d'amortissement sauvegardé !")
                st.rerun()
