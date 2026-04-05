import sqlite3
from datetime import date, datetime
from typing import Optional

import pandas as pd

from services.repositories import df_from_rows

_GOAL_STATUSES = {"ACTIVE", "ACHIEVED", "PAUSED", "CANCELLED"}
_GOAL_PRIORITIES = {"LOW", "NORMAL", "HIGH"}


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clean_text(value) -> Optional[str]:
    if value is None:
        return None
    txt = str(value).strip()
    return txt or None


def _require_name(value, field_name: str) -> str:
    name = _clean_text(value)
    if not name:
        raise ValueError(f"{field_name} est obligatoire.")
    return name


def _normalize_optional_date(value) -> Optional[str]:
    txt = _clean_text(value)
    if txt is None:
        return None
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("La date doit être au format YYYY-MM-DD.") from exc


def _normalize_goal_status(value) -> str:
    status = (_clean_text(value) or "ACTIVE").upper()
    if status not in _GOAL_STATUSES:
        raise ValueError("Statut objectif invalide.")
    return status


def _normalize_goal_priority(value) -> str:
    priority = (_clean_text(value) or "NORMAL").upper()
    if priority not in _GOAL_PRIORITIES:
        raise ValueError("Priorité objectif invalide.")
    return priority


def _validate_non_negative(value: float, field_name: str) -> float:
    number = _to_float(value, 0.0)
    if number < 0:
        raise ValueError(f"{field_name} ne peut pas être négatif.")
    return number


def _validate_float_range(value, field_name: str, minimum: float, maximum: float, default: float) -> float:
    number = _to_float(value, default)
    if number < minimum or number > maximum:
        raise ValueError(f"{field_name} doit être entre {minimum} et {maximum}.")
    return number


def compute_goal_monthly_required_amount(
    target_amount: float,
    current_amount: float,
    target_date: Optional[str],
    today: Optional[date] = None,
) -> float:
    """
    Montant mensuel nécessaire pour atteindre l'objectif à la date cible.
    Retourne 0.0 si la date est absente/invalide ou si l'objectif est déjà atteint.
    """
    remaining = max(_to_float(target_amount) - _to_float(current_amount), 0.0)
    if remaining <= 0:
        return 0.0

    target_iso = _normalize_optional_date(target_date)
    if target_iso is None:
        return 0.0

    target = datetime.strptime(target_iso, "%Y-%m-%d").date()
    today = today or date.today()
    months = (target.year - today.year) * 12 + (target.month - today.month)
    if months <= 0:
        return remaining
    return remaining / months


def _normalize_scope(scope_type: str, scope_id: Optional[int]):
    st = (scope_type or "").strip().lower()
    if st not in ("family", "person"):
        raise ValueError("scope_type must be 'family' or 'person'")

    if st == "family":
        return st, None

    if scope_id is None:
        raise ValueError("scope_id is required when scope_type='person'")
    return st, int(scope_id)


def list_people_for_scope(conn: sqlite3.Connection) -> pd.DataFrame:
    try:
        rows = conn.execute(
            """
            SELECT id, name
            FROM people
            ORDER BY id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return pd.DataFrame(columns=["id", "name"])
    return df_from_rows(rows, ["id", "name"])


def list_goals(
    conn: sqlite3.Connection,
    scope_type: str,
    scope_id: Optional[int] = None,
    status: Optional[str] = None,
) -> pd.DataFrame:
    st, sid = _normalize_scope(scope_type, scope_id)
    params = [st]
    where = ["scope_type = ?"]

    if st == "family":
        where.append("scope_id IS NULL")
    else:
        where.append("scope_id = ?")
        params.append(sid)

    if status:
        where.append("status = ?")
        params.append(str(status).strip().upper())

    try:
        rows = conn.execute(
            f"""
            SELECT
                id, name, scope_type, scope_id, category,
                target_amount, current_amount, target_date,
                priority, status, notes, created_at, updated_at
            FROM financial_goals
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.OperationalError:
        return pd.DataFrame(
            columns=[
                "id",
                "name",
                "scope_type",
                "scope_id",
                "category",
                "target_amount",
                "current_amount",
                "target_date",
                "priority",
                "status",
                "notes",
                "created_at",
                "updated_at",
            ]
        )

    return df_from_rows(
        rows,
        [
            "id",
            "name",
            "scope_type",
            "scope_id",
            "category",
            "target_amount",
            "current_amount",
            "target_date",
            "priority",
            "status",
            "notes",
            "created_at",
            "updated_at",
        ],
    )


def create_goal(conn: sqlite3.Connection, data: dict) -> int:
    st, sid = _normalize_scope(data.get("scope_type", "family"), data.get("scope_id"))
    payload = {
        "name": _require_name(data.get("name"), "Le nom de l'objectif"),
        "category": _clean_text(data.get("category")),
        "target_amount": _validate_non_negative(data.get("target_amount", 0), "Le montant cible"),
        "current_amount": _validate_non_negative(data.get("current_amount", 0), "Le montant actuel"),
        "target_date": _normalize_optional_date(data.get("target_date")),
        "priority": _normalize_goal_priority(data.get("priority")),
        "status": _normalize_goal_status(data.get("status")),
        "notes": _clean_text(data.get("notes")),
    }

    cur = conn.execute(
        """
        INSERT INTO financial_goals (
            name, scope_type, scope_id, category,
            target_amount, current_amount, target_date,
            priority, status, notes, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            payload["name"],
            st,
            sid,
            payload["category"],
            payload["target_amount"],
            payload["current_amount"],
            payload["target_date"],
            payload["priority"],
            payload["status"],
            payload["notes"],
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_goal(conn: sqlite3.Connection, goal_id: int, data: dict) -> None:
    payload = dict(data or {})
    row = conn.execute(
        "SELECT scope_type, scope_id FROM financial_goals WHERE id = ?",
        (int(goal_id),),
    ).fetchone()
    if row is None:
        return

    if "scope_type" in payload or "scope_id" in payload:
        scope_type = payload.get("scope_type", row["scope_type"])
        scope_id = payload.get("scope_id", row["scope_id"])
        st, sid = _normalize_scope(scope_type, scope_id)
        payload["scope_type"] = st
        payload["scope_id"] = sid

    if "name" in payload:
        payload["name"] = _require_name(payload.get("name"), "Le nom de l'objectif")
    if "category" in payload:
        payload["category"] = _clean_text(payload.get("category"))
    if "target_amount" in payload:
        payload["target_amount"] = _validate_non_negative(payload.get("target_amount"), "Le montant cible")
    if "current_amount" in payload:
        payload["current_amount"] = _validate_non_negative(payload.get("current_amount"), "Le montant actuel")
    if "target_date" in payload:
        payload["target_date"] = _normalize_optional_date(payload.get("target_date"))
    if "priority" in payload:
        payload["priority"] = _normalize_goal_priority(payload.get("priority"))
    if "status" in payload:
        payload["status"] = _normalize_goal_status(payload.get("status"))
    if "notes" in payload:
        payload["notes"] = _clean_text(payload.get("notes"))

    allowed_fields = [
        "name",
        "scope_type",
        "scope_id",
        "category",
        "target_amount",
        "current_amount",
        "target_date",
        "priority",
        "status",
        "notes",
    ]

    set_parts = []
    params = []
    for field in allowed_fields:
        if field in payload:
            set_parts.append(f"{field} = ?")
            params.append(payload[field])

    if not set_parts:
        return

    set_parts.append("updated_at = datetime('now')")
    params.append(int(goal_id))

    conn.execute(
        f"""
        UPDATE financial_goals
        SET {', '.join(set_parts)}
        WHERE id = ?
        """,
        tuple(params),
    )
    conn.commit()


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    conn.execute("DELETE FROM financial_goals WHERE id = ?", (int(goal_id),))
    conn.commit()


def list_scenarios(
    conn: sqlite3.Connection,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> pd.DataFrame:
    st, sid = _normalize_scope(scope_type, scope_id)
    params = [st]
    where = ["scope_type = ?"]

    if st == "family":
        where.append("scope_id IS NULL")
    else:
        where.append("scope_id = ?")
        params.append(sid)

    try:
        rows = conn.execute(
            f"""
            SELECT
                id, name, scope_type, scope_id, is_default,
                horizon_years, expected_return_pct, inflation_pct,
                income_growth_pct, expense_growth_pct, monthly_savings_override,
                fire_multiple, use_real_snapshot_base, initial_net_worth_override,
                return_liquidites_pct, return_bourse_pct, return_immobilier_pct,
                return_pe_pct, return_entreprises_pct, exclude_primary_residence,
                created_at, updated_at
            FROM projection_scenarios
            WHERE {' AND '.join(where)}
            ORDER BY is_default DESC, updated_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
    except sqlite3.OperationalError:
        return pd.DataFrame(
            columns=[
                "id", "name", "scope_type", "scope_id", "is_default",
                "horizon_years", "expected_return_pct", "inflation_pct",
                "income_growth_pct", "expense_growth_pct", "monthly_savings_override",
                "fire_multiple", "use_real_snapshot_base", "initial_net_worth_override",
                "return_liquidites_pct", "return_bourse_pct", "return_immobilier_pct",
                "return_pe_pct", "return_entreprises_pct", "exclude_primary_residence",
                "created_at", "updated_at",
            ]
        )

    return df_from_rows(
        rows,
        [
            "id", "name", "scope_type", "scope_id", "is_default",
            "horizon_years", "expected_return_pct", "inflation_pct",
            "income_growth_pct", "expense_growth_pct", "monthly_savings_override",
            "fire_multiple", "use_real_snapshot_base", "initial_net_worth_override",
            "return_liquidites_pct", "return_bourse_pct", "return_immobilier_pct",
            "return_pe_pct", "return_entreprises_pct", "exclude_primary_residence",
            "created_at", "updated_at",
        ],
    )


def create_scenario(conn: sqlite3.Connection, data: dict) -> int:
    st, sid = _normalize_scope(data.get("scope_type", "family"), data.get("scope_id"))
    payload = {
        "name": _require_name(data.get("name"), "Le nom du scénario"),
        "is_default": 1 if _to_int(data.get("is_default", 0)) else 0,
        "horizon_years": _to_int(data.get("horizon_years", 10), 10),
        "expected_return_pct": _validate_float_range(
            data.get("expected_return_pct", 6.0), "Le rendement attendu", -50.0, 50.0, 6.0
        ),
        "inflation_pct": _validate_float_range(
            data.get("inflation_pct", 2.0), "L'inflation", -20.0, 30.0, 2.0
        ),
        "income_growth_pct": _validate_float_range(
            data.get("income_growth_pct", 0.0), "La croissance des revenus", -50.0, 50.0, 0.0
        ),
        "expense_growth_pct": _validate_float_range(
            data.get("expense_growth_pct", 0.0), "La croissance des dépenses", -50.0, 50.0, 0.0
        ),
        "fire_multiple": _validate_float_range(
            data.get("fire_multiple", 25.0), "Le multiple FIRE", 1.0, 200.0, 25.0
        ),
        "use_real_snapshot_base": 1 if _to_int(data.get("use_real_snapshot_base", 1)) else 0,
        # Rendements par classe
        "return_liquidites_pct":  _validate_float_range(data.get("return_liquidites_pct",  2.0), "Rendement liquidités",  -20.0, 50.0, 2.0),
        "return_bourse_pct":      _validate_float_range(data.get("return_bourse_pct",      7.0), "Rendement bourse",      -20.0, 50.0, 7.0),
        "return_immobilier_pct":  _validate_float_range(data.get("return_immobilier_pct",  3.5), "Rendement immobilier",  -20.0, 50.0, 3.5),
        "return_pe_pct":          _validate_float_range(data.get("return_pe_pct",         10.0), "Rendement PE",          -20.0, 50.0, 10.0),
        "return_entreprises_pct": _validate_float_range(data.get("return_entreprises_pct", 5.0), "Rendement entreprises", -20.0, 50.0, 5.0),
        "exclude_primary_residence": 1 if data.get("exclude_primary_residence") else 0,
    }
    if payload["horizon_years"] < 1:
        raise ValueError("L'horizon doit être supérieur ou égal à 1 an.")

    savings_override = data.get("monthly_savings_override")
    payload["monthly_savings_override"] = (
        None if savings_override is None else _validate_float_range(
            savings_override, "L'épargne mensuelle personnalisée", -10_000_000.0, 10_000_000.0, 0.0
        )
    )
    net_override = data.get("initial_net_worth_override")
    payload["initial_net_worth_override"] = (
        None if net_override is None else _validate_float_range(
            net_override, "Le patrimoine initial personnalisé", -1_000_000_000_000.0, 1_000_000_000_000.0, 0.0
        )
    )

    cur = conn.execute(
        """
        INSERT INTO projection_scenarios (
            name, scope_type, scope_id, is_default,
            horizon_years, expected_return_pct, inflation_pct,
            income_growth_pct, expense_growth_pct, monthly_savings_override,
            fire_multiple, use_real_snapshot_base, initial_net_worth_override,
            return_liquidites_pct, return_bourse_pct, return_immobilier_pct,
            return_pe_pct, return_entreprises_pct, exclude_primary_residence,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            payload["name"],
            st,
            sid,
            payload["is_default"],
            payload["horizon_years"],
            payload["expected_return_pct"],
            payload["inflation_pct"],
            payload["income_growth_pct"],
            payload["expense_growth_pct"],
            payload["monthly_savings_override"],
            payload["fire_multiple"],
            payload["use_real_snapshot_base"],
            payload["initial_net_worth_override"],
            payload["return_liquidites_pct"],
            payload["return_bourse_pct"],
            payload["return_immobilier_pct"],
            payload["return_pe_pct"],
            payload["return_entreprises_pct"],
            payload["exclude_primary_residence"],
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_scenario(conn: sqlite3.Connection, scenario_id: int, data: dict) -> None:
    payload = dict(data or {})
    row = conn.execute(
        "SELECT scope_type, scope_id FROM projection_scenarios WHERE id = ?",
        (int(scenario_id),),
    ).fetchone()
    if row is None:
        return

    if "scope_type" in payload or "scope_id" in payload:
        scope_type = payload.get("scope_type", row["scope_type"])
        scope_id = payload.get("scope_id", row["scope_id"])
        st, sid = _normalize_scope(scope_type, scope_id)
        payload["scope_type"] = st
        payload["scope_id"] = sid

    if "name" in payload:
        payload["name"] = _require_name(payload.get("name"), "Le nom du scénario")
    if "is_default" in payload:
        payload["is_default"] = 1 if _to_int(payload.get("is_default")) else 0
    if "horizon_years" in payload:
        horizon = _to_int(payload.get("horizon_years"), 10)
        if horizon < 1:
            raise ValueError("L'horizon doit être supérieur ou égal à 1 an.")
        payload["horizon_years"] = horizon
    if "expected_return_pct" in payload:
        payload["expected_return_pct"] = _validate_float_range(
            payload.get("expected_return_pct"), "Le rendement attendu", -50.0, 50.0, 6.0
        )
    if "inflation_pct" in payload:
        payload["inflation_pct"] = _validate_float_range(
            payload.get("inflation_pct"), "L'inflation", -20.0, 30.0, 2.0
        )
    if "income_growth_pct" in payload:
        payload["income_growth_pct"] = _validate_float_range(
            payload.get("income_growth_pct"), "La croissance des revenus", -50.0, 50.0, 0.0
        )
    if "expense_growth_pct" in payload:
        payload["expense_growth_pct"] = _validate_float_range(
            payload.get("expense_growth_pct"), "La croissance des dépenses", -50.0, 50.0, 0.0
        )
    if "monthly_savings_override" in payload and payload.get("monthly_savings_override") is not None:
        payload["monthly_savings_override"] = _validate_float_range(
            payload.get("monthly_savings_override"),
            "L'épargne mensuelle personnalisée",
            -10_000_000.0,
            10_000_000.0,
            0.0,
        )
    if "fire_multiple" in payload:
        payload["fire_multiple"] = _validate_float_range(
            payload.get("fire_multiple"), "Le multiple FIRE", 1.0, 200.0, 25.0
        )
    if "use_real_snapshot_base" in payload:
        payload["use_real_snapshot_base"] = 1 if _to_int(payload.get("use_real_snapshot_base")) else 0
    if "initial_net_worth_override" in payload and payload.get("initial_net_worth_override") is not None:
        payload["initial_net_worth_override"] = _validate_float_range(
            payload.get("initial_net_worth_override"),
            "Le patrimoine initial personnalisé",
            -1_000_000_000_000.0,
            1_000_000_000_000.0,
            0.0,
        )
    # Rendements par classe
    for field, label, default in [
        ("return_liquidites_pct",  "Rendement liquidités",  2.0),
        ("return_bourse_pct",      "Rendement bourse",      7.0),
        ("return_immobilier_pct",  "Rendement immobilier",  3.5),
        ("return_pe_pct",          "Rendement PE",         10.0),
        ("return_entreprises_pct", "Rendement entreprises", 5.0),
    ]:
        if field in payload:
            payload[field] = _validate_float_range(payload.get(field), label, -20.0, 50.0, default)
    if "exclude_primary_residence" in payload:
        payload["exclude_primary_residence"] = 1 if payload.get("exclude_primary_residence") else 0

    allowed_fields = [
        "name",
        "scope_type",
        "scope_id",
        "is_default",
        "horizon_years",
        "expected_return_pct",
        "inflation_pct",
        "income_growth_pct",
        "expense_growth_pct",
        "monthly_savings_override",
        "fire_multiple",
        "use_real_snapshot_base",
        "initial_net_worth_override",
        "return_liquidites_pct",
        "return_bourse_pct",
        "return_immobilier_pct",
        "return_pe_pct",
        "return_entreprises_pct",
        "exclude_primary_residence",
    ]

    set_parts = []
    params = []
    for field in allowed_fields:
        if field in payload:
            set_parts.append(f"{field} = ?")
            params.append(payload[field])

    if not set_parts:
        return

    set_parts.append("updated_at = datetime('now')")
    params.append(int(scenario_id))

    conn.execute(
        f"""
        UPDATE projection_scenarios
        SET {', '.join(set_parts)}
        WHERE id = ?
        """,
        tuple(params),
    )
    conn.commit()


def delete_scenario(conn: sqlite3.Connection, scenario_id: int) -> None:
    conn.execute("DELETE FROM projection_scenarios WHERE id = ?", (int(scenario_id),))
    conn.commit()
