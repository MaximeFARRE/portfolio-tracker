def eur(x) -> str:
    try:
        return f"{float(x):,.2f} €".replace(",", " ").replace(".00", "")
    except Exception:
        return f"{x} €"
