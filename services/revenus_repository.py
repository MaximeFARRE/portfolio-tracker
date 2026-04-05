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
    Calcule le taux d'épargne mensuel sur les N derniers mois calendaires.

    Retourne un DataFrame avec les colonnes :
        mois          (str  'YYYY-MM-01')
        revenus       (float)
        depenses      (float)
        epargne       (float = revenus - depenses)
        taux_epargne  (float%, ou None si revenus == 0)

    Notes:
    - Les mois sans saisie sont conservés (revenus=0, depenses=0).
    - `end_month` ancre la fenêtre sur un mois précis (YYYY-MM-01) ;
      sinon on ancre sur le mois courant.
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

    # Outer join revenus/dépenses, puis normalisation mensuelle.
    df = pd.merge(df_rev, df_dep, on="mois", how="outer")
    df["revenus"] = pd.to_numeric(df["revenus"], errors="coerce")
    df["depenses"] = pd.to_numeric(df["depenses"], errors="coerce")
    df["revenus"] = df["revenus"].fillna(0.0).infer_objects(copy=False)
    df["depenses"] = df["depenses"].fillna(0.0).infer_objects(copy=False)
    df = df[df["mois"].notna()].copy()
    df["mois"] = df["mois"].astype(str)
    df["mois_dt"] = pd.to_datetime(df["mois"], errors="coerce")
    df = df.dropna(subset=["mois_dt"])
    if df.empty:
        df = pd.DataFrame(columns=["mois_dt", "revenus", "depenses"])
    else:
        df["mois_dt"] = df["mois_dt"].dt.to_period("M").dt.to_timestamp()
        # Sécurité si doublons de mois.
        df = (
            df.groupby("mois_dt", as_index=False)[["revenus", "depenses"]]
            .sum()
            .sort_values("mois_dt")
        )

    if end_month:
        end_ts = pd.to_datetime(end_month, errors="coerce")
        if pd.isna(end_ts):
            end_ts = pd.Timestamp.today()
    else:
        end_ts = pd.Timestamp.today()
    end_ts = pd.Timestamp(end_ts).to_period("M").to_timestamp()

    periods = max(int(n_mois), 1)
    full_idx = pd.date_range(end=end_ts, periods=periods, freq="MS")

    if df.empty:
        df = pd.DataFrame(index=full_idx, data={"revenus": 0.0, "depenses": 0.0})
        df.index.name = "mois_dt"
        df = df.reset_index()
    else:
        df = (
            df.set_index("mois_dt")
            .reindex(full_idx, fill_value=0.0)
            .rename_axis("mois_dt")
            .reset_index()
        )

    df["mois"] = df["mois_dt"].dt.strftime("%Y-%m-01")

    df["epargne"] = df["revenus"] - df["depenses"]
    df["taux_epargne"] = df.apply(
        lambda r: round(r["epargne"] / r["revenus"] * 100, 1) if r["revenus"] > 0 else None,
        axis=1,
    )

    return df[["mois", "revenus", "depenses", "epargne", "taux_epargne"]].reset_index(drop=True)
