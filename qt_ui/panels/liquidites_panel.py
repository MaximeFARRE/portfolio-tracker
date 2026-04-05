"""
Panel Liquidités — remplace ui/liquidites_overview.py
"""
import logging
import pandas as pd
import plotly.express as px
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
)

from qt_ui.theme import (
    BG_PRIMARY, STYLE_TITLE, STYLE_SECTION,
    CHART_GREEN, CHART_BLUE, CHART_PURPLE, plotly_layout,
)
from qt_ui.widgets import PlotlyView, KpiCard, LoadingOverlay

logger = logging.getLogger(__name__)


class LiquiditesPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Liquidités")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        # KPI cards
        kpi_row = QHBoxLayout()
        self._kpi_total = KpiCard("Total liquidités", "—", tone="primary")
        self._kpi_bank = KpiCard("Comptes bancaires", "—", tone="bank")
        self._kpi_bourse = KpiCard("Cash bourse", "—", tone="broker")
        self._kpi_pe = KpiCard("Cash PE", "—", tone="pe")
        for k in [self._kpi_total, self._kpi_bank, self._kpi_bourse, self._kpi_pe]:
            kpi_row.addWidget(k)
        layout.addLayout(kpi_row)

        # Graphique répartition
        lbl_chart = QLabel("Répartition des liquidités")
        lbl_chart.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_chart)
        self._chart = PlotlyView(min_height=280)
        layout.addWidget(self._chart)

        layout.addStretch()

        # ── Overlay de chargement (──────────────────────────────────────────
        self._overlay = LoadingOverlay(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    def _load_data(self) -> None:
        self._overlay.start("Chargement des liquidités…")
        try:
            from services.liquidites import _compute_liquidites_like_overview
            bank_cash, bourse_cash, pe_cash, total = _compute_liquidites_like_overview(
                self._conn, self._person_id
            )

            self._kpi_total.set_content("Total liquidités", f"{total:,.2f} €".replace(",", " "), tone="primary")
            self._kpi_bank.set_content("Comptes bancaires", f"{bank_cash:,.2f} €".replace(",", " "), tone="bank")
            self._kpi_bourse.set_content("Cash bourse", f"{bourse_cash:,.2f} €".replace(",", " "), tone="broker")
            self._kpi_pe.set_content("Cash PE", f"{pe_cash:,.2f} €".replace(",", " "), tone="pe")

            alloc = [
                {"Catégorie": "Banque", "Valeur": bank_cash},
                {"Catégorie": "Bourse (cash)", "Valeur": bourse_cash},
                {"Catégorie": "PE (cash)", "Valeur": pe_cash},
            ]
            df_alloc = pd.DataFrame([a for a in alloc if a["Valeur"] > 0])
            if not df_alloc.empty:
                fig = px.pie(df_alloc, names="Catégorie", values="Valeur", hole=0.45,
                             template="plotly_dark",
                             color_discrete_sequence=[CHART_GREEN, CHART_BLUE, CHART_PURPLE])
                fig.update_layout(**plotly_layout())
                self._chart.set_figure(fig)
        except Exception as e:
            logger.error("Erreur chargement liquidités : %s", e)
        finally:
            self._overlay.stop()
