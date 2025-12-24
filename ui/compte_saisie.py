import streamlit as st
import pandas as pd

from utils.libelles import (
    LIBELLES_TYPE_OPERATION,
    CATEGORIES_DEPENSES,
    code_operation_depuis_libelle,
)
from utils.validators import (
    operation_requiert_actif,
    operation_requiert_quantite_prix,
)
from services import repositories as repo
from utils.cache import reset_cache


def bloc_saisie_operation(conn, person_id: int, account_id: int, account_type: str, key_prefix: str):
    """
    Saisie contextualisée : on est déjà dans le bon compte.
    IMPORTANT : key_prefix doit être UNIQUE par compte (ex: "p1_a3").
    """

    st.markdown("### Saisie")

    # Types d'opérations proposés selon le type de compte
    if account_type == "BANQUE":
        types = ["DEPOT", "RETRAIT", "DEPENSE", "FRAIS", "IMPOT", "INTERETS"]
    elif account_type in {"PEA", "CTO", "CRYPTO"}:
        types = ["ACHAT", "VENTE", "DIVIDENDE", "FRAIS"]
    elif account_type == "IMMOBILIER":
        types = ["LOYER", "DEPENSE", "FRAIS", "IMPOT"]
    elif account_type == "CREDIT":
        types = ["REMBOURSEMENT_CREDIT", "INTERETS", "FRAIS"]
    else:
        types = ["DEPENSE", "FRAIS"]

    libelles = [LIBELLES_TYPE_OPERATION[t] for t in types]

    libelle_type = st.selectbox(
        "Type d’opération",
        libelles,
        key=f"{key_prefix}_type",
    )
    type_op = code_operation_depuis_libelle(libelle_type)

    date = st.date_input(
        "Date",
        value=pd.Timestamp.today().date(),
        key=f"{key_prefix}_date",
    )

    # Catégorie (utile surtout pour dépenses/frais/impôts)
    if type_op in {"DEPENSE", "FRAIS", "IMPOT"}:
        categorie = st.selectbox(
            "Catégorie",
            [""] + CATEGORIES_DEPENSES,
            key=f"{key_prefix}_categorie",
        )
    else:
        categorie = st.text_input(
            "Catégorie (optionnel)",
            value="",
            key=f"{key_prefix}_categorie_txt",
        )

    note = st.text_input(
        "Note (optionnel)",
        value="",
        key=f"{key_prefix}_note",
    )

    fees = st.number_input(
        "Frais",
        min_value=0.0,
        value=0.0,
        step=1.0,
        key=f"{key_prefix}_fees",
    )

    # Actif si requis
    asset_id = None
    quantity = None
    price = None

    if operation_requiert_actif(type_op):
        st.markdown("#### Actif")

        actifs = repo.list_assets(conn)
        symboles = actifs["symbol"].tolist() if not actifs.empty else []

        choix = st.selectbox(
            "Actif existant (optionnel)",
            [""] + symboles,
            key=f"{key_prefix}_asset_pick",
        )

        symbole = st.text_input(
            "Symbole (ex : CW8, AAPL, BTC)",
            value=choix,
            key=f"{key_prefix}_asset_sym",
        ).strip().upper()

        row = repo.get_asset_by_symbol(conn, symbole) if symbole else None

        if row:
            st.success(f"Actif : {row['symbol']} — {row['name']}")
            asset_id = int(row["id"])
        elif symbole:
            st.warning("Actif inconnu.")
            with st.expander("Créer cet actif"):
                nom_actif = st.text_input(
                    "Nom de l’actif",
                    value=symbole,
                    key=f"{key_prefix}_asset_name",
                )
                type_actif = st.selectbox(
                    "Type d’actif",
                    ["action", "etf", "crypto", "private_equity", "autre"],
                    key=f"{key_prefix}_asset_type",
                )
                if st.button("Créer l’actif", key=f"{key_prefix}_asset_create_btn"):
                    repo.create_asset(conn, symbole, nom_actif, type_actif, "EUR")
                    st.success("Actif créé ✅")
                    reset_cache()
                    st.rerun()

    # Quantité / prix si requis
    if operation_requiert_quantite_prix(type_op):
        st.markdown("#### Quantité et prix")

        quantity = st.number_input(
            "Quantité",
            value=1.0,
            step=1.0,
            key=f"{key_prefix}_qty",
        )
        price = st.number_input(
            "Prix unitaire",
            value=0.0,
            step=1.0,
            key=f"{key_prefix}_price",
        )

        montant_calcule = 0.0
        if quantity and price and price > 0:
            montant_calcule = float(quantity) * float(price) + float(fees)

        st.caption(f"Montant calculé : {montant_calcule:.2f} €")

        # Préremplissage PAR COMPTE (clé session_state unique)
        prefill_key = f"{key_prefix}_montant_prefill"
        if st.button("Utiliser le montant calculé", key=f"{key_prefix}_use_calc"):
            st.session_state[prefill_key] = montant_calcule
            st.rerun()

    # Montant (toujours requis)
    prefill_key = f"{key_prefix}_montant_prefill"
    montant_defaut = float(st.session_state.get(prefill_key, 0.0))

    montant = st.number_input(
        "Montant (positif)",
        value=montant_defaut,
        step=10.0,
        key=f"{key_prefix}_amount",
        help="Saisis un montant positif. Le sens (entrée/sortie) est géré par le type d’opération.",
    )

    # Bouton d'enregistrement
    if st.button("Enregistrer l’opération", key=f"{key_prefix}_save"):
        # Validations minimales
        if operation_requiert_actif(type_op) and not asset_id:
            st.error("Ce type d’opération nécessite un actif.")
            return
        if operation_requiert_quantite_prix(type_op) and (quantity is None or quantity == 0):
            st.error("Achat/Vente nécessite une quantité non nulle.")
            return

        data = {
            "date": str(date),
            "person_id": person_id,
            "account_id": account_id,
            "type": type_op,
            "asset_id": asset_id,
            "quantity": float(quantity) if quantity is not None else None,
            "price": float(price) if price is not None else None,
            "fees": float(fees),
            "amount": float(montant),
            "category": (categorie or None),
            "note": (note or None),
        }

        repo.create_transaction(conn, data)
        st.success("Opération enregistrée ✅")

        # Nettoyage du préremplissage (par compte)
        if prefill_key in st.session_state:
            del st.session_state[prefill_key]

        reset_cache()
        st.rerun()
