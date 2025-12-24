import streamlit as st
import pandas as pd
from utils.libelles import afficher_type_operation
from utils.format_monnaie import eur


def tableau_operations(tx_df: pd.DataFrame):
    if tx_df.empty:
        st.info("Aucune opération sur ce compte pour l’instant.")
        return

    df = tx_df.copy()
    df["type"] = df["type"].apply(afficher_type_operation)

    colonnes = ["date", "type", "asset_symbol", "amount", "fees", "category", "note", "id"]
    colonnes = [c for c in colonnes if c in df.columns]
    df = df[colonnes].rename(columns={
        "date": "Date",
        "type": "Type",
        "asset_symbol": "Actif",
        "amount": "Montant",
        "fees": "Frais",
        "category": "Catégorie",
        "note": "Note",
        "id": "Identifiant"
    })

    st.dataframe(df, use_container_width=True)


def bloc_suppression(conn, tx_df: pd.DataFrame, delete_fn):
    st.markdown("#### Supprimer une opération")
    if tx_df.empty:
        st.caption("Rien à supprimer.")
        return

    small = tx_df.head(80).copy()
    small["type_fr"] = small["type"].apply(afficher_type_operation)
    small["label"] = small.apply(
        lambda r: f"#{r['id']} | {r['date']} | {r['type_fr']} | {r.get('asset_symbol','')} | {r.get('amount',0)}",
        axis=1
    )
    choix = st.selectbox("Choisir", [""] + small["label"].tolist())
    if choix:
        tx_id = int(choix.split("|")[0].replace("#", "").strip())
        if st.button("Confirmer la suppression"):
            delete_fn(conn, tx_id)
            st.success("Opération supprimée ✅")
            st.rerun()
