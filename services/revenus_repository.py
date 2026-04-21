import sqlite3
import pandas as pd


def _normalize_month(value: str) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return str(value)
    return ts.to_period("M").to_timestamp().strftime("%Y-%m-01")


def _empty_passive_monthly_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["mois", "dividendes", "interets", "revenus_passifs"])


def ajouter_revenu(conn: sqlite3.Connection, person_id: int, mois: str, categorie: str, montant: float):
    conn.execute(
        "INSERT INTO revenus (person_id, mois, categorie, montant) VALUES (?, ?, ?, ?)",
        (person_id, mois, categorie, montant),
    )
    conn.commit()


def revenus_du_mois(conn: sqlite3.Connection, person_id: int, mois: str) -> pd.DataFrame:
    mois = _normalize_month(mois)
    rows = conn.execute(
        "SELECT id, categorie, montant FROM revenus WHERE person_id = ? AND mois = ?",
        (person_id, mois),
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["id", "categorie", "montant"])

    return pd.DataFrame(rows, columns=["id", "categorie", "montant"])


def dernier_revenu(conn: sqlite3.Connection, person_id: int, mois: str):
    mois = _normalize_month(mois)
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


def revenus_passifs_par_mois(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    """
    Revenus passifs bourse (DIVIDENDE/INTERETS), agrégés par mois en EUR.
    """
    from services.cashflow import get_passive_income_monthly_for_scope

    try:
        df = get_passive_income_monthly_for_scope(conn, "person", int(person_id))
    except Exception:
        return _empty_passive_monthly_df()

    if df is None or df.empty:
        return _empty_passive_monthly_df()

    out = df.copy()
    out["mois"] = pd.to_datetime(out.get("mois"), errors="coerce").dt.strftime("%Y-%m-01")
    out["dividendes"] = pd.to_numeric(out.get("dividendes"), errors="coerce").fillna(0.0)
    out["interets"] = pd.to_numeric(out.get("interets"), errors="coerce").fillna(0.0)
    out["revenus_passifs"] = pd.to_numeric(out.get("revenus_passifs"), errors="coerce").fillna(0.0)
    out = out.dropna(subset=["mois"]).copy()
    return out[["mois", "dividendes", "interets", "revenus_passifs"]].sort_values("mois").reset_index(drop=True)


def revenus_kpis_mois(conn: sqlite3.Connection, person_id: int, mois: str) -> dict:
    """
    KPI mensuels consolidés pour le panel Revenus.
    """
    month = _normalize_month(mois)
    df_manual = revenus_du_mois(conn, person_id, month)
    manual_total = float(pd.to_numeric(df_manual.get("montant"), errors="coerce").fillna(0.0).sum()) if not df_manual.empty else 0.0
    entries_count = int(len(df_manual)) if df_manual is not None else 0

    passive = revenus_passifs_par_mois(conn, person_id)
    if passive is None or passive.empty:
        div = 0.0
        inter = 0.0
    else:
        row = passive[passive["mois"] == month]
        if row.empty:
            div = 0.0
            inter = 0.0
        else:
            div_raw = pd.to_numeric(row.iloc[-1].get("dividendes"), errors="coerce")
            inter_raw = pd.to_numeric(row.iloc[-1].get("interets"), errors="coerce")
            div = 0.0 if pd.isna(div_raw) else float(div_raw)
            inter = 0.0 if pd.isna(inter_raw) else float(inter_raw)

    passifs = div + inter
    return {
        "mois": month,
        "revenus_saisis": float(manual_total),
        "dividendes": float(div),
        "interets": float(inter),
        "revenus_passifs": float(passifs),
        "total_revenus": float(manual_total + passifs),
        "entries_count": entries_count,
    }


def revenus_du_mois_consolides(conn: sqlite3.Connection, person_id: int, mois: str) -> pd.DataFrame:
    """
    Lignes de revenus du mois = revenus saisis + revenus passifs bourse.
    """
    month = _normalize_month(mois)
    manual = revenus_du_mois(conn, person_id, month).copy()
    if manual.empty:
        manual = pd.DataFrame(columns=["id", "categorie", "montant", "source"])
    else:
        manual["source"] = "Saisie"

    kpi = revenus_kpis_mois(conn, person_id, month)
    passive_rows = []
    if abs(float(kpi["dividendes"])) > 0:
        passive_rows.append(
            {"id": pd.NA, "categorie": "Dividendes (Bourse)", "montant": float(kpi["dividendes"]), "source": "Bourse"}
        )
    if abs(float(kpi["interets"])) > 0:
        passive_rows.append(
            {"id": pd.NA, "categorie": "Intérêts (Bourse)", "montant": float(kpi["interets"]), "source": "Bourse"}
        )

    if passive_rows:
        passive_df = pd.DataFrame(passive_rows, columns=["id", "categorie", "montant", "source"])
        return pd.concat([manual, passive_df], ignore_index=True)
    return manual


def revenus_par_mois_consolides(conn: sqlite3.Connection, person_id: int) -> pd.DataFrame:
    """
    Totaux mensuels consolidés = revenus saisis + revenus passifs bourse.
    """
    manual = revenus_par_mois(conn, person_id).copy()
    if manual.empty:
        manual = pd.DataFrame(columns=["mois", "total"])
    manual = manual.rename(columns={"total": "revenus_saisis"})
    manual["mois"] = pd.to_datetime(manual.get("mois"), errors="coerce").dt.strftime("%Y-%m-01")
    manual["revenus_saisis"] = pd.to_numeric(manual.get("revenus_saisis"), errors="coerce").fillna(0.0)
    manual = manual.dropna(subset=["mois"]).copy()

    passive = revenus_passifs_par_mois(conn, person_id)
    if passive is None or passive.empty:
        passive = _empty_passive_monthly_df()

    merged = pd.merge(manual, passive, on="mois", how="outer")
    merged["revenus_saisis"] = pd.to_numeric(merged.get("revenus_saisis"), errors="coerce").fillna(0.0)
    merged["dividendes"] = pd.to_numeric(merged.get("dividendes"), errors="coerce").fillna(0.0)
    merged["interets"] = pd.to_numeric(merged.get("interets"), errors="coerce").fillna(0.0)
    merged["revenus_passifs"] = pd.to_numeric(merged.get("revenus_passifs"), errors="coerce").fillna(0.0)
    merged["total"] = merged["revenus_saisis"] + merged["revenus_passifs"]
    merged = merged.dropna(subset=["mois"]).copy()
    if merged.empty:
        return pd.DataFrame(columns=["mois", "revenus_saisis", "dividendes", "interets", "revenus_passifs", "total"])
    return merged[["mois", "revenus_saisis", "dividendes", "interets", "revenus_passifs", "total"]].sort_values("mois").reset_index(drop=True)


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
