"""
Panel d'un compte Banque — remplace ui/compte_banque.py
"""
import logging
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel
)
from qt_ui.components.animated_tab import AnimatedTabWidget
from qt_ui.widgets import DataTableWidget, MetricLabel
from qt_ui.panels.saisie_panel import SaisiePanel
from qt_ui.theme import (
    BG_PRIMARY, STYLE_SECTION, STYLE_TAB_INNER,
)

logger = logging.getLogger(__name__)


class CompteBanquePanel(QWidget):
    def __init__(self, conn, person_id: int, account_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._account_id = account_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        main_v = QVBoxLayout(self)
        main_v.setContentsMargins(12, 12, 12, 12)
        main_v.setSpacing(12)

        tabs = AnimatedTabWidget()
        tabs.setStyleSheet(STYLE_TAB_INNER)

        # Dashboard
        dash = QWidget()
        dash.setStyleSheet(f"background: {BG_PRIMARY};")
        dash_v = QVBoxLayout(dash)
        dash_v.setContentsMargins(8, 8, 8, 8)
        dash_v.setSpacing(10)

        kpi_row = QHBoxLayout()
        self._kpi_solde = MetricLabel("Solde actuel", "—")
        self._kpi_interets = MetricLabel("Intérêts 12 mois", "—")
        kpi_row.addWidget(self._kpi_solde)
        kpi_row.addWidget(self._kpi_interets)
        kpi_row.addStretch()
        dash_v.addLayout(kpi_row)

        lbl_hist = QLabel("Dernières opérations")
        lbl_hist.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_hist)
        self._table_recent = DataTableWidget()
        self._table_recent.setMinimumHeight(300)
        self._table_recent.set_filter_config([
            {"col": "type",     "kind": "combo",      "label": "Type"},
            {"col": "category", "kind": "combo",      "label": "Catégorie"},
        ])
        dash_v.addWidget(self._table_recent)
        dash_v.addStretch()
        tabs.addTab(dash, "🏦  Tableau de bord")

        # Saisie
        self._saisie = SaisiePanel(conn, person_id, account_id, "BANQUE")
        tabs.addTab(self._saisie, "✏️  Saisie")

        # Historique complet
        hist = QWidget()
        hist.setStyleSheet(f"background: {BG_PRIMARY};")
        hist_v = QVBoxLayout(hist)
        hist_v.setContentsMargins(8, 8, 8, 8)
        self._hist_table = DataTableWidget()
        self._hist_table.setMinimumHeight(400)
        self._hist_table.set_filter_config([
            {"col": "type",     "kind": "combo",        "label": "Type"},
            {"col": "date",     "kind": "date_range",   "label": "Date"},
            {"col": "amount",   "kind": "number_range", "label": "Montant"},
            {"col": "category", "kind": "combo",        "label": "Catégorie"},
        ])
        hist_v.addWidget(self._hist_table)
        tabs.addTab(hist, "📋  Historique")

        main_v.addWidget(tabs)
        self._tabs = tabs
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._load_dashboard()

    def refresh(self) -> None:
        self._load_dashboard()

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self._load_dashboard()
        elif idx == 2:
            self._load_history()

    def _load_dashboard(self) -> None:
        try:
            from services import repositories as repo
            from utils.validators import sens_flux

            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=5000)
            if tx is None or tx.empty:
                self._kpi_solde.set_content("Solde actuel", "0,00 €")
                self._table_recent.set_dataframe(pd.DataFrame())
                return

            # Calcul solde
            solde = 0.0
            interets_12m = 0.0
            today = pd.Timestamp.today()
            start_12m = today - pd.Timedelta(days=365)

            for _, r in tx.iterrows():
                solde += float(r.get("amount", 0)) * sens_flux(str(r.get("type", "")))
                d = pd.to_datetime(str(r.get("date", "")), errors="coerce")
                if d is not None and not pd.isna(d) and d >= start_12m and str(r.get("type", "")) == "INTERETS":
                    interets_12m += float(r.get("amount", 0))

            self._kpi_solde.set_content("Solde actuel", f"{solde:,.2f} €".replace(",", " "))
            self._kpi_interets.set_content("Intérêts 12 mois", f"{interets_12m:,.2f} €".replace(",", " "))

            # Recentes
            cols = ["date", "type", "amount", "fees", "category", "note"]
            cols = [c for c in cols if c in tx.columns]
            self._table_recent.set_dataframe(tx[cols].head(50))
        except Exception as e:
            logger.error("CompteBanquePanel._load_dashboard error: %s", e, exc_info=True)

    def _load_history(self) -> None:
        try:
            from services import repositories as repo
            from utils.libelles import afficher_type_operation

            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=5000)
            if tx is None or tx.empty:
                self._hist_table.set_dataframe(pd.DataFrame())
                return
            if "type" in tx.columns:
                tx = tx.copy()
                tx["type"] = tx["type"].apply(lambda t: afficher_type_operation(str(t)))
            cols = ["date", "type", "amount", "fees", "category", "note", "id"]
            cols = [c for c in cols if c in tx.columns]
            self._hist_table.set_dataframe(tx[cols])
        except Exception as e:
            logger.error("CompteBanquePanel._load_history error: %s", e, exc_info=True)
