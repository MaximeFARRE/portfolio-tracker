def operation_requiert_actif(type_operation: str) -> bool:
    return type_operation in {"ACHAT", "VENTE", "DIVIDENDE"}


def operation_requiert_quantite_prix(type_operation: str) -> bool:
    return type_operation in {"ACHAT", "VENTE"}


def sens_flux(type_operation: str) -> int:
    """
    Retourne +1 si ça augmente le solde du compte, -1 si ça le diminue.
    On suppose que amount est toujours positif saisi par l'utilisateur.

    Positifs  : opérations qui CREDITENT le compte (entrée d'argent).
    Négatifs  : opérations qui DEBITENT le compte (sortie d'argent).
    """
    positifs = {
        "DEPOT",    # dépôt d'argent sur le compte → +
        "ENTREE",   # entrée générique (alias DEPOT) → +
        "CREDIT",   # crédit générique → +
        "VENTE",    # cession d'actif, cash entrant → +
        "DIVIDENDE",# revenu financier → +
        "INTERETS", # intérêts reçus → +
        "LOYER",    # loyer perçu → +
    }
    negatifs = {
        "RETRAIT",              # retrait d'argent du compte → -
        "SORTIE",               # sortie générique (alias RETRAIT) → -
        "DEBIT",                # débit générique → -
        "ACHAT",                # achat d'actif, cash sortant → -
        "DEPENSE",              # dépense courante → -
        "FRAIS",                # frais bancaires/courtage → -
        "IMPOT",                # impôt → -
        "REMBOURSEMENT_CREDIT", # remboursement d'emprunt → -
    }

    type_op = (type_operation or "").strip().upper()

    if type_op in positifs:
        return +1
    if type_op in negatifs:
        return -1

    # Type inconnu : on lève une ValueError pour éviter tout calcul silencieusement faux.
    raise ValueError(
        f"sens_flux: type_operation inconnu '{type_operation}'. "
        f"Positifs attendus: {sorted(positifs)}. "
        f"Négatifs attendus: {sorted(negatifs)}."
    )
