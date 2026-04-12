import logging
import pandas as pd
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------
# CRUD CREDIT (fiche contrat)
# ---------------------------

def upsert_credit(conn, data: Dict[str, Any]) -> int:
    """
    Crée ou met à jour la fiche 'credits' pour un account_id (sous-compte crédit).
    Retourne credit_id.
    """
    account_id = int(data["account_id"])
    row = conn.execute(
        "SELECT id FROM credits WHERE account_id = ?",
        (account_id,)
    ).fetchone()

    fields = [
        "person_id", "account_id", "payer_account_id", "nom", "banque", "type_credit",
        "capital_emprunte", "taux_nominal", "taeg", "duree_mois",
        "mensualite_theorique", "assurance_mensuelle_theorique",
        "date_debut", "actif",
    ]

    values = [data.get(f) for f in fields]

    if row:
        try:
            credit_id = int(row["id"])
        except (TypeError, KeyError):
            credit_id = int(row[0])
        set_clause = ", ".join([f"{f} = ?" for f in fields] + ["updated_at = datetime('now')"])
        conn.execute(
            f"UPDATE credits SET {set_clause} WHERE id = ?",
            (*values, credit_id)
        )
        conn.commit()
        return credit_id

    cols = ", ".join(fields)
    placeholders = ", ".join(["?"] * len(fields))
    cur = conn.execute(
        f"INSERT INTO credits ({cols}) VALUES ({placeholders})",
        values
    )
    conn.commit()
    return int(cur.lastrowid)


def get_credit_by_account(conn, account_id: int) -> Optional[dict]:
    cursor = conn.execute("SELECT * FROM credits WHERE account_id = ?", (int(account_id),))
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        return None
    return dict(zip(cols, rows[0]))


def list_credits_by_person(conn, person_id: int, only_active: bool = True) -> pd.DataFrame:
    q = "SELECT * FROM credits WHERE person_id = ?"
    params = [int(person_id)]
    if only_active:
        q += " AND actif = 1"
    q += " ORDER BY id DESC"
    cursor = conn.execute(q, params)
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


# ---------------------------
# AMORTISSEMENT (import CSV)
# ---------------------------

def replace_amortissement(conn, credit_id: int, rows: List[Dict[str, Any]]) -> int:
    """
    Remplace TOUT le tableau amortissement d’un crédit.
    rows: liste de dicts avec date_echeance, mensualite, capital_amorti, interets, assurance, crd, annee, mois
    """
    credit_id = int(credit_id)
    conn.execute("DELETE FROM credit_amortissements WHERE credit_id = ?", (credit_id,))

    if not rows:
        conn.commit()
        return 0

    def _safe_float(val, default=0.0) -> float:
        try:
            return float(val) if val is not None and val != "" else default
        except (ValueError, TypeError):
            return default

    def _safe_int(val) -> int | None:
        try:
            return int(val) if val is not None and val != "" else None
        except (ValueError, TypeError):
            return None

    conn.executemany(
        """
        INSERT INTO credit_amortissements
        (credit_id, date_echeance, mensualite, capital_amorti, interets, assurance, crd, annee, mois)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                credit_id,
                r.get("date_echeance"),
                _safe_float(r.get("mensualite")),
                _safe_float(r.get("capital_amorti")),
                _safe_float(r.get("interets")),
                _safe_float(r.get("assurance")),
                _safe_float(r.get("crd")),
                _safe_int(r.get("annee")),
                _safe_int(r.get("mois")),
            )
            for r in rows
        ]
    )
    conn.commit()
    return len(rows)


def get_amortissements(conn, credit_id: int) -> pd.DataFrame:
    _COLS = ["date_echeance", "mensualite", "capital_amorti", "interets", "assurance", "crd", "annee", "mois"]
    rows = conn.execute(
        """
        SELECT date_echeance, mensualite, capital_amorti, interets, assurance, crd, annee, mois
        FROM credit_amortissements
        WHERE credit_id = ?
        ORDER BY date_echeance
        """,
        (int(credit_id),),
    ).fetchall()
    return pd.DataFrame(rows, columns=_COLS) if rows else pd.DataFrame(columns=_COLS)


# ---------------------------
# KPI (estimés via amortissement)
# ---------------------------

def get_credit_kpis(conn, credit_id: int) -> Dict[str, Any]:
    df = get_amortissements(conn, credit_id)
    if df.empty:
        return {
            "crd_estime": 0.0,
            "interets_restants": 0.0,
            "assurance_restante": 0.0,
            "cout_restant_total": 0.0,
            "totaux_annuels": pd.DataFrame(columns=["annee", "capital_amorti", "interets", "assurance"]),
        }

    # CRD estimé = dernier crd non nul (sinon 0)
    df2 = df.copy()
    df2["crd"] = pd.to_numeric(df2["crd"], errors="coerce").fillna(0.0)
    crd_estime = float(df2["crd"].iloc[-1]) if len(df2) else 0.0

    interets_restants = float(pd.to_numeric(df2["interets"], errors="coerce").fillna(0.0).sum())
    assurance_restante = float(pd.to_numeric(df2["assurance"], errors="coerce").fillna(0.0).sum())

    totaux = (
        df2.groupby("annee", dropna=True)[["capital_amorti", "interets", "assurance"]]
        .sum()
        .reset_index()
        .sort_values("annee")
    )

    return {
        "crd_estime": crd_estime,
        "interets_restants": interets_restants,
        "assurance_restante": assurance_restante,
        "cout_restant_total": interets_restants + assurance_restante,
        "totaux_annuels": totaux,
        "courbe_crd": df2[["date_echeance", "crd"]].copy(),
    }


# ---------------------------
# Coût réel (via transactions Bankin)
# ---------------------------

def get_cout_mensuel_reel(conn, person_id: int, mois: str) -> float:
    """
    Somme des transactions Bankin du mois pour la catégorie "échéance prêt / emprunt".
    mois: "YYYY-MM-01"
    """
    # on prend le mois complet
    start = str(mois)
    # fin = mois suivant
    start_dt = pd.to_datetime(start)
    end_dt = (start_dt + pd.offsets.MonthBegin(1)).to_pydatetime().date()
    end = str(end_dt)

    df = pd.read_sql_query(
        """
        SELECT amount, category
        FROM transactions
        WHERE person_id = ?
          AND date >= ?
          AND date < ?
        """,
        conn,
        params=[int(person_id), start, end],
    )

    if df.empty or "category" not in df.columns:
        return 0.0

    cat = df["category"].fillna("").str.lower()

    # Filtre "échéance prêt" / "emprunt" (tolérant)
    mask = (
        (cat.str.contains("échéance", regex=False) | cat.str.contains("echeance", regex=False))
        & (cat.str.contains("prêt", regex=False) | cat.str.contains("pret", regex=False) | cat.str.contains("emprunt", regex=False))
    )

    # Les montants dans ta table transactions sont "positifs" et le sens est géré par type.
    # Ici, Bankin import est probablement en type DEPENSE ou similaire : on veut le coût réel => somme des amounts filtrés.
    return float(pd.to_numeric(df.loc[mask, "amount"], errors="coerce").fillna(0.0).sum())

def cout_reel_mois_via_bankin(conn, person_id: int, mois_yyyy_mm_01: str) -> float:
    # Alias compat si ton code appelait un autre nom avant
    return get_cout_mensuel_reel(conn, person_id, mois_yyyy_mm_01)


@dataclass
class CreditParams:
    capital: float
    taux_annuel: float           # en %, ex 1.88
    duree_mois: int
    date_debut: str              # YYYY-MM-DD
    assurance_mensuelle: float = 0.0

    differe_mois: int = 0
    differe_type: str = "aucun"  # "aucun" | "partiel" | "total"
    assurance_pendant_differe: bool = True
    interets_pendant_differe: str = "payes"  # "payes" | "capitalises"

    mensualite: Optional[float] = None       # si None, on calcule


def _mensualite_standard(P: float, taux_mensuel: float, n: int) -> float:
    if n <= 0:
        return 0.0
    if taux_mensuel == 0:
        return P / n
    return P * (taux_mensuel / (1 - (1 + taux_mensuel) ** (-n)))


def build_amortissement(params: CreditParams) -> List[Dict[str, Any]]:
    """
    Génère un amortissement mensuel.
    Gestion différé:
    - partiel : capital_amorti=0, on paie intérêts (et assurance si activée)
    - total :
        - si interets_pendant_differe = "payes" : on paie 0 ou assurance, intérêts payés (CRD stable)
        - si "capitalises" : intérêts s'ajoutent au CRD (CRD augmente)
    """
    P = float(params.capital)
    r_m = float(params.taux_annuel) / 100.0 / 12.0
    n = int(params.duree_mois)
    diff_n = int(params.differe_mois)
    assurance = float(params.assurance_mensuelle or 0.0)

    start = pd.to_datetime(params.date_debut)

    # mensualité après différé (si différé, on amortit sur le reste)
    n_amort = max(n - diff_n, 1)
    mensualite_calc = params.mensualite
    if mensualite_calc is None:
        mensualite_calc = _mensualite_standard(P, r_m, n_amort)

    rows: List[Dict[str, Any]] = []
    crd = P

    for i in range(1, n + 1):
        date_ech = (start + pd.DateOffset(months=i-1)).strftime("%Y-%m-%d")
        annee = int(pd.to_datetime(date_ech).year)
        mois = int(pd.to_datetime(date_ech).month)

        interets = crd * r_m
        capital_amorti = 0.0

        is_differe = (i <= diff_n and params.differe_type != "aucun")

        # assurance ce mois
        assurance_mois = assurance if (not is_differe or params.assurance_pendant_differe) else 0.0

        if is_differe:
            if params.differe_type == "partiel":
                # on paie intérêts (et assurance éventuellement), mais pas de capital
                mensualite = interets + assurance_mois
                # CRD ne bouge pas
            else:
                # differe total
                if params.interets_pendant_differe == "capitalises":
                    # rien payé (ou seulement assurance), intérêts s'ajoutent au CRD
                    mensualite = 0.0 + assurance_mois
                    crd = crd + interets  # capitalisation des intérêts
                    interets = 0.0        # ici on considère qu'ils ne sont pas "payés", donc on les neutralise en flux
                else:
                    # intérêts payés (mais capital non), CRD stable
                    # FIX: les intérêts sont réellement payés => ils doivent figurer dans la mensualité
                    mensualite = interets + assurance_mois
                    # CRD inchangé (capital non amorti), intérêts inclus dans la mensualité
        else:
            # phase amortissement normale
            mensualite = float(mensualite_calc) + assurance_mois
            interets = crd * r_m
            principal_part = float(mensualite_calc) - interets
            # Empêche d'amortir plus que le capital restant (Bug 9)
            capital_amorti = max(min(principal_part, crd), 0.0)
            crd = max(crd - capital_amorti, 0.0)

        rows.append({
            "date_echeance": date_ech,
            "mensualite": float(mensualite),
            "capital_amorti": float(capital_amorti),
            "interets": float(interets),
            "assurance": float(assurance_mois),
            "crd": float(crd),
            "annee": annee,
            "mois": mois
        })

    return rows



def get_crd_a_date(conn, credit_id: int, date_ref: str) -> float:
    """
    Retourne le CRD estimé à la date de référence.
    Prend la dernière échéance <= date_ref.
    Si rien trouvé, fallback sur le premier CRD.
    """
    rows = conn.execute(
        """
        SELECT date_echeance, crd
        FROM credit_amortissements
        WHERE credit_id = ?
        ORDER BY date_echeance
        """,
        (int(credit_id),),
    ).fetchall()
    if not rows:
        return 0.0
    df = pd.DataFrame(rows, columns=["date_echeance", "crd"])

    df["date_echeance"] = pd.to_datetime(df["date_echeance"], errors="coerce")
    df["crd"] = pd.to_numeric(df["crd"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["date_echeance"])

    ref = pd.to_datetime(date_ref)
    past = df[df["date_echeance"] <= ref]
    if not past.empty:
        return float(past.iloc[-1]["crd"])

    # fallback : pas d'échéance passée (crédit très récent) => premier CRD
    return float(df.iloc[0]["crd"])


def cout_reel_mois_credit_via_bankin(conn, credit_id: int, mois_yyyy_mm_01: str) -> float:
    """
    Somme des transactions du mois sur le compte payeur du crédit,
    filtrées sur catégorie "échéance prêt / emprunt".
    """
    try:
        row = conn.execute(
            "SELECT person_id, payer_account_id FROM credits WHERE id = ?",
            (int(credit_id),)
        ).fetchone()
    except Exception:
        return 0.0
    if not row:
        return 0.0
    try:
        payer_val = row["payer_account_id"]
    except (TypeError, KeyError):
        payer_val = row[1] if len(row) > 1 else None
    if payer_val is None:
        logger.warning("cout_reel_mois_credit_via_bankin: credit_id=%s n'a pas de payer_account_id, retour 0.0", credit_id)
        return 0.0
    try:
        person_id = int(row["person_id"])
    except (TypeError, KeyError):
        person_id = int(row[0])
    payer_account_id = int(payer_val)

    start = pd.to_datetime(mois_yyyy_mm_01)
    end = (start + pd.offsets.MonthBegin(1))

    df = pd.read_sql_query(
        """
        SELECT amount, category, type
        FROM transactions
        WHERE person_id = ?
          AND account_id = ?
          AND date >= ?
          AND date < ?
        """,
        conn,
        params=[person_id, payer_account_id, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")],
    )

    if df.empty:
        return 0.0

    cat = df["category"].fillna("").str.lower()
    mask_cat = (
        (cat.str.contains("échéance", regex=False) | cat.str.contains("echeance", regex=False))
        & (cat.str.contains("prêt", regex=False) | cat.str.contains("pret", regex=False) | cat.str.contains("emprunt", regex=False))
    )

    # ton import Bankin met type="DEPENSE" si Amount < 0
    typ = df["type"].fillna("").str.upper()
    mask_type = typ.isin(["DEPENSE", "DEBIT", "OUT"])

    mask = mask_cat & mask_type
    return float(pd.to_numeric(df.loc[mask, "amount"], errors="coerce").fillna(0.0).sum())



def get_credit_dates(conn, credit_id: int) -> dict:
    """
    Retourne:
      - date_debut_echeances: première échéance du tableau
      - date_debut_remboursement: première échéance où capital_amorti > 0
      - date_fin: dernière échéance du tableau
    """
    rows = conn.execute(
        """
        SELECT date_echeance, capital_amorti
        FROM credit_amortissements
        WHERE credit_id = ?
        ORDER BY date_echeance
        """,
        (int(credit_id),),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["date_echeance", "capital_amorti"]) if rows else pd.DataFrame(columns=["date_echeance", "capital_amorti"])

    if df.empty:
        return {
            "date_debut_echeances": None,
            "date_debut_remboursement": None,
            "date_fin": None,
        }

    df["date_echeance"] = pd.to_datetime(df["date_echeance"], errors="coerce")
    df["capital_amorti"] = pd.to_numeric(df["capital_amorti"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["date_echeance"]).sort_values("date_echeance")

    date_debut_echeances = df.iloc[0]["date_echeance"].date()
    date_fin = df.iloc[-1]["date_echeance"].date()

    cap = df[df["capital_amorti"] > 0]
    date_debut_remboursement = cap.iloc[0]["date_echeance"].date() if not cap.empty else None

    return {
        "date_debut_echeances": date_debut_echeances,
        "date_debut_remboursement": date_debut_remboursement,
        "date_fin": date_fin,
    }
