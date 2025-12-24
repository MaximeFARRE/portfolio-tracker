import pandas as pd
from utils.validators import sens_flux


def solde_compte(tx_df: pd.DataFrame) -> float:
    """
    Solde = somme(amount * sens)
    amount est saisi positif, le type donne le sens.
    """
    if tx_df.empty:
        return 0.0
    s = 0.0
    for _, r in tx_df.iterrows():
        s += float(r["amount"]) * sens_flux(str(r["type"]))
    return float(s)


def cashflow_mois(tx_df: pd.DataFrame, annee: int, mois: int) -> float:
    if tx_df.empty:
        return 0.0
    df = tx_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[(df["date"].dt.year == annee) & (df["date"].dt.month == mois)]
    return solde_compte(df)
