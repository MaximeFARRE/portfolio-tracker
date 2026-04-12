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
    CHART_GREEN, CHART_BLUE, CHART_PURPLE, COLOR_WARNING, BG_CARD, plotly_layout,
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

        self._quality_label = QLabel("")
        self._quality_label.setStyleSheet(
            f"color: {COLOR_WARNING}; background: {BG_CARD}; border: 1px solid {COLOR_WARNING}; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px;"
        )
        self._quality_label.setVisible(False)
        layout.addWidget(self._quality_label)

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
            from services.liquidites import get_liquidites_summary
            summary = get_liquidites_summary(self._conn, self._person_id)
            bank_cash = summary["bank_cash_eur"]
            bourse_cash = summary["bourse_cash_eur"]
            pe_cash = summary["pe_cash_eur"]
            total = summary["total_eur"]
            missing_fx = summary.get("missing_fx", [])

            def _fmt_amount(value: float | None, component: str | None = None) -> str:
                if value is None or pd.isna(value):
                    return "—"
                if component and any(item.get("component") == component for item in missing_fx) and float(value) == 0.0:
                    return "—"
                if component is None and missing_fx and float(value) == 0.0:
                    return "—"
                return f"{value:,.2f} €".replace(",", " ")

            if missing_fx:
                pairs = sorted({str(item.get("currency", "?")) + "→EUR" for item in missing_fx})
                self._quality_label.setText(
                    "⚠️ Liquidités partielles : taux FX manquant(s) "
                    f"{', '.join(pairs)}. Certains comptes sont exclus du total."
                )
                self._quality_label.setVisible(True)
            else:
                self._quality_label.setVisible(False)

            total_subtitle = "Total partiel (FX manquant)" if missing_fx else ""
            bank_subtitle = "Partiel" if any(item.get("component") == "bank" for item in missing_fx) else ""
            bourse_subtitle = "Partiel" if any(item.get("component") == "bourse" for item in missing_fx) else ""
            self._kpi_total.set_content("Total liquidités", _fmt_amount(total), subtitle=total_subtitle, tone="primary")
            self._kpi_bank.set_content("Comptes bancaires", _fmt_amount(bank_cash, "bank"), subtitle=bank_subtitle, tone="bank")
            self._kpi_bourse.set_content("Cash bourse", _fmt_amount(bourse_cash, "bourse"), subtitle=bourse_subtitle, tone="broker")
            self._kpi_pe.set_content("Cash PE", _fmt_amount(pe_cash), tone="pe")

            alloc = [
                {"Catégorie": "Banque", "Valeur": bank_cash},
                {"Catégorie": "Bourse (cash)", "Valeur": bourse_cash},
                {"Catégorie": "PE (cash)", "Valeur": pe_cash},
            ]
            df_alloc = pd.DataFrame(
                [a for a in alloc if a["Valeur"] is not None and not pd.isna(a["Valeur"]) and float(a["Valeur"]) > 0.0]
            )
            if not df_alloc.empty:
                fig = px.pie(df_alloc, names="Catégorie", values="Valeur", hole=0.45,
                             template="plotly_dark",
                             color_discrete_sequence=[CHART_GREEN, CHART_BLUE, CHART_PURPLE])
                fig.update_layout(**plotly_layout())
                self._chart.set_figure(fig)
            else:
                self._chart.clear_figure()
        except Exception as e:
            logger.error("Erreur chargement liquidités : %s", e)
        finally:
            self._overlay.stop()
