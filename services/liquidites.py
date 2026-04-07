import logging
import pandas as pd
from services import repositories as repo
from services import pe_cash_repository as pe_cash_repo
from utils.validators import sens_flux

logger = logging.getLogger(__name__)

def _fx_to_eur(conn, amount: float, ccy: str) -> float:
    ccy = (ccy or "EUR").upper()
    if ccy == "EUR":
        return float(amount)

    row = repo.get_latest_fx_rate(conn, base_ccy=ccy, quote_ccy="EUR")
    if row is not None:
        rate = float(row["rate"]) if isinstance(row, dict) else float(row[0])
        return float(amount) * rate

    row2 = repo.get_latest_fx_rate(conn, base_ccy="EUR", quote_ccy=ccy)
    if row2 is not None:
        rate = float(row2["rate"]) if isinstance(row2, dict) else float(row2[0])
        if abs(rate) > 1e-12:
            return float(amount) / rate

    return float(amount)

def _bank_balance_from_tx(tx_df: pd.DataFrame) -> float:
    if tx_df is None or tx_df.empty:
        return 0.0
    s = 0.0
    for _, r in tx_df.iterrows():
        s += float(r.get("amount", 0.0) or 0.0) * sens_flux(str(r.get("type", "")))
    return float(round(s, 2))

def _compute_liquidites_like_overview(conn, person_id: int):
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0, 0.0, 0.0, 0.0

    bank_total_eur = 0.0
    df_banks = accounts[accounts["account_type"].astype(str).str.upper() == "BANQUE"].copy()
    for _, acc in df_banks.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        try:
            is_container = repo.is_bank_container(conn, acc_id)
        except Exception:
            is_container = False

        total_native = 0.0
        if is_container:
            subs = repo.list_bank_subaccounts(conn, acc_id)
            if subs is not None and not subs.empty:
                for _, s in subs.iterrows():
                    sub_id = int(s["sub_account_id"])
                    tx = repo.list_transactions(conn, person_id=person_id, account_id=sub_id, limit=100000)
                    if tx is not None and not tx.empty:
                        for _, r in tx.iterrows():
                            total_native += float(r.get("amount", 0.0) or 0.0) * sens_flux(str(r.get("type", "")))
        else:
            tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
            if tx is not None and not tx.empty:
                for _, r in tx.iterrows():
                    total_native += float(r.get("amount", 0.0) or 0.0) * sens_flux(str(r.get("type", "")))

        bank_total_eur += float(_fx_to_eur(conn, total_native, acc_ccy))

    bank_total_eur = round(float(bank_total_eur), 2)

    bourse_total_eur = 0.0
    df_bourse = accounts[accounts["account_type"].astype(str).str.upper().isin(["PEA", "CTO", "CRYPTO"])].copy()
    for _, acc in df_bourse.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()

        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
        cash_native = 0.0
        if tx is not None and not tx.empty:
            df = tx.copy()
            df["type"] = df["type"].astype(str)
            df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
            df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

            cash_native += float(df.loc[df["type"] == "DEPOT", "amount"].sum())
            cash_native -= float(df.loc[df["type"] == "RETRAIT", "amount"].sum())
            cash_native -= float(df.loc[df["type"] == "ACHAT", "amount"].sum())
            cash_native += float(df.loc[df["type"] == "VENTE", "amount"].sum())
            cash_native += float(df.loc[df["type"] == "DIVIDENDE", "amount"].sum())
            cash_native += float(df.loc[df["type"] == "INTERETS", "amount"].sum())
            cash_native -= float(df.loc[df["type"] == "FRAIS", "amount"].sum())
            cash_native -= float(df["fees"].sum())

        bourse_total_eur += float(_fx_to_eur(conn, cash_native, acc_ccy))

    bourse_total_eur = round(float(bourse_total_eur), 2)

    pe_cash_tx = pe_cash_repo.list_pe_cash_transactions(conn, person_id=person_id)
    pe_total_eur = 0.0
    if pe_cash_tx is not None and not pe_cash_tx.empty:
        df = pe_cash_tx.copy()
        df["tx_type"] = df["tx_type"].astype(str).str.upper()
        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        pe_total_eur = float(df.apply(lambda r: float(r["amount"]) if r["tx_type"] == "DEPOSIT" else -float(r["amount"]), axis=1).sum())
    pe_total_eur = round(float(pe_total_eur), 2)

    total = round(float(bank_total_eur + bourse_total_eur + pe_total_eur), 2)
    return bank_total_eur, bourse_total_eur, pe_total_eur, total


def get_liquidites_summary(conn, person_id: int) -> dict:
    """
    Point d'entrée officiel pour la synthèse des liquidités d'une personne.

    Retourne un dictionnaire avec :
        bank_cash_eur    float  — solde comptes bancaires (EUR)
        bourse_cash_eur  float  — cash non investi sur comptes bourse (EUR)
        pe_cash_eur      float  — cash sur plateformes PE (EUR)
        total_eur        float  — somme des trois

    Retourne des zéros si aucune liquidité disponible.
    """
    bank, bourse, pe, total = _compute_liquidites_like_overview(conn, person_id)

    if total == 0.0:
        logger.info(
            "get_liquidites_summary: aucune liquidité pour person_id=%s", person_id,
        )

    return {
        "bank_cash_eur": bank,
        "bourse_cash_eur": bourse,
        "pe_cash_eur": pe,
        "total_eur": total,
    }

