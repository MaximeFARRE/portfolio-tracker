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
from ui.depenses_scanner import onglet_depenses
from ui.revenus_scanner import onglet_revenus
from ui.sankey import afficher_sankey
from services.sankey import months_range, year_to_date_months
from services.credits import list_credits_by_person
from ui.credits_overview import afficher_credit_overview
from ui.private_equity_overview import afficher_private_equity_overview
from ui.compte_bourse import afficher_compte_bourse
from ui.entreprises_overview import afficher_entreprises_overview
from ui.liquidites_overview import afficher_liquidites_overview 
from ui.vue_ensemble_overview import afficher_vue_ensemble_overview
from utils.format_monnaie import money
from ui.bourse_global_overview import afficher_bourse_global_overview
from ui.projections_overview import afficher_projections_overview


st.set_page_config(page_title="Personnes", layout="wide")


def main():
    sidebar_personnes()

    conn = cached_conn()
    people = repo.list_people(conn)
    
    try:
        from ui.vue_ensemble_overview import ensure_daily_snapshots_for_all_people
        ensure_daily_snapshots_for_all_people(conn, mode="AUTO", force_refresh_prices=True)
    except Exception:
        pass


    st.title("Personnes")

    # --- Sélection personne (page unique) ---
    noms = people["name"].tolist()
    nom_personne = st.selectbox("Choisir une personne", noms)
    person_id = int(people.loc[people["name"] == nom_personne, "id"].iloc[0])

    tabs_fixes = st.tabs(["Vue d’ensemble", "Dépenses", "Revenus", "Crédit", "Private Equity", "Entreprises", "Liquidités", "Bourse", "📈 Projections"])

    with tabs_fixes[0]:
        afficher_vue_ensemble_overview(conn, person_id=person_id)

    with tabs_fixes[1]:
        onglet_depenses(conn, person_id=person_id, key_prefix=f"p{person_id}_dep")

    with tabs_fixes[2]:
        onglet_revenus(conn, person_id=person_id, key_prefix=f"p{person_id}_rev")

    with tabs_fixes[3]:
        afficher_credit_overview(conn, person_id=person_id)

    with tabs_fixes[4]:
        afficher_private_equity_overview(conn, person_id=person_id)
    
    with tabs_fixes[5]:
        afficher_entreprises_overview(conn, person_id=person_id)
        
    with tabs_fixes[6]:
        afficher_liquidites_overview(conn, person_id=person_id)
    
    with tabs_fixes[7]:
        afficher_bourse_global_overview(conn, person_id=person_id)

    with tabs_fixes[8]:
        afficher_projections_overview(conn, person_id=person_id)

    # --- Comptes dynamiques ---
    comptes = repo.list_accounts(conn, person_id=person_id)
    
    # ------------------------------------------------------------
    # BANQUE container : on masque les sous-comptes des onglets principaux
    # ------------------------------------------------------------
    try:
        sub_ids = repo.list_all_subaccount_ids(conn, person_id)
        if sub_ids:
            comptes = comptes[~comptes["id"].isin(sub_ids)].copy()
    except Exception:
        pass


    # --- KPIs simples V1 (basés sur les flux) ---
    tx_person = repo.list_transactions(conn, person_id=person_id, limit=5000)
    solde_global = calc.solde_compte(tx_person)

    aujourd_hui = pd.Timestamp.today()
    cashflow_mois = calc.cashflow_mois(tx_person, int(aujourd_hui.year), int(aujourd_hui.month))
    # Mois courant au format DB (YYYY-MM-01) pour le Sankey
    mois = f"{int(aujourd_hui.year):04d}-{int(aujourd_hui.month):02d}-01"

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

            if account_type == "CREDIT":
                from ui.credit_dashboard import afficher_dashboard_credit

                with col_g:
                    st.markdown("### Crédit")
                    afficher_dashboard_credit(conn, person_id=person_id, account_id=account_id)

                with col_d:
                    st.markdown("### Import / Modification")
                    st.info("Les paramètres du crédit se modifient dans Import → Crédit.")
                    st.caption("Les coûts mensuels réels viennent des transactions Bankin (catégorie échéance prêt / emprunt).")

                    # (optionnel) afficher quand même l’historique brut du compte CREDIT si tu en as
                    st.markdown("### Historique (compte)")
                    tableau_operations(tx_acc)

            else:
                if account_type == "BANQUE":
                    from ui.compte_banque import afficher_compte_banque

                    afficher_compte_banque(
                        conn,
                        person_id=person_id,
                        bank_account_id=account_id,
                        key_prefix=f"p{person_id}_a{account_id}_bank",
                    )
                
                elif account_type in {"PEA", "CTO", "CRYPTO"}:
                    afficher_compte_bourse(
                        conn,
                        person_id=person_id,
                        account_id=account_id,
                        account_type=account_type,
                        tx_acc=tx_acc,
                        key_prefix=f"p{person_id}_a{account_id}",
                    )
                else:
                    with col_g:
                        st.markdown("### Historique")
                        tableau_operations(tx_acc)

                    with col_d:
                        st.markdown("### Ajouter une opération (dans ce compte)")
                        bloc_saisie_operation(
                            conn,
                            person_id=person_id,
                            account_id=account_id,
                            account_type=account_type,
                            key_prefix=f"p{person_id}_a{account_id}",
                        )

                    
          
 

    # mois courant au format DB
    today = pd.Timestamp.today()
    mois_courant = f"{today.year:04d}-{today.month:02d}-01"
    mois_dernier = f"{(today - pd.DateOffset(months=1)).year:04d}-{(today - pd.DateOffset(months=1)).month:02d}-01"

    periode = st.selectbox(
        "Période du Sankey",
        ["Mois en cours", "Dernier mois", "3 derniers mois", "6 derniers mois", "12 derniers mois", "Année en cours"],
        index=0
    )

    if periode == "Mois en cours":
        mois_list = [mois_courant]
    elif periode == "Dernier mois":
        mois_list = [mois_dernier]
    elif periode == "3 derniers mois":
        mois_list = months_range(mois_courant, 3)
    elif periode == "6 derniers mois":
        mois_list = months_range(mois_courant, 6)
    elif periode == "12 derniers mois":
        mois_list = months_range(mois_courant, 12)
    else:  # Année en cours
        mois_list = year_to_date_months(mois_courant)

    afficher_sankey(conn, person_id=person_id, mois_list=mois_list, titre="Sankey — Cashflow")


    st.divider()
    st.caption("Note V1 : les soldes sont calculés à partir des opérations (flux). La valorisation automatique (cours) viendra plus tard.")


if __name__ == "__main__":
    main()
