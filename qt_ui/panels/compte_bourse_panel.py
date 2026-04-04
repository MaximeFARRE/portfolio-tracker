"""
Panel d'un compte Bourse (PEA/CTO/CRYPTO) — remplace ui/compte_bourse.py
"""
import logging
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from qt_ui.components.animated_tab import AnimatedTabWidget
from PyQt6.QtCore import QThread, pyqtSignal

from qt_ui.widgets import PlotlyView, DataTableWidget, MetricLabel, LoadingOverlay
from qt_ui.panels.saisie_panel import SaisiePanel, ASSET_TYPES
from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY, STYLE_SECTION, STYLE_STATUS,
    STYLE_TAB_INNER, plotly_layout,
)

logger = logging.getLogger(__name__)


class PriceRefreshThread(QThread):
    finished = pyqtSignal(int, int)

    def __init__(self, account_id: int, account_ccy: str):
        super().__init__()
        self._account_id = account_id
        self._account_ccy = account_ccy

    def run(self):
        from services import repositories as repo
        from services import pricing, fx
        from services.db import get_conn
        n_ok, n_fail = 0, 0
        with get_conn() as local_conn:
            asset_ids = repo.list_account_asset_ids(local_conn, account_id=self._account_id)
            for aid in asset_ids:
                a = local_conn.execute("SELECT symbol FROM assets WHERE id = ?", (aid,)).fetchone()
                if not a:
                    continue
                sym = a[0] if not hasattr(a, '__getitem__') else a["symbol"]
                px_val, ccy = pricing.fetch_last_price_auto(sym)
                if px_val is not None:
                    repo.upsert_price(local_conn, asset_id=aid, date=pricing.today_str(),
                                      price=px_val, currency=ccy, source="AUTO")
                    if ccy:
                        repo.update_asset_currency(local_conn, aid, str(ccy).upper())
                        if str(ccy).upper() != self._account_ccy:
                            fx.ensure_fx_rate(local_conn, str(ccy).upper(), self._account_ccy)
                    n_ok += 1
                else:
                    n_fail += 1
        self.finished.emit(n_ok, n_fail)


class CompteBoursePanel(QWidget):
    def __init__(self, conn, person_id: int, account_id: int, account_type: str, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._account_id = account_id
        self._account_type = account_type
        self._thread = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        main_v = QVBoxLayout(self)
        main_v.setContentsMargins(12, 12, 12, 12)
        main_v.setSpacing(12)

        # Onglets internes : Tableau de bord / Saisie / Historique
        tabs = AnimatedTabWidget()
        tabs.setStyleSheet(STYLE_TAB_INNER)

        # Onglet dashboard
        dash = QWidget()
        dash.setStyleSheet(f"background: {BG_PRIMARY};")
        dash_v = QVBoxLayout(dash)
        dash_v.setContentsMargins(8, 8, 8, 8)
        dash_v.setSpacing(10)

        # Refresh btn
        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("↻  Rafraîchir les prix")
        self._btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_refresh.clicked.connect(self._on_refresh_prices)
        btn_row.addWidget(self._btn_refresh)
        self._refresh_status = QLabel()
        self._refresh_status.setStyleSheet(STYLE_STATUS)
        btn_row.addWidget(self._refresh_status)
        btn_row.addStretch()
        dash_v.addLayout(btn_row)

        # KPIs
        kpi_row = QHBoxLayout()
        self._kpi_holdings = MetricLabel("Holdings (EUR)", "—")
        self._kpi_pnl = MetricLabel("PnL latent", "—")
        self._kpi_nb = MetricLabel("Positions", "—")
        kpi_row.addWidget(self._kpi_holdings)
        kpi_row.addWidget(self._kpi_pnl)
        kpi_row.addWidget(self._kpi_nb)
        kpi_row.addStretch()
        dash_v.addLayout(kpi_row)

        # Tableau positions
        lbl_pos = QLabel("📌 Positions")
        lbl_pos.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_pos)
        self._table_pos = DataTableWidget()
        self._table_pos.setMinimumHeight(220)
        self._table_pos.set_combo_delegate("asset_type", ASSET_TYPES)
        self._table_pos.hide_column("asset_id")
        self._table_pos.cell_changed.connect(self._on_asset_type_changed)
        dash_v.addWidget(self._table_pos)

        # Graphique répartition
        lbl_alloc = QLabel("Répartition")
        lbl_alloc.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_alloc)
        self._chart_alloc = PlotlyView(min_height=280)
        dash_v.addWidget(self._chart_alloc)

        dash_v.addStretch()
        tabs.addTab(dash, "📊  Tableau de bord")

        # Onglet saisie
        self._saisie = SaisiePanel(conn, person_id, account_id, account_type)
        tabs.addTab(self._saisie, "✏️  Saisie")

        # Onglet historique
        hist = QWidget()
        hist.setStyleSheet(f"background: {BG_PRIMARY};")
        hist_v = QVBoxLayout(hist)
        hist_v.setContentsMargins(8, 8, 8, 8)
        self._hist_table = DataTableWidget()
        self._hist_table.setMinimumHeight(400)
        hist_v.addWidget(self._hist_table)
        tabs.addTab(hist, "📋  Historique")

        main_v.addWidget(tabs)
        self._tabs = tabs
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # ── Overlay de chargement ──────────────────────────────────────────
        self._overlay = LoadingOverlay(self)
        self._load_dashboard()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    def refresh(self) -> None:
        self._load_dashboard()
        if self._tabs.currentIndex() == 2:
            self._load_history()

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self._load_dashboard()
        elif idx == 1:
            self._saisie._load_assets()
        elif idx == 2:
            self._load_history()

    def _on_refresh_prices(self) -> None:
        self._btn_refresh.setEnabled(False)
        self._refresh_status.setText("Rafraîchissement...")
        try:
            from services import repositories as repo
            acc = repo.get_account(self._conn, self._account_id)
            acc_ccy = (acc["currency"] if acc and acc["currency"] else "EUR").upper()
        except Exception as e:
            logger.warning("Could not fetch account currency: %s", e)
            acc_ccy = "EUR"
        self._thread = PriceRefreshThread(self._account_id, acc_ccy)
        self._thread.finished.connect(self._on_refresh_done)
        self._thread.start()

    def _on_refresh_done(self, n_ok: int, n_fail: int) -> None:
        self._btn_refresh.setEnabled(True)
        self._refresh_status.setText(f"✅ {n_ok} OK, {n_fail} non trouvés")
        self._load_dashboard()

    def _load_dashboard(self) -> None:
        self._overlay.start("Chargement du portefeuille…")
        try:
            from services import repositories as repo
            from services import portfolio

            acc = repo.get_account(self._conn, self._account_id)
            acc_ccy = (acc["currency"] if acc and acc["currency"] else "EUR").upper() if acc else "EUR"

            tx_acc = repo.list_transactions(self._conn, account_id=self._account_id, limit=10000)
            asset_ids = repo.list_account_asset_ids(self._conn, account_id=self._account_id)
            latest_prices = repo.get_latest_prices(self._conn, asset_ids)

            pos = portfolio.compute_positions_v2_fx(self._conn, tx_acc, latest_prices, acc_ccy)

            if pos.empty:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucune position (ACHAT/VENTE)."}]))
                return

            total_val = float(pos["value"].sum()) if "value" in pos.columns else 0.0
            total_pnl = float(pos["pnl_latent"].sum()) if "pnl_latent" in pos.columns else 0.0
            nb_pos = len(pos[pos["quantity"] > 0]) if "quantity" in pos.columns else len(pos)

            self._kpi_holdings.set_content("Holdings", f"{total_val:,.2f} €".replace(",", " "))
            self._kpi_pnl.set_content("PnL latent", f"{total_pnl:+,.2f} €".replace(",", " "),
                                       delta=f"{total_pnl:+.2f}", delta_positive=total_pnl >= 0)
            self._kpi_nb.set_content("Positions", str(nb_pos))

            display_cols = ["asset_id", "symbol", "name", "asset_type", "quantity", "pru", "last_price", "value", "pnl_latent", "asset_ccy"]
            display_cols = [c for c in display_cols if c in pos.columns]
            self._table_pos.set_dataframe(pos[display_cols])

            # Graphique
            if "value" in pos.columns and "symbol" in pos.columns:
                df_pie = pos[pos["value"] > 0][["symbol", "value"]].copy()
                if not df_pie.empty:
                    fig = px.pie(df_pie, names="symbol", values="value", hole=0.4,
                                 template="plotly_dark",
                                 labels={"symbol": "Actif", "value": "Valeur (€)"})
                    fig.update_layout(**plotly_layout())
                    self._chart_alloc.set_figure(fig)

        except Exception as e:
            logger.error("CompteBoursePanel._load_dashboard error: %s", e, exc_info=True)
        finally:
            self._overlay.stop()

    def _on_asset_type_changed(self, row: int, col_name: str, new_value) -> None:
        if col_name != "asset_type":
            return
        df = self._table_pos.get_dataframe()
        if row < len(df) and "asset_id" in df.columns:
            try:
                asset_id = int(df.iloc[row]["asset_id"])
                from services import repositories as repo
                repo.update_asset_type(self._conn, asset_id, str(new_value))
            except Exception as e:
                logger.error("Erreur mise à jour asset_type: %s", e, exc_info=True)

    def _load_history(self) -> None:
        try:
            from services import repositories as repo
            from utils.libelles import afficher_type_operation

            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=5000)
            if tx is None or tx.empty:
                self._hist_table.set_dataframe(pd.DataFrame([{"Info": "Aucune opération."}]))
                return
            if "type" in tx.columns:
                tx = tx.copy()
                tx["type"] = tx["type"].apply(lambda t: afficher_type_operation(str(t)))
            cols = ["date", "type", "asset_symbol", "amount", "fees", "category", "note", "id"]
            cols = [c for c in cols if c in tx.columns]
            self._hist_table.set_dataframe(tx[cols])
        except Exception as e:
            logger.error("CompteBoursePanel._load_history error: %s", e, exc_info=True)
