import streamlit as st
import pandas as pd

from utils.libelles import (
    LIBELLES_TYPE_OPERATION,
    code_operation_depuis_libelle,
)
from utils.validators import (
    operation_requiert_actif,
    operation_requiert_quantite_prix,
)
from services import repositories as repo
from utils.cache import reset_cache
from utils.format_monnaie import money, ccy_symbol

def r2(x):
    try:
        return round(float(x), 2)
    except:
        return x


def bloc_saisie_operation(conn, person_id: int, account_id: int, account_type: str, key_prefix: str):
    """
    Saisie contextualisée : on est déjà dans le bon compte.
    IMPORTANT : key_prefix doit être UNIQUE par compte (ex: "p1_a3").
    """

    st.markdown("### Saisie")
    acc = repo.get_account(conn, account_id)
    account_ccy = (acc["currency"] if acc and acc["currency"] else "EUR").upper()

    # ─────────────────────────────────────────────────────────────
    # 1) Types d'opérations proposés selon le type de compte
    # ─────────────────────────────────────────────────────────────
    if account_type == "BANQUE":
        types = ["DEPOT", "RETRAIT", "DEPENSE", "FRAIS", "IMPOT", "INTERETS"]
    elif account_type in {"PEA", "CTO", "CRYPTO"}:
        types = ["DEPOT", "RETRAIT", "ACHAT", "VENTE", "DIVIDENDE", "FRAIS", "INTERETS"]
    elif account_type == "IMMOBILIER":
        types = ["LOYER", "DEPENSE", "FRAIS", "IMPOT"]
    elif account_type == "CREDIT":
        types = ["REMBOURSEMENT_CREDIT", "INTERETS", "FRAIS"]
    else:
        types = ["DEPENSE", "FRAIS"]

    libelles = [LIBELLES_TYPE_OPERATION[t] for t in types]

    # ─────────────────────────────────────────────────────────────
    # 2) En-tête : type + date + frais
    # ─────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
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

    with col2:
        fees = st.number_input(
            "Frais (optionnel)",
            min_value=0.0,
            value=0.0,
            step=0.5,
            key=f"{key_prefix}_fees",
        )

    st.divider()

    # ─────────────────────────────────────────────────────────────
    # 3) Actif (si requis) : choisir un ticker existant OU en créer un
    # ─────────────────────────────────────────────────────────────
    if operation_requiert_actif(type_op):
        st.markdown("#### Actif")

        actifs = repo.list_assets(conn)
        symboles = actifs["symbol"].tolist() if not actifs.empty else []

        k_asset_mode = f"{key_prefix}_asset_mode_v2"
        k_asset_existing = f"{key_prefix}_asset_existing_v2"
        k_asset_new_symbol = f"{key_prefix}_asset_new_symbol_v2"
        k_asset_new_name = f"{key_prefix}_asset_new_name_v2"
        k_asset_new_type = f"{key_prefix}_asset_new_type_v2"

        mode = st.radio(
            "Mode",
            ["Choisir un actif existant", "Créer un nouvel actif"],
            horizontal=True,
            key=k_asset_mode,
        )

        if mode == "Choisir un actif existant":
            if not symboles:
                st.warning("Aucun actif existant. Crée un actif.")
            else:
                symbole = st.selectbox("Ticker", symboles, key=k_asset_existing)
                row = repo.get_asset_by_symbol(conn, symbole)
                if row:
                    asset_id = int(row["id"])
                    st.session_state[f"{key_prefix}_asset_id_v2"] = asset_id
                    st.caption(f"{row['symbol']} — {row['name']}")
                else :
                    st.error("Actif introuvable en base.")  
                    st.session_state[f"{key_prefix}_asset_id_v2"] = None
                    
        else:
            colA, colB = st.columns(2)
            with colA:
                symbole_new = st.text_input(
                    "Ticker / Symbole",
                    placeholder="AAPL, CW8, BTC-USD...",
                    key=k_asset_new_symbol,
                ).strip().upper()
            with colB:
                nom_new = st.text_input(
                    "Nom",
                    value=symbole_new,
                    placeholder="Apple Inc.",
                    key=k_asset_new_name,
                )

            type_new = st.selectbox(
                "Type d’actif",
                ["action", "etf", "crypto", "private_equity", "autre"],
                key=k_asset_new_type,
            )

        st.divider()


    # ─────────────────────────────────────────────────────────────
    # 4) Champs selon type d’opération
    # ─────────────────────────────────────────────────────────────
    
    asset_id = None
    symbole_new = ""
    nom_new = ""
    type_new = "action"
  
    quantity = None
    price = None
    montant = None

    if operation_requiert_quantite_prix(type_op):
        st.markdown("#### Achat / Vente (champs liés)")

        # Keys V2 pour éviter tout conflit avec les anciennes keys
        k_mode = f"{key_prefix}_mode_calc_v2"
        k_qty = f"{key_prefix}_qty_v2"
        k_price = f"{key_prefix}_price_v2"
        k_total = f"{key_prefix}_total_v2"

        mode_calc = st.radio(
            "Mode de saisie",
            ["Quantité + Prix → Montant", "Quantité + Montant → Prix"],
            horizontal=True,
            key=k_mode,
        )

        # Init state
        if k_qty not in st.session_state:
            st.session_state[k_qty] = 1.0
        if k_price not in st.session_state:
            st.session_state[k_price] = 0.0
        if k_total not in st.session_state:
            st.session_state[k_total] = 0.0

        def sync_from_qty_price():
            qty = float(st.session_state.get(k_qty, 0.0) or 0.0)
            price = float(st.session_state.get(k_price, 0.0) or 0.0)
            total = qty * price  # HORS frais
            st.session_state[k_total] = round(total, 2)

        def sync_from_qty_total():
            qty = float(st.session_state.get(k_qty, 0.0) or 0.0)
            total = float(st.session_state.get(k_total, 0.0) or 0.0)
            if qty <= 0:
                st.session_state[k_price] = 0.0
                return
            price = total / qty  # HORS frais
            if price < 0:
                price = 0.0
            st.session_state[k_price] = round(price, 2)

        c1, c2, c3 = st.columns(3)

        with c1:
            st.number_input(
                "Quantité",
                min_value=0.0,
                step=1.0,
                key=k_qty,
                on_change=sync_from_qty_price if mode_calc.startswith("Quantité + Prix") else sync_from_qty_total,
            )

        with c2:
            st.number_input(
                "Prix unitaire",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key=k_price,
                disabled=mode_calc.startswith("Quantité + Montant"),
                on_change=sync_from_qty_price,
            )

        with c3:
            st.number_input(
                "Montant total (hors frais)",
                step=0.01,
                format="%.2f",
                key=k_total,
                disabled=mode_calc.startswith("Quantité + Prix"),
                on_change=sync_from_qty_total,
                help="Montant total HORS frais. Les frais sont saisis séparément.",
            )

        quantity = float(st.session_state.get(k_qty, 0.0) or 0.0)
        price = float(st.session_state.get(k_price, 0.0) or 0.0)
        montant = float(st.session_state.get(k_total, 0.0) or 0.0)

        st.caption(f"Hors frais : {quantity:g} × {price:.2f} = {money(montant, account_ccy)} — Frais : {money(fees, account_ccy)}")

    else:
        # Pour les opérations sans qty/prix (dividende, frais, intérêts, etc.)
        montant = st.number_input(
        f"Montant ({account_ccy})",
        value=0.0,
        step=10.0,
        key=f"{key_prefix}_amount",
        help="Montant positif. Le sens (entrée/sortie) est géré par le type d’opération.",
    )


    # Catégorie / Note supprimées (V1)
    categorie = None
    note = None

    st.divider()

    # ─────────────────────────────────────────────────────────────
    # 5) Enregistrement
    # ─────────────────────────────────────────────────────────────
    if st.button("Enregistrer l’opération", key=f"{key_prefix}_save", use_container_width=True):

        # Si création nouvel actif : on le crée ici
        if operation_requiert_actif(type_op):
            asset_id = st.session_state.get(f"{key_prefix}_asset_id_v2", asset_id)
            mode = st.session_state.get(f"{key_prefix}_asset_mode_v2", "Choisir un actif existant")

            if mode == "Créer un nouvel actif":
                symbole_new = st.session_state.get(f"{key_prefix}_asset_new_symbol_v2", "").strip().upper()
                nom_new = st.session_state.get(f"{key_prefix}_asset_new_name_v2", symbole_new)
                type_new = st.session_state.get(f"{key_prefix}_asset_new_type_v2", "action")

                if not symbole_new:
                    st.error("Ticker / Symbole obligatoire pour créer un actif.")
                    return

                row = repo.get_asset_by_symbol(conn, symbole_new)
                if not row:
                    repo.create_asset(conn, symbole_new, (nom_new or symbole_new), type_new, "EUR")
                    row = repo.get_asset_by_symbol(conn, symbole_new)

                asset_id = int(row["id"]) if row else None


        # Validations minimales
        if operation_requiert_actif(type_op) and not asset_id:
            st.error("Ce type d’opération nécessite un actif.")
            return

        if operation_requiert_quantite_prix(type_op):
            if quantity is None or quantity <= 0:
                st.error("Achat/Vente nécessite une quantité > 0.")
                return
            if price is None or price <= 0:
                st.error("Achat/Vente nécessite un prix unitaire > 0.")
                return

        data = {
            "date": str(date),
            "person_id": person_id,
            "account_id": account_id,
            "type": type_op,
            "asset_id": asset_id,
            "quantity": round(float(quantity), 2) if quantity is not None else None,
            "price": round(float(price), 2) if price is not None else None,
            "fees": round(float(fees), 2),
            "amount": round(float(montant), 2) if montant is not None else 0.0,
            "category": (categorie or None),
            "note": (note or None),
        }

        repo.create_transaction(conn, data)
        st.success("Opération enregistrée ✅")

        reset_cache()
        st.rerun()
