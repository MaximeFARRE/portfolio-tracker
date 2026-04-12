import pandas as pd

PAGE_SIZE = 50


def paginate_df(df: pd.DataFrame, page: int = 0, page_size: int = PAGE_SIZE) -> pd.DataFrame:
    """
    Retourne une tranche paginée du DataFrame sans dépendance UI.

    Cette fonction remplace l'ancien helper Streamlit pour éviter toute
    dépendance `streamlit` hors dossier `legacy/`.
    """
    if df is None or df.empty:
        return df

    size = max(1, int(page_size))
    total = len(df)
    n_pages = max(1, (total - 1) // size + 1)
    page_idx = max(0, min(int(page), n_pages - 1))
    start = page_idx * size
    return df.iloc[start: start + size]
