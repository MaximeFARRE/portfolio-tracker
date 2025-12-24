import streamlit as st
from utils.cache import cached_conn
from services import repositories as repo


def sidebar_personnes():
    st.sidebar.title("StreamUnit")

    conn = cached_conn()
    people = repo.list_people(conn)

    st.sidebar.subheader("Navigation")
    st.sidebar.page_link("pages/1_Famille.py", label="Vue d’ensemble famille", icon="🏠")

    st.sidebar.subheader("Personnes")
    for _, r in people.iterrows():
        st.sidebar.page_link("pages/2_Personnes.py", label=r["name"], icon="👤")
