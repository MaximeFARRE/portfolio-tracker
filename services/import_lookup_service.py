"""
Lookups utilisés par la page d'import : personnes et comptes.
Centralise les requêtes de résolution nom→id et filtrage de comptes
afin que la UI n'exécute plus de SQL directement.
"""
import logging
import pandas as pd
from services import repositories as repo

logger = logging.getLogger(__name__)


def get_person_id_by_name(conn, name: str, people_df: pd.DataFrame | None = None) -> int | None:
    """
    Retourne l'id de la personne dont le nom correspond exactement à `name`.
    Retourne None si la personne est introuvable.
    """
    df = people_df if people_df is not None else repo.list_people(conn)
    if df is None or df.empty:
        logger.warning("get_person_id_by_name: aucune personne en base.")
        return None
    match = df[df["name"] == name]
    if match.empty:
        logger.warning("get_person_id_by_name: personne '%s' introuvable.", name)
        return None
    return int(match.iloc[0]["id"])


def list_accounts_by_types(
    conn,
    person_id: int,
    account_types: list[str],
    accounts_df: pd.DataFrame | None = None,
) -> list[dict]:
    """
    Retourne les comptes d'une personne filtrés par types (ex. ['PEA', 'CTO']).
    Chaque dict contient : id, name, account_type.
    Résultat trié par account_type puis name.
    """
    df = accounts_df if accounts_df is not None else repo.list_accounts(conn, person_id=person_id)
    if df is None or df.empty:
        return []
    types_upper = [t.upper() for t in account_types]
    mask = df["account_type"].astype(str).str.upper().isin(types_upper)
    filtered = df[mask].sort_values(["account_type", "name"])
    return filtered[["id", "name", "account_type"]].to_dict(orient="records")
