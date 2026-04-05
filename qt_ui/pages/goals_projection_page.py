"""
Page Objectifs & Projection.
"""
import logging
from datetime import date
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qt_ui.components.animated_tab import AnimatedTabWidget
from qt_ui.theme import (
    BG_ACTIVE, BG_CARD, BG_PRIMARY, BG_SIDEBAR,
    BORDER_DEFAULT, BORDER_SUBTLE,
    COLOR_SUCCESS, COLOR_WARNING, STYLE_BTN_DANGER, STYLE_BTN_PRIMARY,
    STYLE_BTN_PRIMARY_BORDERED, STYLE_BTN_SUCCESS, STYLE_GROUP, STYLE_INPUT_FOCUS,
    STYLE_SCROLLAREA, STYLE_SECTION, STYLE_STATUS, STYLE_STATUS_ERROR, STYLE_STATUS_SUCCESS,
    STYLE_STATUS_WARNING,
    STYLE_TAB, STYLE_TITLE, STYLE_TITLE_LARGE, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
    plotly_layout,
)
from qt_ui.widgets import DataTableWidget, KpiCard, MetricLabel, PlotlyView
from services.goals_projection_repository import (
    create_goal, create_scenario, delete_goal, delete_scenario,
    compute_goal_monthly_required_amount, list_goals, list_people_for_scope, list_scenarios,
    update_goal, update_scenario,
)
from services.projections import (
    ScenarioParams, build_standard_scenarios, compute_weighted_return,
    estimate_fire_reach_date, get_primary_residence_value_for_scope,
    get_projection_base_for_scope, run_projection,
)
from services.simulation_presets_repository import (
    get_all_presets, initialize_default_presets, PRESET_DEFAULTS,
)
from services.native_milestones import (
    NATIVE_MILESTONE_DEFINITIONS,
    build_native_milestones_for_scope,
    get_featured_milestone_for_category,
    get_scope_milestone_metrics,
)
from utils.format_monnaie import money

logger = logging.getLogger(__name__)

_COMBO_STYLE = f"""
    QComboBox {{
        background: {BG_CARD};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 14px;
        min-width: 220px;
    }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{
        background: {BG_CARD};
        color: {TEXT_PRIMARY};
        selection-background-color: {BG_ACTIVE};
    }}
"""

_MILESTONE_PROGRESS_STYLE = f"""
    QProgressBar {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: 6px;
        text-align: center;
        height: 14px;
        color: {TEXT_PRIMARY};
    }}
    QProgressBar::chunk {{
        background: {COLOR_SUCCESS};
        border-radius: 5px;
    }}
"""

_PRIORITY_ITEMS = [("Basse", "LOW"), ("Normale", "NORMAL"), ("Haute", "HIGH")]
_STATUS_ITEMS = [("Actif", "ACTIVE"), ("Atteint", "ACHIEVED"), ("En pause", "PAUSED"), ("Annulé", "CANCELLED")]


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class NativeMilestoneCard(QGroupBox):
    """Carte compacte pour un jalon natif."""

    def __init__(self, category_label: str, parent=None):
        super().__init__(category_label, parent)
        self.setStyleSheet(STYLE_GROUP)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        self._level_label = QLabel("Niveau 0")
        self._level_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self._level_label)

        self._value_label = QLabel("Valeur actuelle : —")
        self._value_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._value_label)

        self._next_label = QLabel("Prochain palier : —")
        self._next_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._next_label)

        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setStyleSheet(_MILESTONE_PROGRESS_STYLE)
        bar_row.addWidget(self._progress_bar, 1)
        self._progress_label = QLabel("0.0 %")
        self._progress_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        bar_row.addWidget(self._progress_label)
        layout.addLayout(bar_row)

        self._subtitle_label = QLabel("—")
        self._subtitle_label.setWordWrap(True)
        self._subtitle_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self._subtitle_label)

    def set_milestone_data(self, milestone: Optional[dict]) -> None:
        if not milestone:
            self._level_label.setText("Niveau 0")
            self._value_label.setText("Valeur actuelle : —")
            self._next_label.setText("Prochain palier : —")
            self._progress_bar.setValue(0)
            self._progress_label.setText("0.0 %")
            self._subtitle_label.setText("Aucune donnée disponible.")
            return

        level_number = int(milestone.get("level_number", 0))
        display_value = str(milestone.get("display_value") or "—")
        progress_pct = max(0.0, min(_safe_float(milestone.get("progress_pct")), 100.0))
        is_max_level = bool(milestone.get("is_max_level"))

        self._level_label.setText(f"Niveau {level_number}")
        self._value_label.setText(f"Valeur actuelle : {display_value}")
        if is_max_level:
            self._next_label.setText("Prochain palier : niveau maximal atteint")
        else:
            next_threshold = milestone.get("next_threshold")
            unit = str(milestone.get("unit") or "")
            if next_threshold is None:
                self._next_label.setText("Prochain palier : —")
            elif unit == "PCT":
                self._next_label.setText(f"Prochain palier : {next_threshold:.1f} %")
            else:
                self._next_label.setText(f"Prochain palier : {money(next_threshold)}")

        self._progress_bar.setValue(int(round(progress_pct)))
        self._progress_label.setText(f"{progress_pct:.1f} %")
        self._subtitle_label.setText(str(milestone.get("subtitle") or ""))

class GoalEditDialog(QDialog):
    def __init__(self, goal_data: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self._goal_data = goal_data or {}
        self._build_ui()
        self._fill_initial_values()

    def _build_ui(self) -> None:
        self.setWindowTitle("Modifier un objectif" if self._goal_data else "Nouvel objectif")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        box = QGroupBox("Détails de l'objectif")
        box.setStyleSheet(STYLE_GROUP)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._name = QLineEdit()
        self._name.setStyleSheet(STYLE_INPUT_FOCUS)
        self._category = QLineEdit()
        self._category.setStyleSheet(STYLE_INPUT_FOCUS)
        self._target_amount = QDoubleSpinBox()
        self._target_amount.setRange(0, 1_000_000_000)
        self._target_amount.setDecimals(2)
        self._target_amount.setSuffix(" €")
        self._target_amount.setStyleSheet(STYLE_INPUT_FOCUS)
        self._current_amount = QDoubleSpinBox()
        self._current_amount.setRange(0, 1_000_000_000)
        self._current_amount.setDecimals(2)
        self._current_amount.setSuffix(" €")
        self._current_amount.setStyleSheet(STYLE_INPUT_FOCUS)
        self._use_target_date = QCheckBox("Date cible")
        self._target_date = QDateEdit()
        self._target_date.setCalendarPopup(True)
        self._target_date.setDisplayFormat("dd/MM/yyyy")
        self._target_date.setDate(QDate.currentDate())
        self._target_date.setStyleSheet(STYLE_INPUT_FOCUS)
        self._priority = QComboBox()
        self._priority.setStyleSheet(STYLE_INPUT_FOCUS)
        for label, code in _PRIORITY_ITEMS:
            self._priority.addItem(label, code)
        self._status = QComboBox()
        self._status.setStyleSheet(STYLE_INPUT_FOCUS)
        for label, code in _STATUS_ITEMS:
            self._status.addItem(label, code)
        self._notes = QLineEdit()
        self._notes.setStyleSheet(STYLE_INPUT_FOCUS)
        date_row = QWidget()
        date_layout = QHBoxLayout(date_row)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.addWidget(self._use_target_date)
        date_layout.addWidget(self._target_date)
        form.addRow("Nom :", self._name)
        form.addRow("Catégorie :", self._category)
        form.addRow("Montant cible :", self._target_amount)
        form.addRow("Montant actuel :", self._current_amount)
        form.addRow("Échéance :", date_row)
        form.addRow("Priorité :", self._priority)
        form.addRow("Statut :", self._status)
        form.addRow("Notes :", self._notes)
        layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._use_target_date.toggled.connect(self._target_date.setEnabled)

    def _fill_initial_values(self) -> None:
        if not self._goal_data:
            self._use_target_date.setChecked(False)
            return

        self._name.setText(str(self._goal_data.get("name") or ""))
        self._category.setText(str(self._goal_data.get("category") or ""))
        self._target_amount.setValue(_safe_float(self._goal_data.get("target_amount")))
        self._current_amount.setValue(_safe_float(self._goal_data.get("current_amount")))
        self._notes.setText(str(self._goal_data.get("notes") or ""))

        idx_priority = self._priority.findData(str(self._goal_data.get("priority") or "NORMAL").upper())
        if idx_priority >= 0:
            self._priority.setCurrentIndex(idx_priority)

        idx_status = self._status.findData(str(self._goal_data.get("status") or "ACTIVE").upper())
        if idx_status >= 0:
            self._status.setCurrentIndex(idx_status)

        target_date_raw = self._goal_data.get("target_date")
        target_date = pd.to_datetime(target_date_raw, errors="coerce") if target_date_raw else pd.NaT
        if pd.notna(target_date):
            self._use_target_date.setChecked(True)
            self._target_date.setDate(QDate(target_date.year, target_date.month, target_date.day))
        else:
            self._use_target_date.setChecked(False)

    def _on_accept(self) -> None:
        if not self._name.text().strip():
            QMessageBox.warning(self, "Validation", "Le nom de l'objectif est obligatoire.")
            return
        self.accept()

    def get_payload(self) -> dict:
        return {
            "name": self._name.text().strip(),
            "category": self._category.text().strip() or None,
            "target_amount": float(self._target_amount.value()),
            "current_amount": float(self._current_amount.value()),
            "target_date": self._target_date.date().toString("yyyy-MM-dd") if self._use_target_date.isChecked() else None,
            "priority": str(self._priority.currentData() or "NORMAL"),
            "status": str(self._status.currentData() or "ACTIVE"),
            "notes": self._notes.text().strip() or None,
        }


class GoalsProjectionPage(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._scope_type: str = "family"
        self._scope_id: Optional[int] = None
        self._base_data: dict = {}
        self._projection_df = pd.DataFrame()
        self._standard_projection_results: dict[str, pd.DataFrame] = {}
        self._goals_raw_df = pd.DataFrame()
        self._scenarios_raw_df = pd.DataFrame()
        self._native_milestones: list[dict] = []
        self._native_metrics: dict = {}
        self._featured_milestone: Optional[dict] = None
        self._active_scenario_name: str = "Personnalisé"
        self._active_preset: Optional[str] = None   # 'pessimiste' | 'realiste' | 'optimiste' | None
        self._presets_cache: dict = {}               # {preset_key: params_dict}
        self._rp_value_for_scope: float = 0.0       # valeur RP pour affichage
        self._build_ui()
        self._load_scope_options()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"background: {BG_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setStyleSheet(f"background: {BG_SIDEBAR}; border-bottom: 1px solid {BORDER_SUBTLE};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)

        title = QLabel("Objectifs & Projection")
        title.setStyleSheet(STYLE_TITLE_LARGE)
        header_layout.addWidget(title)
        header_layout.addWidget(QLabel("  ->  "))

        self._scope_combo = QComboBox()
        self._scope_combo.setStyleSheet(_COMBO_STYLE)
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        header_layout.addWidget(self._scope_combo)
        header_layout.addStretch()
        layout.addWidget(header)

        self._tabs = AnimatedTabWidget()
        self._tabs.setStyleSheet(STYLE_TAB)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._panel_projection = self._build_projection_tab()
        self._panel_goals = self._build_goals_tab()
        self._panel_scenarios = self._build_scenarios_tab()

        self._tabs.addTab(self._panel_projection, "Projection")
        self._tabs.addTab(self._panel_goals, "Objectifs")
        self._tabs.addTab(self._panel_scenarios, "Scénarios")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(STYLE_SCROLLAREA)
        scroll.setWidget(self._tabs)
        layout.addWidget(scroll, 1)

    def refresh(self) -> None:
        self._load_scope_options()

    def _load_scope_options(self) -> None:
        previous_scope = (self._scope_type, self._scope_id)

        self._scope_combo.blockSignals(True)
        self._scope_combo.clear()
        self._scope_combo.addItem("Famille", ("family", None))

        try:
            people_df = list_people_for_scope(self._conn)
        except Exception as exc:
            logger.error("Erreur chargement des personnes pour scope : %s", exc)
            people_df = pd.DataFrame(columns=["id", "name"])

        if people_df is not None and not people_df.empty:
            for _, row in people_df.iterrows():
                self._scope_combo.addItem(str(row["name"]), ("person", int(row["id"])))

        selected_index = 0
        for i in range(self._scope_combo.count()):
            data = self._scope_combo.itemData(i)
            if not data:
                continue
            if data[0] == previous_scope[0] and data[1] == previous_scope[1]:
                selected_index = i
                break

        self._scope_combo.setCurrentIndex(selected_index)
        self._scope_combo.blockSignals(False)
        self._on_scope_changed(self._scope_combo.currentIndex())

    def _on_scope_changed(self, index: int) -> None:
        data = self._scope_combo.itemData(index)
        if not data:
            return
        self._scope_type = str(data[0])
        self._scope_id = None if data[1] is None else int(data[1])
        self._load_scope_data()

    def _on_tab_changed(self, _index: int) -> None:
        self._refresh_active_tab()

    def _refresh_active_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx == 0:
            self._refresh_projection_tab()
        elif idx == 1:
            self._refresh_goals_tab()
        elif idx == 2:
            self._refresh_scenarios_tab()

    def _build_projection_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Projection patrimoniale")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        metric_row = QHBoxLayout()
        self._metric_income = MetricLabel("Revenus mensuels moyens", "—")
        self._metric_expenses = MetricLabel("Dépenses mensuelles moyennes", "—")
        metric_row.addWidget(self._metric_income)
        metric_row.addWidget(self._metric_expenses)
        metric_row.addStretch()
        layout.addLayout(metric_row)

        kpi_row_1 = QHBoxLayout()
        self._kpi_current_net = KpiCard(tone="blue")
        self._kpi_horizon_net = KpiCard(tone="green")
        self._kpi_fire_target = KpiCard(tone="purple")
        for card in (self._kpi_current_net, self._kpi_horizon_net, self._kpi_fire_target):
            kpi_row_1.addWidget(card)
        layout.addLayout(kpi_row_1)

        kpi_row_2 = QHBoxLayout()
        self._kpi_fire_progress = KpiCard(tone="primary")
        self._kpi_monthly_savings = KpiCard(tone="neutral")
        self._kpi_fire_date = KpiCard(tone="neutral")
        for card in (self._kpi_fire_progress, self._kpi_monthly_savings, self._kpi_fire_date):
            kpi_row_2.addWidget(card)
        layout.addLayout(kpi_row_2)

        params_box = QGroupBox("Paramètres de simulation")
        params_box.setStyleSheet(STYLE_GROUP)
        params_form = QFormLayout(params_box)
        params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        params_form.setSpacing(8)

        # ── Mode de simulation (presets) ──────────────────────────────────────
        preset_widget = QWidget()
        preset_widget.setStyleSheet("background: transparent;")
        preset_layout = QHBoxLayout(preset_widget)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(6)

        _PRESET_BTN_BASE = f"""
            QPushButton {{
                background: {BG_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
                padding: 5px 14px; font-size: 13px;
            }}
            QPushButton:hover {{ background: {BG_ACTIVE}; }}
        """
        self._btn_preset_pessimiste = QPushButton("Pessimiste")
        self._btn_preset_realiste   = QPushButton("Réaliste")
        self._btn_preset_optimiste  = QPushButton("Optimiste")
        for btn in (self._btn_preset_pessimiste, self._btn_preset_realiste, self._btn_preset_optimiste):
            btn.setStyleSheet(_PRESET_BTN_BASE)
        self._btn_preset_pessimiste.clicked.connect(lambda: self._apply_preset("pessimiste"))
        self._btn_preset_realiste.clicked.connect(lambda: self._apply_preset("realiste"))
        self._btn_preset_optimiste.clicked.connect(lambda: self._apply_preset("optimiste"))
        preset_layout.addWidget(self._btn_preset_pessimiste)
        preset_layout.addWidget(self._btn_preset_realiste)
        preset_layout.addWidget(self._btn_preset_optimiste)
        self._lbl_active_preset = QLabel("Personnalisé")
        self._lbl_active_preset.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-style: italic;")
        preset_layout.addWidget(self._lbl_active_preset)
        preset_layout.addStretch()
        params_form.addRow("Mode :", preset_widget)

        # ── Durée ─────────────────────────────────────────────────────────────
        self._spin_horizon_years = QSpinBox()
        self._spin_horizon_years.setRange(1, 50)
        self._spin_horizon_years.setStyleSheet(STYLE_INPUT_FOCUS)
        params_form.addRow("Durée :", self._spin_horizon_years)

        # ── Rendements par classe d'actif ─────────────────────────────────────
        returns_group = QGroupBox("Rendements par classe d'actif")
        returns_group.setStyleSheet(STYLE_GROUP)
        returns_form = QFormLayout(returns_group)
        returns_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        returns_form.setSpacing(6)

        def _make_return_spin(default_val: float) -> QDoubleSpinBox:
            s = QDoubleSpinBox()
            s.setRange(-20.0, 50.0)
            s.setDecimals(2)
            s.setSuffix(" %")
            s.setValue(default_val)
            s.setStyleSheet(STYLE_INPUT_FOCUS)
            return s

        self._spin_return_liq   = _make_return_spin(2.0)
        self._spin_return_bourse= _make_return_spin(7.0)
        self._spin_return_immo  = _make_return_spin(3.5)
        self._spin_return_pe    = _make_return_spin(10.0)
        self._spin_return_ent   = _make_return_spin(5.0)

        returns_form.addRow("Liquidités / épargne :", self._spin_return_liq)
        returns_form.addRow("Bourse (ETF, actions) :", self._spin_return_bourse)
        returns_form.addRow("Immobilier locatif :",    self._spin_return_immo)
        returns_form.addRow("Private Equity :",        self._spin_return_pe)
        returns_form.addRow("Entreprises :",           self._spin_return_ent)

        self._lbl_weighted_return = QLabel("Rendement global effectif : — %")
        self._lbl_weighted_return.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold; padding: 4px 0;"
        )
        returns_form.addRow(self._lbl_weighted_return)

        params_form.addRow(returns_group)

        # ── Macro ─────────────────────────────────────────────────────────────
        self._spin_inflation = QDoubleSpinBox()
        self._spin_inflation.setRange(-5.0, 20.0)
        self._spin_inflation.setDecimals(2)
        self._spin_inflation.setSuffix(" %")
        self._spin_inflation.setStyleSheet(STYLE_INPUT_FOCUS)
        params_form.addRow("Inflation :", self._spin_inflation)

        self._spin_income_growth = QDoubleSpinBox()
        self._spin_income_growth.setRange(-20.0, 20.0)
        self._spin_income_growth.setDecimals(2)
        self._spin_income_growth.setSuffix(" %")
        self._spin_income_growth.setStyleSheet(STYLE_INPUT_FOCUS)
        params_form.addRow("Croissance revenus :", self._spin_income_growth)

        self._spin_expense_growth = QDoubleSpinBox()
        self._spin_expense_growth.setRange(-20.0, 20.0)
        self._spin_expense_growth.setDecimals(2)
        self._spin_expense_growth.setSuffix(" %")
        self._spin_expense_growth.setStyleSheet(STYLE_INPUT_FOCUS)
        params_form.addRow("Croissance dépenses :", self._spin_expense_growth)

        # ── Overrides ─────────────────────────────────────────────────────────
        savings_row = QWidget()
        savings_layout = QHBoxLayout(savings_row)
        savings_layout.setContentsMargins(0, 0, 0, 0)
        savings_layout.setSpacing(8)
        self._chk_savings_override = QCheckBox("Utiliser")
        self._spin_savings_override = QDoubleSpinBox()
        self._spin_savings_override.setRange(-1_000_000, 1_000_000)
        self._spin_savings_override.setDecimals(2)
        self._spin_savings_override.setSuffix(" €")
        self._spin_savings_override.setStyleSheet(STYLE_INPUT_FOCUS)
        savings_layout.addWidget(self._chk_savings_override)
        savings_layout.addWidget(self._spin_savings_override)
        savings_layout.addStretch()
        params_form.addRow("Épargne mensuelle personnalisée :", savings_row)

        net_row = QWidget()
        net_layout = QHBoxLayout(net_row)
        net_layout.setContentsMargins(0, 0, 0, 0)
        net_layout.setSpacing(8)
        self._chk_net_override = QCheckBox("Utiliser")
        self._spin_net_override = QDoubleSpinBox()
        self._spin_net_override.setRange(-1_000_000_000, 1_000_000_000)
        self._spin_net_override.setDecimals(2)
        self._spin_net_override.setSuffix(" €")
        self._spin_net_override.setStyleSheet(STYLE_INPUT_FOCUS)
        net_layout.addWidget(self._chk_net_override)
        net_layout.addWidget(self._spin_net_override)
        net_layout.addStretch()
        params_form.addRow("Patrimoine initial personnalisé :", net_row)

        self._spin_fire_multiple = QDoubleSpinBox()
        self._spin_fire_multiple.setRange(1.0, 200.0)
        self._spin_fire_multiple.setDecimals(2)
        self._spin_fire_multiple.setStyleSheet(STYLE_INPUT_FOCUS)
        params_form.addRow("Multiple FIRE :", self._spin_fire_multiple)

        # ── Résidence principale ──────────────────────────────────────────────
        rp_row = QWidget()
        rp_row.setStyleSheet("background: transparent;")
        rp_layout = QHBoxLayout(rp_row)
        rp_layout.setContentsMargins(0, 0, 0, 0)
        rp_layout.setSpacing(8)
        self._chk_exclude_rp = QCheckBox("Exclure la/les résidence(s) principale(s)")
        self._chk_exclude_rp.setToolTip(
            "Retire la valeur des biens marqués 'RP' du patrimoine de simulation.\n"
            "Utile pour projeter uniquement les actifs financiers productifs."
        )
        self._lbl_rp_amount = QLabel("")
        self._lbl_rp_amount.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        rp_layout.addWidget(self._chk_exclude_rp)
        rp_layout.addWidget(self._lbl_rp_amount)
        rp_layout.addStretch()
        params_form.addRow("Résidence principale :", rp_row)

        # ── Affichage / boutons ───────────────────────────────────────────────
        self._chk_show_standard = QCheckBox("Afficher aussi Pessimiste / Médian / Optimiste")
        params_form.addRow("Affichage :", self._chk_show_standard)

        btn_row = QHBoxLayout()
        self._btn_projection_reset = QPushButton("Réinitialiser aux données réelles")
        self._btn_projection_reset.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        self._btn_projection_reset.clicked.connect(self._on_reset_projection_clicked)
        btn_row.addWidget(self._btn_projection_reset)

        self._btn_projection_run = QPushButton("Lancer la simulation")
        self._btn_projection_run.setStyleSheet(STYLE_BTN_SUCCESS)
        self._btn_projection_run.clicked.connect(self._on_run_projection_clicked)
        btn_row.addWidget(self._btn_projection_run)
        btn_row.addStretch()
        params_form.addRow("", btn_row)

        self._projection_status = QLabel("")
        self._projection_status.setStyleSheet(STYLE_STATUS)
        params_form.addRow("Statut :", self._projection_status)

        layout.addWidget(params_box)

        # Connexions
        self._chk_savings_override.toggled.connect(self._spin_savings_override.setEnabled)
        self._chk_net_override.toggled.connect(self._spin_net_override.setEnabled)
        self._chk_exclude_rp.toggled.connect(self._on_exclude_rp_changed)
        for _spin in (self._spin_return_liq, self._spin_return_bourse, self._spin_return_immo,
                      self._spin_return_pe, self._spin_return_ent):
            _spin.valueChanged.connect(self._on_params_changed)

        lbl_chart = QLabel("Courbe de projection")
        lbl_chart.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_chart)
        self._projection_chart = PlotlyView(min_height=340)
        layout.addWidget(self._projection_chart)

        lbl_fire = QLabel("Progression FIRE")
        lbl_fire.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_fire)
        self._fire_chart = PlotlyView(min_height=240)
        layout.addWidget(self._fire_chart)

        self._summary_text = QLabel("")
        self._summary_text.setWordWrap(True)
        self._summary_text.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; line-height: 1.4;")
        layout.addWidget(self._summary_text)

        self._projection_milestone_hint = QLabel("")
        self._projection_milestone_hint.setWordWrap(True)
        self._projection_milestone_hint.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._projection_milestone_hint)

        layout.addStretch()
        return w

    def _build_goals_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Objectifs financiers")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        self._native_global_box = QGroupBox("Niveau global patrimoine")
        self._native_global_box.setStyleSheet(STYLE_GROUP)
        global_layout = QVBoxLayout(self._native_global_box)
        global_layout.setContentsMargins(10, 10, 10, 10)
        global_layout.setSpacing(6)

        self._native_global_level = QLabel("Niveau 0")
        self._native_global_level.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: bold;")
        global_layout.addWidget(self._native_global_level)

        self._native_global_value = QLabel("Valeur actuelle : —")
        self._native_global_value.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        global_layout.addWidget(self._native_global_value)

        self._native_global_next = QLabel("Prochain palier : —")
        self._native_global_next.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        global_layout.addWidget(self._native_global_next)

        global_bar_row = QHBoxLayout()
        global_bar_row.setSpacing(8)
        self._native_global_progress = QProgressBar()
        self._native_global_progress.setRange(0, 100)
        self._native_global_progress.setStyleSheet(_MILESTONE_PROGRESS_STYLE)
        global_bar_row.addWidget(self._native_global_progress, 1)
        self._native_global_progress_label = QLabel("0.0 %")
        self._native_global_progress_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        global_bar_row.addWidget(self._native_global_progress_label)
        global_layout.addLayout(global_bar_row)

        self._native_global_subtitle = QLabel("Aucune donnée disponible.")
        self._native_global_subtitle.setWordWrap(True)
        self._native_global_subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        global_layout.addWidget(self._native_global_subtitle)
        layout.addWidget(self._native_global_box)

        milestones_grid = QGridLayout()
        milestones_grid.setHorizontalSpacing(10)
        milestones_grid.setVerticalSpacing(10)
        self._native_milestone_cards: dict[str, NativeMilestoneCard] = {}
        for idx, definition in enumerate(NATIVE_MILESTONE_DEFINITIONS):
            card = NativeMilestoneCard(definition["category_label"])
            row = idx // 2
            col = idx % 2
            milestones_grid.addWidget(card, row, col)
            self._native_milestone_cards[str(definition["category_key"])] = card
        layout.addLayout(milestones_grid)

        self._native_milestones_status = QLabel("")
        self._native_milestones_status.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._native_milestones_status)

        btn_row = QHBoxLayout()
        self._btn_goal_new = QPushButton("Nouvel objectif")
        self._btn_goal_new.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        self._btn_goal_new.clicked.connect(self._on_new_goal_clicked)
        btn_row.addWidget(self._btn_goal_new)
        self._btn_goal_edit = QPushButton("Modifier")
        self._btn_goal_edit.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_goal_edit.clicked.connect(self._on_edit_goal_clicked)
        btn_row.addWidget(self._btn_goal_edit)
        self._btn_goal_delete = QPushButton("Supprimer")
        self._btn_goal_delete.setStyleSheet(STYLE_BTN_DANGER)
        self._btn_goal_delete.clicked.connect(self._on_delete_goal_clicked)
        btn_row.addWidget(self._btn_goal_delete)
        self._btn_goal_achieved = QPushButton("Marquer comme atteint")
        self._btn_goal_achieved.setStyleSheet(STYLE_BTN_SUCCESS)
        self._btn_goal_achieved.clicked.connect(self._on_mark_goal_achieved_clicked)
        btn_row.addWidget(self._btn_goal_achieved)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._goals_table = DataTableWidget(searchable=True)
        self._goals_table.setMinimumHeight(360)
        self._goals_table.hide_column("id")
        layout.addWidget(self._goals_table)

        self._goals_status = QLabel("")
        self._goals_status.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._goals_status)
        layout.addStretch()
        return w

    def _build_scenarios_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Scénarios sauvegardés")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        self._btn_scenario_create = QPushButton("Créer depuis les paramètres actuels")
        self._btn_scenario_create.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        self._btn_scenario_create.clicked.connect(self._on_create_scenario_clicked)
        btn_row.addWidget(self._btn_scenario_create)
        self._btn_scenario_load = QPushButton("Charger scénario")
        self._btn_scenario_load.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_scenario_load.clicked.connect(self._on_load_scenario_clicked)
        btn_row.addWidget(self._btn_scenario_load)
        self._btn_scenario_default = QPushButton("Définir par défaut")
        self._btn_scenario_default.setStyleSheet(STYLE_BTN_SUCCESS)
        self._btn_scenario_default.clicked.connect(self._on_set_default_scenario_clicked)
        btn_row.addWidget(self._btn_scenario_default)
        self._btn_scenario_delete = QPushButton("Supprimer scénario")
        self._btn_scenario_delete.setStyleSheet(STYLE_BTN_DANGER)
        self._btn_scenario_delete.clicked.connect(self._on_delete_scenario_clicked)
        btn_row.addWidget(self._btn_scenario_delete)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._scenarios_table = DataTableWidget(searchable=True)
        self._scenarios_table.setMinimumHeight(320)
        self._scenarios_table.hide_column("id")
        layout.addWidget(self._scenarios_table)

        self._scenarios_status = QLabel("")
        self._scenarios_status.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._scenarios_status)
        layout.addStretch()
        return w

    def _load_scope_data(self) -> None:
        # Charger les presets pour ce scope (initialise les défauts si absents)
        try:
            initialize_default_presets(self._conn, self._scope_type, self._scope_id)
            self._presets_cache = get_all_presets(self._conn, self._scope_type, self._scope_id)
        except Exception as exc:
            logger.warning("Impossible de charger les presets : %s", exc)
            self._presets_cache = {}

        # Valeur RP pour affichage dans le toggle
        try:
            self._rp_value_for_scope = get_primary_residence_value_for_scope(
                self._conn, self._scope_type, self._scope_id
            )
        except Exception:
            self._rp_value_for_scope = 0.0
        self._update_rp_toggle_state()

        self._base_data = {}
        exclude_rp = self._chk_exclude_rp.isChecked() if hasattr(self, "_chk_exclude_rp") else False
        try:
            self._base_data = get_projection_base_for_scope(
                self._conn, self._scope_type, self._scope_id,
                exclude_primary_residence=exclude_rp,
            )
        except Exception as exc:
            logger.error("Erreur base projection: %s", exc)
            self._base_data = {
                "scope_type": self._scope_type,
                "scope_id": self._scope_id,
                "scope_label": self._scope_label(),
                "net_worth": 0.0,
                "gross_worth": 0.0,
                "liquidities": 0.0,
                "bourse": 0.0,
                "immobilier": 0.0,
                "private_equity": 0.0,
                "entreprises": 0.0,
                "credits": 0.0,
                "avg_monthly_income": 0.0,
                "avg_monthly_expenses": 0.0,
                "avg_monthly_savings": 0.0,
                "fire_annual_expenses_base": 0.0,
                "snapshot_week_date": None,
            }
            self._projection_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._projection_status.setText(f"Erreur base projection : {exc}")

        self._load_native_milestones()
        self._refresh_goals_tab()
        self._refresh_scenarios_tab()

        default_loaded = False
        if not self._scenarios_raw_df.empty:
            defaults = self._scenarios_raw_df[self._scenarios_raw_df["is_default"] == 1]
            if not defaults.empty:
                self._apply_scenario_to_projection_inputs(defaults.iloc[0].to_dict())
                default_loaded = True

        if not default_loaded:
            self._reset_projection_inputs_to_real_data()

        self._refresh_projection_tab()

    # ── Presets ───────────────────────────────────────────────────────────────

    def _apply_preset(self, preset_key: str) -> None:
        """Remplit tous les spinboxes de paramètres avec les valeurs du preset."""
        params = self._presets_cache.get(preset_key) or PRESET_DEFAULTS.get(preset_key, {})
        if not params:
            return

        # Bloquer _on_params_changed pendant le remplissage
        for _spin in (self._spin_return_liq, self._spin_return_bourse, self._spin_return_immo,
                      self._spin_return_pe, self._spin_return_ent, self._spin_inflation,
                      self._spin_income_growth, self._spin_expense_growth, self._spin_fire_multiple):
            _spin.blockSignals(True)

        self._spin_return_liq.setValue(float(params.get("return_liquidites_pct",  2.0)))
        self._spin_return_bourse.setValue(float(params.get("return_bourse_pct",   7.0)))
        self._spin_return_immo.setValue(float(params.get("return_immobilier_pct", 3.5)))
        self._spin_return_pe.setValue(float(params.get("return_pe_pct",          10.0)))
        self._spin_return_ent.setValue(float(params.get("return_entreprises_pct",  5.0)))
        self._spin_inflation.setValue(float(params.get("inflation_pct",           2.0)))
        self._spin_income_growth.setValue(float(params.get("income_growth_pct",   1.0)))
        self._spin_expense_growth.setValue(float(params.get("expense_growth_pct", 1.0)))
        self._spin_fire_multiple.setValue(float(params.get("fire_multiple",       25.0)))

        for _spin in (self._spin_return_liq, self._spin_return_bourse, self._spin_return_immo,
                      self._spin_return_pe, self._spin_return_ent, self._spin_inflation,
                      self._spin_income_growth, self._spin_expense_growth, self._spin_fire_multiple):
            _spin.blockSignals(False)

        self._active_preset = preset_key
        self._update_preset_buttons_style()
        self._update_weighted_return_label()

    def _update_preset_buttons_style(self) -> None:
        """Surligne le bouton du preset actif; grise les autres."""
        _ACTIVE_STYLES = {
            "pessimiste": f"QPushButton {{ background: #ef4444; color: white; border: none; border-radius: 4px; padding: 5px 14px; font-size: 13px; font-weight: bold; }}",
            "realiste":   f"QPushButton {{ background: #22c55e; color: white; border: none; border-radius: 4px; padding: 5px 14px; font-size: 13px; font-weight: bold; }}",
            "optimiste":  f"QPushButton {{ background: #60a5fa; color: white; border: none; border-radius: 4px; padding: 5px 14px; font-size: 13px; font-weight: bold; }}",
        }
        _BASE_STYLE = f"""
            QPushButton {{
                background: {BG_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
                padding: 5px 14px; font-size: 13px;
            }}
            QPushButton:hover {{ background: {BG_ACTIVE}; }}
        """
        pairs = [
            ("pessimiste", self._btn_preset_pessimiste),
            ("realiste",   self._btn_preset_realiste),
            ("optimiste",  self._btn_preset_optimiste),
        ]
        for key, btn in pairs:
            btn.setStyleSheet(_ACTIVE_STYLES[key] if key == self._active_preset else _BASE_STYLE)

        if self._active_preset is None:
            self._lbl_active_preset.setText("Personnalisé")
            self._lbl_active_preset.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-style: italic;")
        else:
            labels = {"pessimiste": "Pessimiste", "realiste": "Réaliste", "optimiste": "Optimiste"}
            self._lbl_active_preset.setText(f"Mode : {labels[self._active_preset]}")
            self._lbl_active_preset.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")

    def _on_params_changed(self) -> None:
        """Appelé quand un spinbox de rendement est modifié manuellement."""
        self._active_preset = None
        self._update_preset_buttons_style()
        self._update_weighted_return_label()

    def _update_weighted_return_label(self) -> None:
        """Met à jour le label de rendement global effectif (moyenne pondérée)."""
        if not hasattr(self, "_lbl_weighted_return"):
            return
        params = self._build_projection_params()
        if self._base_data:
            weighted = compute_weighted_return(self._base_data, params)
        else:
            weighted = params.expected_return_pct
        self._lbl_weighted_return.setText(f"Rendement global effectif : {weighted:.2f} %")

    # ── Résidence principale ──────────────────────────────────────────────────

    def _update_rp_toggle_state(self) -> None:
        """Active/désactive le toggle RP et affiche le montant."""
        if not hasattr(self, "_chk_exclude_rp"):
            return
        has_rp = self._rp_value_for_scope > 0.0
        self._chk_exclude_rp.setEnabled(has_rp)
        if has_rp:
            self._lbl_rp_amount.setText(f"(-\u00a0{self._rp_value_for_scope:,.0f}\u00a0€ si exclu)")
            self._chk_exclude_rp.setToolTip(
                f"Retire {self._rp_value_for_scope:,.0f}\u00a0€ de résidence(s) principale(s) "
                f"du patrimoine de simulation."
            )
        else:
            self._lbl_rp_amount.setText("Aucune résidence principale détectée")
            self._lbl_rp_amount.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-style: italic;")

    def _on_exclude_rp_changed(self, checked: bool) -> None:
        """Recharge la base de projection avec ou sans RP."""
        try:
            self._base_data = get_projection_base_for_scope(
                self._conn, self._scope_type, self._scope_id,
                exclude_primary_residence=checked,
            )
            self._update_weighted_return_label()
        except Exception as exc:
            logger.error("Erreur rechargement base projection (RP) : %s", exc)

    # ─────────────────────────────────────────────────────────────────────────

    def _scope_label(self) -> str:
        return "Famille" if self._scope_type == "family" else self._scope_combo.currentText()

    def _load_native_milestones(self) -> None:
        try:
            self._native_metrics = get_scope_milestone_metrics(self._conn, self._scope_type, self._scope_id)
            self._native_milestones = build_native_milestones_for_scope(
                self._conn,
                self._scope_type,
                self._scope_id,
                metrics=self._native_metrics,
            )
            self._featured_milestone = get_featured_milestone_for_category(self._native_milestones, "net_worth")
        except Exception as exc:
            logger.error("Erreur chargement jalons natifs : %s", exc)
            self._native_milestones = []
            self._featured_milestone = None
            self._native_metrics = {}
            self._native_milestones_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._native_milestones_status.setText(f"Erreur chargement jalons natifs : {exc}")

    def _refresh_projection_milestone_hint(self) -> None:
        milestone = self._featured_milestone
        if not milestone:
            self._projection_milestone_hint.setStyleSheet(STYLE_STATUS_WARNING)
            self._projection_milestone_hint.setText("Niveau global patrimoine indisponible pour ce périmètre.")
            return

        progress_pct = _safe_float(milestone.get("progress_pct"))
        self._projection_milestone_hint.setStyleSheet(STYLE_STATUS_SUCCESS if progress_pct >= 100 else STYLE_STATUS)
        self._projection_milestone_hint.setText(
            f"Niveau global patrimoine : niveau {int(milestone.get('level_number', 0))} "
            f"({milestone.get('display_value', '—')}). {milestone.get('subtitle', '')}"
        )

    def _refresh_native_milestones_ui(self) -> None:
        if not hasattr(self, "_native_global_level"):
            return

        milestones_map = {str(item.get("category_key")): item for item in self._native_milestones}
        for key, card in self._native_milestone_cards.items():
            card.set_milestone_data(milestones_map.get(key))

        featured = self._featured_milestone
        if not featured:
            self._native_global_level.setText("Niveau 0")
            self._native_global_value.setText("Valeur actuelle : —")
            self._native_global_next.setText("Prochain palier : —")
            self._native_global_progress.setValue(0)
            self._native_global_progress_label.setText("0.0 %")
            self._native_global_subtitle.setText("Aucune donnée disponible pour le niveau global.")
            self._native_milestones_status.setStyleSheet(STYLE_STATUS_WARNING)
            self._native_milestones_status.setText("Jalons natifs indisponibles pour ce périmètre.")
            return

        level_number = int(featured.get("level_number", 0))
        progress_pct = max(0.0, min(_safe_float(featured.get("progress_pct")), 100.0))
        self._native_global_level.setText(f"Niveau {level_number}")
        self._native_global_value.setText(f"Valeur actuelle : {featured.get('display_value', '—')}")
        if featured.get("is_max_level"):
            self._native_global_next.setText("Prochain palier : niveau maximal atteint")
        else:
            next_threshold = featured.get("next_threshold")
            if next_threshold is None:
                self._native_global_next.setText("Prochain palier : —")
            else:
                self._native_global_next.setText(f"Prochain palier : {money(next_threshold)}")
        self._native_global_progress.setValue(int(round(progress_pct)))
        self._native_global_progress_label.setText(f"{progress_pct:.1f} %")
        streak = int(_safe_float(self._native_metrics.get("positive_savings_streak"), 0))
        subtitle = str(featured.get("subtitle") or "")
        if streak > 0:
            subtitle = f"{subtitle} Série positive d'épargne : {streak} mois."
        self._native_global_subtitle.setText(subtitle)
        has_data = any(_safe_float(m.get("current_value")) > 0 for m in self._native_milestones)
        if has_data:
            self._native_milestones_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._native_milestones_status.setText(
                f"Périmètre {self._scope_label()} : {len(self._native_milestones)} jalons natifs calculés."
            )
        else:
            self._native_milestones_status.setStyleSheet(STYLE_STATUS_WARNING)
            self._native_milestones_status.setText(
                f"Périmètre {self._scope_label()} : données insuffisantes, progression initiale à 0 %."
            )

    def _set_projection_empty_state(self, message: str, status_style: str = STYLE_STATUS_WARNING) -> None:
        self._projection_df = pd.DataFrame()
        self._standard_projection_results = {}
        self._projection_chart.set_figure(go.Figure())
        self._fire_chart.set_figure(go.Figure())
        self._summary_text.setText(message)
        self._projection_status.setStyleSheet(status_style)
        self._projection_status.setText(message)
        self._projection_milestone_hint.setStyleSheet(STYLE_STATUS_WARNING)
        self._projection_milestone_hint.setText("Niveau global patrimoine indisponible.")

        self._kpi_current_net.set_content("Patrimoine actuel", money(0.0), subtitle=self._scope_label(), tone="blue")
        self._kpi_horizon_net.set_content("Patrimoine projeté à horizon", money(0.0), subtitle="—", tone="neutral")
        self._kpi_fire_target.set_content("Objectif FIRE", money(0.0), subtitle="—", tone="neutral")
        self._kpi_fire_progress.set_content("Progression FIRE", "0.0%", subtitle="—", tone="neutral")
        self._kpi_monthly_savings.set_content("Épargne mensuelle", money(0.0), subtitle="—", tone="neutral")
        self._kpi_fire_date.set_content("Date FIRE estimée", "—", subtitle="—", tone="neutral")
        self._metric_income.set_content("Revenus mensuels moyens", money(0.0))
        self._metric_expenses.set_content("Dépenses mensuelles moyennes", money(0.0))

    def _reset_projection_inputs_to_real_data(self) -> None:
        avg_savings = _safe_float(self._base_data.get("avg_monthly_savings"))
        base_net    = _safe_float(self._base_data.get("net_worth"))

        self._spin_horizon_years.setValue(10)
        self._spin_inflation.setValue(2.0)
        self._spin_income_growth.setValue(1.0)
        self._spin_expense_growth.setValue(1.0)
        self._spin_fire_multiple.setValue(25.0)
        self._chk_show_standard.setChecked(False)

        self._chk_savings_override.setChecked(False)
        self._spin_savings_override.setValue(avg_savings)
        self._spin_savings_override.setEnabled(False)
        self._chk_net_override.setChecked(False)
        self._spin_net_override.setValue(base_net)
        self._spin_net_override.setEnabled(False)

        # Applique le preset "réaliste" comme point de départ
        self._apply_preset("realiste")
        self._active_scenario_name = "Personnalisé"

    def _apply_scenario_to_projection_inputs(self, scenario_row: dict) -> None:
        self._active_scenario_name = str(scenario_row.get("name") or "Scénario")
        self._spin_horizon_years.setValue(max(int(_safe_float(scenario_row.get("horizon_years"), 10)), 1))
        self._spin_inflation.setValue(_safe_float(scenario_row.get("inflation_pct"), 2.0))
        self._spin_income_growth.setValue(_safe_float(scenario_row.get("income_growth_pct"), 1.0))
        self._spin_expense_growth.setValue(_safe_float(scenario_row.get("expense_growth_pct"), 1.0))
        self._spin_fire_multiple.setValue(_safe_float(scenario_row.get("fire_multiple"), 25.0))

        # Rendements par classe — avec fallback sur expected_return_pct pour anciens scénarios
        fallback_return = _safe_float(scenario_row.get("expected_return_pct"), 6.0)
        self._spin_return_liq.setValue(_safe_float(scenario_row.get("return_liquidites_pct"),  fallback_return * 0.3))
        self._spin_return_bourse.setValue(_safe_float(scenario_row.get("return_bourse_pct"),   fallback_return))
        self._spin_return_immo.setValue(_safe_float(scenario_row.get("return_immobilier_pct"), fallback_return * 0.6))
        self._spin_return_pe.setValue(_safe_float(scenario_row.get("return_pe_pct"),           fallback_return * 1.5))
        self._spin_return_ent.setValue(_safe_float(scenario_row.get("return_entreprises_pct"), fallback_return * 0.8))

        # RP exclusion
        exclude_rp = bool(int(_safe_float(scenario_row.get("exclude_primary_residence"), 0)))
        self._chk_exclude_rp.blockSignals(True)
        self._chk_exclude_rp.setChecked(exclude_rp and self._rp_value_for_scope > 0.0)
        self._chk_exclude_rp.blockSignals(False)
        if exclude_rp and self._rp_value_for_scope > 0.0:
            self._on_exclude_rp_changed(True)

        self._active_preset = None
        self._update_preset_buttons_style()
        self._update_weighted_return_label()

        savings_override = scenario_row.get("monthly_savings_override")
        has_savings = savings_override is not None
        self._chk_savings_override.setChecked(has_savings)
        self._spin_savings_override.setEnabled(has_savings)
        if has_savings:
            self._spin_savings_override.setValue(_safe_float(savings_override))
        else:
            self._spin_savings_override.setValue(_safe_float(self._base_data.get("avg_monthly_savings")))

        net_override = scenario_row.get("initial_net_worth_override")
        has_net = net_override is not None
        self._chk_net_override.setChecked(has_net)
        self._spin_net_override.setEnabled(has_net)
        if has_net:
            self._spin_net_override.setValue(_safe_float(net_override))
        else:
            self._spin_net_override.setValue(_safe_float(self._base_data.get("net_worth")))

    def _build_projection_params(self) -> ScenarioParams:
        savings_override = float(self._spin_savings_override.value()) if self._chk_savings_override.isChecked() else None
        net_override     = float(self._spin_net_override.value())     if self._chk_net_override.isChecked()     else None
        return ScenarioParams(
            label=self._active_scenario_name,
            horizon_years=int(self._spin_horizon_years.value()),
            return_liquidites_pct=  float(self._spin_return_liq.value()),
            return_bourse_pct=      float(self._spin_return_bourse.value()),
            return_immobilier_pct=  float(self._spin_return_immo.value()),
            return_pe_pct=          float(self._spin_return_pe.value()),
            return_entreprises_pct= float(self._spin_return_ent.value()),
            inflation_pct=          float(self._spin_inflation.value()),
            income_growth_pct=      float(self._spin_income_growth.value()),
            expense_growth_pct=     float(self._spin_expense_growth.value()),
            monthly_savings_override=savings_override,
            fire_multiple=          float(self._spin_fire_multiple.value()),
            initial_net_worth_override=net_override,
            exclude_primary_residence=self._chk_exclude_rp.isChecked(),
        )

    def _on_run_projection_clicked(self) -> None:
        if self._active_preset:
            labels = {"pessimiste": "Pessimiste", "realiste": "Réaliste", "optimiste": "Optimiste"}
            self._active_scenario_name = labels.get(self._active_preset, "Personnalisé")
        else:
            self._active_scenario_name = "Personnalisé"
        self._refresh_projection_tab()

    def _on_reset_projection_clicked(self) -> None:
        self._reset_projection_inputs_to_real_data()
        self._refresh_projection_tab()

    def _refresh_projection_tab(self) -> None:
        if not self._base_data:
            self._set_projection_empty_state("Aucune base de projection disponible pour ce scope.")
            return

        params = self._build_projection_params()
        try:
            self._projection_df = run_projection(self._base_data, params)
            if self._projection_df.empty:
                self._set_projection_empty_state("Projection indisponible pour ce scope.")
                return
            self._standard_projection_results = {}
            if self._chk_show_standard.isChecked():
                for sc in build_standard_scenarios(
                    self._base_data, int(params.horizon_years),
                    presets=self._presets_cache or None,
                ):
                    self._standard_projection_results[sc.label] = run_projection(self._base_data, sc)
            self._update_weighted_return_label()

            self._update_projection_kpis(params)
            self._projection_chart.set_figure(self._build_projection_chart(self._projection_df))
            self._fire_chart.set_figure(self._build_fire_progress_chart(self._projection_df))
            self._summary_text.setText(self._build_projection_summary(params))
            self._refresh_projection_milestone_hint()

            warnings = []
            if not self._base_data.get("snapshot_week_date"):
                warnings.append("aucun snapshot hebdomadaire")
            if _safe_float(self._base_data.get("avg_monthly_income")) == 0.0:
                warnings.append("aucun revenu mensuel")
            if _safe_float(self._base_data.get("avg_monthly_expenses")) == 0.0:
                warnings.append("aucune dépense mensuelle")

            if warnings:
                self._projection_status.setStyleSheet(STYLE_STATUS_WARNING)
                self._projection_status.setText(
                    f"Simulation à jour ({self._scope_label()}) avec données incomplètes : {', '.join(warnings)}."
                )
            else:
                self._projection_status.setStyleSheet(STYLE_STATUS_SUCCESS)
                self._projection_status.setText(
                    f"Simulation à jour ({self._scope_label()}) - horizon {params.horizon_years} an(s)."
                )
        except Exception as exc:
            logger.error("Erreur simulation: %s", exc)
            self._set_projection_empty_state(f"Erreur simulation : {exc}", status_style=STYLE_STATUS_ERROR)

    def _update_projection_kpis(self, params: ScenarioParams) -> None:
        if self._projection_df.empty:
            return

        current_net = _safe_float(self._base_data.get("net_worth"))
        projected_horizon = _safe_float(self._projection_df.iloc[-1].get("projected_net_worth"))
        fire_target = _safe_float(self._projection_df.iloc[-1].get("fire_target"))
        fire_progress_now = _safe_float(self._projection_df.iloc[0].get("fire_progress_pct"))

        savings_value = (
            _safe_float(self._base_data.get("avg_monthly_savings"))
            if params.monthly_savings_override is None
            else _safe_float(params.monthly_savings_override)
        )
        savings_label = (
            "Basée sur revenus - dépenses"
            if params.monthly_savings_override is None
            else "Valeur personnalisée"
        )

        fire_info = estimate_fire_reach_date(self._projection_df)
        fire_date = fire_info.get("fire_date_label") or "Non atteint sur l'horizon"
        fire_reached = bool(fire_info.get("fire_reached"))

        self._kpi_current_net.set_content("Patrimoine actuel", money(current_net), subtitle=self._scope_label(), tone="blue")
        self._kpi_horizon_net.set_content("Patrimoine projeté à horizon", money(projected_horizon), subtitle=f"{params.horizon_years} an(s)", tone="green" if projected_horizon >= current_net else "alert")
        self._kpi_fire_target.set_content("Objectif FIRE", money(fire_target), subtitle=f"Multiple {params.fire_multiple:.2f}", tone="purple")
        self._kpi_fire_progress.set_content("Progression FIRE", f"{fire_progress_now:.1f}%", subtitle="Aujourd'hui", tone="success" if fire_progress_now >= 100 else "primary")
        self._kpi_monthly_savings.set_content("Épargne mensuelle", money(savings_value), subtitle=savings_label, tone="success" if savings_value >= 0 else "alert")
        self._kpi_fire_date.set_content("Date FIRE estimée", fire_date, subtitle="Projection actuelle", tone="success" if fire_reached else "neutral")

        self._metric_income.set_content("Revenus mensuels moyens", money(self._base_data.get("avg_monthly_income", 0.0)))
        self._metric_expenses.set_content("Dépenses mensuelles moyennes", money(self._base_data.get("avg_monthly_expenses", 0.0)))

    def _build_projection_chart(self, active_df: pd.DataFrame) -> go.Figure:
        fig = go.Figure()
        x_active = active_df["month_index"] / 12.0
        fig.add_trace(go.Scatter(
            x=x_active,
            y=active_df["projected_net_worth"],
            mode="lines",
            line=dict(color="#60a5fa", width=3),
            name=f"Scénario actif ({self._active_scenario_name})",
        ))

        fire_target = _safe_float(active_df.iloc[-1].get("fire_target")) if not active_df.empty else 0.0
        fig.add_trace(go.Scatter(
            x=x_active,
            y=[fire_target] * len(active_df),
            mode="lines",
            line=dict(color="#f59e0b", width=2, dash="dash"),
            name="Objectif FIRE",
        ))

        std_colors = {"Pessimiste": "#ef4444", "Médian": "#22c55e", "Optimiste": "#93c5fd"}
        for label, df_std in self._standard_projection_results.items():
            fig.add_trace(go.Scatter(
                x=df_std["month_index"] / 12.0,
                y=df_std["projected_net_worth"],
                mode="lines",
                line=dict(color=std_colors.get(label, "#94a3b8"), width=1.8, dash="dot"),
                name=label,
            ))

        fig.update_layout(**plotly_layout(
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        ))
        fig.update_xaxes(title="Années")
        fig.update_yaxes(title="Patrimoine net (€)")
        return fig

    def _build_fire_progress_chart(self, df: pd.DataFrame) -> go.Figure:
        fig = go.Figure()
        x_vals = df["month_index"] / 12.0
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=df["fire_progress_pct"],
            mode="lines",
            line=dict(color="#22c55e", width=2.5),
            name="Progression FIRE",
        ))
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=[100.0] * len(df),
            mode="lines",
            line=dict(color="#f59e0b", width=1.5, dash="dash"),
            name="Seuil FIRE",
        ))
        fig.update_layout(**plotly_layout(
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        ))
        fig.update_xaxes(title="Années")
        fig.update_yaxes(title="Progression (%)")
        return fig

    def _build_projection_summary(self, params: ScenarioParams) -> str:
        if self._projection_df.empty:
            return "Aucune projection disponible."

        current_net = _safe_float(self._base_data.get("net_worth"))
        fire_target = _safe_float(self._projection_df.iloc[-1].get("fire_target"))
        fire_info = estimate_fire_reach_date(self._projection_df)
        if fire_info.get("fire_reached"):
            status_line = (
                f"Statut estimé : FIRE atteint à {fire_info.get('fire_date_label')} "
                f"avec l'hypothèse « {self._active_scenario_name} »."
            )
        else:
            status_line = (
                f"Statut estimé : FIRE non atteint sur {params.horizon_years} an(s) "
                f"avec l'hypothèse « {self._active_scenario_name} »."
            )
        return (
            f"Patrimoine actuel : {money(current_net)} | Objectif FIRE : {money(fire_target)} | "
            f"Horizon : {params.horizon_years} an(s).\n{status_line}"
        )

    def _selected_id_from_table(self, table_widget: DataTableWidget, id_col: str = "id") -> Optional[int]:
        view = getattr(table_widget, "_view", None)
        if view is None or view.selectionModel() is None:
            return None
        selected_rows = view.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row_index = selected_rows[0].row()
        df = table_widget.get_dataframe()
        if df.empty or id_col not in df.columns or row_index >= len(df):
            return None
        try:
            return int(df.iloc[row_index][id_col])
        except Exception:
            return None

    def _goal_required_monthly_amount(self, target_amount: float, current_amount: float, target_date_raw: Optional[str]) -> float:
        try:
            return compute_goal_monthly_required_amount(target_amount, current_amount, target_date_raw)
        except Exception:
            return 0.0

    def _goal_status_with_alert(self, row: dict, monthly_needed: float) -> str:
        status_code = str(row.get("status") or "ACTIVE").upper()
        target_amount = _safe_float(row.get("target_amount"))
        current_amount = _safe_float(row.get("current_amount"))

        if status_code == "CANCELLED":
            return "Annulé"
        if status_code == "PAUSED":
            return "En pause"
        if status_code == "ACHIEVED" or current_amount >= target_amount:
            return "Atteint"

        target_date_raw = row.get("target_date")
        target_date = pd.to_datetime(target_date_raw, errors="coerce") if target_date_raw else pd.NaT
        if pd.notna(target_date) and target_date.date() < date.today() and current_amount < target_amount:
            return "En retard"

        base_savings = max(_safe_float(self._base_data.get("avg_monthly_savings")), 0.0)
        if monthly_needed > 0 and base_savings > 0 and monthly_needed > base_savings:
            return "En retard"
        return "En bonne voie"

    def _goal_progress_bar(self, progress_pct: float) -> str:
        # Barre ASCII pour rester lisible dans DataTableWidget.
        pct = max(0.0, min(_safe_float(progress_pct), 100.0))
        width = 16
        filled = int(round((pct / 100.0) * width))
        return f"[{'#' * filled}{'-' * (width - filled)}] {pct:.1f}%"

    def _goals_status_color(self, status_text: str):
        txt = str(status_text)
        if "retard" in txt.lower():
            return COLOR_WARNING
        if "Atteint" in txt:
            return COLOR_SUCCESS
        if "Annulé" in txt:
            return TEXT_MUTED
        if "pause" in txt.lower():
            return TEXT_SECONDARY
        return None

    def _refresh_goals_tab(self) -> None:
        self._refresh_native_milestones_ui()
        try:
            self._goals_raw_df = list_goals(self._conn, self._scope_type, self._scope_id)
        except Exception as exc:
            logger.error("Erreur chargement objectifs: %s", exc)
            self._goals_raw_df = pd.DataFrame()
            self._goals_table.set_dataframe(pd.DataFrame([{"Erreur": str(exc)}]))
            self._goals_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._goals_status.setText(f"Erreur chargement objectifs : {exc}")
            return

        if self._goals_raw_df.empty:
            self._goals_table.set_dataframe(pd.DataFrame([{"Information": "Aucun objectif pour ce périmètre."}]))
            self._goals_status.setStyleSheet(STYLE_STATUS)
            self._goals_status.setText(f"Périmètre {self._scope_label()} : 0 objectif.")
            return

        rows = []
        for _, goal in self._goals_raw_df.iterrows():
            target_amount = _safe_float(goal.get("target_amount"))
            current_amount = _safe_float(goal.get("current_amount"))
            progress_pct = min((current_amount / target_amount) * 100.0, 999.0) if target_amount > 0 else 0.0
            monthly_needed = self._goal_required_monthly_amount(target_amount, current_amount, goal.get("target_date"))
            goal_status = self._goal_status_with_alert(goal.to_dict(), monthly_needed)
            rows.append({
                "id": int(goal["id"]),
                "Nom": str(goal.get("name") or ""),
                "Catégorie": str(goal.get("category") or ""),
                "Montant cible": target_amount,
                "Montant actuel": current_amount,
                "Avancement": self._goal_progress_bar(progress_pct),
                "Progression %": round(progress_pct, 1),
                "Date cible": str(goal.get("target_date") or "—"),
                "Montant mensuel nécessaire": round(monthly_needed, 2),
                "Statut": goal_status,
            })

        display_df = pd.DataFrame(rows)
        self._goals_table.set_dataframe(display_df)
        self._goals_table.hide_column("id")
        self._goals_table.set_column_colors({"Statut": self._goals_status_color})
        self._goals_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._goals_status.setText(f"Périmètre {self._scope_label()} : {len(display_df)} objectif(s).")

    def _find_goal_row(self, goal_id: int) -> Optional[dict]:
        if self._goals_raw_df.empty:
            return None
        matches = self._goals_raw_df[self._goals_raw_df["id"] == int(goal_id)]
        if matches.empty:
            return None
        return matches.iloc[0].to_dict()

    def _on_new_goal_clicked(self) -> None:
        dialog = GoalEditDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.get_payload()
        payload["scope_type"] = self._scope_type
        payload["scope_id"] = self._scope_id
        try:
            create_goal(self._conn, payload)
            self._refresh_goals_tab()
            self._goals_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._goals_status.setText("Objectif créé.")
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de créer l'objectif :\n{exc}")

    def _on_edit_goal_clicked(self) -> None:
        goal_id = self._selected_id_from_table(self._goals_table)
        if goal_id is None:
            QMessageBox.information(self, "Objectifs", "Sélectionnez un objectif à modifier.")
            return
        goal_row = self._find_goal_row(goal_id)
        if goal_row is None:
            QMessageBox.warning(self, "Objectifs", "Objectif introuvable.")
            return
        dialog = GoalEditDialog(goal_data=goal_row, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            update_goal(self._conn, goal_id, dialog.get_payload())
            self._refresh_goals_tab()
            self._goals_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._goals_status.setText("Objectif modifié.")
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de modifier l'objectif :\n{exc}")

    def _on_delete_goal_clicked(self) -> None:
        goal_id = self._selected_id_from_table(self._goals_table)
        if goal_id is None:
            QMessageBox.information(self, "Objectifs", "Sélectionnez un objectif à supprimer.")
            return
        answer = QMessageBox.question(
            self, "Confirmer la suppression", "Supprimer cet objectif ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_goal(self._conn, goal_id)
            self._refresh_goals_tab()
            self._goals_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._goals_status.setText("Objectif supprimé.")
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de supprimer l'objectif :\n{exc}")

    def _on_mark_goal_achieved_clicked(self) -> None:
        goal_id = self._selected_id_from_table(self._goals_table)
        if goal_id is None:
            QMessageBox.information(self, "Objectifs", "Sélectionnez un objectif.")
            return
        goal_row = self._find_goal_row(goal_id)
        if goal_row is None:
            QMessageBox.warning(self, "Objectifs", "Objectif introuvable.")
            return
        try:
            update_goal(self._conn, goal_id, {"status": "ACHIEVED", "current_amount": _safe_float(goal_row.get("target_amount"))})
            self._refresh_goals_tab()
            self._goals_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._goals_status.setText("Objectif marqué comme atteint.")
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de mettre à jour l'objectif :\n{exc}")

    def _refresh_scenarios_tab(self) -> None:
        try:
            self._scenarios_raw_df = list_scenarios(self._conn, self._scope_type, self._scope_id)
        except Exception as exc:
            logger.error("Erreur chargement scénarios: %s", exc)
            self._scenarios_raw_df = pd.DataFrame()
            self._scenarios_table.set_dataframe(pd.DataFrame([{"Erreur": str(exc)}]))
            self._scenarios_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._scenarios_status.setText(f"Erreur chargement scénarios : {exc}")
            return

        if self._scenarios_raw_df.empty:
            self._scenarios_table.set_dataframe(pd.DataFrame([{"Information": "Aucun scénario pour ce périmètre."}]))
            self._scenarios_status.setStyleSheet(STYLE_STATUS)
            self._scenarios_status.setText(f"Périmètre {self._scope_label()} : 0 scénario.")
            return

        rows = []
        for _, sc in self._scenarios_raw_df.iterrows():
            rows.append({
                "id": int(sc["id"]),
                "Nom": str(sc.get("name") or ""),
                "Par défaut": "Oui" if int(_safe_float(sc.get("is_default"), 0)) == 1 else "",
                "Horizon": int(_safe_float(sc.get("horizon_years"), 10)),
                "Rdt. global %": round(_safe_float(sc.get("expected_return_pct"), 0.0), 2),
                "Bourse %": round(_safe_float(sc.get("return_bourse_pct"), 0.0), 2),
                "Immo %": round(_safe_float(sc.get("return_immobilier_pct"), 0.0), 2),
                "PE %": round(_safe_float(sc.get("return_pe_pct"), 0.0), 2),
                "Excl. RP": "Oui" if int(_safe_float(sc.get("exclude_primary_residence"), 0)) else "",
                "Inflation %": round(_safe_float(sc.get("inflation_pct"), 0.0), 2),
                "Épargne personnalisée": ("—" if sc.get("monthly_savings_override") is None else round(_safe_float(sc.get("monthly_savings_override")), 2)),
                "Multiple FIRE": round(_safe_float(sc.get("fire_multiple"), 25.0), 2),
                "Mis à jour": str(sc.get("updated_at") or ""),
            })
        display_df = pd.DataFrame(rows)
        self._scenarios_table.set_dataframe(display_df)
        self._scenarios_table.hide_column("id")
        self._scenarios_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._scenarios_status.setText(f"Périmètre {self._scope_label()} : {len(display_df)} scénario(s).")

    def _find_scenario_row(self, scenario_id: int) -> Optional[dict]:
        if self._scenarios_raw_df.empty:
            return None
        matches = self._scenarios_raw_df[self._scenarios_raw_df["id"] == int(scenario_id)]
        if matches.empty:
            return None
        return matches.iloc[0].to_dict()

    def _on_create_scenario_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouveau scénario", "Nom du scénario :")
        if not ok:
            return
        scenario_name = name.strip()
        if not scenario_name:
            QMessageBox.warning(self, "Scénarios", "Le nom du scénario est obligatoire.")
            return

        params = self._build_projection_params()
        payload = {
            "name": scenario_name,
            "scope_type": self._scope_type,
            "scope_id": self._scope_id,
            "is_default": 0,
            "horizon_years": int(params.horizon_years),
            "expected_return_pct": float(params.expected_return_pct),  # moyenne calculée
            "inflation_pct": float(params.inflation_pct),
            "income_growth_pct": float(params.income_growth_pct),
            "expense_growth_pct": float(params.expense_growth_pct),
            "monthly_savings_override": params.monthly_savings_override,
            "fire_multiple": float(params.fire_multiple),
            "use_real_snapshot_base": 1 if params.initial_net_worth_override is None else 0,
            "initial_net_worth_override": params.initial_net_worth_override,
            "return_liquidites_pct":  float(params.return_liquidites_pct),
            "return_bourse_pct":      float(params.return_bourse_pct),
            "return_immobilier_pct":  float(params.return_immobilier_pct),
            "return_pe_pct":          float(params.return_pe_pct),
            "return_entreprises_pct": float(params.return_entreprises_pct),
            "exclude_primary_residence": params.exclude_primary_residence,
        }
        try:
            create_scenario(self._conn, payload)
            self._refresh_scenarios_tab()
            self._scenarios_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._scenarios_status.setText(f"Scénario « {scenario_name} » créé.")
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de créer le scénario :\n{exc}")

    def _on_load_scenario_clicked(self) -> None:
        scenario_id = self._selected_id_from_table(self._scenarios_table)
        if scenario_id is None:
            QMessageBox.information(self, "Scénarios", "Sélectionnez un scénario à charger.")
            return
        row = self._find_scenario_row(scenario_id)
        if row is None:
            QMessageBox.warning(self, "Scénarios", "Scénario introuvable.")
            return
        self._apply_scenario_to_projection_inputs(row)
        self._refresh_projection_tab()
        self._tabs.setCurrentIndex(0)

    def _on_delete_scenario_clicked(self) -> None:
        scenario_id = self._selected_id_from_table(self._scenarios_table)
        if scenario_id is None:
            QMessageBox.information(self, "Scénarios", "Sélectionnez un scénario à supprimer.")
            return
        answer = QMessageBox.question(
            self, "Confirmer la suppression", "Supprimer ce scénario ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_scenario(self._conn, scenario_id)
            self._refresh_scenarios_tab()
            self._scenarios_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._scenarios_status.setText("Scénario supprimé.")
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de supprimer le scénario :\n{exc}")

    def _on_set_default_scenario_clicked(self) -> None:
        scenario_id = self._selected_id_from_table(self._scenarios_table)
        if scenario_id is None:
            QMessageBox.information(self, "Scénarios", "Sélectionnez un scénario.")
            return
        try:
            for _, sc in self._scenarios_raw_df.iterrows():
                update_scenario(self._conn, int(sc["id"]), {"is_default": 0})
            update_scenario(self._conn, int(scenario_id), {"is_default": 1})
            self._refresh_scenarios_tab()
            self._scenarios_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._scenarios_status.setText("Scénario par défaut mis à jour.")
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible de définir le scénario par défaut :\n{exc}")
