"""
LEGACY - Streamlit uniquement.

Ce fichier n'est pas utilisé par l'application Desktop Qt.
Le chemin actif d'import Desktop est : ``qt_ui/pages/import_page.py``.

Conservé temporairement pour historique/migration ; ne pas utiliser pour le flux Qt.
"""

import streamlit as st
import pandas as pd

from utils.cache import cached_conn
from services.imports import import_wide_csv_to_monthly_table, import_bankin_csv
from services.credits import CreditParams, build_amortissement, replace_amortissement, upsert_credit

PEOPLE = ["Papa", "Maman", "Maxime", "Valentin"]

st.set_page_config(page_title="Import (Legacy Streamlit)", layout="wide")
st.title("Importer / Configurer (Legacy Streamlit)")
st.caption("Version legacy Streamlit. Pour l'app Desktop, utiliser l'écran Qt d'import.")

conn = cached_conn()
person = st.selectbox("Personne", PEOPLE)

mode = st.selectbox(
    "Type",
    ["Dépenses (mensuel)", "Revenus (mensuel)", "Bankin (transactions)", "Crédit (config + génération)"]
)

# -----------------------------------------
# DEPENSES / REVENUS (CSV wide mensuel)
# -----------------------------------------
if mode in ("Dépenses (mensuel)", "Revenus (mensuel)"):
    uploaded = st.file_uploader("Choisir un CSV", type=["csv"])
    table = "depenses" if mode.startswith("Dépenses") else "revenus"

    st.caption("Format attendu : Date | Catégories... | Total (Total ignoré).")
    delete_existing = st.checkbox("Remplacer les données existantes (cette personne)", value=True)

    if uploaded and st.button("Importer"):
        try:
            res = import_wide_csv_to_monthly_table(
                conn,
                table=table,
                person_name=person,
                file=uploaded,
                delete_existing=delete_existing,
            )
            st.success(f"Import OK ✅ {res['nb_lignes']} lignes insérées dans {res['table']}")
            st.write("Mois importés :", res["mois"])
            st.write("Catégories détectées :", res["categories"])
        except Exception as e:
            st.error(str(e))

# -----------------------------------------
# BANKIN (CSV transactions)
# -----------------------------------------
if mode == "Bankin (transactions)":
    uploaded = st.file_uploader("Choisir un CSV Bankin", type=["csv"])
    st.caption("Importe le CSV Bankin dans la table transactions (et optionnellement remplit depenses/revenus).")

    also_fill = st.checkbox("Créer aussi les totaux mensuels (depenses/revenus)", value=True)
    purge_tx = st.checkbox("Supprimer les anciennes transactions de cette personne", value=False)

    if uploaded and st.button("Importer Bankin"):
        try:
            res = import_bankin_csv(
                conn,
                person_name=person,
                file=uploaded,
                also_fill_monthly_tables=also_fill,
                purge_existing_transactions=purge_tx,
            )
            st.success(f"Import Bankin OK ✅ {res['transactions_inserted']} transactions ajoutées")
            st.write("Mois dépenses :", res["months_depenses"])
            st.write("Mois revenus :", res["months_revenus"])
            st.write("Catégories dépenses :", res["dep_categories"])
            st.write("Catégories revenus :", res["rev_categories"])
        except Exception as e:
            st.error(str(e))

# -----------------------------------------
# CREDIT (NO CSV) : fiche + génération amort.
# -----------------------------------------
if mode == "Crédit (config + génération)":
    st.caption("Tu renseignes la fiche crédit ici. L’amortissement est généré automatiquement (avec gestion du différé).")

    # person_id
    rowp = conn.execute("SELECT id FROM people WHERE name = ?", (person,)).fetchone()
    if not rowp:
        st.error("Personne introuvable dans la table people.")
        st.stop()
    person_id = int(rowp["id"])

    # Sélection sous-compte CREDIT
    df_credit = pd.read_sql_query(
        "SELECT id, name FROM accounts WHERE person_id = ? AND account_type = 'CREDIT' ORDER BY name",
        conn,
        params=[person_id],
    )

    if df_credit.empty:
        st.warning("Aucun sous-compte CREDIT. Crée-le d’abord dans Personnes → Ajouter un compte.")
        st.stop()

    df_credit["label"] = df_credit.apply(lambda r: f"{r['name']} (id={r['id']})", axis=1)
    choix = st.selectbox("Sous-compte crédit", df_credit["label"].tolist())
    account_id = int(choix.split("id=")[1].replace(")", "").strip())

    df_banque = pd.read_sql_query(
        "SELECT id, name FROM accounts WHERE person_id = ? AND account_type = 'BANQUE' ORDER BY name",
        conn,
        params=[person_id],
    )
    if df_banque.empty:
        st.warning("Aucun compte BANQUE trouvé. Crée un compte bancaire pour lier le prélèvement.")
        payer_account_id = None
    else:
        df_banque["label"] = df_banque.apply(lambda r: f"{r['name']} (id={r['id']})", axis=1)
        choix_payeur = st.selectbox("Compte bancaire payeur (prélèvement)", df_banque["label"].tolist())
        payer_account_id = int(choix_payeur.split("id=")[1].replace(")", "").strip())


    st.divider()
    st.subheader("Fiche crédit")

    c1, c2, c3 = st.columns(3)
    with c1:
        nom = st.text_input("Nom du crédit", value="Crédit")
        banque = st.text_input("Banque", value="")
        type_credit = st.selectbox("Type", ["immo", "conso", "auto", "etudiant", "autre"], index=1)
    with c2:
        capital_emprunte = st.number_input("Capital emprunté", value=0.0, step=1000.0)
        taux_nominal = st.number_input("Taux nominal (%)", value=0.0, step=0.01)
        taeg = st.number_input("TAEG (%)", value=0.0, step=0.01)
    with c3:
        duree_mois = st.number_input("Durée (mois)", value=1, step=1, min_value=1)
        mensualite_theorique = st.number_input("Mensualité théorique (hors assurance)", value=0.0, step=10.0)
        assurance_mensuelle = st.number_input("Assurance mensuelle", value=0.0, step=1.0)

    date_debut = st.date_input("Date de début", value=pd.Timestamp.today().date())
    actif = st.checkbox("Crédit actif", value=True)

    st.divider()
    st.subheader("Différé")

    d1, d2, d3 = st.columns(3)
    with d1:
        differe_mois = st.number_input("Différé (mois)", value=0, step=1, min_value=0)
        differe_type = st.selectbox("Type de différé", ["aucun", "partiel", "total"], index=0)
    with d2:
        assurance_pendant = st.checkbox("Assurance pendant différé", value=True)
        interets_diff = st.selectbox("Intérêts pendant différé", ["payes", "capitalises"], index=0)
    with d3:
        use_override = st.checkbox("Forcer la mensualité", value=False)
        mensualite_override = st.number_input("Mensualité forcée (hors assurance)", value=0.0, step=10.0)

    st.divider()

    # Bouton unique : enregistre fiche + génère amort.
    if st.button("Enregistrer + Générer amortissement"):
        # 1) fiche
        credit_id = upsert_credit(conn, {
            "person_id": person_id,
            "account_id": account_id,
            "nom": nom.strip(),
            "banque": banque.strip() or None,
            "type_credit": type_credit,
            "capital_emprunte": float(capital_emprunte),
            "taux_nominal": float(taux_nominal),
            "taeg": float(taeg),
            "duree_mois": int(duree_mois),
            "mensualite_theorique": float(mensualite_theorique),
            "assurance_mensuelle_theorique": float(assurance_mensuelle),
            "date_debut": str(date_debut),
            "actif": 1 if actif else 0,
            "payer_account_id": payer_account_id,

        })

        # 2) génération amortissement
        params = CreditParams(
            capital=float(capital_emprunte),
            taux_annuel=float(taux_nominal),
            duree_mois=int(duree_mois),
            date_debut=str(date_debut),
            assurance_mensuelle=float(assurance_mensuelle),
            differe_mois=int(differe_mois),
            differe_type=str(differe_type),
            assurance_pendant_differe=bool(assurance_pendant),
            interets_pendant_differe=str(interets_diff),
            mensualite=float(mensualite_override) if (use_override and mensualite_override > 0) else None
        )

        rows = build_amortissement(params)
        n = replace_amortissement(conn, credit_id, rows)

        st.success(f"Crédit enregistré ✅ | Amortissement généré ✅ ({n} lignes)")
        st.caption("Le coût réel mensuel se calcule via les transactions Bankin (catégorie échéance prêt / emprunt).")
