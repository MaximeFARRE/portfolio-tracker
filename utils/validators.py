def operation_requiert_actif(type_operation: str) -> bool:
    return type_operation in {"ACHAT", "VENTE", "DIVIDENDE"}


def operation_requiert_quantite_prix(type_operation: str) -> bool:
    return type_operation in {"ACHAT", "VENTE"}


def sens_flux(type_operation: str) -> int:
    """
    Retourne +1 si ça augmente le solde du compte, -1 si ça le diminue.
    On suppose que amount est toujours positif saisi par l'utilisateur.
    """
    positifs = {"DEPOT", "RETRAIT", "VENTE", "DIVIDENDE", "INTERETS", "LOYER"}
    negatifs = {"ACHAT", "DEPENSE", "FRAIS", "IMPOT", "REMBOURSEMENT_CREDIT"}

    if type_operation in positifs:
        return +1
    if type_operation in negatifs:
        return -1
    return -1
