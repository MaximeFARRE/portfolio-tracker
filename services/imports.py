# services/imports.py
import sqlite3
import pandas as pd


def _ensure_person(conn: sqlite3.Connection, person_name: str) -> int:
    row = conn.execute("SELECT id FROM people WHERE name = ?", (person_name,)).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])

    conn.execute("INSERT INTO people(name) VALUES (?)", (person_name,))
    conn.commit()
    row2 = conn.execute("SELECT id FROM people WHERE name = ?", (person_name,)).fetchone()
    return int(row2[0] if not hasattr(row2, "keys") else row2["id"])


def _read_clean_wide_csv(file) -> pd.DataFrame:
    # sep=None détecte automatiquement ; ou ,
    df = pd.read_csv(file, sep=None, engine="python")

    # Supprime les colonnes "Unnamed: X" (souvent générées par Excel)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]

    # Nettoie noms de colonnes
    df.columns = [str(c).strip() for c in df.columns]

    return df


def _to_float(x) -> float:
    if pd.isna(x):
        return 0.0
    s = str(x).strip()
    if s == "":
        return 0.0
    # gère la virgule décimale française
    s = s.replace(" ", "").replace("\u00A0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _month_key_from_date(date_value) -> str:
    # date_value peut être NaN, string, etc.
    if pd.isna(date_value):
        raise ValueError("Date manquante")

    s = str(date_value).strip()
    if s == "":
        raise ValueError("Date vide")

    # format attendu: 30/09/2025 (dd/mm/yyyy)
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.isna(d):
        raise ValueError(f"Date invalide: {s}")

    # On stocke le mois: YYYY-MM-01 (ton format DB)
    return f"{d.year:04d}-{d.month:02d}-01"


def import_wide_csv_to_monthly_table(
    conn: sqlite3.Connection,
    *,
    table: str,                 # "depenses" ou "revenus"
    person_name: str,
    file,                       # file uploader ou chemin
    date_col: str = "Date",
    ignore_cols=("Total",),
    delete_existing: bool = True,
    drop_zeros: bool = True,
):
    """
    CSV format attendu (wide):
    Date | Catégorie 1 | Catégorie 2 | ... | Total

    DB format (long):
    (person_id, mois, categorie, montant)
    """
    if table not in ("depenses", "revenus"):
        raise ValueError("table doit être 'depenses' ou 'revenus'")

    person_id = _ensure_person(conn, person_name)
    df = _read_clean_wide_csv(file)

    if date_col not in df.columns:
        raise ValueError(f"Colonne '{date_col}' introuvable. Colonnes: {list(df.columns)}")

    # Colonnes catégories = tout sauf Date et ignore_cols
    cat_cols = [c for c in df.columns if c != date_col and c not in ignore_cols]

    # Melt wide -> long
    long = df.melt(id_vars=[date_col], value_vars=cat_cols, var_name="categorie", value_name="montant")
    long["montant"] = long["montant"].apply(_to_float)

    if drop_zeros:
        long = long[long["montant"] != 0]

    # Convertit la date de fin de mois en clé mois YYYY-MM-01
    # Supprime les lignes sans date (NaN, vides)
    long = long.dropna(subset=[date_col])
    long = long[long[date_col].astype(str).str.strip() != ""]

    long["mois"] = long[date_col].apply(_month_key_from_date)

    # Option : on supprime l’existant pour cette personne (plus simple et safe)
    if delete_existing:
        conn.execute(f"DELETE FROM {table} WHERE person_id = ?", (person_id,))
        conn.commit()

    # Insert en masse
    rows = [(person_id, r["mois"], r["categorie"], float(r["montant"])) for _, r in long.iterrows()]

    conn.executemany(
        f"INSERT INTO {table} (person_id, mois, categorie, montant) VALUES (?, ?, ?, ?)",
        rows
    )
    conn.commit()

    return {
        "person_id": person_id,
        "table": table,
        "nb_lignes": len(rows),
        "categories": sorted(set(long["categorie"].tolist())),
        "mois": sorted(set(long["mois"].tolist())),
    }
