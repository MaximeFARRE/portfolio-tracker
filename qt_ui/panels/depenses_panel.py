"""
Panel Dépenses — remplace ui/depenses_scanner.py
"""
import logging
import pandas as pd
import plotly.express as px
from datetime import date
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QGroupBox
)
from PyQt6.QtCore import Qt

from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY, STYLE_INPUT, STYLE_GROUP, STYLE_SECTION,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_STATUS_WARNING,
    STYLE_BTN_UNDO, plotly_layout, plotly_time_series_layout,
)
from qt_ui.widgets import PlotlyView, DataTableWidget, KpiCard, LoadingOverlay

logger = logging.getLogger(__name__)

CATEGORIES_DEPENSES = ["Loyer", "Remboursement crédit", "Nourriture", "Éducation", "Transports", "Autres"]
MOIS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


class DepensesPanel(QWidget):
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
        scanner_grp = QGroupBox("Saisie rapide (mode scanner)")
        scanner_grp.setStyleSheet(STYLE_GROUP)
        scanner_v = QVBoxLayout(scanner_grp)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Catégorie :"))
        self._cat_combo = QComboBox()
        self._cat_combo.addItems(CATEGORIES_DEPENSES)
        self._cat_combo.setStyleSheet(STYLE_INPUT)
        cat_row.addWidget(self._cat_combo)
        cat_row.addStretch()
        scanner_v.addLayout(cat_row)

        form_row = QHBoxLayout()
        self._montant_edit = QLineEdit()
        self._montant_edit.setPlaceholderText("Ex : 4, 12.5, 23")
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

        # KPI résumé du mois
        kpi_row = QHBoxLayout()
        self._kpi_total = KpiCard("Total dépenses", "—", tone="red")
        self._kpi_count = KpiCard("Nombre d'entrées", "—", tone="neutral")
        kpi_row.addWidget(self._kpi_total)
        kpi_row.addWidget(self._kpi_count)
        kpi_row.addStretch()
        layout.addLayout(kpi_row)

        # Tableau du mois
        lbl_table = QLabel("Dépenses du mois")
        lbl_table.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_table)
        self._table_mois = DataTableWidget()
        self._table_mois.setMinimumHeight(200)
        layout.addWidget(self._table_mois)

        # Graphique par catégorie
        lbl_chart = QLabel("Répartition par catégorie")
        lbl_chart.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_chart)
        self._chart_cat = PlotlyView(min_height=280)
        layout.addWidget(self._chart_cat)

        # Historique mensuel
        lbl_hist = QLabel("Historique mensuel")
        lbl_hist.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_hist)
        self._chart_hist = PlotlyView(min_height=320)
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
            self._saisie_result.setStyleSheet(STYLE_STATUS_ERROR)
            self._saisie_result.setText("Montant doit être > 0.")
            return

        from services.depenses_repository import ajouter_depense
        mois = self._get_mois()
        cat = self._cat_combo.currentText()
        ajouter_depense(self._conn, self._person_id, mois, cat, montant)
        self._saisie_result.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._saisie_result.setText(f"Ajouté : {cat} — {montant:.2f} €")
        self._montant_edit.clear()
        self._refresh_view()

    def _on_undo(self) -> None:
        from services.depenses_repository import derniere_depense, supprimer_depense_par_id
        mois = self._get_mois()
        last = derniere_depense(self._conn, self._person_id, mois)
        if last is None:
            self._saisie_result.setStyleSheet(STYLE_STATUS_WARNING)
            self._saisie_result.setText("Rien à annuler pour ce mois.")
            return
        depense_id, cat, montant = last
        supprimer_depense_par_id(self._conn, depense_id)
        self._saisie_result.setStyleSheet(STYLE_STATUS_WARNING)
        self._saisie_result.setText(f"Annulé : {cat} — {montant:.2f} €")
        self._refresh_view()

    def _refresh_view(self) -> None:
        self._overlay.start("Chargement des dépenses…")
        try:
            from services.depenses_repository import depenses_du_mois, depenses_par_mois
            mois = self._get_mois()

            # Données du mois
            df_mois = depenses_du_mois(self._conn, self._person_id, mois)
            if df_mois is None or df_mois.empty:
                self._kpi_total.set_content("Total dépenses", "0,00 €", tone="red")
                self._kpi_count.set_content("Entrées", "0", tone="neutral")
                self._table_mois.set_dataframe(pd.DataFrame())
                self._chart_cat.clear_figure()
                return

            total = float(df_mois["montant"].sum()) if "montant" in df_mois.columns else 0.0
            self._kpi_total.set_content("Total dépenses", f"{total:,.2f} €".replace(",", " "), tone="red")
            self._kpi_count.set_content("Entrées", str(len(df_mois)), tone="neutral")
            self._table_mois.set_dataframe(df_mois)

            # Graphique catégories
            if "categorie" in df_mois.columns and "montant" in df_mois.columns:
                df_cat = df_mois.groupby("categorie", as_index=False)["montant"].sum()
                df_cat = df_cat.sort_values("montant", ascending=False)
                fig_cat = px.bar(df_cat, x="categorie", y="montant",
                                 template="plotly_dark",
                                 labels={"categorie": "Catégorie", "montant": "Montant (€)"},
                                 color="montant", color_continuous_scale="Reds")
                fig_cat.update_layout(**plotly_layout(showlegend=False))
                self._chart_cat.set_figure(fig_cat)

            # Historique mensuel
            try:
                df_hist = depenses_par_mois(self._conn, self._person_id)
                if df_hist is not None and not df_hist.empty and "mois" in df_hist.columns:
                    df_hist["mois"] = pd.to_datetime(df_hist["mois"], errors="coerce")
                    df_hist = df_hist.dropna(subset=["mois"]).sort_values("mois")
                    total_col = [c for c in df_hist.columns if c not in ("mois", "person_id", "person_name")]
                    if total_col:
                        df_hist["total"] = df_hist[total_col].sum(axis=1)
                        fig_h = px.bar(df_hist, x="mois", y="total", template="plotly_dark",
                                       labels={"mois": "Mois", "total": "Total dépenses (€)"})
                        fig_h.update_layout(**plotly_time_series_layout())
                        self._chart_hist.set_figure(fig_h)
            except Exception as e:
                logger.warning("Chargement historique mensuel dépenses échoué : %s", e)

        except Exception as e:
            self._saisie_result.setStyleSheet(STYLE_STATUS_ERROR)
            self._saisie_result.setText(f"Erreur : {e}")
        finally:
            self._overlay.stop()
