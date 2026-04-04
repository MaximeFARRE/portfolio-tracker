"""
Panel Bourse Global — remplace ui/bourse_global_overview.py
"""
import logging
import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea,
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

from qt_ui.widgets import PlotlyView, DataTableWidget, KpiCard
from qt_ui.theme import (
    BG_PRIMARY, BORDER_SUBTLE, TEXT_SECONDARY, TEXT_MUTED,
    STYLE_BTN_PRIMARY, STYLE_TITLE_XL, STYLE_SECTION,
    STYLE_STATUS, COLOR_SUCCESS, COLOR_ERROR,
    plotly_layout,
)

logger = logging.getLogger(__name__)

# ── Mapping colonnes internes → libellés affichage ────────────────────────────
_COL_LABELS = {
    "symbol":     "Symbole",
    "name":       "Nom",
    "quantity":   "Qté",
    "pru":        "PRU (€)",
    "last_price": "Prix (€)",
    "value":      "Valeur (€)",
    "poids_%":    "Poids %",
    "pnl_latent": "PnL (€)",
    "compte":     "Compte",
    "type":       "Type",
}

# ── Couleurs du graphe revenus ────────────────────────────────────────────────
_INCOME_COLORS = {
    "DIVIDENDE": "#4ade80",
    "INTERETS":  "#60a5fa",
}


def _fmt_eur(value: float, decimals: int = 0) -> str:
    """Formate un montant en € avec espace fine comme séparateur de milliers."""
    fmt = f"{value:,.{decimals}f}".replace(",", "\u202f")
    return f"{fmt} €"


def _sep() -> QFrame:
    """Séparateur horizontal discret."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {BORDER_SUBTLE}; max-height: 1px;")
    return line


# ─────────────────────────────────────────────────────────────────────────────

class RefreshPricesThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, person_id: int):
        super().__init__()
        self._person_id = person_id

    def run(self):
        try:
            from services import repositories as repo
            from services import pricing, fx
            from services.db import get_conn

            with get_conn() as local_conn:
                df_acc = repo.list_accounts(local_conn, person_id=self._person_id)
                if df_acc is None or df_acc.empty:
                    self.finished.emit("Aucun compte bourse.")
                    return

                bourse_types = {"PEA", "CTO", "CRYPTO"}
                df_b = df_acc[df_acc["account_type"].astype(str).str.upper().isin(bourse_types)]
                n_ok, n_fail = 0, 0
                for _, row in df_b.iterrows():
                    account_id = int(row["id"])
                    acc_ccy = str(row.get("currency") or "EUR").upper()
                    asset_ids = repo.list_account_asset_ids(local_conn, account_id=account_id)
                    for aid in asset_ids:
                        a = local_conn.execute("SELECT symbol FROM assets WHERE id = ?", (aid,)).fetchone()
                        if not a:
                            continue
                        sym = a[0] if not hasattr(a, '__getitem__') else a["symbol"]
                        px_val, ccy = pricing.fetch_last_price_auto(sym)
                        if px_val is not None:
                            repo.upsert_price(local_conn, asset_id=aid, date=pricing.today_str(),
                                              price=px_val, currency=ccy, source="AUTO")
                            if ccy and str(ccy).upper() != acc_ccy:
                                repo.update_asset_currency(local_conn, aid, str(ccy).upper())
                                fx.ensure_fx_rate(local_conn, str(ccy).upper(), acc_ccy)
                            n_ok += 1
                        else:
                            n_fail += 1
            self.finished.emit(f"{n_ok} OK, {n_fail} non trouvés")
        except Exception as e:
            logger.error("RefreshPricesThread error: %s", e, exc_info=True)
            self.finished.emit(f"Erreur : {e}")


# ─────────────────────────────────────────────────────────────────────────────

class BourseGlobalPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._thread = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")

        # ── Scroll area ──────────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}")
        outer.addWidget(scroll)

        inner = QWidget()
        inner.setStyleSheet(f"background: {BG_PRIMARY};")
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)

        # ── En-tête ──────────────────────────────────────────────────────────
        header_row = QHBoxLayout()

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        lbl_title = QLabel("📈  Bourse — Vue Globale")
        lbl_title.setStyleSheet(STYLE_TITLE_XL)
        self._lbl_subtitle = QLabel("Portefeuille consolidé")
        self._lbl_subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        title_col.addWidget(lbl_title)
        title_col.addWidget(self._lbl_subtitle)
        header_row.addLayout(title_col)
        header_row.addStretch()

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        self._btn_refresh = QPushButton("↻  Rafraîchir les prix")
        self._btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_refresh.setFixedWidth(175)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._refresh_status = QLabel()
        self._refresh_status.setStyleSheet(STYLE_STATUS)
        self._refresh_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        btn_col.addWidget(self._btn_refresh, alignment=Qt.AlignmentFlag.AlignRight)
        btn_col.addWidget(self._refresh_status, alignment=Qt.AlignmentFlag.AlignRight)
        header_row.addLayout(btn_col)

        layout.addLayout(header_row)
        layout.addWidget(_sep())

        # ── KPI Row 1 — métriques principales ────────────────────────────────
        kpi_row1 = QHBoxLayout()
        kpi_row1.setSpacing(10)
        self._kpi_invested = KpiCard("Total Investi",   "—", emoji="💰", tone="neutral")
        self._kpi_holdings = KpiCard("Valeur Actuelle", "—", emoji="📊", tone="broker")
        self._kpi_perf     = KpiCard("Perf Globale",    "—", subtitle="YTD : —", emoji="📈", tone="neutral")
        self._kpi_pnl      = KpiCard("PnL Latent",      "—", emoji="⚡", tone="neutral")
        for card in (self._kpi_invested, self._kpi_holdings, self._kpi_perf, self._kpi_pnl):
            kpi_row1.addWidget(card, stretch=1)
        layout.addLayout(kpi_row1)

        # ── KPI Row 2 — revenus & positions ──────────────────────────────────
        kpi_row2 = QHBoxLayout()
        kpi_row2.setSpacing(10)
        self._kpi_nb  = KpiCard("Positions ouvertes", "—", emoji="🎯", tone="neutral")
        self._kpi_div = KpiCard("Dividendes perçus",  "—", emoji="💵", tone="success")
        self._kpi_int = KpiCard("Intérêts perçus",    "—", emoji="🏦", tone="success")
        for card in (self._kpi_nb, self._kpi_div, self._kpi_int):
            kpi_row2.addWidget(card, stretch=1)
        kpi_row2.addStretch(1)
        layout.addLayout(kpi_row2)

        layout.addWidget(_sep())

        # ── Graphiques ───────────────────────────────────────────────────────
        lbl_charts = QLabel("Évolution & Revenus")
        lbl_charts.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_charts)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        vbox_hist = QVBoxLayout()
        vbox_hist.setSpacing(4)
        lbl_hist = QLabel("Évolution du portefeuille")
        lbl_hist.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._chart_history = PlotlyView(min_height=280)
        vbox_hist.addWidget(lbl_hist)
        vbox_hist.addWidget(self._chart_history)
        charts_row.addLayout(vbox_hist, stretch=3)

        vbox_inc = QVBoxLayout()
        vbox_inc.setSpacing(4)
        lbl_inc = QLabel("Revenus passifs (Dividendes & Intérêts)")
        lbl_inc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._chart_income = PlotlyView(min_height=280)
        vbox_inc.addWidget(lbl_inc)
        vbox_inc.addWidget(self._chart_income)
        charts_row.addLayout(vbox_inc, stretch=2)

        layout.addLayout(charts_row)
        layout.addWidget(_sep())

        # ── Table + Répartition ───────────────────────────────────────────────
        lbl_pos_section = QLabel("Positions détaillées")
        lbl_pos_section.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_pos_section)

        table_area = QHBoxLayout()
        table_area.setSpacing(12)

        self._table_pos = DataTableWidget()
        self._table_pos.setMinimumHeight(260)
        table_area.addWidget(self._table_pos, stretch=3)

        vbox_alloc = QVBoxLayout()
        vbox_alloc.setSpacing(4)
        lbl_alloc = QLabel("Répartition par actif")
        lbl_alloc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._chart_alloc = PlotlyView(min_height=260)
        vbox_alloc.addWidget(lbl_alloc)
        vbox_alloc.addWidget(self._chart_alloc)
        table_area.addLayout(vbox_alloc, stretch=2)

        layout.addLayout(table_area)

    # ── Contrôles ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    def _on_refresh(self) -> None:
        self._btn_refresh.setEnabled(False)
        self._refresh_status.setText("En cours…")
        self._thread = RefreshPricesThread(self._person_id)
        self._thread.finished.connect(self._on_refresh_done)
        self._thread.start()

    def _on_refresh_done(self, msg: str) -> None:
        self._btn_refresh.setEnabled(True)
        self._refresh_status.setText(f"✅ {msg}")
        self._load_data()

    # ── Chargement des données ────────────────────────────────────────────────

    def _load_data(self) -> None:
        try:
            from services import repositories as repo
            from services import portfolio
            from services.bourse_analytics import get_bourse_performance_metrics, compute_invested_series

            # ── Comptes bourse ──────────────────────────────────────────────
            df_acc = repo.list_accounts(self._conn, person_id=self._person_id)
            if df_acc is None or df_acc.empty:
                return

            bourse_types = {"PEA", "CTO", "CRYPTO"}
            df_b = df_acc[df_acc["account_type"].astype(str).str.upper().isin(bourse_types)]
            if df_b.empty:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucun compte bourse."}]))
                return

            # ── Positions live ──────────────────────────────────────────────
            all_pos = []
            for _, row in df_b.iterrows():
                account_id = int(row["id"])
                acc_ccy    = str(row.get("currency") or "EUR").upper()
                tx_acc     = repo.list_transactions(self._conn, account_id=account_id, limit=10000)
                asset_ids  = repo.list_account_asset_ids(self._conn, account_id=account_id)
                prices     = repo.get_latest_prices(self._conn, asset_ids)
                pos        = portfolio.compute_positions_v2_fx(self._conn, tx_acc, prices, acc_ccy)
                if not pos.empty:
                    pos["compte"] = str(row["name"])
                    pos["type"]   = str(row["account_type"])
                    all_pos.append(pos)

            if not all_pos:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucune position ouverte."}]))
                return

            df_all    = pd.concat(all_pos, ignore_index=True)
            total_val = float(df_all["value"].sum())       if "value"      in df_all.columns else 0.0
            total_pnl = float(df_all["pnl_latent"].sum())  if "pnl_latent" in df_all.columns else 0.0
            nb_pos    = len(df_all[df_all["quantity"] > 0]) if "quantity"  in df_all.columns else len(df_all)
            nb_acc    = len(df_b)

            # ── Métriques analytiques ────────────────────────────────────────
            metrics = get_bourse_performance_metrics(
                self._conn, self._person_id, current_live_value=total_val
            )
            inv_eur = metrics.get("invested_eur",    0.0)
            g_perf  = metrics.get("global_perf_pct", 0.0)
            y_perf  = metrics.get("ytd_perf_pct",    0.0)
            t_div   = metrics.get("total_dividends",  0.0)
            t_int   = metrics.get("total_interests",  0.0)

            # ── Sous-titre dynamique ─────────────────────────────────────────
            today_str = datetime.date.today().strftime("%d/%m/%Y")
            self._lbl_subtitle.setText(
                f"{nb_pos} position(s) · {nb_acc} compte(s) · màj le {today_str}"
            )

            # ── KPI — ligne 1 ────────────────────────────────────────────────
            self._kpi_invested.set_content(
                "Total Investi", _fmt_eur(inv_eur),
                emoji="💰", tone="neutral",
            )
            self._kpi_holdings.set_content(
                "Valeur Actuelle", _fmt_eur(total_val),
                emoji="📊", tone="broker",
            )
            s_g = "+" if g_perf > 0 else ""
            s_y = "+" if y_perf > 0 else ""
            self._kpi_perf.set_content(
                "Perf Globale",
                f"{s_g}{g_perf:.2f} %",
                subtitle=f"YTD : {s_y}{y_perf:.2f} %",
                emoji="📈",
                tone="success" if g_perf >= 0 else "alert",
            )
            self._kpi_pnl.set_content(
                "PnL Latent",
                f"{'+'  if total_pnl >= 0 else ''}{_fmt_eur(total_pnl)}",
                emoji="⚡",
                tone="success" if total_pnl >= 0 else "alert",
            )

            # ── KPI — ligne 2 ────────────────────────────────────────────────
            self._kpi_nb.set_content(
                "Positions", str(nb_pos),
                subtitle=f"{nb_acc} compte(s)",
                emoji="🎯", tone="neutral",
            )
            self._kpi_div.set_content(
                "Dividendes", _fmt_eur(t_div),
                emoji="💵", tone="success",
            )
            self._kpi_int.set_content(
                "Intérêts", _fmt_eur(t_int),
                emoji="🏦", tone="success",
            )

            # ── Table des positions (U5) ──────────────────────────────────────
            display_cols = ["symbol", "name", "quantity", "pru", "last_price",
                            "value", "pnl_latent", "compte", "type"]
            display_cols = [c for c in display_cols if c in df_all.columns]
            if total_val > 0 and "value" in df_all.columns:
                df_all["poids_%"] = (df_all["value"] / total_val * 100.0).round(2)
                idx = display_cols.index("pnl_latent") if "pnl_latent" in display_cols else len(display_cols)
                display_cols.insert(idx, "poids_%")

            df_display = df_all[display_cols].copy().sort_values("value", ascending=False)
            df_display.rename(columns=_COL_LABELS, inplace=True)

            pnl_col = _COL_LABELS.get("pnl_latent", "PnL (€)")
            self._table_pos.set_dataframe(df_display)
            self._table_pos.set_column_colors({
                pnl_col: lambda v: COLOR_SUCCESS if _safe_float(v) >= 0 else COLOR_ERROR
            })

            # ── Graphe historique (U3) ────────────────────────────────────────
            df_snap = metrics.get("snapshots_df")
            if df_snap is not None and not df_snap.empty and "date" in df_snap.columns:
                fig_hist = go.Figure()

                # Courbe principale
                fig_hist.add_trace(go.Scatter(
                    x=df_snap["date"], y=df_snap["bourse_holdings"],
                    mode="lines", name="Portefeuille",
                    line=dict(color="#4ade80", width=2),
                    fill="tozeroy", fillcolor="rgba(74,222,128,0.07)",
                    hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:,.0f} €<extra>Portefeuille</extra>",
                ))

                # Point live mis en évidence
                last_row = df_snap.iloc[-1]
                live_val = float(last_row["bourse_holdings"])
                fig_hist.add_trace(go.Scatter(
                    x=[last_row["date"]], y=[live_val],
                    mode="markers", name="Valeur actuelle",
                    marker=dict(color="#4ade80", size=10, symbol="circle",
                                line=dict(color="#ffffff", width=2)),
                    hovertemplate=f"<b>Aujourd'hui</b><br>{_fmt_eur(live_val)}<extra></extra>",
                    showlegend=False,
                ))

                # Courbe montant investi cumulé
                df_invested = compute_invested_series(self._conn, self._person_id)
                if not df_invested.empty:
                    fig_hist.add_trace(go.Scatter(
                        x=df_invested["date"], y=df_invested["invested_eur"],
                        mode="lines", name="Montant investi",
                        line=dict(color="#94a3b8", width=1.5, dash="dot"),
                        hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:,.0f} €<extra>Investi</extra>",
                    ))

                fig_hist.update_layout(
                    **plotly_layout(margin=dict(l=10, r=10, t=36, b=10)),
                    xaxis=dict(
                        title="", showgrid=True, gridcolor="#1e2538", gridwidth=1,
                        tickformat="%b %Y",
                    ),
                    yaxis=dict(
                        title="", showgrid=True, gridcolor="#1e2538", gridwidth=1,
                        tickformat=",.0f", ticksuffix=" €",
                    ),
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, font=dict(size=11),
                    ),
                    hovermode="x unified",
                )
                self._chart_history.set_figure(fig_hist)

            # ── Graphe revenus (U4) ───────────────────────────────────────────
            df_inc = metrics.get("income_df")
            if df_inc is not None and not df_inc.empty:
                df_inc_grp = df_inc.groupby(["month", "type"], as_index=False)["amount_eur"].sum()
                fig_inc = px.bar(
                    df_inc_grp, x="month", y="amount_eur", color="type",
                    barmode="stack", template="plotly_dark",
                    color_discrete_map=_INCOME_COLORS,
                    labels={"amount_eur": "", "month": "", "type": "Type"},
                )
                fig_inc.update_traces(
                    hovertemplate="<b>%{x}</b><br>%{y:,.2f} €<extra>%{fullData.name}</extra>"
                )
                fig_inc.update_layout(
                    **plotly_layout(margin=dict(l=10, r=10, t=36, b=10)),
                    xaxis=dict(showgrid=False, tickangle=-45),
                    yaxis=dict(
                        showgrid=True, gridcolor="#1e2538",
                        tickformat=",.0f", ticksuffix=" €",
                    ),
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, font=dict(size=11),
                    ),
                )
                self._chart_income.set_figure(fig_inc)

            # ── Pie chart répartition (U6) ────────────────────────────────────
            if "value" in df_all.columns and "symbol" in df_all.columns:
                df_pie = df_all[df_all["value"] > 0][["symbol", "value"]].copy()
                if not df_pie.empty:
                    fig_pie = px.pie(
                        df_pie, names="symbol", values="value", hole=0.42,
                        template="plotly_dark",
                        color_discrete_sequence=px.colors.qualitative.Set3,
                    )
                    fig_pie.update_traces(
                        textinfo="label+percent",
                        textposition="outside",
                        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>%{percent}<extra></extra>",
                        pull=[0.04] + [0.0] * (len(df_pie) - 1),
                    )
                    fig_pie.update_layout(
                        **plotly_layout(margin=dict(l=24, r=24, t=24, b=24)),
                        showlegend=False,
                    )
                    self._chart_alloc.set_figure(fig_pie)

        except Exception as e:
            logger.error("BourseGlobalPanel._load_data error: %s", e, exc_info=True)


def _safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0
