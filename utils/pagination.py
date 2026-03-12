import streamlit as st
import pandas as pd

PAGE_SIZE = 50


def paginate_df(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """
    Affiche les contrôles de pagination et retourne la tranche courante du DataFrame.
    key : clé unique pour le composant (ex: "bourse_ops", "banque_tx").
    """
    total = len(df)
    if total == 0:
        return df

    n_pages = max(1, (total - 1) // PAGE_SIZE + 1)

    if f"page_{key}" not in st.session_state:
        st.session_state[f"page_{key}"] = 0

    page = st.session_state[f"page_{key}"]
    # clamp au cas où le df se réduit
    page = max(0, min(page, n_pages - 1))
    st.session_state[f"page_{key}"] = page

    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if st.button("◀ Précédent", key=f"prev_{key}", disabled=(page == 0)):
            st.session_state[f"page_{key}"] = page - 1
            st.rerun()
    with col2:
        start_row = page * PAGE_SIZE + 1
        end_row = min((page + 1) * PAGE_SIZE, total)
        st.caption(f"Page **{page + 1}** / {n_pages}  •  lignes {start_row}–{end_row} sur {total}")
    with col3:
        if st.button("Suivant ▶", key=f"next_{key}", disabled=(page >= n_pages - 1)):
            st.session_state[f"page_{key}"] = page + 1
            st.rerun()

    start = page * PAGE_SIZE
    return df.iloc[start: start + PAGE_SIZE]
