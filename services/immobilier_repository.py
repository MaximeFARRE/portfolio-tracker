"""
Repository Immobilier — biens directs (RP, locatif, parking, etc.)
et remontée automatique des SCPI détenues dans des comptes titres / AV.
"""
import sqlite3
import pandas as pd
from typing import Optional

from services.repositories import df_from_rows


# ── Création / migration des tables ───────────────────────────────────────────

def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS immobiliers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL UNIQUE,
            property_type       TEXT    NOT NULL DEFAULT 'AUTRE',
            valuation_eur       REAL    NOT NULL DEFAULT 0,
            debt_eur            REAL    NOT NULL DEFAULT 0,
            monthly_rent_eur    REAL    NOT NULL DEFAULT 0,
            annual_charges_eur  REAL    NOT NULL DEFAULT 0,
            annual_tax_eur      REAL    NOT NULL DEFAULT 0,
            note                TEXT,
            effective_date      TEXT    NOT NULL DEFAULT (date('now')),
            created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS immobilier_shares (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id       INTEGER NOT NULL,
            person_id         INTEGER NOT NULL,
            pct               REAL    NOT NULL DEFAULT 100,
            initial_invest_eur REAL   NOT NULL DEFAULT 0,
            initial_date      TEXT,
            UNIQUE (property_id, person_id),
            FOREIGN KEY (property_id) REFERENCES immobiliers(id) ON DELETE CASCADE,
            FOREIGN KEY (person_id)   REFERENCES people(id)      ON DELETE CASCADE
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS immobilier_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            property_id         INTEGER NOT NULL,
            valuation_eur       REAL    NOT NULL DEFAULT 0,
            debt_eur            REAL    NOT NULL DEFAULT 0,
            monthly_rent_eur    REAL    NOT NULL DEFAULT 0,
            annual_charges_eur  REAL    NOT NULL DEFAULT 0,
            annual_tax_eur      REAL    NOT NULL DEFAULT 0,
            note                TEXT,
            effective_date      TEXT    NOT NULL DEFAULT (date('now')),
            created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (property_id) REFERENCES immobiliers(id) ON DELETE CASCADE
        );
    """)

    conn.commit()


# ── CRUD biens directs ────────────────────────────────────────────────────────

def list_properties(conn: sqlite3.Connection) -> pd.DataFrame:
    ensure_tables(conn)
    rows = conn.execute("""
        SELECT id, name, property_type, valuation_eur, debt_eur,
               monthly_rent_eur, annual_charges_eur, annual_tax_eur,
               note, effective_date, created_at
        FROM immobiliers ORDER BY name;
    """).fetchall()
    return df_from_rows(rows, [
        "id", "name", "property_type", "valuation_eur", "debt_eur",
        "monthly_rent_eur", "annual_charges_eur", "annual_tax_eur",
        "note", "effective_date", "created_at",
    ])


def get_property(conn: sqlite3.Connection, property_id: int):
    ensure_tables(conn)
    return conn.execute(
        "SELECT * FROM immobiliers WHERE id = ?;", (property_id,)
    ).fetchone()


def create_property(
    conn: sqlite3.Connection,
    name: str,
    property_type: str,
    valuation_eur: float,
    debt_eur: float,
    monthly_rent_eur: float,
    annual_charges_eur: float,
    annual_tax_eur: float,
    note: Optional[str],
    effective_date: Optional[str] = None,
) -> int:
    ensure_tables(conn)
    if not effective_date:
        effective_date = pd.Timestamp.today().date().isoformat()

    cur = conn.execute("""
        INSERT INTO immobiliers(name, property_type, valuation_eur, debt_eur,
            monthly_rent_eur, annual_charges_eur, annual_tax_eur, note, effective_date)
        VALUES (?,?,?,?,?,?,?,?,?);
    """, (
        name.strip(), property_type,
        float(valuation_eur), float(debt_eur),
        float(monthly_rent_eur), float(annual_charges_eur), float(annual_tax_eur),
        note, effective_date,
    ))
    property_id = int(cur.lastrowid)

    # Entrée initiale dans l'historique
    conn.execute("""
        INSERT INTO immobilier_history(property_id, valuation_eur, debt_eur,
            monthly_rent_eur, annual_charges_eur, annual_tax_eur, note, effective_date)
        VALUES (?,?,?,?,?,?,?,?);
    """, (
        property_id,
        float(valuation_eur), float(debt_eur),
        float(monthly_rent_eur), float(annual_charges_eur), float(annual_tax_eur),
        f"Création{' — ' + note if note else ''}",
        effective_date,
    ))

    conn.commit()
    return property_id


def update_property(
    conn: sqlite3.Connection,
    property_id: int,
    property_type: str,
    valuation_eur: float,
    debt_eur: float,
    monthly_rent_eur: float,
    annual_charges_eur: float,
    annual_tax_eur: float,
    note: Optional[str],
    effective_date: Optional[str] = None,
) -> None:
    ensure_tables(conn)
    if not effective_date:
        effective_date = pd.Timestamp.today().date().isoformat()

    conn.execute("""
        UPDATE immobiliers
        SET property_type = ?, valuation_eur = ?, debt_eur = ?,
            monthly_rent_eur = ?, annual_charges_eur = ?, annual_tax_eur = ?,
            note = ?, effective_date = ?
        WHERE id = ?;
    """, (
        property_type,
        float(valuation_eur), float(debt_eur),
        float(monthly_rent_eur), float(annual_charges_eur), float(annual_tax_eur),
        note, effective_date,
        int(property_id),
    ))

    conn.execute("""
        INSERT INTO immobilier_history(property_id, valuation_eur, debt_eur,
            monthly_rent_eur, annual_charges_eur, annual_tax_eur, note, effective_date)
        VALUES (?,?,?,?,?,?,?,?);
    """, (
        int(property_id),
        float(valuation_eur), float(debt_eur),
        float(monthly_rent_eur), float(annual_charges_eur), float(annual_tax_eur),
        note, effective_date,
    ))

    conn.commit()


def replace_shares(
    conn: sqlite3.Connection,
    property_id: int,
    person_id: int,
    pct: float,
    initial_invest_eur: float,
    initial_date: Optional[str],
) -> None:
    """Insère ou met à jour la quote-part d'une personne pour un bien."""
    ensure_tables(conn)
    conn.execute("""
        INSERT INTO immobilier_shares(property_id, person_id, pct, initial_invest_eur, initial_date)
        VALUES (?,?,?,?,?)
        ON CONFLICT(property_id, person_id) DO UPDATE SET
            pct               = excluded.pct,
            initial_invest_eur = excluded.initial_invest_eur,
            initial_date      = excluded.initial_date;
    """, (int(property_id), int(person_id), float(pct), float(initial_invest_eur), initial_date))
    conn.commit()


def list_history(conn: sqlite3.Connection, property_id: int, limit: int = 20) -> pd.DataFrame:
    ensure_tables(conn)
    rows = conn.execute("""
        SELECT id, effective_date, created_at, valuation_eur, debt_eur,
               monthly_rent_eur, annual_charges_eur, annual_tax_eur, note
        FROM immobilier_history
        WHERE property_id = ?
        ORDER BY effective_date DESC, id DESC
        LIMIT ?;
    """, (int(property_id), int(limit))).fetchall()
    return df_from_rows(rows, [
        "id", "effective_date", "created_at",
        "valuation_eur", "debt_eur", "monthly_rent_eur",
        "annual_charges_eur", "annual_tax_eur", "note",
    ])


# ── Positions par personne (biens directs) ────────────────────────────────────

def list_positions_for_person(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    ensure_tables(conn)
    rows = conn.execute("""
        SELECT
            imm.id            AS property_id,
            imm.name,
            imm.property_type,
            imm.valuation_eur,
            imm.debt_eur,
            imm.monthly_rent_eur,
            imm.annual_charges_eur,
            imm.annual_tax_eur,
            imm.note,
            imm.effective_date,
            s.pct,
            s.initial_invest_eur,
            s.initial_date
        FROM immobilier_shares s
        JOIN immobiliers imm ON imm.id = s.property_id
        WHERE s.person_id = ?
        ORDER BY imm.name;
    """, (int(person_id),)).fetchall()
    return df_from_rows(rows, [
        "property_id", "name", "property_type",
        "valuation_eur", "debt_eur", "monthly_rent_eur",
        "annual_charges_eur", "annual_tax_eur", "note", "effective_date",
        "pct", "initial_invest_eur", "initial_date",
    ])


# ── Remontée automatique des SCPI ─────────────────────────────────────────────

def list_scpi_positions_for_person(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    """
    Détecte automatiquement les SCPI détenues via des transactions (comptes titres / AV).
    asset_type = 'scpi' → on calcule les parts nettes et la dernière valorisation connue.
    """
    rows = conn.execute("""
        SELECT
            a.id     AS asset_id,
            a.symbol,
            a.name,
            a.currency,
            SUM(CASE
                WHEN t.type = 'ACHAT' THEN  t.quantity
                WHEN t.type = 'VENTE' THEN -t.quantity
                ELSE 0
            END) AS qty,
            (SELECT p.price FROM prices p
             WHERE p.asset_id = a.id ORDER BY p.date DESC LIMIT 1) AS last_price,
            (SELECT p.date  FROM prices p
             WHERE p.asset_id = a.id ORDER BY p.date DESC LIMIT 1) AS last_price_date
        FROM transactions t
        JOIN assets a ON a.id = t.asset_id
        WHERE t.person_id = ?
          AND a.asset_type = 'scpi'
        GROUP BY a.id
        HAVING qty > 0.0001;
    """, (int(person_id),)).fetchall()
    return df_from_rows(rows, [
        "asset_id", "symbol", "name", "currency",
        "qty", "last_price", "last_price_date",
    ])


# ── Agrégation directe + SCPI ─────────────────────────────────────────────────

def aggregate_positions(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    """
    Fusionne biens directs + SCPI automatiques.
    Calcule toutes les colonnes dérivées (valeur détenue, dette imputable,
    valeur nette, rendement brut…).

    Règle anti-doublon : si une SCPI est déjà saisie manuellement (même nom),
    on garde la ligne manuelle et on ignore la remontée automatique.
    """
    rows = []

    # --- Biens directs ---
    direct_df = list_positions_for_person(conn, person_id)
    direct_names_lower = set()

    for _, r in direct_df.iterrows():
        pct      = float(r.get("pct")              or 100.0)
        pct_frac = pct / 100.0
        valo     = float(r.get("valuation_eur")    or 0.0)
        dette    = float(r.get("debt_eur")         or 0.0)
        loyer_m  = float(r.get("monthly_rent_eur") or 0.0)
        loyers_a = loyer_m * 12.0
        rdt      = (loyers_a / valo * 100.0) if valo > 0 else None

        name = str(r.get("name") or "")
        direct_names_lower.add(name.lower())

        rows.append({
            "property_id":     r.get("property_id"),
            "nom":             name,
            "type":            str(r.get("property_type") or "AUTRE"),
            "source":          "Direct",
            "valeur_totale":   valo,
            "pct":             pct,
            "valeur_detenue":  valo * pct_frac,
            "dette_totale":    dette,
            "dette_imputable": dette * pct_frac,
            "valeur_nette":    (valo - dette) * pct_frac,
            "loyer_mensuel":   loyer_m,
            "loyers_annuels":  loyers_a,
            "rendement_brut":  rdt,
            "note":            str(r.get("note") or ""),
            "effective_date":  str(r.get("effective_date") or ""),
        })

    # --- SCPI automatiques ---
    scpi_df = list_scpi_positions_for_person(conn, person_id)

    for _, r in scpi_df.iterrows():
        name = str(r.get("name") or r.get("symbol") or "—")
        # Ne pas dupliquer si déjà saisi manuellement
        if name.lower() in direct_names_lower:
            continue

        qty   = float(r.get("qty")        or 0.0)
        price = float(r.get("last_price") or 0.0)
        valo  = qty * price

        rows.append({
            "property_id":     None,
            "nom":             name,
            "type":            "SCPI",
            "source":          "Actif existant",
            "valeur_totale":   valo,
            "pct":             100.0,
            "valeur_detenue":  valo,
            "dette_totale":    0.0,
            "dette_imputable": 0.0,
            "valeur_nette":    valo,
            "loyer_mensuel":   0.0,
            "loyers_annuels":  0.0,
            "rendement_brut":  None,
            "note":            (
                f"{r.get('symbol','')} · {qty:.4f} parts"
                f" @ {price:.2f} {r.get('currency','EUR')}"
                f" · prix au {r.get('last_price_date','?')}"
            ),
            "effective_date":  str(r.get("last_price_date") or ""),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
