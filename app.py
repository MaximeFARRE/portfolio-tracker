import streamlit as st
from utils.cache import cached_conn

# Initialise DB + seed au démarrage (sans afficher de page)
cached_conn()

st.set_page_config(page_title="StreamUnit", layout="wide")

st.title("StreamUnit")

st.write("Utilise le menu à gauche pour naviguer :")
st.write("- Vue d’ensemble famille")
st.write("- Personnes (Papa, Maman, Maxime, Valentin)")
st.write("")
st.info("V1 : saisie manuelle par compte, sans connexion automatique.")
