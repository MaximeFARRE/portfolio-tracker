"""
Panel Revenus — remplace ui/revenus_scanner.py
"""
import logging
import pandas as pd
import plotly.express as px
from datetime import date
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QGroupBox
)

from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY, STYLE_INPUT, STYLE_GROUP, STYLE_SECTION,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_STATUS_WARNING,
    STYLE_BTN_UNDO, CHART_GREEN, plotly_layout, plotly_time_series_layout,
)
from qt_ui.widgets import PlotlyView, DataTableWidget, KpiCard, LoadingOverlay

logger = logging.getLogger(__name__)

CATEGORIES_REVENUS = ["Salaire", "Prime", "Freelance", "Loyers perçus", "Dividendes", "Intérêts", "Autres"]
MOIS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

class RevenusPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Sélection mois/année
        sel_grp = QGroupBox("Période")
        sel_grp.setStyleSheet(STYLE_GROUP)
        sel_h = QHBoxLayout(sel_grp)

        today = date.today()
        sel_h.addWidget(QLabel("Année :"))
        self._annee_combo = QComboBox()
        self._annee_combo.setStyleSheet(STYLE_INPUT)
        for y in range(today.year - 5, today.year + 1):
            self._annee_combo.addItem(str(y), y)
        self._annee_combo.setCurrentIndex(self._annee_combo.count() - 1)
        sel_h.addWidget(self._annee_combo)

        sel_h.addWidget(QLabel("Mois :"))
        self._mois_combo = QComboBox()
        self._mois_combo.setStyleSheet(STYLE_INPUT)
        for m in MOIS_FR:
            self._mois_combo.addItem(m)
        self._mois_combo.setCurrentIndex(today.month - 1)
        sel_h.addWidget(self._mois_combo)

        btn_refresh = QPushButton("🔄  Rafraîchir")
        btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_refresh.clicked.connect(self._refresh_view)
        sel_h.addWidget(btn_refresh)
        sel_h.addStretch()
        layout.addWidget(sel_grp)

        # Saisie rapide
        scanner_grp = QGroupBox("Saisie rapide")
        scanner_grp.setStyleSheet(STYLE_GROUP)
        scanner_v = QVBoxLayout(scanner_grp)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Catégorie :"))
        self._cat_combo = QComboBox()
        self._cat_combo.addItems(CATEGORIES_REVENUS)
        self._cat_combo.setStyleSheet(STYLE_INPUT)
        cat_row.addWidget(self._cat_combo)
        cat_row.addStretch()
        scanner_v.addLayout(cat_row)

        form_row = QHBoxLayout()
        self._montant_edit = QLineEdit()
        self._montant_edit.setPlaceholderText("Ex : 2500, 800")
        self._montant_edit.setStyleSheet(STYLE_INPUT)
        self._montant_edit.returnPressed.connect(self._on_add)
        form_row.addWidget(self._montant_edit, 1)

        btn_add = QPushButton("Ajouter ➕")
        btn_add.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_add.clicked.connect(self._on_add)
        form_row.addWidget(btn_add)

        btn_undo = QPushButton("Annuler dernière ↩️")
        btn_undo.setStyleSheet(STYLE_BTN_UNDO)
        btn_undo.clicked.connect(self._on_undo)
        form_row.addWidget(btn_undo)
        scanner_v.addLayout(form_row)

        self._saisie_result = QLabel()
        self._saisie_result.setStyleSheet(STYLE_STATUS_SUCCESS)
        scanner_v.addWidget(self._saisie_result)
        layout.addWidget(scanner_grp)

        # KPI
        kpi_row = QHBoxLayout()
        self._kpi_total = KpiCard("Total revenus", "—", tone="green")
        self._kpi_count = KpiCard("Entrées saisies", "—", tone="neutral")
        self._kpi_div = KpiCard("Dividendes", "—", tone="success")
        self._kpi_int = KpiCard("Intérêts", "—", tone="primary")
        self._kpi_div.setToolTip("Dividendes bourse intégrés aux revenus du mois.")
        self._kpi_int.setToolTip("Intérêts bourse intégrés aux revenus du mois.")
        kpi_row.addWidget(self._kpi_total)
        kpi_row.addWidget(self._kpi_count)
        kpi_row.addWidget(self._kpi_div)
        kpi_row.addWidget(self._kpi_int)
        kpi_row.addStretch()
        layout.addLayout(kpi_row)

        lbl_table = QLabel("Revenus du mois")
        lbl_table.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_table)
        self._table_mois = DataTableWidget()
        self._table_mois.setMinimumHeight(180)
        layout.addWidget(self._table_mois)

        lbl_chart = QLabel("Répartition par catégorie")
        lbl_chart.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_chart)
        self._chart_cat = PlotlyView(min_height=260)
        layout.addWidget(self._chart_cat)

        lbl_hist = QLabel("Historique mensuel")
        lbl_hist.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_hist)
        self._chart_hist = PlotlyView(min_height=300)
        layout.addWidget(self._chart_hist)

        layout.addStretch()
        # ── Overlay de chargement ──────────────────────────────────────────
        self._overlay = LoadingOverlay(self)
        self._refresh_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    def refresh(self) -> None:
        self._refresh_view()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._refresh_view()

    def _get_mois(self) -> str:
        annee = self._annee_combo.currentData()
        mois_num = self._mois_combo.currentIndex() + 1
        return f"{annee:04d}-{mois_num:02d}-01"

    def _on_add(self) -> None:
        txt = self._montant_edit.text().strip().replace(",", ".")
        try:
            montant = float(txt)
        except ValueError:
            self._saisie_result.setStyleSheet(STYLE_STATUS_ERROR)
            self._saisie_result.setText("Montant invalide.")
            return
        if montant <= 0:
            return

        from services.revenus_repository import ajouter_revenu
        mois = self._get_mois()
        cat = self._cat_combo.currentText()
        ajouter_revenu(self._conn, self._person_id, mois, cat, montant)
        self._saisie_result.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._saisie_result.setText(f"Ajouté : {cat} — {montant:.2f} €")
        self._montant_edit.clear()
        self._refresh_view()

    def _on_undo(self) -> None:
        from services.revenus_repository import derniere_revenu, supprimer_revenu_par_id
        mois = self._get_mois()
        last = derniere_revenu(self._conn, self._person_id, mois)
        if last is None:
            self._saisie_result.setStyleSheet(STYLE_STATUS_WARNING)
            self._saisie_result.setText("Rien à annuler pour ce mois.")
            return
        rev_id, cat, montant = last
        supprimer_revenu_par_id(self._conn, rev_id)
        self._saisie_result.setStyleSheet(STYLE_STATUS_WARNING)
        self._saisie_result.setText(f"Annulé : {cat} — {montant:.2f} €")
        self._refresh_view()

    def _refresh_view(self) -> None:
        self._overlay.start("Chargement des revenus…")
        try:
            from services.revenus_repository import (
                revenus_du_mois_consolides,
                revenus_kpis_mois,
                revenus_par_mois_consolides,
            )
            mois = self._get_mois()
            kpis = revenus_kpis_mois(self._conn, self._person_id, mois)
            df_mois = revenus_du_mois_consolides(self._conn, self._person_id, mois)

            total = float(kpis.get("total_revenus", 0.0))
            total_txt = f"{total:,.2f} €".replace(",", " ")
            self._kpi_total.set_content("Total revenus", total_txt, tone="green")
            self._kpi_count.set_content("Entrées saisies", str(int(kpis.get("entries_count", 0))), tone="neutral")
            self._kpi_div.set_content(
                "Dividendes",
                f"{float(kpis.get('dividendes', 0.0)):,.2f} €".replace(",", " "),
                tone="success",
            )
            self._kpi_int.set_content(
                "Intérêts",
                f"{float(kpis.get('interets', 0.0)):,.2f} €".replace(",", " "),
                tone="primary",
            )

            if df_mois is None or df_mois.empty:
                self._table_mois.set_dataframe(pd.DataFrame())
                self._chart_cat.clear_figure()
            else:
                self._table_mois.set_dataframe(df_mois)

                if "categorie" in df_mois.columns and "montant" in df_mois.columns:
                    df_cat = df_mois.groupby("categorie", as_index=False)["montant"].sum()
                    fig_cat = px.bar(df_cat, x="categorie", y="montant", template="plotly_dark",
                                     color="montant", color_continuous_scale="Greens",
                                     labels={"categorie": "Catégorie", "montant": "Montant (€)"})
                    fig_cat.update_layout(**plotly_layout(showlegend=False))
                    self._chart_cat.set_figure(fig_cat)
                else:
                    self._chart_cat.clear_figure()

            try:
                df_hist = revenus_par_mois_consolides(self._conn, self._person_id)
                if df_hist is not None and not df_hist.empty and "mois" in df_hist.columns:
                    df_hist["mois"] = pd.to_datetime(df_hist["mois"], errors="coerce")
                    df_hist = df_hist.dropna(subset=["mois"]).sort_values("mois")
                    if "total" in df_hist.columns:
                        fig_h = px.bar(df_hist, x="mois", y="total", template="plotly_dark",
                                       labels={"mois": "Mois", "total": "Total revenus (€)"},
                                       color_discrete_sequence=[CHART_GREEN])
                        fig_h.update_layout(**plotly_time_series_layout())
                        self._chart_hist.set_figure(fig_h)
                    else:
                        self._chart_hist.clear_figure()
                else:
                    self._chart_hist.clear_figure()
            except Exception as e:
                logger.warning("Chargement historique mensuel revenus échoué : %s", e)
                self._chart_hist.clear_figure()

        except Exception as e:
            self._saisie_result.setStyleSheet(STYLE_STATUS_ERROR)
            self._saisie_result.setText(f"Erreur : {e}")
        finally:
            self._overlay.stop()
