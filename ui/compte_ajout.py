import streamlit as st
from utils.libelles import TYPES_COMPTE, afficher_type_compte
from services import repositories as repo
from utils.cache import reset_cache


def bloc_ajout_compte(conn, person_id: int):
    with st.expander("➕ Ajouter un compte", expanded=False):
        col1, col2 = st.columns([2, 1])
        with col1:
            nom = st.text_input("Nom du compte (ex : BNP, Caisse d’Épargne, PEA Bourso)")
        with col2:
            devise = st.selectbox("Devise", ["EUR", "USD", "CHF"], index=0)

        type_code = st.selectbox(
            "Type de compte",
            TYPES_COMPTE,
            format_func=afficher_type_compte
        )
        institution = st.text_input("Institution (optionnel)")

        if st.button("Créer le compte"):
            if not nom.strip():
                st.error("Le nom du compte est obligatoire.")
                return
            repo.create_account(conn, person_id, nom.strip(), type_code, institution.strip() or None, devise)
            st.success("Compte créé ✅")
            reset_cache()
            st.rerun()
