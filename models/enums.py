from enum import Enum


class AccountType(str, Enum):
    BANQUE = "BANQUE"
    PEA = "PEA"
    CTO = "CTO"
    CRYPTO = "CRYPTO"
    PE = "PE"
    IMMOBILIER = "IMMOBILIER"
    CREDIT = "CREDIT"


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    PRIVATE_EQUITY = "private_equity"
    CASH_EQUIVALENT = "cash_equivalent"
    REAL_ESTATE = "real_estate"
    OTHER = "other"


class TxType(str, Enum):
    # Types utilisés en base de données (valeurs réelles)
    ACHAT = "ACHAT"
    VENTE = "VENTE"
    DIVIDENDE = "DIVIDENDE"
    DEPOT = "DEPOT"
    RETRAIT = "RETRAIT"
    DEPENSE = "DEPENSE"
    FRAIS = "FRAIS"
    INTERETS = "INTERETS"
    REMBOURSEMENT_CREDIT = "REMBOURSEMENT_CREDIT"
    LOYER = "LOYER"
    IMPOT = "IMPOT"
    ENTREE = "ENTREE"
    SORTIE = "SORTIE"
