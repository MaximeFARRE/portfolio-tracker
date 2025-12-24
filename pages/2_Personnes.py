import streamlit as st
import pandas as pd

from utils.cache import cached_conn
from services import repositories as repo
from services import calculations as calc
from utils.libelles import afficher_type_compte
from ui.compte_ajout import bloc_ajout_compte
from ui.compte_saisie import bloc_saisie_operation
from ui.compte_vue import tableau_operations
from ui.barre_navigation import sidebar_personnes

st.set_page_config(page_title="Personnes", layout="wide")


def main():
    sidebar_personnes()

    conn = cached_conn()
    people = repo.list_people(conn)

    st.title("Personnes")

    # --- Sélection personne (page unique) ---
    noms = people["name"].tolist()
    nom_personne = st.selectbox("Choisir une personne", noms)
    person_id = int(people.loc[people["name"] == nom_personne, "id"].iloc[0])

    # --- Comptes dynamiques ---
    comptes = repo.list_accounts(conn, person_id=person_id)

    # --- KPIs simples V1 (basés sur les flux) ---
    tx_person = repo.list_transactions(conn, person_id=person_id, limit=5000)
    solde_global = calc.solde_compte(tx_person)

    aujourd_hui = pd.Timestamp.today()
    cashflow_mois = calc.cashflow_mois(tx_person, int(aujourd_hui.year), int(aujourd_hui.month))

    c1, c2, c3 = st.columns(3)
    c1.metric("Solde global (flux)", f"{solde_global:,.2f} €".replace(",", " "))
    c2.metric("Cashflow du mois (flux)", f"{cashflow_mois:,.2f} €".replace(",", " "))
    c3.metric("Nombre d’opérations", str(len(tx_person)))

    st.divider()

    # --- Ajouter un compte ---
    bloc_ajout_compte(conn, person_id)

    st.divider()

    # --- Onglets = comptes ---
    if comptes.empty:
        st.info("Aucun compte. Ajoute un compte ci-dessus.")
        return

    # Ordre d'affichage : par type puis nom
    comptes = comptes.sort_values(["account_type", "name"]).reset_index(drop=True)

    labels_onglets = [
        f"{row['name']} ({afficher_type_compte(row['account_type'])})"
        for _, row in comptes.iterrows()
    ]

    tabs = st.tabs(labels_onglets)

    for i, tab in enumerate(tabs):
        with tab:
            account_id = int(comptes.loc[i, "id"])
            account_name = str(comptes.loc[i, "name"])
            account_type = str(comptes.loc[i, "account_type"])

            st.subheader(f"{account_name} — {afficher_type_compte(account_type)}")

            # --- Transactions du compte ---
            tx_acc = repo.list_transactions(conn, account_id=account_id, limit=2000)

            # --- Résumé simple (solde par flux) ---
            solde_acc = calc.solde_compte(tx_acc)
            st.caption(f"Solde du compte (flux) : **{solde_acc:,.2f} €**".replace(",", " "))

            col_g, col_d = st.columns([2, 1], gap="large")

            with col_g:
                st.markdown("### Historique")
                tableau_operations(tx_acc)

            with col_d:
                st.markdown("### Ajouter une opération (dans ce compte)")
                bloc_saisie_operation(conn, person_id=person_id, account_id=account_id, account_type=account_type, key_prefix=f"p{person_id}_a{account_id}")

    st.divider()
    st.caption("Note V1 : les soldes sont calculés à partir des opérations (flux). La valorisation automatique (cours) viendra plus tard.")


if __name__ == "__main__":
    main()
