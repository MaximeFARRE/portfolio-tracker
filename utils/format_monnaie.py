def ccy_symbol(ccy: str) -> str:
    ccy = (ccy or "EUR").upper()
    return {
        "EUR": "€",
        "USD": "$",
        "GBP": "£",
        "JPY": "¥",
        "CHF": "CHF",
        "CAD": "CAD",
        "AUD": "AUD",
    }.get(ccy, ccy)


def money(x, ccy: str = "EUR") -> str:
    """Format standard : 12 345.67 $ (ou € / CHF / ...)"""
    try:
        v = float(x)
        return f"{v:,.2f} {ccy_symbol(ccy)}".replace(",", " ")
    except Exception:
        return f"{x} {ccy_symbol(ccy)}"


# Compat : si d'autres fichiers appellent eur(x)
def eur(x) -> str:
    return money(x, "EUR")
