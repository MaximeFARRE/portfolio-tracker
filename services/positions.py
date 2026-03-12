from __future__ import annotations
import pandas as pd
import sqlite3

def compute_positions_asof(conn: sqlite3.Connection, person_id: int, asof_date: str, account_ids: list[int] | None = None) -> pd.DataFrame:
    params = [int(person_id), str(asof_date)]
    where_acc = ""
    if account_ids:
        q = ",".join(["?"] * len(account_ids))
        where_acc = f" AND t.account_id IN ({q})"
        params.extend([int(x) for x in account_ids])

    rows = conn.execute(
        f"""
        SELECT
            t.account_id,
            t.asset_id,
            a.symbol AS symbol,
            a.currency AS asset_ccy,
            t.type,
            t.quantity
        FROM transactions t
        LEFT JOIN assets a ON a.id = t.asset_id
        WHERE t.person_id = ?
          AND t.date <= ?
          AND t.asset_id IS NOT NULL
          AND t.type IN ('ACHAT','VENTE')
          {where_acc}
        ORDER BY t.date ASC, t.id ASC
        """,
        tuple(params),
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["account_id","asset_id","symbol","asset_ccy","quantity"])

    _cols_pos = ["account_id", "asset_id", "symbol", "asset_ccy", "type", "quantity"]
    try:
        df = pd.DataFrame([dict(r) for r in rows])
    except (TypeError, KeyError):
        df = pd.DataFrame(list(rows), columns=_cols_pos)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["q_signed"] = df["quantity"]
    df.loc[df["type"] == "VENTE", "q_signed"] = -df.loc[df["type"] == "VENTE", "quantity"]

    g = df.groupby(["account_id","asset_id","symbol","asset_ccy"], as_index=False)["q_signed"].sum()
    g = g.rename(columns={"q_signed": "quantity"})
    return g[g["quantity"] > 1e-12].copy()
