import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

from services.credits import get_credit_by_account, get_credit_kpis,cout_reel_mois_via_bankin, cout_reel_mois_credit_via_bankin, get_crd_a_date


def afficher_dashboard_credit(conn, person_id: int, account_id: int):
    credit = get_credit_by_account(conn, account_id)

    if not credit:
        st.info("Aucune fiche crédit trouvée. Va dans Import → Crédit pour la créer.")
        return

    k = get_credit_kpis(conn, credit_id=int(credit["id"]))

    # --- KPIs ---
    today = pd.Timestamp.today()
    mois_courant = f"{today.year:04d}-{today.month:02d}-01"
    today = pd.Timestamp.today()
    mois_courant = f"{today.year:04d}-{today.month:02d}-01"
    cout_reel = cout_reel_mois_credit_via_bankin(conn, credit_id=int(credit["id"]), mois_yyyy_mm_01=mois_courant)
    capital_init = float(credit.get("capital_emprunte") or 0.0)
    today = pd.Timestamp.today().normalize()
    crd_today = get_crd_a_date(conn, credit_id=int(credit["id"]), date_ref=str(today.date()))
    capital_rembourse = max(0.0, capital_init - crd_today)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CRD estimé (tableau)", f"{k['crd_estime']:,.2f} €".replace(",", " "))
    c2.metric("Capital remboursé", f"{capital_rembourse:,.2f} €".replace(",", " "))
    c3.metric("Intérêts restants (estim.)", f"{k['interets_restants']:,.2f} €".replace(",", " "))
    c4.metric("Assurance restante (estim.)", f"{k['assurance_restante']:,.2f} €".replace(",", " "))
    c5.metric("Coût réel du mois (Bankin)", f"{cout_reel:,.2f} €".replace(",", " "))

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
    st.markdown("### Évolution")
    courbe = k["courbe_crd"]
    if courbe.empty:
        st.info("Aucun amortissement importé. Va dans Import → Crédit pour importer le CSV.")
        return

    courbe_plot = courbe.copy()
    courbe_plot["date_echeance"] = pd.to_datetime(courbe_plot["date_echeance"], errors="coerce")
    courbe_plot = courbe_plot.dropna(subset=["date_echeance"])

    # Courbe complète CRD
    series_crd = courbe_plot.set_index("date_echeance")["crd"].sort_index()

    fig, ax = plt.subplots()
    ax.plot(series_crd.index, series_crd.values)

    # Point rouge à aujourd'hui
    today = pd.Timestamp.today().normalize()
    crd_today = get_crd_a_date(conn, credit_id=int(credit["id"]), date_ref=str(today.date()))

    ax.scatter([today], [crd_today], color="red", zorder=5)
    ax.annotate(
        "Aujourd'hui",
        (today, crd_today),
        textcoords="offset points",
        xytext=(8, 8),
    )

    ax.set_xlabel("Date")
    ax.set_ylabel("Capital restant dû (CRD)")
    st.pyplot(fig, clear_figure=True)

    st.markdown("### Totaux annuels")
    tot = k["totaux_annuels"]
    if tot.empty:
        st.info("Pas de totaux annuels (colonne annee manquante ?).")
    else:
        tot_plot = tot.set_index("annee")[["capital_amorti", "interets", "assurance"]]
        st.bar_chart(tot_plot)
