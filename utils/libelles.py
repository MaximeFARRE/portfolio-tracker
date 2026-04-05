# Libellés et codes normalisés (sans accents en base, affichage en français).

# Types de compte en base
TYPES_COMPTE = [
    "BANQUE", "PEA", "PEA_PME", "CTO", "CRYPTO",
    "ASSURANCE_VIE", "PER", "PEE",
    "IMMOBILIER", "CREDIT", "PE",
]

LIBELLES_TYPE_COMPTE = {
    "BANQUE":        "Banque",
    "PEA":           "PEA",
    "PEA_PME":       "PEA-PME",
    "CTO":           "Compte-titres",
    "CRYPTO":        "Crypto",
    "ASSURANCE_VIE": "Assurance-vie",
    "PER":           "PER",
    "PEE":           "PEE",
    "IMMOBILIER":    "Immobilier",
    "CREDIT":        "Crédit",
    "PE":            "Private equity",
}

# Types d'opération en base
TYPES_OPERATION = [
    "ACHAT", "VENTE", "DIVIDENDE",
    "DEPOT", "RETRAIT",
    "DEPENSE", "FRAIS", "IMPOT",
    "INTERETS", "REMBOURSEMENT_CREDIT",
    "LOYER", "ABONDEMENT",
]

LIBELLES_TYPE_OPERATION = {
    "ACHAT":                 "Achat",
    "VENTE":                 "Vente",
    "DIVIDENDE":             "Dividende",
    "DEPOT":                 "Dépôt",
    "RETRAIT":               "Retrait",
    "DEPENSE":               "Dépense",
    "FRAIS":                 "Frais",
    "IMPOT":                 "Impôt",
    "INTERETS":              "Intérêts",
    "REMBOURSEMENT_CREDIT":  "Remboursement crédit",
    "LOYER":                 "Loyer",
    "ABONDEMENT":            "Abondement",
}

# Suggestions catégories (dépenses)
CATEGORIES_DEPENSES = [
    "Alimentation", "Transport", "Logement", "Santé", "Loisirs",
    "Abonnements", "Restaurants", "Shopping", "Vacances", "Divers"
]


def afficher_type_compte(code: str) -> str:
    return LIBELLES_TYPE_COMPTE.get(code, code)


def afficher_type_operation(code: str) -> str:
    return LIBELLES_TYPE_OPERATION.get(code, code)


def code_operation_depuis_libelle(libelle: str) -> str:
    for k, v in LIBELLES_TYPE_OPERATION.items():
        if v == libelle:
            return k
    return "DEPENSE"
