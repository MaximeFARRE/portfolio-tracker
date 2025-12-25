import sqlite3
import pandas as pd


def ajouter_depense(conn: sqlite3.Connection, person_id: int, mois: str, categorie: str, montant: float):
    conn.execute(
        "INSERT INTO depenses (person_id, mois, categorie, montant) VALUES (?, ?, ?, ?)",
        (person_id, mois, categorie, montant),
    )
    conn.commit()


def depenses_du_mois(conn: sqlite3.Connection, person_id: int, mois: str) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT id, categorie, montant FROM depenses WHERE person_id = ? AND mois = ?",
        (person_id, mois),
    ).fetchall()

    if not rows:
        return pd.DataFrame(rows, columns=["id", "categorie", "montant"])


    return pd.DataFrame(rows, columns=["id", "categorie", "montant"])


def derniere_depense(conn: sqlite3.Connection, person_id: int, mois: str):
    row = conn.execute(
        """
        SELECT id, categorie, montant
        FROM depenses
        WHERE person_id = ? AND mois = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (person_id, mois),
    ).fetchone()
    return row  # None si vide


def supprimer_depense_par_id(conn: sqlite3.Connection, depense_id: int):
    conn.execute("DELETE FROM depenses WHERE id = ?", (depense_id,))
    conn.commit()

def maj_depense(conn: sqlite3.Connection, depense_id: int, categorie: str, montant: float):
    conn.execute(
        "UPDATE depenses SET categorie = ?, montant = ? WHERE id = ?",
        (categorie, montant, depense_id),
    )
    conn.commit()

def depenses_par_mois(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT mois, SUM(montant) as total
        FROM depenses
        WHERE person_id = ?
        GROUP BY mois
        ORDER BY mois
        """,
        (person_id,),
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["mois", "total"])

    return pd.DataFrame(rows, columns=["mois", "total"])
