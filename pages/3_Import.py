import streamlit as st
from services.imports import import_wide_csv_to_monthly_table
from services.db import get_conn  # adapte si ta fonction s'appelle autrement

PEOPLE = ["Papa", "Maman", "Maxime", "Valentin"]

st.title("Importer des données (CSV)")

conn = get_conn()

person = st.selectbox("Personne", PEOPLE)
module = st.selectbox("Type d'import", ["Dépenses", "Revenus"])
table = "depenses" if module == "Dépenses" else "revenus"

st.caption("Format attendu : Date | Catégories... | Total (Total ignoré).")

uploaded = st.file_uploader("Choisir un CSV", type=["csv"])

delete_existing = st.checkbox("Remplacer les données existantes de cette personne", value=True)

if uploaded and st.button("Importer"):
    try:
        result = import_wide_csv_to_monthly_table(
            conn,
            table=table,
            person_name=person,
            file=uploaded,
            delete_existing=delete_existing,
        )
        st.success(f"Import OK ✅ {result['nb_lignes']} lignes insérées dans {result['table']}")
        st.write("Mois importés :", result["mois"])
        st.write("Catégories détectées :", result["categories"])
    except Exception as e:
        st.error(str(e))
