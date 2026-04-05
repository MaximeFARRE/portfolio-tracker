import streamlit as st
import pandas as pd

from utils.cache import cached_conn
from services import repositories as repo
from services import calculations as calc
from ui.barre_navigation import sidebar_personnes

# --- nouveaux onglets (imports additifs, safe)
try:
    from ui.famille_dashboard import afficher_famille_dashboard
except Exception:
    afficher_famille_dashboard = None

try:
    from ui.data_health import afficher_data_health
except Exception:
    afficher_data_health = None


st.set_page_config(page_title="Famille", layout="wide")


def main():
    sidebar_personnes()
    conn = cached_conn()

    st.title("Vue d’ensemble — Famille")

    tab_weekly, tab_debug, tab_flux = st.tabs(
        ["👨‍👩‍👧‍👦 Snapshots weekly", "🛠️ Diagnostic", "📒 Flux (V1)"]
    )

    # --- Weekly Famille
    with tab_weekly:
        if afficher_famille_dashboard is None:
            st.info("Dashboard famille weekly non disponible (ui/famille_dashboard.py).")
        else:
            afficher_famille_dashboard(conn)

    # --- Debug
    with tab_debug:
        if afficher_data_health is None:
            st.info("UI diagnostic non disponible (ui/data_health.py).")
        else:
            afficher_data_health(conn)

    # --- Flux (ton code actuel, inchangé)
    with tab_flux:
        people = repo.list_people(conn)
        accounts = repo.list_accounts(conn)
        tx_all = repo.list_transactions(conn, limit=20000)

        if people.empty:
            st.error("Aucune personne en base.")
            return

        solde_total = calc.solde_compte(tx_all)

        today = pd.Timestamp.today()
        cashflow_mois = calc.cashflow_mois(tx_all, int(today.year), int(today.month))

        c1, c2, c3 = st.columns(3)
        c1.metric("Solde famille (flux)", f"{solde_total:,.2f} €".replace(",", " "))
        c2.metric("Cashflow du mois (flux)", f"{cashflow_mois:,.2f} €".replace(",", " "))
        c3.metric("Nombre d’opérations", str(len(tx_all)))

        st.divider()

        st.subheader("Répartition par personne")

        lignes = []
        for _, p in people.iterrows():
            pid = int(p["id"])
            nom = str(p["name"])
            tx_p = tx_all[tx_all["person_id"] == pid].copy() if not tx_all.empty else pd.DataFrame()
            solde_p = calc.solde_compte(tx_p)
            lignes.append({"Personne": nom, "Solde (flux)": solde_p, "Opérations": len(tx_p)})

        df_people = pd.DataFrame(lignes).sort_values("Solde (flux)", ascending=False)
        st.dataframe(df_people, use_container_width=True)

        st.divider()

        st.subheader("Comptes — aperçu")

        if accounts.empty:
            st.info("Aucun compte pour l’instant.")
            return

        lignes_c = []
        for _, a in accounts.iterrows():
            acc_id = int(a["id"])
            acc_name = str(a["name"])
            pid = int(a["person_id"])
            person_name = str(people.loc[people["id"] == pid, "name"].iloc[0])

            tx_c = tx_all[tx_all["account_id"] == acc_id].copy() if not tx_all.empty else pd.DataFrame()
            solde_c = calc.solde_compte(tx_c)

            lignes_c.append({
                "Personne": person_name,
                "Compte": acc_name,
                "Solde (flux)": solde_c,
                "Opérations": len(tx_c)
            })

        df_accounts = pd.DataFrame(lignes_c).sort_values("Solde (flux)", ascending=False)
        st.dataframe(df_accounts, use_container_width=True)

        st.divider()

        st.subheader("Dernières opérations")

        if tx_all.empty:
            st.info("Aucune opération enregistrée.")
            return

        cols = ["date", "person_name", "account_name", "type", "asset_symbol", "amount", "fees", "category", "note", "id"]
        cols = [c for c in cols if c in tx_all.columns]
        df_last = tx_all[cols].head(50).copy()

        df_last = df_last.rename(columns={
            "date": "Date",
            "person_name": "Personne",
            "account_name": "Compte",
            "type": "Type",
            "asset_symbol": "Actif",
            "amount": "Montant",
            "fees": "Frais",
            "category": "Catégorie",
            "note": "Note",
            "id": "Identifiant"
        })

        st.dataframe(df_last, use_container_width=True)

        st.caption("Note V1 : cette vue est basée sur les flux (opérations). La valorisation (cours) viendra plus tard.")


if __name__ == "__main__":
    main()
