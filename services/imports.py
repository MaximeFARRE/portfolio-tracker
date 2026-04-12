# services/imports.py
import logging
import sqlite3
import pandas as pd

_logger = logging.getLogger(__name__)


def _ensure_person(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO people(name) VALUES (?)", (name,))
    conn.commit()
    row = conn.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
    return int(row[0] if not hasattr(row, "keys") else row["id"])


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


def _parse_date_strict(s: str):
    """
    Parse une date depuis une chaîne en format explicite.

    Formats supportés, testés dans l'ordre :
      - dd/mm/yyyy  (format FR, exports Excel/CSV)
      - YYYY-MM-DD  (format ISO, Bankin)

    N'utilise pas dayfirst=True ni l'inférence automatique de pandas
    afin d'éviter les UserWarning de pandas >= 2.0 et les ambiguïtés.

    Retourne pd.NaT si aucun format ne correspond.
    """
    # Format FR : 30/09/2025
    if len(s) == 10 and s[2] == "/":
        d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
        if pd.notna(d):
            return d

    # Format ISO : 2025-09-30
    if len(s) == 10 and s[4] == "-":
        d = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
        if pd.notna(d):
            return d

    return pd.NaT


def _month_key_from_date(date_value) -> str:
    """Convertit une valeur de date (string FR ou ISO) en clé mois YYYY-MM-01."""
    if pd.isna(date_value):
        raise ValueError("Date manquante")

    s = str(date_value).strip()
    if s == "":
        raise ValueError("Date vide")

    # Formats attendus : 30/09/2025 (dd/mm/yyyy) ou 2025-09-30 (YYYY-MM-DD)
    d = _parse_date_strict(s)
    if pd.isna(d):
        raise ValueError(f"Date invalide: {s}")

    # On stocke le mois : YYYY-MM-01 (format DB)
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
    import_batch_id: int | None = None,
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

    # Validation basique
    if table == "depenses":
        negatifs = long[long["montant"] < 0]
        if not negatifs.empty:
            _logger.warning("import_csv_wide: %d montants négatifs dans les dépenses (ignorés)", len(negatifs))
            long = long[long["montant"] >= 0]

    rows = [
        (person_id, r["mois"], r["categorie"], float(r["montant"]), import_batch_id)
        for _, r in long.iterrows()
    ]

    # DELETE ciblé sur les mois du fichier importé uniquement (pas l’historique complet)
    if delete_existing:
        months = long["mois"].dropna().unique().tolist()
        if months:
            placeholders = ",".join(["?"] * len(months))
            conn.execute(
                f"DELETE FROM {table} WHERE person_id = ? AND mois IN ({placeholders})",
                (person_id, *months),
            )

    conn.executemany(
        f"INSERT INTO {table} (person_id, mois, categorie, montant, import_batch_id) VALUES (?, ?, ?, ?, ?)",
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

# --- Bankin import ---

# Mapping Bankin -> catégories finales (N3) simplifiées (ta version figée)
def map_bankin_to_final(parent_cat: str, cat: str, amount: float) -> str:
    parent_cat = (parent_cat or "").strip()
    cat = (cat or "").strip()

    # --- Revenus (Bankin parent "Entrées d'argent") ---
    if parent_cat == "Entrées d'argent":
        if cat in ("Salaires",):
            return "Salaire"
        if cat in ("Retraite", "Loyers reçus"):
            return "Revenus récurrents"
        if cat in ("Intérêts",):
            return "Revenus financiers"
        if cat in ("Allocations et pensions",):
            return "Aides & allocations"
        if cat in ("Autres rentrées", "Extra", "Ventes", "Remboursements", "Dépôt d'argent", "Services"):
            return "Autres revenus"
        if cat in ("Économies", "Emprunt", "Virements internes"):
            return "Flux financiers"
        return "Autres revenus"

    # --- Dépenses ---
    if parent_cat == "Logement":
        if cat == "Loyer":
            return "Loyer"
        if cat in ("Eau", "Gaz", "Électricité", "Charges diverses"):
            return "Charges logement"
        if cat in ("Assurance habitation", "Entretien", "Décoration", "Extérieur et jardin", "Logement - Autres"):
            return "Assurance & entretien logement"
        return "Assurance & entretien logement"

    if parent_cat == "Alimentation et restau.":
        if cat in ("Supermarché / Épicerie", "Alimentation - autres"):
            return "Courses"
        if cat in ("Restaurants", "Sortie au restaurant"):
            return "Restaurants"
        if cat in ("Fast foods", "Café"):
            return "Restaurants"  # simplifié
        return "Courses"

    if parent_cat == "Achats et shopping":
        return "Achats personnels"

    if parent_cat == "Abonnements":
        if cat in ("Internet", "Téléphonie fixe", "Téléphonie mobile"):
            return "Télécoms & Internet"
        if cat in ("Câble / Satellite", "Abonnements - autres"):
            return "Loisirs numériques"
        return "Loisirs numériques"

    if parent_cat == "Auto et transports":
        if cat in ("Carburant", "Transports en commun"):
            return "Transport quotidien"
        if cat in ("Assurance véhicule", "Entretien véhicule", "Stationnement", "Péage"):
            return "Véhicule"
        if cat in ("Billets d'avion", "Billets de train", "Location de véhicule"):
            return "Voyages (transport)"
        return "Transport quotidien"

    if parent_cat == "Loisirs et sorties":
        if cat in ("Voyages / vacances", "Hôtels"):
            return "Voyages & vacances"
        return "Loisirs & sorties"

    if parent_cat == "Santé":
        if cat == "Mutuelle":
            return "Complémentaire santé"
        return "Soins"

    if parent_cat == "Scolarité et enfants":
        if cat in ("École", "Fournitures scolaires", "Logement étudiant"):
            return "Scolarité"
        return "Enfants"

    if parent_cat == "Impôts et taxes":
        return "Impôts & charges"

    if parent_cat == "Banque":
        # frais bancaires, remboursements emprunts, etc. -> on simplifie en "Impôts & charges"
        return "Impôts & charges"

    if parent_cat == "Divers":
        return "Dépenses courantes"

    if parent_cat == "Retraits, chèques et virements":
        # Pour "tout afficher", on les garde visibles en Flux financiers
        return "Flux financiers"

    # fallback global
    return "Dépenses courantes"


def _ensure_account(conn: sqlite3.Connection, person_id: int, account_name: str) -> int:
    row = conn.execute(
        "SELECT id FROM accounts WHERE person_id = ? AND name = ?",
        (person_id, account_name),
    ).fetchone()
    if row:
        return int(row[0] if not hasattr(row, "keys") else row["id"])

    conn.execute(
        """
        INSERT INTO accounts(person_id, name, account_type, institution, currency)
        VALUES (?, ?, 'BANQUE', NULL, 'EUR')
        """,
        (person_id, account_name),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM accounts WHERE person_id = ? AND name = ?",
        (person_id, account_name),
    ).fetchone()
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def import_bankin_csv(
    conn: sqlite3.Connection,
    *,
    person_name: str,
    file,
    also_fill_monthly_tables: bool = True,
    purge_existing_transactions: bool = False,
    import_batch_id: int | None = None,
) -> dict:
    """
    Importe le CSV Bankin dans transactions.
    Optionnel : alimente aussi depenses/revenus (mensuel) par somme de catégorie finale.

    CSV attendu (Bankin) colonnes typiques :
    Date (YYYY-MM-DD), Amount (+/-), Description, Account Name, Category Name, Parent Category Name
    """
    df = pd.read_csv(file, sep=None, engine="python")
    df.columns = [c.strip() for c in df.columns]

    required = ["Date", "Amount", "Description", "Account Name", "Category Name", "Parent Category Name"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Colonne manquante dans l'export Bankin : {col}. Colonnes trouvées: {list(df.columns)}")

    person_id = _ensure_person(conn, person_name)

    if purge_existing_transactions:
        conn.execute("DELETE FROM transactions WHERE person_id = ?", (person_id,))
        conn.commit()

    # Pour alimenter depenses/revenus en "mensuel par catégorie"
    monthly_dep = {}  # (mois, categorie_finale) -> sum
    monthly_rev = {}

    existing_fingerprints = set()
    if not purge_existing_transactions:
        rows = conn.execute(
            """
            SELECT date, type, amount, note 
            FROM transactions 
            WHERE person_id = ? AND note LIKE 'Bankin:%'
            """,
            (person_id,)
        ).fetchall()
        for r_ext in rows:
            d_ext = str(r_ext[0] if not hasattr(r_ext, "keys") else r_ext["date"])
            t_ext = str(r_ext[1] if not hasattr(r_ext, "keys") else r_ext["type"])
            a_ext = float(r_ext[2] if not hasattr(r_ext, "keys") else r_ext["amount"] or 0.0)
            n_ext = str(r_ext[3] if not hasattr(r_ext, "keys") else r_ext["note"] or "")
            existing_fingerprints.add((d_ext, t_ext, round(a_ext, 2), n_ext))

    inserted = 0

    for _, r in df.iterrows():
        date_str = str(r["Date"]).strip()  # Bankin: YYYY-MM-DD
        d = pd.to_datetime(date_str, errors="coerce")
        if pd.isna(d):
            continue

        mois = f"{d.year:04d}-{d.month:02d}-01"

        amount = float(r["Amount"])
        desc = str(r["Description"]) if not pd.isna(r["Description"]) else ""
        account_name = str(r["Account Name"]) if not pd.isna(r["Account Name"]) else "Compte Bankin"
        cat = str(r["Category Name"]) if not pd.isna(r["Category Name"]) else ""
        parent = str(r["Parent Category Name"]) if not pd.isna(r["Parent Category Name"]) else ""

        categorie_finale = map_bankin_to_final(parent, cat, amount)

        account_id = _ensure_account(conn, person_id, account_name)

        # type & amount (DB transactions stocke amount positif, sens géré par type)
        if amount < 0:
            tx_type = "DEPENSE"
            tx_amount = abs(amount)
            monthly_dep[(mois, categorie_finale)] = monthly_dep.get((mois, categorie_finale), 0.0) + tx_amount
        else:
            tx_type = "DEPOT"
            tx_amount = amount
            monthly_rev[(mois, categorie_finale)] = monthly_rev.get((mois, categorie_finale), 0.0) + tx_amount

        note_complete = f"Bankin: {parent} > {cat} | {desc}"
        fingerprint = (d.strftime("%Y-%m-%d"), tx_type, round(tx_amount, 2), note_complete)

        if fingerprint in existing_fingerprints:
            continue

        conn.execute(
            """
            INSERT INTO transactions(date, person_id, account_id, type, asset_id, quantity, price, fees, amount, category, note, import_batch_id)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?, ?, ?)
            """,
            (d.strftime("%Y-%m-%d"), person_id, account_id, tx_type, tx_amount, categorie_finale, note_complete, import_batch_id),
        )
        existing_fingerprints.add(fingerprint)
        inserted += 1

    conn.commit()

    # Option : remplir depenses/revenus (mensuel)
    if also_fill_monthly_tables:
        # Purge les mois importés pour éviter les doublons en cas de re-import
        dep_months = sorted(set(m for (m, _) in monthly_dep.keys()))
        rev_months = sorted(set(m for (m, _) in monthly_rev.keys()))

        if dep_months:
            placeholders = ",".join(["?"] * len(dep_months))
            conn.execute(
                f"DELETE FROM depenses WHERE person_id = ? AND mois IN ({placeholders})",
                (person_id, *dep_months),
            )
        if rev_months:
            placeholders = ",".join(["?"] * len(rev_months))
            conn.execute(
                f"DELETE FROM revenus WHERE person_id = ? AND mois IN ({placeholders})",
                (person_id, *rev_months),
            )

        for (mois, cat), total in monthly_dep.items():
            conn.execute(
                """
                INSERT INTO depenses(person_id, mois, categorie, montant)
                VALUES (?, ?, ?, ?)
                """,
                (person_id, mois, cat, float(total)),
            )

        for (mois, cat), total in monthly_rev.items():
            conn.execute(
                """
                INSERT INTO revenus(person_id, mois, categorie, montant)
                VALUES (?, ?, ?, ?)
                """,
                (person_id, mois, cat, float(total)),
            )
        conn.commit()

    return {
        "person_id": person_id,
        "transactions_inserted": inserted,
        "months_depenses": sorted(set(m for (m, _) in monthly_dep.keys())),
        "months_revenus": sorted(set(m for (m, _) in monthly_rev.keys())),
        "dep_categories": sorted(set(c for (_, c) in monthly_dep.keys())),
        "rev_categories": sorted(set(c for (_, c) in monthly_rev.keys())),
    }
