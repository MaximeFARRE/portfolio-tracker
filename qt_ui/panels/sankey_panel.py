"""
Panel Sankey — remplace ui/sankey.py
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton
)
from qt_ui.widgets import PlotlyView
from qt_ui.theme import (
    BG_PRIMARY, STYLE_INPUT, STYLE_BTN_PRIMARY, STYLE_TITLE,
    TEXT_PRIMARY, CHART_SANKEY, plotly_layout,
)

logger = logging.getLogger(__name__)


class SankeyPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Flux de trésorerie — Sankey")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        # Sélection période
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Période :"))
        self._period_combo = QComboBox()
        self._period_combo.setStyleSheet(STYLE_INPUT)
        self._period_combo.addItems(["Mois courant", "3 derniers mois", "Année en cours", "12 derniers mois"])
        ctrl_row.addWidget(self._period_combo)
        btn_show = QPushButton("🔄  Afficher")
        btn_show.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_show.clicked.connect(self.refresh)
        ctrl_row.addWidget(btn_show)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        self._chart = PlotlyView(min_height=500)
        layout.addWidget(self._chart)
        layout.addStretch()

    def refresh(self) -> None:
        self._load_sankey()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_sankey()

    def _load_sankey(self) -> None:
        try:
            from services.sankey import build_cashflow_sankey
            import plotly.graph_objects as go
            from datetime import date

            today = date.today()
            idx = self._period_combo.currentIndex()

            if idx == 0:
                mois = [f"{today.year:04d}-{today.month:02d}-01"]
            elif idx == 1:
                mois = []
                for i in range(2, -1, -1):
                    m = today.month - i
                    y = today.year
                    while m <= 0:
                        m += 12
                        y -= 1
                    mois.append(f"{y:04d}-{m:02d}-01")
            elif idx == 2:
                mois = [f"{today.year:04d}-{m:02d}-01" for m in range(1, today.month + 1)]
            else:
                mois = []
                for i in range(11, -1, -1):
                    m = today.month - i
                    y = today.year
                    while m <= 0:
                        m += 12
                        y -= 1
                    mois.append(f"{y:04d}-{m:02d}-01")

            data = build_cashflow_sankey(self._conn, person_id=self._person_id, mois_list=mois)
            if not data or not data.get("values"):
                self._chart.clear_figure()
                return

            fig = go.Figure(go.Sankey(
                arrangement="snap",
                node=dict(
                    label=data["labels"],
                    pad=15,
                    thickness=20,
                    color="#2563eb",
                    line=dict(color=BG_PRIMARY, width=0.5),
                ),
                link=dict(
                    source=data["sources"],
                    target=data["targets"],
                    value=data["values"],
                    color=CHART_SANKEY,
                ),
            ))
            fig.update_layout(
                **plotly_layout(),
                font=dict(color=TEXT_PRIMARY, size=12),
            )
            self._chart.set_figure(fig)
        except Exception as e:
            logger.error("Erreur chargement Sankey: %s", e, exc_info=True)
            self._chart.clear_figure()
