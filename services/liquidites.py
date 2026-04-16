import logging
import pandas as pd
from services import repositories as repo
from services import pe_cash_repository as pe_cash_repo
from services import fx
from services.asset_panel_mapping import INVESTMENT_ACCOUNT_TYPES
from utils.validators import sens_flux

logger = logging.getLogger(__name__)

_SENS_MAP = {
    "DEPOT": 1.0,
    "ENTREE": 1.0,
    "CREDIT": 1.0,
    "VENTE": 1.0,
    "DIVIDENDE": 1.0,
    "INTERETS": 1.0,
    "LOYER": 1.0,
    "ABONDEMENT": 1.0,
    "RETRAIT": -1.0,
    "SORTIE": -1.0,
    "DEBIT": -1.0,
    "ACHAT": -1.0,
    "DEPENSE": -1.0,
    "FRAIS": -1.0,
    "IMPOT": -1.0,
    "REMBOURSEMENT_CREDIT": -1.0,
}


def _livret_balance_from_tx(tx_df: pd.DataFrame) -> float:
    """Solde d'un livret : seuls DEPOT (+), RETRAIT (-) et INTERETS (+) sont valides."""
    if tx_df is None or tx_df.empty:
        return 0.0
    df = tx_df.copy()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
    type_upper = df.get("type", "").astype(str).str.strip().str.upper()
    depot    = float(df.loc[type_upper == "DEPOT",    "amount"].sum())
    retrait  = float(df.loc[type_upper == "RETRAIT",  "amount"].sum())
    interets = float(df.loc[type_upper == "INTERETS", "amount"].sum())
    return round(depot - retrait + interets, 2)


def _bank_balance_from_tx(tx_df: pd.DataFrame) -> float:
    if tx_df is None or tx_df.empty:
        return 0.0
    df = tx_df.copy()
    df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
    type_norm = df.get("type", "").astype(str).str.strip().str.upper()
    signs = type_norm.map(_SENS_MAP)
    if signs.isna().any():
        # Fallback strict sur la logique existante si un type non standard apparait.
        signs = type_norm.apply(sens_flux).astype(float)
    return float(round(float((df["amount"] * signs).sum()), 2))

def _compute_liquidites_like_overview(conn, person_id: int):
    accounts = repo.list_accounts(conn, person_id=person_id)
    if accounts is None or accounts.empty:
        return 0.0, 0.0, 0.0, 0.0, []

    fx_cache: dict[tuple[str, str], float | None] = {}
    missing_fx: list[dict] = []

    def _convert_cached(amount: float, from_ccy: str, to_ccy: str = "EUR") -> float | None:
        key = (str(from_ccy or "EUR").upper(), str(to_ccy or "EUR").upper())
        if key[0] == key[1]:
            return float(amount)
        if key not in fx_cache:
            fx_cache[key] = fx.convert(conn, 1.0, key[0], key[1])
        rate = fx_cache[key]
        if rate is None:
            return None
        return float(amount) * float(rate)

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
                    total_native += _bank_balance_from_tx(tx)
        else:
            tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
            total_native += _bank_balance_from_tx(tx)

        eur = _convert_cached(total_native, acc_ccy, "EUR")
        if eur is None:
            logger.warning(
                "_compute_liquidites: FX %s→EUR indisponible pour compte %s, ignoré du total.",
                acc_ccy, acc_id,
            )
            missing_fx.append({
                "component": "bank",
                "account_id": acc_id,
                "currency": acc_ccy,
                "amount_native": round(float(total_native), 2),
            })
            continue
        bank_total_eur += eur

    bank_total_eur = round(float(bank_total_eur), 2)

    # ── Livrets (DEPOT/RETRAIT/INTERETS, pas de container, toujours EUR) ──────
    livret_total_eur = 0.0
    df_livrets = accounts[accounts["account_type"].astype(str).str.upper() == "LIVRET"].copy()
    for _, acc in df_livrets.iterrows():
        acc_id = int(acc["id"])
        acc_ccy = str(acc.get("currency", "EUR") or "EUR").upper()
        tx = repo.list_transactions(conn, person_id=person_id, account_id=acc_id, limit=100000)
        total_native = _livret_balance_from_tx(tx)
        eur = _convert_cached(total_native, acc_ccy, "EUR")
        if eur is None:
            logger.warning(
                "_compute_liquidites: FX %s→EUR indisponible pour livret %s, ignoré du total.",
                acc_ccy, acc_id,
            )
            missing_fx.append({
                "component": "livret",
                "account_id": acc_id,
                "currency": acc_ccy,
                "amount_native": round(float(total_native), 2),
            })
            continue
        livret_total_eur += eur
    livret_total_eur = round(float(livret_total_eur), 2)

    bourse_total_eur = 0.0
    df_bourse = accounts[
        accounts["account_type"].astype(str).str.upper().isin(INVESTMENT_ACCOUNT_TYPES)
    ].copy()
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

        eur = _convert_cached(cash_native, acc_ccy, "EUR")
        if eur is None:
            logger.warning(
                "_compute_liquidites: FX %s→EUR indisponible pour compte bourse %s, ignoré du total.",
                acc_ccy, acc_id,
            )
            missing_fx.append({
                "component": "bourse",
                "account_id": acc_id,
                "currency": acc_ccy,
                "amount_native": round(float(cash_native), 2),
            })
            continue
        bourse_total_eur += eur

    bourse_total_eur = round(float(bourse_total_eur), 2)

    pe_cash_tx = pe_cash_repo.list_pe_cash_transactions(conn, person_id=person_id)
    pe_total_eur = 0.0
    if pe_cash_tx is not None and not pe_cash_tx.empty:
        df = pe_cash_tx.copy()
        df["tx_type"] = df["tx_type"].astype(str).str.upper()
        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        pe_total_eur = float(df.apply(lambda r: float(r["amount"]) if r["tx_type"] == "DEPOSIT" else -float(r["amount"]), axis=1).sum())
    pe_total_eur = round(float(pe_total_eur), 2)

    total = round(float(bank_total_eur + livret_total_eur + bourse_total_eur + pe_total_eur), 2)
    return bank_total_eur, livret_total_eur, bourse_total_eur, pe_total_eur, total, missing_fx


def get_liquidites_summary(conn, person_id: int) -> dict:
    """
    Point d'entrée officiel pour la synthèse des liquidités d'une personne.

    Retourne un dictionnaire avec :
        bank_cash_eur    float  — solde comptes bancaires BANQUE (EUR)
        livret_cash_eur  float  — solde livrets réglementés (EUR)
        bourse_cash_eur  float  — cash non investi sur comptes bourse (EUR)
        pe_cash_eur      float  — cash sur plateformes PE (EUR)
        total_eur        float  — somme des quatre composantes

    `quality_status` vaut `partial` si un compte a été exclu faute de FX.
    """
    bank, livret, bourse, pe, total, missing_fx = _compute_liquidites_like_overview(conn, person_id)

    if total == 0.0 and not missing_fx:
        logger.info(
            "get_liquidites_summary: aucune liquidité pour person_id=%s", person_id,
        )
    elif missing_fx:
        logger.warning(
            "get_liquidites_summary: synthèse partielle pour person_id=%s, FX manquants=%s",
            person_id, missing_fx,
        )

    return {
        "bank_cash_eur": bank,
        "livret_cash_eur": livret,
        "bourse_cash_eur": bourse,
        "pe_cash_eur": pe,
        "total_eur": total,
        "quality_status": "partial" if missing_fx else "ok",
        "missing_fx": missing_fx,
    }

