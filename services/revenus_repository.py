import sqlite3
import pandas as pd


def ajouter_revenu(conn: sqlite3.Connection, person_id: int, mois: str, categorie: str, montant: float):
    conn.execute(
        "INSERT INTO revenus (person_id, mois, categorie, montant) VALUES (?, ?, ?, ?)",
        (person_id, mois, categorie, montant),
    )
    conn.commit()


def revenus_du_mois(conn: sqlite3.Connection, person_id: int, mois: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT id, categorie, montant FROM revenus WHERE person_id = ? AND mois = ?",
        (person_id, mois),
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["id", "categorie", "montant"])

    return pd.DataFrame(rows, columns=["id", "categorie", "montant"])


def dernier_revenu(conn: sqlite3.Connection, person_id: int, mois: str):
    row = conn.execute(
        """
        SELECT id, categorie, montant
        FROM revenus
        WHERE person_id = ? AND mois = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (person_id, mois),
    ).fetchone()
    return row  # None si vide


def supprimer_revenu_par_id(conn: sqlite3.Connection, revenu_id: int):
    conn.execute("DELETE FROM revenus WHERE id = ?", (revenu_id,))
    conn.commit()


def maj_revenu(conn: sqlite3.Connection, revenu_id: int, categorie: str, montant: float):
    conn.execute(
        "UPDATE revenus SET categorie = ?, montant = ? WHERE id = ?",
        (categorie, montant, revenu_id),
    )
    conn.commit()


def revenus_par_mois(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT mois, SUM(montant) as total
        FROM revenus
        WHERE person_id = ?
        GROUP BY mois
        ORDER BY mois
        """,
        (person_id,),
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["mois", "total"])

    return pd.DataFrame(rows, columns=["mois", "total"])


def compute_taux_epargne_mensuel(
    conn,
    person_id: int,
    n_mois: int = 24,
    end_month: str | None = None,
) -> pd.DataFrame:
    """
    [DEPRECATED] Calcule le taux d'épargne mensuel.
    Ceci est désormais un wrapper vers `services.cashflow.get_person_monthly_savings_series`.
    """
    from services.cashflow import get_person_monthly_savings_series
    return get_person_monthly_savings_series(
        conn,
        person_id,
        n_mois=n_mois,
        end_month=end_month,
    )
