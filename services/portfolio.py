import pandas as pd


def compute_positions_v1(tx_df: pd.DataFrame, latest_prices: pd.DataFrame) -> pd.DataFrame:
    """
    V1:
    - calcule Quantité et PRU à partir des transactions ACHAT/VENTE
    - applique le dernier prix connu (table prices)
    - calcule Valeur et PnL latent (sans FX)
    """
    empty_cols = ["asset_id", "symbol", "name", "quantity", "pru", "last_price", "value", "pnl_latent", "valuation_status"]
    if tx_df is None or tx_df.empty:
        return pd.DataFrame(columns=empty_cols)

    # On ne garde que ACHAT/VENTE avec asset_id
    df = tx_df.copy()
    df = df[df["asset_id"].notna()].copy()
    df = df[df["type"].isin(["ACHAT", "VENTE"])].copy()
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    # Assure numeric
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)

    positions = {}

    # Tri chronologique (important pour PRU)
    df = df.sort_values(["date", "id"], ascending=[True, True])

    for _, r in df.iterrows():
        aid = int(r["asset_id"])
        sym = r.get("asset_symbol", "")
        name = r.get("asset_name", "")

        if aid not in positions:
            positions[aid] = {"asset_id": aid, "symbol": sym, "name": name, "quantity": 0.0, "pru": 0.0}

        q = float(r["quantity"])
        px = round(float(r["price"]), 2)

        if r["type"] == "ACHAT":
            # PRU pondéré
            old_q = positions[aid]["quantity"]
            old_pru = positions[aid]["pru"]
            new_q = old_q + q
            if new_q > 0:
                positions[aid]["pru"] = (old_q * old_pru + q * px) / new_q
            positions[aid]["quantity"] = new_q

        elif r["type"] == "VENTE":
            # En V1: on réduit juste la quantité, PRU inchangé
            positions[aid]["quantity"] = positions[aid]["quantity"] - q

    out = pd.DataFrame(list(positions.values()))

    # Nettoyage: ne garde que positions positives
    out = out[out["quantity"] > 1e-12].copy()
    if out.empty:
        return pd.DataFrame(columns=empty_cols)

    # Merge latest prices. Prix absent = donnée non valorisable, pas zéro métier.
    if latest_prices is None or latest_prices.empty:
        lp = pd.DataFrame(columns=["asset_id", "last_price"])
    else:
        lp = latest_prices.rename(columns={"price": "last_price"}).copy()
        for col in ["asset_id", "last_price"]:
            if col not in lp.columns:
                lp[col] = pd.NA
    out = out.merge(lp[["asset_id", "last_price"]], on="asset_id", how="left")
    out["last_price"] = pd.to_numeric(out["last_price"], errors="coerce")
    out["valuation_status"] = "ok"
    out.loc[out["last_price"].isna() | (out["last_price"] <= 0), "valuation_status"] = "missing_price"

    out["value"] = out["quantity"] * out["last_price"]
    out["pnl_latent"] = (out["last_price"] - out["pru"]) * out["quantity"]

    # Colonnes dans l’ordre
    out = out[["asset_id", "symbol", "name", "quantity", "pru", "last_price", "value", "pnl_latent", "valuation_status"]]
    return out

def compute_positions_v2_fx(conn, tx_df: pd.DataFrame, latest_prices: pd.DataFrame, account_ccy: str) -> pd.DataFrame:
    """
    V2 FX:
    - mêmes calculs que V1 mais convertit tout en devise du compte (account_ccy)
    - PRU, last_price, value, pnl_latent -> convertis en devise du compte
    Hypothèses:
    - assets.currency existe et est renseigné (sinon fallback sur latest_prices.currency ou account_ccy)
    - fx_rates contient les paires nécessaires (sinon fallback sans conversion)
    """
    from services import fx  # import ici pour éviter import circulaire

    account_ccy = (account_ccy or "EUR").upper()

    out = compute_positions_v1(tx_df, latest_prices)
    if out.empty:
        return out

    # latest_prices peut contenir currency, sinon on va chercher dans DB assets
    lp = latest_prices.copy() if latest_prices is not None else pd.DataFrame()
    if "currency" not in lp.columns:
        lp["currency"] = None

    # Map asset_id -> currency via DB si possible
    asset_ids = out["asset_id"].astype(int).tolist()
    if asset_ids:
        qmarks = ",".join(["?"] * len(asset_ids))
        rows = conn.execute(
            f"SELECT id as asset_id, currency, asset_type FROM assets WHERE id IN ({qmarks});",
            tuple(asset_ids),
        ).fetchall()
        cur_df = pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame(columns=["asset_id", "currency", "asset_type"])

        out = out.merge(cur_df, on="asset_id", how="left", suffixes=("", "_asset"))
    else:
        out["currency"] = None
        out["asset_type"] = None

    # devise actif: priorité assets.currency, sinon latest_prices.currency, sinon account_ccy
    lp2 = lp[["asset_id", "currency"]].drop_duplicates() if not lp.empty else pd.DataFrame(columns=["asset_id","currency"])
    out = out.merge(lp2, on="asset_id", how="left", suffixes=("", "_price"))

    def pick_ccy(r):
        c1 = r.get("currency")
        c2 = r.get("currency_price")
        c = c1 if isinstance(c1, str) and c1 else (c2 if isinstance(c2, str) and c2 else account_ccy)
        return (c or account_ccy).upper()

    out["asset_ccy"] = out.apply(pick_ccy, axis=1)

    import logging
    _log = logging.getLogger(__name__)

    def _convert_or_nan(amount, from_ccy, to_ccy):
        if pd.isna(amount):
            return amount
        res = fx.convert(conn, amount, from_ccy, to_ccy)
        if res is None:
            _log.warning("FX: Unable to convert %s from %s to %s - generating NaN", amount, from_ccy, to_ccy)
            return float('nan')
        return res

    # Conversion PRU + last_price en devise compte
    status = out.get("valuation_status", pd.Series(["ok"] * len(out), index=out.index)).copy()
    original_pru = out["pru"].copy()
    original_last_price = out["last_price"].copy()
    out["pru"] = out.apply(lambda r: _convert_or_nan(r["pru"], r["asset_ccy"], account_ccy), axis=1)
    out["last_price"] = out.apply(lambda r: _convert_or_nan(r["last_price"], r["asset_ccy"], account_ccy), axis=1)
    missing_fx = (
        status.eq("ok")
        & (original_pru.notna() | original_last_price.notna())
        & (out["pru"].isna() | out["last_price"].isna())
    )
    status.loc[missing_fx] = "missing_fx"
    out["valuation_status"] = status

    # Recalcul value & pnl_latent après conversion
    out["value"] = out["quantity"] * out["last_price"]
    out["pnl_latent"] = (out["last_price"] - out["pru"]) * out["quantity"]

    # Option: on garde la colonne asset_ccy pour debug
    if "asset_type" not in out.columns:
        out["asset_type"] = "autre"
    out["asset_type"] = out["asset_type"].fillna("autre")
    out = out[["asset_id","symbol","name","asset_type","quantity","pru","last_price","value","pnl_latent","asset_ccy","valuation_status"]]
    return out
