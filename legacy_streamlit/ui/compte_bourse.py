import streamlit as st
import pandas as pd

from services import repositories as repo
from services import portfolio
from services import pricing
from ui.compte_vue import tableau_operations
from ui.compte_saisie import bloc_saisie_operation
from utils.cache import reset_cache
from utils.format_monnaie import money
from services import fx


def afficher_compte_bourse(conn, person_id: int, account_id: int, account_type: str, tx_acc: pd.DataFrame, key_prefix: str):
    acc = repo.get_account(conn, account_id)
    account_ccy = (acc["currency"] if acc and acc["currency"] else "EUR").upper()


    st.markdown("### Tableau de bord")

    # 1) Refresh prices
    if st.button("↻ Rafraîchir les prix du compte", use_container_width=True, key=f"{key_prefix}_refresh_prices"):
        asset_ids = repo.list_account_asset_ids(conn, account_id=account_id)

        n_ok = 0
        n_fail = 0
        for aid in asset_ids:
            a = conn.execute("SELECT * FROM assets WHERE id = ?;", (aid,)).fetchone()
            if not a:
                continue
            sym = a["symbol"]
            px, ccy = pricing.fetch_last_price_auto(sym)
            if px is not None:
                repo.upsert_price(conn, asset_id=aid, date=pricing.today_str(), price=px, currency=ccy, source="AUTO")

                # ✅ met à jour la devise de cotation de l'actif (USD/EUR...)
                if ccy:
                    repo.update_asset_currency(conn, aid, str(ccy).upper())

                    # ✅ si devise actif ≠ devise compte, on s'assure d'avoir le FX en base
                    if str(ccy).upper() != account_ccy:
                        fx.ensure_fx_rate(conn, str(ccy).upper(), account_ccy)

                n_ok += 1

            else:
                n_fail += 1

        st.success(f"Prix mis à jour ✅ ({n_ok} OK, {n_fail} non trouvés)")
        reset_cache()
        st.rerun()

    # 2) Positions
    st.markdown("#### 📌 Positions")

    asset_ids = repo.list_account_asset_ids(conn, account_id=account_id)
    latest_prices = repo.get_latest_prices(conn, asset_ids)

    pos = portfolio.compute_positions_v2_fx(conn, tx_acc, latest_prices, account_ccy)

    if pos.empty:
        st.info("Aucune position (ACHAT/VENTE) sur ce compte.")
    else:
        # Affichage propre
        df = pos.copy()
        df = df.rename(columns={
            "symbol": "Symbole",
            "name": "Nom",
            "quantity": "Quantité",
            "pru": "PRU",
            "last_price": "Dernier prix",
            "value": "Valeur",
            "pnl_latent": "PnL latent",
        })
        st.dataframe(df[["Symbole","Nom","Quantité","PRU","Dernier prix","Valeur","PnL latent","asset_ccy"]], use_container_width=True)


    # ============================================================
    # 📈 KPI & Courbes (V1+)
    # - 1 graphique : Valeur portefeuille + Investi net cumulé
    # - PnL réalisé (méthode PRU moyen)
    # - Perf % : 12 derniers mois + depuis le début
    # ============================================================

    st.markdown("#### 📈 KPI & courbes")

    # --- Sécurise tx ---
    tx = tx_acc.copy()
    if not tx.empty:
        tx["date"] = pd.to_datetime(tx["date"], errors="coerce")
        tx = tx.dropna(subset=["date"]).sort_values("date")

    def compute_cash_balance(tx: pd.DataFrame) -> float:
        if tx is None or tx.empty:
            return 0.0

        df = tx.copy()
        df["type"] = df["type"].astype(str)
        df["amount"] = pd.to_numeric(df.get("amount", 0.0), errors="coerce").fillna(0.0)
        df["fees"] = pd.to_numeric(df.get("fees", 0.0), errors="coerce").fillna(0.0)

        cash = 0.0

        cash += float(df.loc[df["type"] == "DEPOT", "amount"].sum())
        cash -= float(df.loc[df["type"] == "RETRAIT", "amount"].sum())

        cash -= float(df.loc[df["type"] == "ACHAT", "amount"].sum())
        cash += float(df.loc[df["type"] == "VENTE", "amount"].sum())

        cash += float(df.loc[df["type"] == "DIVIDENDE", "amount"].sum())
        cash += float(df.loc[df["type"] == "INTERETS", "amount"].sum())

        cash -= float(df.loc[df["type"] == "FRAIS", "amount"].sum())

        # on retire les frais "fees" (colonne) de toutes les opérations
        cash -= float(df["fees"].sum())

        return round(cash, 2)

    cash_balance = compute_cash_balance(tx_acc)


    # --- KPIs instantanés (latents) ---
    valeur = float(pos["value"].sum()) if (pos is not None and not pos.empty and "value" in pos.columns) else 0.0
    pnl_latent = float(pos["pnl_latent"].sum()) if (pos is not None and not pos.empty and "pnl_latent" in pos.columns) else 0.0

    # --- PnL réalisé (PRU moyen) ---
    def compute_realized_pnl_avg_cost(tx_df: pd.DataFrame) -> float:
        """
        Calcule un PnL réalisé par actif avec un PRU moyen (moving average).
        Hypothèses V1 :
        - BUY/SELL utilisent quantity + price (si amount existe, on ne s'en sert pas)
        - Fees : on les traite séparément (donc PnL réalisé hors frais)
        """
        if tx_df.empty:
            return 0.0

        df = tx_df[tx_df["type"].isin(["ACHAT", "VENTE"])].copy()
        if df.empty:
            return 0.0

        # sécurité colonnes
        for c in ["asset_id", "quantity", "price"]:
            if c not in df.columns:
                return 0.0

        realized = 0.0
        # état par actif : qty, avg_cost
        state = {}

        for _, r in df.iterrows():
            aid = r["asset_id"]
            qty = float(r["quantity"] or 0.0)
            px = float(r["price"] or 0.0)
            if aid is None or qty <= 0 or px <= 0:
                continue

            if aid not in state:
                state[aid] = {"qty": 0.0, "avg": 0.0}

            if r["type"] == "ACHAT":
                old_qty = state[aid]["qty"]
                old_avg = state[aid]["avg"]
                new_qty = old_qty + qty
                # PRU moyen pondéré (hors frais)
                new_avg = ((old_qty * old_avg) + (qty * px)) / new_qty if new_qty > 0 else 0.0
                state[aid]["qty"] = new_qty
                state[aid]["avg"] = new_avg

            elif r["type"] == "VENTE":
                old_qty = state[aid]["qty"]
                old_avg = state[aid]["avg"]
                sell_qty = min(qty, old_qty)  # sécurité si vente > détenu
                realized += sell_qty * (px - old_avg)  # hors frais
                state[aid]["qty"] = old_qty - sell_qty
                # avg inchangé

        return float(realized)

    pnl_realise = compute_realized_pnl_avg_cost(tx) if not tx.empty else 0.0

    # --- Dividendes & flux ---
    dividendes = 0.0
    buys = sells = fees_total = 0.0

    if not tx.empty and "amount" in tx.columns and "type" in tx.columns:
        dividendes = float(tx.loc[tx["type"] == "DIVIDENDE", "amount"].sum())
        # si amount est bien "montant total hors frais" (comme ton formulaire)
        buys = float(tx.loc[tx["type"] == "ACHAT", "amount"].sum())
        sells = float(tx.loc[tx["type"] == "VENTE", "amount"].sum())

    if not tx.empty and "fees" in tx.columns:
        fees_total = float(tx["fees"].fillna(0.0).sum())

    investi_net = buys - sells  # hors frais (les frais sont à part)

    # --- Perf depuis le début (approx, V1) ---
    # Gain total approx = pnl_latent + pnl_realise + dividendes - fees_total
    gain_total = pnl_latent + pnl_realise + dividendes - fees_total
    base_invest = (buys + fees_total) if (buys + fees_total) > 0 else 0.0
    perf_total = (gain_total / base_invest * 100.0) if base_invest > 0 else 0.0

    # --- Perf 12 derniers mois (approx) ---
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=365)
    tx_12m = tx[tx["date"] >= cutoff].copy() if not tx.empty else pd.DataFrame()

    div_12m = float(tx_12m.loc[tx_12m["type"] == "DIVIDENDE", "amount"].sum()) if (not tx_12m.empty and "amount" in tx_12m.columns) else 0.0
    buys_12m = float(tx_12m.loc[tx_12m["type"] == "ACHAT", "amount"].sum()) if (not tx_12m.empty and "amount" in tx_12m.columns) else 0.0
    sells_12m = float(tx_12m.loc[tx_12m["type"] == "VENTE", "amount"].sum()) if (not tx_12m.empty and "amount" in tx_12m.columns) else 0.0
    fees_12m = float(tx_12m["fees"].fillna(0.0).sum()) if (not tx_12m.empty and "fees" in tx_12m.columns) else 0.0

    # On approxime une perf 12m à partir d'une valeur "début période" (mark-to-market simplifié)
    # -> on prend la courbe "Valeur portefeuille (approx)" (définie plus bas) et on lit la valeur au cutoff.
    # Si pas dispo, on met 0.
    start_value_12m = 0.0  # sera mis à jour après construction de la courbe

    # --- Affichage KPIs ---
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Valeur", money(valeur, account_ccy))
    c2.metric("Investi net", money(investi_net, account_ccy))
    c3.metric("PnL latent", money(pnl_latent, account_ccy))
    c4.metric("PnL réalisé", money(pnl_realise, account_ccy))
    c5.metric("Perf totale", f"{perf_total:.2f} %")
    # perf 12m sera calculée après la courbe
    c6.metric("Perf 12 mois", "…")
    c7.metric("Liquidités", money(cash_balance, account_ccy))


    # --- Courbe combinée : Investi net cumulé + Valeur portefeuille (approx) ---
    def build_invested_curve(tx_df: pd.DataFrame) -> pd.Series:
        if tx_df.empty:
            return pd.Series(dtype=float)
        df = tx_df[tx_df["type"].isin(["ACHAT", "VENTE"])].copy()
        if df.empty or "amount" not in df.columns:
            return pd.Series(dtype=float)

        df["signed"] = 0.0
        df.loc[df["type"] == "ACHAT", "signed"] = df.loc[df["type"] == "ACHAT", "amount"].astype(float)
        df.loc[df["type"] == "VENTE", "signed"] = -df.loc[df["type"] == "VENTE", "amount"].astype(float)

        s = df.groupby(df["date"].dt.date)["signed"].sum().cumsum()
        s.index = pd.to_datetime(s.index)
        return s

    def build_value_curve_approx(conn, account_id: int, tx_df: pd.DataFrame) -> pd.Series:
        """
        Courbe valeur portefeuille (approx) :
        - dates = dates d'opérations + aujourd'hui
        - valeur = somme(qty détenue à date * dernier prix connu <= date)
        Nécessite prices(asset_id, date, price).
        """
        if tx_df.empty:
            return pd.Series(dtype=float)

        df = tx_df[tx_df["type"].isin(["ACHAT", "VENTE"])].copy()
        if df.empty:
            return pd.Series(dtype=float)
        if "asset_id" not in df.columns or "quantity" not in df.columns:
            return pd.Series(dtype=float)

        df["q_signed"] = 0.0
        df.loc[df["type"] == "ACHAT", "q_signed"] = df.loc[df["type"] == "ACHAT", "quantity"].astype(float)
        df.loc[df["type"] == "VENTE", "q_signed"] = -df.loc[df["type"] == "VENTE", "quantity"].astype(float)

        dates = sorted(set(df["date"].dt.date.tolist() + [pd.Timestamp.today().date()]))
        asset_ids = sorted([int(x) for x in df["asset_id"].dropna().unique().tolist()])

        if not asset_ids:
            return pd.Series(dtype=float)

        q_marks = ",".join(["?"] * len(asset_ids))
        rows = conn.execute(
            f"SELECT asset_id, date, price FROM prices WHERE asset_id IN ({q_marks})",
            tuple(asset_ids),
        ).fetchall()

        px_df = pd.DataFrame(rows, columns=["asset_id", "date", "price"])
        if px_df.empty:
            return pd.Series(dtype=float)

        px_df["date"] = pd.to_datetime(px_df["date"], errors="coerce")
        px_df = px_df.dropna(subset=["date"]).sort_values(["asset_id", "date"])

        out = []
        for d in dates:
            dts = pd.Timestamp(d)

            held = df[df["date"] <= dts].groupby("asset_id")["q_signed"].sum()
            total_value = 0.0

            for aid, qty in held.items():
                if qty == 0:
                    continue
                sub = px_df[(px_df["asset_id"] == aid) & (px_df["date"] <= dts)]
                if sub.empty:
                    continue
                last_px = float(sub.iloc[-1]["price"])
                total_value += float(qty) * last_px

            out.append((dts, round(total_value, 2)))

        s = pd.Series([v for _, v in out], index=[t for t, _ in out], dtype=float)
        s = s.sort_index()
        return s

    invested_curve = build_invested_curve(tx) if not tx.empty else pd.Series(dtype=float)
    value_curve = pd.Series(dtype=float)
    try:
        value_curve = build_value_curve_approx(conn, account_id, tx)
    except Exception:
        value_curve = pd.Series(dtype=float)

    # Graph combiné (alignement des index)
    if invested_curve.empty and value_curve.empty:
        st.info("Pas assez de données pour afficher les courbes.")
    else:
        df_plot = pd.DataFrame(index=pd.to_datetime(sorted(set(list(invested_curve.index) + list(value_curve.index)))))
        if not invested_curve.empty:
            df_plot["Investi net cumulé"] = invested_curve.reindex(df_plot.index).ffill()
        if not value_curve.empty:
            df_plot["Valeur portefeuille (approx)"] = value_curve.reindex(df_plot.index).ffill()

        st.line_chart(df_plot)

        # ---- calc perf 12 mois une fois qu'on a start_value ----
        if not value_curve.empty:
            # valeur au cutoff (dernier point <= cutoff)
            vc = value_curve.copy()
            vc = vc[vc.index <= cutoff]
            if not vc.empty:
                start_value_12m = float(vc.iloc[-1])
            else:
                start_value_12m = 0.0

        gain_12m = (valeur - start_value_12m) + div_12m - fees_12m - (buys_12m - sells_12m)
        denom_12m = (start_value_12m + buys_12m + fees_12m)
        perf_12m = (gain_12m / denom_12m * 100.0) if denom_12m > 0 else 0.0

        # Remet à jour le metric (hack simple : ré-affiche la ligne KPI 12m sous le graphe)
        st.caption(f"Performance 12 mois (approx) : {perf_12m:.2f} %")

    # ----------------------------
    # 3) Saisie nouvelle opération
    # ----------------------------
    st.divider()
    st.markdown("### ➕ Ajouter une opération")
    bloc_saisie_operation(
        conn,
        person_id=person_id,
        account_id=account_id,
        account_type=account_type,
        key_prefix=key_prefix,
    )

    st.markdown("### Historique")
    tableau_operations(tx_acc)