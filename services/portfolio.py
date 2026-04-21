import logging

import pandas as pd

logger = logging.getLogger(__name__)


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

def _to_float_or_none(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _build_open_cost_basis_in_target(
    conn,
    tx_df: pd.DataFrame,
    *,
    asset_ccy_by_id: dict[int, str],
    account_ccy: str,
    target_ccy: str,
) -> dict[int, dict]:
    """
    Reconstruit un PRU de coût en devise cible (ex: EUR) pour les positions ouvertes.

    - Base transactionnelle: ACHAT/VENTE du compte
    - Coût achat prioritaire: amount + fees (devise compte) converti en devise cible
    - Fallback coût achat: price natif converti en devise cible
    - En cas de donnée insuffisante (amount/price/fx), la position est marquée invalide
      pour la décomposition marché vs change.
    """
    from services import fx, market_history

    empty: dict[int, dict] = {}
    if tx_df is None or tx_df.empty:
        return empty

    df = tx_df.copy()
    if "asset_id" not in df.columns or "type" not in df.columns:
        return empty

    df = df[df["asset_id"].notna()].copy()
    df["type"] = df["type"].astype(str).str.upper()
    df = df[df["type"].isin(["ACHAT", "VENTE"])].copy()
    if df.empty:
        return empty

    if "quantity" not in df.columns:
        df["quantity"] = 0.0
    if "price" not in df.columns:
        df["price"] = pd.NA
    if "amount" not in df.columns:
        df["amount"] = pd.NA
    if "fees" not in df.columns:
        df["fees"] = 0.0

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["fees"] = pd.to_numeric(df["fees"], errors="coerce").fillna(0.0)

    sort_cols = []
    if "date" in df.columns:
        sort_cols.append("date")
    if "id" in df.columns:
        sort_cols.append("id")
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=[True] * len(sort_cols))

    weekly_fx_cache: dict[tuple[str, str, str], float | None] = {}
    spot_fx_cache: dict[tuple[str, str], float | None] = {}

    def _norm_ccy(ccy: str | None, fallback: str) -> str:
        c = str(ccy or "").strip().upper()
        return c or fallback

    def _convert_to_target(amount: float, from_ccy: str, tx_date: str | None) -> float | None:
        from_norm = _norm_ccy(from_ccy, target_ccy)
        if from_norm == target_ccy:
            return float(amount)
        if tx_date:
            wk_key = (from_norm, target_ccy, tx_date)
            if wk_key not in weekly_fx_cache:
                weekly_fx_cache[wk_key] = market_history.convert_weekly(
                    conn, float(amount), from_norm, target_ccy, tx_date
                )
            wk_val = weekly_fx_cache[wk_key]
            if wk_val is not None:
                return float(wk_val)
        sp_key = (from_norm, target_ccy)
        if sp_key not in spot_fx_cache:
            sp_rate = fx.convert(conn, 1.0, from_norm, target_ccy)
            spot_fx_cache[sp_key] = sp_rate
        rate = spot_fx_cache[sp_key]
        if rate is None:
            return None
        return float(amount) * float(rate)

    states: dict[int, dict] = {}

    for _, r in df.iterrows():
        aid = int(r["asset_id"])
        tx_type = str(r.get("type") or "").upper()
        qty = _to_float_or_none(r.get("quantity")) or 0.0
        if qty <= 0:
            continue

        st = states.setdefault(aid, {"qty": 0.0, "pru_target": 0.0, "valid": True})

        if tx_type == "ACHAT":
            tx_date_raw = r.get("date")
            tx_date = str(tx_date_raw)[:10] if tx_date_raw is not None else None

            amount = _to_float_or_none(r.get("amount"))
            fees = _to_float_or_none(r.get("fees")) or 0.0
            unit_target = None

            if amount is not None and amount > 0:
                gross_account = float(amount) + float(fees)
                converted = _convert_to_target(gross_account, account_ccy, tx_date)
                if converted is not None:
                    unit_target = float(converted) / float(qty)

            if unit_target is None:
                px_native = _to_float_or_none(r.get("price"))
                if px_native is not None and px_native > 0:
                    asset_ccy = _norm_ccy(asset_ccy_by_id.get(aid), target_ccy)
                    converted_px = _convert_to_target(float(px_native), asset_ccy, tx_date)
                    if converted_px is not None:
                        unit_target = float(converted_px)

            old_q = float(st["qty"])
            new_q = old_q + float(qty)
            if unit_target is None:
                st["valid"] = False
                st["qty"] = new_q
                continue

            old_pru_t = float(st["pru_target"])
            st["pru_target"] = ((old_q * old_pru_t) + (float(qty) * float(unit_target))) / new_q if new_q > 0 else 0.0
            st["qty"] = new_q

        elif tx_type == "VENTE":
            old_q = float(st["qty"])
            if old_q <= 0:
                continue
            new_q = max(old_q - float(qty), 0.0)
            st["qty"] = new_q
            if new_q <= 1e-12:
                # Position fermée: reset complet pour ne pas polluer un futur cycle d'achats.
                st["qty"] = 0.0
                st["pru_target"] = 0.0
                st["valid"] = True

    out: dict[int, dict] = {}
    for aid, st in states.items():
        qty = float(st.get("qty", 0.0) or 0.0)
        if qty <= 1e-12:
            continue
        out[int(aid)] = {
            "qty": qty,
            "pru_target": _to_float_or_none(st.get("pru_target")),
            "valid": bool(st.get("valid", True)),
        }
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

    def _convert_or_nan(amount, from_ccy, to_ccy):
        if pd.isna(amount):
            return amount
        res = fx.convert(conn, amount, from_ccy, to_ccy)
        if res is None:
            logger.warning("FX: Unable to convert %s from %s to %s - generating NaN", amount, from_ccy, to_ccy)
            return float("nan")
        return res

    # Cost basis en EUR (source de vérité pour séparer marché vs change).
    asset_ccy_map = {
        int(r["asset_id"]): str(r.get("asset_ccy") or account_ccy).upper()
        for _, r in out.iterrows()
    }
    cost_basis_eur = _build_open_cost_basis_in_target(
        conn,
        tx_df,
        asset_ccy_by_id=asset_ccy_map,
        account_ccy=account_ccy,
        target_ccy="EUR",
    )

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

    # Décomposition en EUR:
    # - total_gain_eur
    # - market_gain_eur
    # - fx_gain_eur
    # Formules:
    #   valeur_actuelle_eur = qty * prix_actuel_devise * fx_actuel
    #   valeur_theorique_sans_change = qty * prix_actuel_devise * fx_moyen_achat
    #   fx_gain_eur = valeur_actuelle_eur - valeur_theorique_sans_change
    #   market_gain_eur = valeur_theorique_sans_change - coût_total_eur
    fx_now_cache: dict[str, float | None] = {}

    def _fx_now_to_eur(ccy: str) -> float | None:
        c = str(ccy or "EUR").upper()
        if c == "EUR":
            return 1.0
        if c not in fx_now_cache:
            fx_now_cache[c] = fx.convert(conn, 1.0, c, "EUR")
        return fx_now_cache[c]

    total_gain_vals: list[float | None] = []
    market_gain_vals: list[float | None] = []
    fx_gain_vals: list[float | None] = []
    breakdown_status_vals: list[str] = []

    for idx, r in out.iterrows():
        aid = int(r["asset_id"])
        asset_ccy = str(r.get("asset_ccy") or "EUR").upper()
        qty = _to_float_or_none(r.get("quantity"))
        px_native = _to_float_or_none(original_last_price.loc[idx])
        pru_native = _to_float_or_none(original_pru.loc[idx])
        pnl_fallback = _to_float_or_none(r.get("pnl_latent"))

        total_gain = None
        market_gain = None
        fx_gain = None
        breakdown_status = "ok"

        if qty is None or qty <= 0:
            breakdown_status = "invalid_qty"
        elif px_native is None or px_native <= 0:
            breakdown_status = "missing_price"
            total_gain = pnl_fallback
            if asset_ccy == "EUR":
                market_gain = total_gain
                fx_gain = 0.0
        else:
            fx_now = _fx_now_to_eur(asset_ccy)
            value_current_eur = None if fx_now is None else float(qty) * float(px_native) * float(fx_now)

            basis = cost_basis_eur.get(aid)
            has_basis = bool(basis and basis.get("valid"))
            pru_buy_eur = _to_float_or_none((basis or {}).get("pru_target"))

            if asset_ccy == "EUR":
                fx_gain = 0.0
                if has_basis and pru_buy_eur is not None:
                    cost_total_eur = float(qty) * float(pru_buy_eur)
                    if value_current_eur is not None:
                        market_gain = value_current_eur - cost_total_eur
                        total_gain = market_gain
                    else:
                        breakdown_status = "missing_price"
                else:
                    breakdown_status = "missing_cost"
                    total_gain = pnl_fallback
                    market_gain = total_gain
            else:
                if value_current_eur is None:
                    breakdown_status = "missing_fx_current"
                    total_gain = pnl_fallback
                elif not has_basis or pru_buy_eur is None or pru_native is None or pru_native <= 0:
                    breakdown_status = "missing_cost"
                    total_gain = pnl_fallback
                else:
                    fx_avg_buy = float(pru_buy_eur) / float(pru_native)
                    value_no_fx = float(qty) * float(px_native) * fx_avg_buy
                    cost_total_eur = float(qty) * float(pru_buy_eur)
                    fx_gain = float(value_current_eur) - float(value_no_fx)
                    market_gain = float(value_no_fx) - float(cost_total_eur)
                    total_gain = float(market_gain) + float(fx_gain)

        if total_gain is None and pnl_fallback is not None:
            total_gain = pnl_fallback
            if asset_ccy == "EUR" and market_gain is None:
                market_gain = total_gain
                fx_gain = 0.0
            if breakdown_status == "ok":
                breakdown_status = "fallback_total"

        total_gain_vals.append(total_gain)
        market_gain_vals.append(market_gain)
        fx_gain_vals.append(fx_gain)
        breakdown_status_vals.append(breakdown_status)

    out["total_gain_eur"] = pd.to_numeric(pd.Series(total_gain_vals, index=out.index), errors="coerce")
    out["market_gain_eur"] = pd.to_numeric(pd.Series(market_gain_vals, index=out.index), errors="coerce")
    out["fx_gain_eur"] = pd.to_numeric(pd.Series(fx_gain_vals, index=out.index), errors="coerce")
    out["fx_breakdown_status"] = pd.Series(breakdown_status_vals, index=out.index).astype(str)

    # Compat rétro: l'ancienne colonne pnl_fx reste disponible.
    out["pnl_fx"] = out["fx_gain_eur"]

    if "asset_type" not in out.columns:
        out["asset_type"] = "autre"
    out["asset_type"] = out["asset_type"].fillna("autre")
    out = out[[
        "asset_id", "symbol", "name", "asset_type",
        "quantity", "pru", "last_price", "value",
        "pnl_latent", "total_gain_eur", "market_gain_eur", "fx_gain_eur", "pnl_fx",
        "asset_ccy", "valuation_status", "fx_breakdown_status",
    ]]
    return out
