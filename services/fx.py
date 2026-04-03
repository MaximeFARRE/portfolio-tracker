import logging
import requests
from services import repositories as repo
from services import pricing

logger = logging.getLogger(__name__)


def fetch_fx_rate(base_ccy: str, quote_ccy: str) -> float | None:
    """
    API simple : Frankfurter.
    Exemple: https://api.frankfurter.app/latest?from=USD&to=EUR
    """
    base_ccy = (base_ccy or "").upper()
    quote_ccy = (quote_ccy or "").upper()
    if not base_ccy or not quote_ccy:
        return None
    if base_ccy == quote_ccy:
        return 1.0

    url = f"https://api.frankfurter.app/latest?from={base_ccy}&to={quote_ccy}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return None

    data = r.json()
    return float(data["rates"][quote_ccy])


def ensure_fx_rate(conn, base_ccy: str, quote_ccy: str) -> float | None:
    """
    Renvoie un taux base->quote.
    - prend le dernier en base si dispo
    - sinon fetch web + insert en DB
    - retourne None si aucune source n'a pu fournir le taux (loggué)
    """
    base_ccy = (base_ccy or "").upper()
    quote_ccy = (quote_ccy or "").upper()

    if base_ccy == quote_ccy:
        return 1.0

    row = repo.get_latest_fx_rate(conn, base_ccy, quote_ccy)
    if row:
        return float(row["rate"])

    rate = fetch_fx_rate(base_ccy, quote_ccy)
    if rate is not None:
        repo.insert_fx_rate(conn, base_ccy, quote_ccy, pricing.today_str(), rate)
    else:
        logger.warning(
            "FX: impossible de récupérer le taux %s→%s (DB vide + API en échec). "
            "Aucune conversion ne sera appliquée.",
            base_ccy,
            quote_ccy,
        )
    return rate


def convert(conn, amount: float, from_ccy: str, to_ccy: str) -> float | None:
    """
    Convertit amount de from_ccy vers to_ccy.

    Retourne None si le taux de change est introuvable, afin que l'appelant
    puisse détecter l'échec et ne pas utiliser un montant non converti.
    Les appelants qui tolèrent un fallback à 0 peuvent écrire :
        result = convert(...) or 0.0
    """
    from_ccy = (from_ccy or "").upper()
    to_ccy = (to_ccy or "").upper()
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return float(amount)

    rate = ensure_fx_rate(conn, from_ccy, to_ccy)
    if rate is None:
        logger.error(
            "FX.convert: taux %s→%s indisponible. "
            "Montant %.4f NON converti — retourne None pour forcer la détection par l'appelant.",
            from_ccy,
            to_ccy,
            amount,
        )
        return None
    return float(amount) * float(rate)
