"""
Source de vérité: mapping des types d'actifs vers les panels métier.

Objectif:
- éviter la dispersion de règles `asset_type -> panel` dans les services/UI
- exposer des helpers simples réutilisables par les calculs métier
"""
from __future__ import annotations


ASSET_TYPES_CANONICAL = [
    "action",
    "etf",
    "fonds",
    "scpi",
    "obligation",
    "fonds_euros",
    "crypto",
    "private_equity",
    "non_cote",
    "autre",
]

# Mapping cible V1 (choix métier explicites):
# - fonds_euros: fallback sur bourse (faute de panel épargne dédié)
# - autre: fallback explicite sur bourse
ASSET_TYPE_TO_PANEL = {
    "action": "bourse",
    "etf": "bourse",
    "obligation": "bourse",
    "crypto": "bourse",
    "fonds_euros": "bourse",
    "autre": "bourse",
    "scpi": "immobilier",
    "fonds": "private_equity",
    "private_equity": "private_equity",
    "non_cote": "private_equity",
}

# Tous les comptes d'investissement multi-supports pilotés par le panel CompteBourse.
INVESTMENT_ACCOUNT_TYPES = {
    "PEA",
    "PEA_PME",
    "CTO",
    "CRYPTO",
    "ASSURANCE_VIE",
    "PER",
    "PEE",
}


def normalize_asset_type(asset_type: str | None) -> str:
    return str(asset_type or "autre").strip().lower() or "autre"


def panel_for_asset_type(asset_type: str | None) -> str:
    at = normalize_asset_type(asset_type)
    return ASSET_TYPE_TO_PANEL.get(at, "bourse")


def asset_types_for_panel(panel: str) -> set[str]:
    target = str(panel or "").strip().lower()
    return {asset for asset, mapped in ASSET_TYPE_TO_PANEL.items() if mapped == target}


def is_asset_type_in_panel(asset_type: str | None, panel: str) -> bool:
    return panel_for_asset_type(asset_type) == str(panel or "").strip().lower()

