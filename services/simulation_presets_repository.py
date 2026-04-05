"""
services/simulation_presets_repository.py
CRUD pour les presets de simulation (pessimiste / realiste / optimiste) par scope.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Valeurs par défaut des presets ────────────────────────────────────────────

PRESET_KEYS = ("pessimiste", "realiste", "optimiste")

PRESET_DEFAULTS: dict[str, dict] = {
    "pessimiste": {
        "return_liquidites_pct":  1.5,
        "return_bourse_pct":      4.0,
        "return_immobilier_pct":  2.0,
        "return_pe_pct":          5.0,
        "return_entreprises_pct": 3.0,
        "inflation_pct":          3.0,
        "income_growth_pct":      0.5,
        "expense_growth_pct":     2.0,
        "fire_multiple":         27.0,
        "savings_factor":         0.85,
    },
    "realiste": {
        "return_liquidites_pct":  2.0,
        "return_bourse_pct":      7.0,
        "return_immobilier_pct":  3.5,
        "return_pe_pct":         10.0,
        "return_entreprises_pct": 5.0,
        "inflation_pct":          2.0,
        "income_growth_pct":      1.0,
        "expense_growth_pct":     1.0,
        "fire_multiple":         25.0,
        "savings_factor":         1.0,
    },
    "optimiste": {
        "return_liquidites_pct":  3.0,
        "return_bourse_pct":      9.0,
        "return_immobilier_pct":  5.0,
        "return_pe_pct":         15.0,
        "return_entreprises_pct": 8.0,
        "inflation_pct":          1.5,
        "income_growth_pct":      2.0,
        "expense_growth_pct":     0.5,
        "fire_multiple":         25.0,
        "savings_factor":         1.15,
    },
}

_PRESET_FIELDS = (
    "return_liquidites_pct",
    "return_bourse_pct",
    "return_immobilier_pct",
    "return_pe_pct",
    "return_entreprises_pct",
    "inflation_pct",
    "income_growth_pct",
    "expense_growth_pct",
    "fire_multiple",
    "savings_factor",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else float(default)
    except (TypeError, ValueError):
        return float(default)


def _normalize_scope(scope_type: str, scope_id: Optional[int]):
    st = (scope_type or "").strip().lower()
    if st == "family":
        return st, None
    if st == "person":
        if scope_id is None:
            raise ValueError("scope_id requis pour scope_type='person'")
        return st, int(scope_id)
    raise ValueError(f"scope_type invalide : {scope_type!r}")


def _row_as_dict(row: Any) -> dict:
    if row is None:
        return {}
    try:
        return dict(row)
    except Exception:
        return {}


def _fetch_row(conn, scope_type: str, scope_id: Optional[int], preset: str):
    """Retourne la ligne de preset ou None."""
    if scope_id is None:
        return conn.execute(
            """
            SELECT * FROM simulation_preset_settings
            WHERE scope_type = ? AND scope_id IS NULL AND preset = ?
            LIMIT 1
            """,
            (scope_type, preset),
        ).fetchone()
    return conn.execute(
        """
        SELECT * FROM simulation_preset_settings
        WHERE scope_type = ? AND scope_id = ? AND preset = ?
        LIMIT 1
        """,
        (scope_type, int(scope_id), preset),
    ).fetchone()


# ── API publique ──────────────────────────────────────────────────────────────

def get_preset(conn, preset: str, scope_type: str, scope_id: Optional[int] = None) -> dict:
    """
    Retourne les paramètres du preset pour le scope donné.
    Replie sur les valeurs par défaut si aucune entrée en BDD.
    """
    preset = preset.lower()
    if preset not in PRESET_KEYS:
        raise ValueError(f"Preset invalide : {preset!r}")
    st, sid = _normalize_scope(scope_type, scope_id)

    defaults = PRESET_DEFAULTS[preset]
    try:
        row = _fetch_row(conn, st, sid, preset)
    except Exception:
        row = None

    if row is None:
        return {"preset": preset, "scope_type": st, "scope_id": sid, **defaults}

    result = {"preset": preset, "scope_type": st, "scope_id": sid}
    for field in _PRESET_FIELDS:
        try:
            result[field] = _to_float(row[field], defaults[field])
        except Exception:
            result[field] = defaults[field]
    return result


def get_all_presets(conn, scope_type: str, scope_id: Optional[int] = None) -> dict[str, dict]:
    """Retourne {preset_key: params_dict} pour les 3 presets du scope."""
    return {pk: get_preset(conn, pk, scope_type, scope_id) for pk in PRESET_KEYS}


def initialize_default_presets(conn, scope_type: str, scope_id: Optional[int] = None) -> None:
    """
    Insère les 3 presets par défaut pour un scope si absents.
    À appeler après le changement de scope ou au démarrage.
    """
    st, sid = _normalize_scope(scope_type, scope_id)
    for preset, defaults in PRESET_DEFAULTS.items():
        try:
            existing = _fetch_row(conn, st, sid, preset)
            if existing is not None:
                continue
            conn.execute(
                """
                INSERT INTO simulation_preset_settings
                  (scope_type, scope_id, preset,
                   return_liquidites_pct, return_bourse_pct, return_immobilier_pct,
                   return_pe_pct, return_entreprises_pct,
                   inflation_pct, income_growth_pct, expense_growth_pct,
                   fire_multiple, savings_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    st, sid, preset,
                    defaults["return_liquidites_pct"],
                    defaults["return_bourse_pct"],
                    defaults["return_immobilier_pct"],
                    defaults["return_pe_pct"],
                    defaults["return_entreprises_pct"],
                    defaults["inflation_pct"],
                    defaults["income_growth_pct"],
                    defaults["expense_growth_pct"],
                    defaults["fire_multiple"],
                    defaults["savings_factor"],
                ),
            )
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass


def update_preset(
    conn,
    preset: str,
    scope_type: str,
    scope_id: Optional[int] = None,
    params: Optional[dict] = None,
) -> None:
    """
    Upsert des paramètres d'un preset pour un scope donné.
    Les champs absents de `params` conservent leurs valeurs existantes ou les défauts.
    """
    preset = preset.lower()
    if preset not in PRESET_KEYS:
        raise ValueError(f"Preset invalide : {preset!r}")
    st, sid = _normalize_scope(scope_type, scope_id)
    p = params or {}
    defaults = PRESET_DEFAULTS[preset]

    # Lire les valeurs actuelles pour ne pas écraser ce qui n'est pas fourni
    existing = {}
    try:
        row = _fetch_row(conn, st, sid, preset)
        if row is not None:
            existing = _row_as_dict(row)
    except Exception:
        pass

    def _val(field: str) -> float:
        if field in p:
            return _to_float(p[field], defaults[field])
        if field in existing:
            return _to_float(existing[field], defaults[field])
        return defaults[field]

    vals = tuple(_val(f) for f in _PRESET_FIELDS)

    if existing:
        # UPDATE
        set_clause = ", ".join(f"{f} = ?" for f in _PRESET_FIELDS)
        if sid is None:
            conn.execute(
                f"UPDATE simulation_preset_settings SET {set_clause} "
                f"WHERE scope_type = ? AND scope_id IS NULL AND preset = ?",
                vals + (st, preset),
            )
        else:
            conn.execute(
                f"UPDATE simulation_preset_settings SET {set_clause} "
                f"WHERE scope_type = ? AND scope_id = ? AND preset = ?",
                vals + (st, int(sid), preset),
            )
    else:
        # INSERT
        conn.execute(
            """
            INSERT INTO simulation_preset_settings
              (scope_type, scope_id, preset,
               return_liquidites_pct, return_bourse_pct, return_immobilier_pct,
               return_pe_pct, return_entreprises_pct,
               inflation_pct, income_growth_pct, expense_growth_pct,
               fire_multiple, savings_factor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (st, sid, preset) + vals,
        )
    conn.commit()
