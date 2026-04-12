"""
Utilitaires bas niveau partagés par tous les services.
Pas de dépendances internes — importer librement.
"""
from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convertit en float avec fallback sûr."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def row_get(row: Any, key: str, idx: int = 0):
    """Accès tolérant à une row (dict-like ou tuple-like)."""
    if row is None:
        return None
    try:
        return row[key]
    except Exception:
        try:
            return row[idx]
        except Exception:
            return None


def fmt_amount(value: Any) -> str:
    """Formate un montant avec séparateur d'espace et 2 décimales."""
    num = safe_float(value, 0.0)
    return f"{num:,.2f}".replace(",", " ")

