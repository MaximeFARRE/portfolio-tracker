import streamlit as st
import pandas as pd
from datetime import date
import matplotlib.pyplot as plt

from services.revenus_repository import (
    ajouter_revenu,
    revenus_du_mois,
    revenus_par_mois,
    dernier_revenu,
    supprimer_revenu_par_id,
    maj_revenu,
)

# Catégories simples (tu peux les modifier)
CATEGORIES_REVENUS = [
    "Salaire",
    "Prime",
    "Remboursement",
    "Dividendes",
    "Intérêts",
    "Autres",
]

MOIS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
]


def onglet_revenus(conn, person_id: int, key_prefix: str = "revenus"):
    st.subheader("Revenus")

    # ----------------------------
    # Sélection mois (Année + Mois)
    # ----------------------------
    today = date.today()

    col_a, col_m = st.columns(2)

    with col_a:
        annees = list(range(today.year - 5, today.year + 1))
        annee = st.selectbox(
            "Année",
            options=annees,
            index=len(annees) - 1,
            key=f"{key_prefix}_annee",
        )

    with col_m:
        mois_nom = st.selectbox(
            "Mois",
            options=MOIS_FR,
            index=today.month - 1,
            key=f"{key_prefix}_mois",
        )

    mois_num = MOIS_FR.index(mois_nom) + 1
    mois = f"{annee:04d}-{mois_num:02d}-01"  # format stable DB

    st.caption(f"Mois sélectionné : {mois_nom} {annee}")

    st.divider()

    # ----------------------------
    # Scanner (saisie rapide)
    # ----------------------------
    st.markdown("### Saisie rapide (mode scanner)")

    categorie_active = st.selectbox(
        "Catégorie active",
        CATEGORIES_REVENUS,
        key=f"{key_prefix}_cat",
    )

    with st.form(key=f"{key_prefix}_form", clear_on_submit=True):
        montant_str = st.text_input(
            "Montant",
            placeholder="Ex : 1200, 300.5, 50",
            key=f"{key_prefix}_montant_txt",
        )

        ajouter = st.form_submit_button("Ajouter ➕")

        if ajouter:
            try:
                montant = float(montant_str.replace(",", "."))
            except ValueError:
                st.error("Montant invalide")
                st.stop()

            if montant <= 0:
                st.error("Montant invalide")
                st.stop()

            ajouter_revenu(conn, person_id, mois, categorie_active, montant)

    # Annuler dernière saisie
    col_undo1, col_undo2 = st.columns([2, 1])
    with col_undo2:
        if st.button("Annuler la dernière saisie ↩️", use_container_width=True, key=f"{key_prefix}_undo"):
            last = dernier_revenu(conn, person_id, mois)
            if last is None:
                st.warning("Rien à annuler pour ce mois.")
            else:
                revenu_id, cat, montant = last
                supprimer_revenu_par_id(conn, revenu_id)
                st.success(f"Annulé : {cat} — {montant:.2f} €")
                st.rerun()

    # ----------------------------
    # Modifier / supprimer (data_editor)
    # ----------------------------
    with st.expander("Modifier / supprimer des saisies (détail)", expanded=False):
        df_detail = revenus_du_mois(conn, person_id, mois)

        if df_detail.empty:
            st.info("Aucune ligne à modifier.")
        else:
            st.info("Tu peux modifier la catégorie ou le montant, puis cliquer sur Appliquer.")

            edited = st.data_editor(
                df_detail,
                use_container_width=True,
                num_rows="dynamic",
                key=f"{key_prefix}_editor",
            )

            if st.button("Appliquer les modifications ✅", key=f"{key_prefix}_apply"):
                edited = edited[["id", "categorie", "montant"]].copy()

                for _, row in edited.iterrows():
                    try:
                        revenu_id = int(row["id"])
                        categorie = str(row["categorie"])
                        montant = float(str(row["montant"]).replace(",", "."))
                        if montant <= 0:
                            continue
                        if categorie not in CATEGORIES_REVENUS:
                            continue
                        maj_revenu(conn, revenu_id, categorie, montant)
                    except Exception:
                        continue

                st.success("Modifications appliquées ✅")
                st.rerun()

    # ----------------------------
    # Synthèse
    # ----------------------------
    st.markdown("### Synthèse du mois")

    df = revenus_du_mois(conn, person_id, mois)

    if df.empty:
        st.info("Aucun revenu pour ce mois.")
        return

    resume = (
        df.groupby("categorie")["montant"]
        .sum()
        .reindex(CATEGORIES_REVENUS, fill_value=0.0)
        .reset_index()
    )
    resume.columns = ["Catégorie", "Total (€)"]

    total = float(resume["Total (€)"].sum())

    st.dataframe(resume, use_container_width=True)
    st.markdown(f"### Total du mois : **{total:.2f} €**")

    st.divider()
    st.subheader("Graphiques")

    # Choix période
    periode = st.radio(
        "Période",
        ["Total", "12 derniers mois", "Dernier mois"],
        horizontal=True,
        key=f"{key_prefix}_periode",
    )

    # Courbe : total par mois
    df_mois = revenus_par_mois(conn, person_id).copy()
    if df_mois.empty:
        st.info("Pas assez de données pour afficher une courbe.")
        return

    df_mois["mois"] = pd.to_datetime(df_mois["mois"])
    df_mois = df_mois.sort_values("mois")

    if periode == "12 derniers mois":
        df_mois = df_mois.tail(12)
    elif periode == "Dernier mois":
        df_mois = df_mois.tail(1)

    df_courbe = df_mois.set_index("mois")[["total"]]
    df_courbe = df_courbe.rename(columns={"total": "Revenus"})

    st.line_chart(df_courbe, height=260)

    # Camembert : répartition du mois
    st.markdown("### Répartition du mois sélectionné")
    df_mois_detail = revenus_du_mois(conn, person_id, mois)

    if df_mois_detail.empty:
        st.info("Aucun revenu ce mois-ci.")
    else:
        repartition = (
            df_mois_detail.groupby("categorie")["montant"]
            .sum()
            .reindex(CATEGORIES_REVENUS, fill_value=0.0)
            .reset_index()
        )
        repartition.columns = ["Catégorie", "Montant"]
        repartition = repartition[repartition["Montant"] > 0]

        if repartition.empty:
            st.info("Aucun revenu ce mois-ci.")
        else:
            st.pyplot(_camembert(repartition))


def _camembert(df_repartition: pd.DataFrame):
    fig, ax = plt.subplots()
    ax.pie(
        df_repartition["Montant"],
        labels=df_repartition["Catégorie"],
        autopct="%1.1f%%",
        startangle=90,
    )
    ax.axis("equal")
    return fig
