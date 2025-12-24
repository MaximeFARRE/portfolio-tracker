def eur(x: float) -> str:
    try:
        return f"{x:,.2f} €".replace(",", " ").replace(".", ",")
    except Exception:
        return f"{x} €"
