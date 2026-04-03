"""
Panel Bourse Global — remplace ui/bourse_global_overview.py
"""
import logging
import pandas as pd
import plotly.express as px
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import QThread, pyqtSignal
from qt_ui.widgets import PlotlyView, DataTableWidget, MetricLabel, KpiCard
from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY, STYLE_TITLE, STYLE_SECTION,
    STYLE_STATUS, plotly_layout,
)
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


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


class BourseGlobalPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._thread = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Bourse — Vue globale")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("↻  Rafraîchir tous les prix")
        self._btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_refresh.clicked.connect(self._on_refresh)
        btn_row.addWidget(self._btn_refresh)
        self._refresh_status = QLabel()
        self._refresh_status.setStyleSheet(STYLE_STATUS)
        btn_row.addWidget(self._refresh_status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # KPIs Row 1
        kpi_row1 = QHBoxLayout()
        self._kpi_invested = KpiCard("Total Investi", "—", tone="neutral")
        self._kpi_holdings = KpiCard("Valeur Actuelle", "—", tone="broker")
        self._kpi_perf = KpiCard("Perf Globale", "—", subtitle="YTD : —", tone="neutral")
        kpi_row1.addWidget(self._kpi_invested)
        kpi_row1.addWidget(self._kpi_holdings)
        kpi_row1.addWidget(self._kpi_perf)
        kpi_row1.addStretch()
        layout.addLayout(kpi_row1)
        
        # KPIs Row 2
        kpi_row2 = QHBoxLayout()
        self._kpi_pnl = KpiCard("PnL latent total", "—", tone="neutral")
        self._kpi_div = KpiCard("Dividendes perçus", "—", tone="success")
        self._kpi_int = KpiCard("Intérêts perçus", "—", tone="success")
        self._kpi_nb = KpiCard("Positions ouvertes", "—", tone="neutral")
        kpi_row2.addWidget(self._kpi_pnl)
        kpi_row2.addWidget(self._kpi_div)
        kpi_row2.addWidget(self._kpi_int)
        kpi_row2.addWidget(self._kpi_nb)
        kpi_row2.addStretch()
        layout.addLayout(kpi_row2)
        
        # Graphique Evolution et Revenus
        charts_row = QHBoxLayout()
        vbox_hist = QVBoxLayout()
        lbl_hist = QLabel("Évolution du Portefeuille")
        lbl_hist.setStyleSheet(STYLE_SECTION)
        vbox_hist.addWidget(lbl_hist)
        self._chart_history = PlotlyView(min_height=260)
        vbox_hist.addWidget(self._chart_history)
        charts_row.addLayout(vbox_hist, stretch=2)
        
        vbox_inc = QVBoxLayout()
        lbl_inc = QLabel("Revenus (Dividendes & Intérêts)")
        lbl_inc.setStyleSheet(STYLE_SECTION)
        vbox_inc.addWidget(lbl_inc)
        self._chart_income = PlotlyView(min_height=260)
        vbox_inc.addWidget(self._chart_income)
        charts_row.addLayout(vbox_inc, stretch=1)
        
        layout.addLayout(charts_row)

        table_area = QHBoxLayout()
        
        vbox_pos = QVBoxLayout()
        lbl_pos = QLabel("Positions (tous comptes bourse)")
        lbl_pos.setStyleSheet(STYLE_SECTION)
        vbox_pos.addWidget(lbl_pos)
        self._table_pos = DataTableWidget()
        self._table_pos.setMinimumHeight(250)
        vbox_pos.addWidget(self._table_pos)
        table_area.addLayout(vbox_pos, stretch=2)

        vbox_alloc = QVBoxLayout()
        lbl_alloc = QLabel("Répartition")
        lbl_alloc.setStyleSheet(STYLE_SECTION)
        vbox_alloc.addWidget(lbl_alloc)
        self._chart_alloc = PlotlyView(min_height=250)
        vbox_alloc.addWidget(self._chart_alloc)
        table_area.addLayout(vbox_alloc, stretch=1)
        
        layout.addLayout(table_area)

        layout.addStretch()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    def _on_refresh(self) -> None:
        self._btn_refresh.setEnabled(False)
        self._refresh_status.setText("Rafraîchissement en cours...")
        self._thread = RefreshPricesThread(self._person_id)
        self._thread.finished.connect(self._on_refresh_done)
        self._thread.start()

    def _on_refresh_done(self, msg: str) -> None:
        self._btn_refresh.setEnabled(True)
        self._refresh_status.setText(f"✅ {msg}")
        self._load_data()

    def _load_data(self) -> None:
        try:
            from services import repositories as repo
            from services import portfolio

            df_acc = repo.list_accounts(self._conn, person_id=self._person_id)
            if df_acc is None or df_acc.empty:
                return

            bourse_types = {"PEA", "CTO", "CRYPTO"}
            df_b = df_acc[df_acc["account_type"].astype(str).str.upper().isin(bourse_types)]
            if df_b.empty:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucun compte bourse."}]))
                return

            all_pos = []
            for _, row in df_b.iterrows():
                account_id = int(row["id"])
                acc_ccy = str(row.get("currency") or "EUR").upper()
                tx_acc = repo.list_transactions(self._conn, account_id=account_id, limit=10000)
                asset_ids = repo.list_account_asset_ids(self._conn, account_id=account_id)
                latest_prices = repo.get_latest_prices(self._conn, asset_ids)
                pos = portfolio.compute_positions_v2_fx(self._conn, tx_acc, latest_prices, acc_ccy)
                if not pos.empty:
                    pos["compte"] = str(row["name"])
                    pos["type"] = str(row["account_type"])
                    all_pos.append(pos)

            if not all_pos:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucune position ouverte."}]))
                return

            df_all = pd.concat(all_pos, ignore_index=True)

            total_val = float(df_all["value"].sum()) if "value" in df_all.columns else 0.0
            total_pnl = float(df_all["pnl_latent"].sum()) if "pnl_latent" in df_all.columns else 0.0
            nb_pos = len(df_all[df_all["quantity"] > 0]) if "quantity" in df_all.columns else len(df_all)

            # --- New Performance Metrics UI ---
            from services.bourse_analytics import get_bourse_performance_metrics
            metrics = get_bourse_performance_metrics(self._conn, self._person_id)
            inv_eur = metrics.get("invested_eur", 0.0)
            g_perf = metrics.get("global_perf_pct", 0.0)
            y_perf = metrics.get("ytd_perf_pct", 0.0)
            t_div = metrics.get("total_dividends", 0.0)
            t_int = metrics.get("total_interests", 0.0)
            
            self._kpi_invested.set_content("Total Investi", f"{inv_eur:,.2f} €".replace(",", " "))
            self._kpi_holdings.set_content("Valeur Actuelle", f"{total_val:,.2f} €".replace(",", " "), tone="broker")
            
            s_g = "+" if g_perf > 0 else ""
            s_y = "+" if y_perf > 0 else ""
            self._kpi_perf.set_content(
                "Perf Globale", 
                f"{s_g}{g_perf:,.2f} %", 
                subtitle=f"YTD : {s_y}{y_perf:,.2f} %", 
                tone="success" if g_perf >= 0 else "alert"
            )
            
            self._kpi_pnl.set_content("PnL latent", f"{total_pnl:+,.2f} €".replace(",", " "), tone="success" if total_pnl >= 0 else "alert")
            self._kpi_nb.set_content("Positions", str(nb_pos))
            self._kpi_div.set_content("Dividendes", f"{t_div:,.2f} €".replace(",", " "), tone="success")
            self._kpi_int.set_content("Intérêts", f"{t_int:,.2f} €".replace(",", " "), tone="success")
            
            # --- Table ---
            display_cols = ["symbol", "name", "quantity", "pru", "last_price", "value", "pnl_latent", "compte", "type"]
            display_cols = [c for c in display_cols if c in df_all.columns]
            
            # Add "% port"
            if total_val > 0 and "value" in df_all.columns:
                df_all["poids_%"] = (df_all["value"] / total_val * 100.0).round(2)
                display_cols.insert(6, "poids_%")
                
            self._table_pos.set_dataframe(df_all[display_cols].sort_values("value", ascending=False))

            # --- Chart Alloc ---
            if "value" in df_all.columns and "symbol" in df_all.columns:
                df_pie = df_all[df_all["value"] > 0][["symbol", "value"]].copy()
                if not df_pie.empty:
                    fig = px.pie(df_pie, names="symbol", values="value", hole=0.4,
                                 template="plotly_dark")
                    fig.update_layout(**plotly_layout())
                    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                    self._chart_alloc.set_figure(fig)

            # --- Chart History ---
            df_snap = metrics.get("snapshots_df")
            if df_snap is not None and not df_snap.empty and "date" in df_snap.columns:
                fig_hist = px.line(df_snap, x="date", y="bourse_holdings", 
                                   template="plotly_dark", labels={"bourse_holdings": "Valeur Bourse (€)", "date": "Date"})
                fig_hist.update_traces(line_color="#00E676", line_width=3)
                if inv_eur > 0:
                   fig_hist.add_hline(y=inv_eur, line_dash="dash", line_color="#888888", annotation_text="Total Investi")
                fig_hist.update_layout(**plotly_layout())
                self._chart_history.set_figure(fig_hist)
                
            # --- Chart Income ---
            df_inc = metrics.get("income_df")
            if df_inc is not None and not df_inc.empty:
                # Group by month and type
                df_inc_grp = df_inc.groupby(["month", "type"], as_index=False)["amount_eur"].sum()
                fig_inc = px.bar(df_inc_grp, x="month", y="amount_eur", color="type",
                                 barmode="stack", template="plotly_dark",
                                 labels={"amount_eur": "Montant (€)", "month": "Mois", "type": "Type"})
                fig_inc.update_layout(**plotly_layout())
                self._chart_income.set_figure(fig_inc)

        except Exception as e:
            logger.error("BourseGlobalPanel._load_data error: %s", e, exc_info=True)
