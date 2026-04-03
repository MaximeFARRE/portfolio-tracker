import pandas as pd
from utils.validators import sens_flux


def solde_compte(tx_df: pd.DataFrame) -> float:
    """
    Solde = somme(amount * sens)
    amount est saisi positif, le type donne le sens.
    Version vectorisée (10-100x plus rapide que iterrows).
    """
    if tx_df.empty:
        return 0.0
    amounts = pd.to_numeric(tx_df["amount"], errors="coerce").fillna(0.0)
    signs = tx_df["type"].astype(str).map(lambda t: sens_flux(t))
    return float((amounts * signs).sum())


def cashflow_mois(tx_df: pd.DataFrame, annee: int, mois: int) -> float:
    if tx_df.empty:
        return 0.0
    df = tx_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[(df["date"].dt.year == annee) & (df["date"].dt.month == mois)]
    return solde_compte(df)
