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
) -> pd.DataFrame:
    """
    Calcule le taux d'épargne mensuel sur les N derniers mois avec données.

    Retourne un DataFrame avec les colonnes :
        mois          (str  'YYYY-MM-01')
        revenus       (float)
        depenses      (float)
        epargne       (float = revenus - depenses)
        taux_epargne  (float%, ou None si revenus == 0)
    """
    df_rev = revenus_par_mois(conn, person_id)
    df_dep = pd.read_sql_query(
        """
        SELECT mois, SUM(montant) as total
        FROM depenses
        WHERE person_id = ?
        GROUP BY mois
        ORDER BY mois
        """,
        conn,
        params=(int(person_id),),
    )

    df_rev = df_rev.rename(columns={"total": "revenus"})
    df_dep = df_dep.rename(columns={"total": "depenses"})

    # Outer join : garde les mois avec revenus OU dépenses
    # On remplit colonne par colonne pour éviter le FutureWarning de pandas sur le
    # downcasting silencieux de fillna() appliqué à un DataFrame entier (objet dtype).
    df = pd.merge(df_rev, df_dep, on="mois", how="outer")
    df["revenus"] = df["revenus"].fillna(0.0)
    df["depenses"] = df["depenses"].fillna(0.0)
    df = df.infer_objects(copy=False)
    df = df[df["mois"].notna()].copy()
    df["mois"] = df["mois"].astype(str)
    df = df.sort_values("mois")

    # Uniquement les mois avec au moins une donnée, derniers N seulement
    df = df[(df["revenus"] > 0) | (df["depenses"] > 0)].tail(n_mois)

    df["epargne"] = df["revenus"] - df["depenses"]
    df["taux_epargne"] = df.apply(
        lambda r: round(r["epargne"] / r["revenus"] * 100, 1) if r["revenus"] > 0 else None,
        axis=1,
    )

    return df.reset_index(drop=True)
