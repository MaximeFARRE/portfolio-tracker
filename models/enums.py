from enum import Enum

class AccountType(str, Enum):
    PEA = "PEA"
    CTO = "CTO"
    CASH = "CASH"
    PE = "PE"
    CRYPTO = "CRYPTO"
    REAL_ESTATE = "REAL_ESTATE"
    LOAN = "LOAN"

class AssetType(str, Enum):
    stock = "stock"
    etf = "etf"
    crypto = "crypto"
    private_equity = "private_equity"
    cash_equivalent = "cash_equivalent"
    real_estate = "real_estate"
    other = "other"

class TxType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    EXPENSE = "EXPENSE"
    FEE = "FEE"
    INTEREST = "INTEREST"
    LOAN_PAYMENT = "LOAN_PAYMENT"
    RENT_INCOME = "RENT_INCOME"
    TAX = "TAX"
