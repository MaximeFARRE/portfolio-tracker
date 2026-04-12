"""
Panel Prévision avancée — moteur déterministe, Monte Carlo, stress tests.
Consomme uniquement services.prevision (façade publique) et
services.simulation_presets_repository pour les hypothèses de rendement.
"""
import logging
import math
import time
from typing import Optional

import plotly.graph_objects as go
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qt_ui.theme import (
    BG_CARD,
    BG_PRIMARY,
    BORDER_DEFAULT,
    BORDER_SUBTLE,
    STYLE_BTN_PRIMARY_BORDERED,
    STYLE_BTN_SUCCESS,
    STYLE_GROUP,
    STYLE_INPUT_FOCUS,
    STYLE_SECTION,
    STYLE_STATUS,
    STYLE_STATUS_ERROR,
    STYLE_STATUS_SUCCESS,
    STYLE_STATUS_WARNING,
    STYLE_TITLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    plotly_layout,
)
from qt_ui.widgets import KpiCard, PlotlyView
from utils.format_monnaie import money

logger = logging.getLogger(__name__)

# Correspondance champ preset → clé PrevisionConfig par classe d'actif
_RETURN_FIELDS = {
    "Liquidités":  ("return_liquidites_pct",  "vol_liquidites_pct"),
    "Bourse":      ("return_bourse_pct",       "vol_bourse_pct"),
    "Immobilier":  ("return_immobilier_pct",   "vol_immobilier_pct"),
    "PE":          ("return_pe_pct",           "vol_pe_pct"),
    "Entreprises": ("return_entreprises_pct",  "vol_entreprises_pct"),
    "Crypto":      (None,                      "vol_crypto_pct"),
}

_PRESET_LABELS = {
    "pessimiste": "😟  Pessimiste",
    "realiste":   "📊  Réaliste",
    "optimiste":  "🚀  Optimiste",
}

# Couleurs des 3 scénarios pour les graphiques
_PRESET_COLORS = {
    "pessimiste": "#ef4444",
    "realiste":   "#60a5fa",
    "optimiste":  "#22c55e",
}

_CRYPTO_RETURN_DEFAULT = 0.0


# ─── Threads ─────────────────────────────────────────────────────────────

class _PrevisionThread(QThread):
    """Exécute run_prevision dans un thread séparé."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, scope_type: str, scope_id: Optional[int], config, engine: str):
        super().__init__()
        self._scope_type = scope_type
        self._scope_id = scope_id
        self._config = config
        self._engine = engine

    def run(self):
        try:
            from services.db import get_conn
            from services.projection_service import ProjectionService
            with get_conn() as conn:
                result = ProjectionService.generate_projection(
                    conn=conn, 
                    scope_type=self._scope_type, 
                    scope_id=self._scope_id,
                    engine_type="advanced",
                    options={
                        "config": self._config,
                        "engine": self._engine
                    }
                )
            self.finished.emit(result)
        except Exception as exc:
            logger.error("Erreur prevision thread: %s", exc)
            self.error.emit(str(exc))


class _StressThread(QThread):
    """Exécute run_stress_prevision dans un thread séparé."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, scope_type: str, scope_id: Optional[int], config, scenario):
        super().__init__()
        self._scope_type = scope_type
        self._scope_id = scope_id
        self._config = config
        self._scenario = scenario

    def run(self):
        try:
            from services.db import get_conn
            from services.projection_service import ProjectionService
            with get_conn() as conn:
                result = ProjectionService.generate_projection(
                    conn=conn, 
                    scope_type=self._scope_type, 
                    scope_id=self._scope_id,
                    engine_type="advanced",
                    options={
                        "config": self._config,
                        "scenario": self._scenario
                    }
                )
            self.finished.emit(result)
        except Exception as exc:
            logger.error("Erreur stress thread: %s", exc)
            self.error.emit(str(exc))


class _MultiScenarioThread(QThread):
    """
    Lance les 3 simulations (Pessimiste / Réaliste / Optimiste) en mode
    déterministe pour le même scope, puis renvoie les 3 résultats.
    Les presets sont chargés depuis la DB dans le thread.
    """
    finished = pyqtSignal(object)   # dict[str, PrevisionResult]
    error = pyqtSignal(str)

    def __init__(self, scope_type: str, scope_id: Optional[int], base_params: dict):
        """
        Args:
            base_params: paramètres communs aux 3 simulations
                         (horizon_years, num_simulations, monthly_contribution,
                          target_goal_amount).
        """
        super().__init__()
        self._scope_type = scope_type
        self._scope_id = scope_id
        self._base_params = base_params

    def run(self):
        try:
            from services.db import get_conn
            from services.projection_service import ProjectionService
            from services.prevision_models import PrevisionConfig
            from services.simulation_presets_repository import get_preset, initialize_default_presets

            with get_conn() as conn:
                initialize_default_presets(conn, self._scope_type, self._scope_id)
                results = {}
                for preset_key in ("pessimiste", "realiste", "optimiste"):
                    p = get_preset(conn, preset_key, self._scope_type, self._scope_id)
                    config = _build_config_from_preset(p, self._base_params)
                    results[preset_key] = ProjectionService.generate_projection(
                        conn=conn, 
                        scope_type=self._scope_type, 
                        scope_id=self._scope_id,
                        engine_type="advanced",
                        options={
                            "config": config,
                            "engine": "deterministic"
                        }
                    )
            
            multi_warnings = set()
            for res in results.values():
                if res and res.base:
                    multi_warnings.update(getattr(res.base, "warnings", []))
            
            self.finished.emit({"results": results, "warnings": list(multi_warnings)})
        except Exception as exc:
            logger.error("Erreur multi-scenario thread: %s", exc)
            self.error.emit(str(exc))


# ─── Helpers ─────────────────────────────────────────────────────────────

def _pct(value: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value * 100:.1f} %"


def _pct_signed(value: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    v = value * 100
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f} %"


def _months_display(months: Optional[int]) -> str:
    if months is None:
        return "—"
    if months < 12:
        return f"{months} mois"
    return f"{months / 12:.1f} ans"


def _info_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {TEXT_PRIMARY}; font-size: 12px; "
        f"background: {BG_CARD}; border: 1px solid {BORDER_SUBTLE}; "
        f"border-radius: 3px; padding: 3px 8px;"
    )
    return lbl


def _pct_val(preset_data: dict, field: str, default_pct: float) -> float:
    """Lit un champ en % depuis un preset et retourne la valeur en décimal."""
    return float(preset_data.get(field, default_pct)) / 100.0


def _build_config_from_preset(preset_data: dict, base_params: dict):
    """Construit un PrevisionConfig à partir des données d'un preset + params de base."""
    from services.prevision_models import PrevisionConfig

    expected_returns = {
        "Liquidités":  _pct_val(preset_data, "return_liquidites_pct",  2.0),
        "Bourse":      _pct_val(preset_data, "return_bourse_pct",       7.0),
        "Immobilier":  _pct_val(preset_data, "return_immobilier_pct",   3.5),
        "PE":          _pct_val(preset_data, "return_pe_pct",          10.0),
        "Entreprises": _pct_val(preset_data, "return_entreprises_pct",  5.0),
        "Crypto":      _CRYPTO_RETURN_DEFAULT,
    }
    expected_volatilities = {
        "Liquidités":  _pct_val(preset_data, "vol_liquidites_pct",   1.0),
        "Bourse":      _pct_val(preset_data, "vol_bourse_pct",       15.0),
        "Immobilier":  _pct_val(preset_data, "vol_immobilier_pct",    5.0),
        "PE":          _pct_val(preset_data, "vol_pe_pct",           20.0),
        "Entreprises": _pct_val(preset_data, "vol_entreprises_pct",  15.0),
        "Crypto":      _pct_val(preset_data, "vol_crypto_pct",       50.0),
    }
    return PrevisionConfig(
        horizon_years=base_params.get("horizon_years", 20),
        num_simulations=base_params.get("num_simulations", 1000),
        monthly_contribution=base_params.get("monthly_contribution", 0.0),
        target_goal_amount=base_params.get("target_goal_amount"),
        inflation_rate=_pct_val(preset_data, "inflation_pct", 2.0),
        fire_multiple=float(preset_data.get("fire_multiple", 25.0)),
        expected_returns=expected_returns,
        expected_volatilities=expected_volatilities,
    )


# ─── Panel principal ─────────────────────────────────────────────────────

class PrevisionAvanceePanel(QWidget):
    """
    Panel dédié à la prévision avancée (déterministe, Monte Carlo, stress).
    Les hypothèses de rendement/volatilité sont lues depuis les presets
    (Pessimiste / Réaliste / Optimiste) configurés dans la page Paramètres.
    """

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._scope_type: str = "family"
        self._scope_id: Optional[int] = None
        self._thread: Optional[QThread] = None
        self._result = None
        self._stress_result = None
        self._multi_results: dict = {}   # {preset_key: PrevisionResult}
        self._preset_data: dict = {}
        self._preset_info_labels: dict = {}
        self._preset_cache_ttl_sec = 30.0
        self._preset_cache: dict[tuple[str, Optional[int], str], tuple[float, dict]] = {}

        self._build_ui()
        self._load_people()

    # ── Construction UI ──────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Prévision avancée")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        subtitle = QLabel(
            "Moteur de projection avancé : déterministe, Monte Carlo, stress tests."
        )
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        layout.addWidget(subtitle)

        layout.addWidget(self._build_scope_box())
        layout.addWidget(self._build_params_general_box())
        layout.addWidget(self._build_params_flux_box())
        layout.addWidget(self._build_preset_box())
        layout.addWidget(self._build_params_stress_box())
        layout.addLayout(self._build_action_buttons())

        self._warnings_label = QLabel("")
        self._warnings_label.setStyleSheet("color: #d97706; background: #fffbeb; border: 1px solid #fcd34d; border-radius: 4px; padding: 10px; font-weight: bold; font-size: 13px;")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setVisible(False)
        layout.addWidget(self._warnings_label)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(STYLE_STATUS)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addLayout(self._build_kpi_section())

        self._diagnostics_label = QLabel("")
        self._diagnostics_label.setWordWrap(True)
        self._diagnostics_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; line-height: 1.5;"
        )
        layout.addWidget(self._diagnostics_label)

        # ── Graphique trajectoire (simulation courante) ───────────────
        lbl_traj = QLabel("Trajectoire de projection")
        lbl_traj.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_traj)
        self._chart_trajectory = PlotlyView(min_height=340)
        layout.addWidget(self._chart_trajectory)

        # ── Histogramme Monte Carlo ───────────────────────────────────
        lbl_histo = QLabel("Distribution du patrimoine final")
        lbl_histo.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_histo)
        self._chart_histogram = PlotlyView(min_height=260)
        layout.addWidget(self._chart_histogram)

        # ── Graphique comparaison 3 scénarios (conditionnel) ─────────
        self._multi_section_title = QLabel(
            "Comparaison Pessimiste / Réaliste / Optimiste"
        )
        self._multi_section_title.setStyleSheet(STYLE_SECTION)
        self._multi_section_title.setVisible(False)
        layout.addWidget(self._multi_section_title)

        self._chart_multi = PlotlyView(min_height=320)
        self._chart_multi.setVisible(False)
        layout.addWidget(self._chart_multi)

        # ── Graphique stress (conditionnel) ───────────────────────────
        self._stress_section_title = QLabel("Comparaison baseline vs stress")
        self._stress_section_title.setStyleSheet(STYLE_SECTION)
        self._stress_section_title.setVisible(False)
        layout.addWidget(self._stress_section_title)

        self._chart_stress = PlotlyView(min_height=300)
        self._chart_stress.setVisible(False)
        layout.addWidget(self._chart_stress)

        layout.addLayout(self._build_stress_kpi_section())
        layout.addStretch()

        self._set_empty_state()

    def _build_scope_box(self) -> QGroupBox:
        box = QGroupBox("Portée de la simulation")
        box.setStyleSheet(STYLE_GROUP)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        self._combo_scope = QComboBox()
        self._combo_scope.setStyleSheet(self._combo_style())
        self._combo_scope.currentIndexChanged.connect(self._on_scope_combo_changed)
        form.addRow("Simuler pour :", self._combo_scope)
        return box

    def _build_params_general_box(self) -> QGroupBox:
        box = QGroupBox("Paramètres généraux")
        box.setStyleSheet(STYLE_GROUP)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self._spin_horizon = QSpinBox()
        self._spin_horizon.setRange(1, 50)
        self._spin_horizon.setValue(20)
        self._spin_horizon.setSuffix(" ans")
        self._spin_horizon.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow("Horizon :", self._spin_horizon)

        self._combo_engine = QComboBox()
        self._combo_engine.addItem("Monte Carlo", "monte_carlo")
        self._combo_engine.addItem("Déterministe", "deterministic")
        self._combo_engine.setStyleSheet(self._combo_style())
        self._combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        form.addRow("Moteur :", self._combo_engine)

        self._spin_simulations = QSpinBox()
        self._spin_simulations.setRange(100, 10000)
        self._spin_simulations.setValue(1000)
        self._spin_simulations.setSingleStep(100)
        self._spin_simulations.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow("Simulations (Monte Carlo) :", self._spin_simulations)

        return box

    def _build_params_flux_box(self) -> QGroupBox:
        box = QGroupBox("Flux mensuels")
        box.setStyleSheet(STYLE_GROUP)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self._spin_contribution = QDoubleSpinBox()
        self._spin_contribution.setRange(-100_000, 100_000)
        self._spin_contribution.setDecimals(0)
        self._spin_contribution.setSuffix(" €/mois")
        self._spin_contribution.setValue(0)
        self._spin_contribution.setSingleStep(100)
        self._spin_contribution.setStyleSheet(STYLE_INPUT_FOCUS)
        contrib_help = QLabel("0 = utiliser la capacité d'épargne réelle du scope")
        contrib_help.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        form.addRow("Apport mensuel :", self._spin_contribution)
        form.addRow("", contrib_help)

        self._spin_goal = QDoubleSpinBox()
        self._spin_goal.setRange(0, 100_000_000)
        self._spin_goal.setDecimals(0)
        self._spin_goal.setSuffix(" €")
        self._spin_goal.setValue(500_000)
        self._spin_goal.setSingleStep(10_000)
        self._spin_goal.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow("Objectif patrimonial :", self._spin_goal)

        return box

    def _build_preset_box(self) -> QGroupBox:
        """
        Sélecteur Pessimiste / Réaliste / Optimiste.
        Affiche en read-only les paramètres du preset pour le scope courant.
        """
        box = QGroupBox("Hypothèses de rendement et de volatilité")
        box.setStyleSheet(STYLE_GROUP)
        v = QVBoxLayout(box)
        v.setSpacing(10)

        preset_row = QFormLayout()
        preset_row.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._combo_preset = QComboBox()
        for key, label in _PRESET_LABELS.items():
            self._combo_preset.addItem(label, key)
        self._combo_preset.setCurrentIndex(1)   # Réaliste par défaut
        self._combo_preset.setStyleSheet(self._combo_style())
        self._combo_preset.currentIndexChanged.connect(self._load_preset_display)
        preset_row.addRow("Scénario :", self._combo_preset)
        v.addLayout(preset_row)

        note = QLabel("💡 Modifiez ces valeurs dans la page Paramètres → Presets de simulation.")
        note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        note.setWordWrap(True)
        v.addWidget(note)

        grid = QGridLayout()
        grid.setSpacing(6)
        header_style = f"color: {TEXT_MUTED}; font-size: 11px; font-weight: bold;"
        for col, text in enumerate(["Classe d'actif", "Rendement annuel", "Volatilité annuelle"]):
            h = QLabel(text)
            h.setStyleSheet(header_style)
            grid.addWidget(h, 0, col)

        for row_idx, (name, _) in enumerate(_RETURN_FIELDS.items(), start=1):
            lbl_name = QLabel(name)
            lbl_name.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
            lbl_ret = _info_label("—")
            lbl_vol = _info_label("—")
            grid.addWidget(lbl_name, row_idx, 0)
            grid.addWidget(lbl_ret,  row_idx, 1)
            grid.addWidget(lbl_vol,  row_idx, 2)
            self._preset_info_labels[name] = (lbl_ret, lbl_vol)

        row_infl = len(_RETURN_FIELDS) + 1
        lbl_infl_name = QLabel("Inflation")
        lbl_infl_name.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._lbl_inflation_info = _info_label("—")
        grid.addWidget(lbl_infl_name,            row_infl, 0)
        grid.addWidget(self._lbl_inflation_info, row_infl, 1)

        v.addLayout(grid)
        return box

    def _build_params_stress_box(self) -> QGroupBox:
        box = QGroupBox("Stress test")
        box.setStyleSheet(STYLE_GROUP)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        self._combo_stress = QComboBox()
        self._combo_stress.addItem("Aucun (baseline)", None)
        self._combo_stress.setStyleSheet(self._combo_style())
        self._load_stress_scenarios()
        form.addRow("Scénario :", self._combo_stress)
        return box

    def _build_action_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self._btn_run = QPushButton("▶  Lancer la simulation")
        self._btn_run.setStyleSheet(STYLE_BTN_SUCCESS)
        self._btn_run.clicked.connect(self._on_run_clicked)
        row.addWidget(self._btn_run)

        self._btn_multi = QPushButton("⚖  Comparer les 3 scénarios")
        self._btn_multi.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        self._btn_multi.clicked.connect(self._on_multi_clicked)
        row.addWidget(self._btn_multi)

        self._btn_reset = QPushButton("↺  Réinitialiser")
        self._btn_reset.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        self._btn_reset.clicked.connect(self._on_reset_clicked)
        row.addWidget(self._btn_reset)

        row.addStretch()
        return row

    def _build_kpi_section(self) -> QVBoxLayout:
        row1 = QHBoxLayout()
        self._kpi_final   = KpiCard(tone="blue")
        self._kpi_median  = KpiCard(tone="green")
        self._kpi_p10     = KpiCard(tone="neutral")
        self._kpi_p90     = KpiCard(tone="purple")
        for card in (self._kpi_final, self._kpi_median, self._kpi_p10, self._kpi_p90):
            row1.addWidget(card)

        row2 = QHBoxLayout()
        self._kpi_proba    = KpiCard(tone="primary")
        self._kpi_drawdown = KpiCard(tone="neutral")
        self._kpi_var      = KpiCard(tone="neutral")
        self._kpi_fire     = KpiCard(tone="neutral")
        for card in (self._kpi_proba, self._kpi_drawdown, self._kpi_var, self._kpi_fire):
            row2.addWidget(card)

        container = QVBoxLayout()
        container.setSpacing(8)
        container.addLayout(row1)
        container.addLayout(row2)
        return container

    def _build_stress_kpi_section(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._kpi_stress_delta    = KpiCard(tone="neutral")
        self._kpi_stress_drawdown = KpiCard(tone="neutral")
        self._kpi_stress_recovery = KpiCard(tone="neutral")
        for card in (self._kpi_stress_delta, self._kpi_stress_drawdown,
                     self._kpi_stress_recovery):
            card.setVisible(False)
            row.addWidget(card)
        return row

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: {BG_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
                padding: 6px 10px; font-size: 13px; min-width: 200px;
            }}
            QComboBox::drop-down {{ border: none; }}
        """

    # ── Chargements initiaux ─────────────────────────────────────────────

    def _load_people(self):
        """Peuple le combo scope avec Famille + toutes les personnes."""
        self._combo_scope.blockSignals(True)
        self._combo_scope.clear()
        self._combo_scope.addItem("Famille", ("family", None))
        try:
            from services.goals_projection_repository import list_people_for_scope
            people_df = list_people_for_scope(self._conn)
            if people_df is not None and not people_df.empty:
                for _, row in people_df.iterrows():
                    self._combo_scope.addItem(str(row["name"]), ("person", int(row["id"])))
        except Exception as exc:
            logger.error("Impossible de charger les personnes: %s", exc)
        self._sync_scope_combo()
        self._combo_scope.blockSignals(False)
        self._load_preset_display()

    def _load_stress_scenarios(self):
        try:
            from services.projection_service import ProjectionService
            for key, scenario in ProjectionService.list_standard_stress_scenarios().items():
                self._combo_stress.addItem(scenario.description, key)
        except Exception as exc:
            logger.error("Impossible de charger les scénarios de stress: %s", exc)

    # ── Chargement du preset et affichage info ────────────────────────

    def _load_preset_display(self, *, force: bool = False):
        """Charge le preset depuis la DB et met à jour les labels info."""
        preset_key = self._combo_preset.currentData()
        if not preset_key:
            return
        try:
            from services.simulation_presets_repository import get_preset, initialize_default_presets
            cache_key = (self._scope_type, self._scope_id, str(preset_key))
            now = time.monotonic()
            cached = self._preset_cache.get(cache_key)

            if (
                not force
                and cached is not None
                and (now - cached[0]) <= self._preset_cache_ttl_sec
            ):
                self._preset_data = cached[1]
            else:
                initialize_default_presets(self._conn, self._scope_type, self._scope_id)
                self._preset_data = get_preset(
                    self._conn, preset_key, self._scope_type, self._scope_id
                )
                self._preset_cache[cache_key] = (now, self._preset_data)
        except Exception as exc:
            logger.error("Impossible de charger le preset '%s': %s", preset_key, exc)
            self._preset_data = {}
            return

        for name, (ret_field, vol_field) in _RETURN_FIELDS.items():
            if name not in self._preset_info_labels:
                continue
            lbl_ret, lbl_vol = self._preset_info_labels[name]
            if ret_field is not None:
                lbl_ret.setText(f"{self._preset_data.get(ret_field, 0.0):.1f} %")
            else:
                lbl_ret.setText(f"{_CRYPTO_RETURN_DEFAULT * 100:.1f} %")
            lbl_vol.setText(f"{self._preset_data.get(vol_field, 0.0):.1f} %")

        self._lbl_inflation_info.setText(
            f"{self._preset_data.get('inflation_pct', 2.0):.1f} %"
        )

    # ── API publique ─────────────────────────────────────────────────────

    def set_scope(self, scope_type: str, scope_id: Optional[int]):
        """Appelé par la page parente quand le scope global change."""
        self._scope_type = scope_type
        self._scope_id = scope_id
        self._sync_scope_combo()
        self._load_preset_display()

    def refresh(self):
        """Rafraîchit le panel (appelé quand l'onglet devient visible)."""
        self._load_preset_display()

    # ── Sync combo scope ─────────────────────────────────────────────────

    def _sync_scope_combo(self):
        for i in range(self._combo_scope.count()):
            data = self._combo_scope.itemData(i)
            if data and data[0] == self._scope_type and data[1] == self._scope_id:
                self._combo_scope.setCurrentIndex(i)
                return

    def _on_scope_combo_changed(self, _index: int):
        data = self._combo_scope.currentData()
        if not data:
            return
        self._scope_type = data[0]
        self._scope_id = data[1]
        self._load_preset_display()

    # ── Événements ───────────────────────────────────────────────────────

    def _on_engine_changed(self, _index: int):
        is_mc = self._combo_engine.currentData() == "monte_carlo"
        self._spin_simulations.setEnabled(is_mc)

    def _on_run_clicked(self):
        """Lance la simulation pour le preset et le scope courants."""
        if self._thread and self._thread.isRunning():
            return
        self._read_scope_from_combo()
        if not self._preset_data:
            self._load_preset_display()
        self._set_loading_state("Simulation en cours…")

        config = self._build_config()
        engine = self._combo_engine.currentData()
        stress_key = self._combo_stress.currentData()

        if stress_key:
            self._run_stress(config, stress_key)
        else:
            self._run_prevision(config, engine)

    def _on_multi_clicked(self):
        """Lance les 3 simulations déterministes pour comparer les scénarios."""
        if self._thread and self._thread.isRunning():
            return
        self._read_scope_from_combo()
        self._set_loading_state("Comparaison des 3 scénarios en cours…")
        self._set_buttons_enabled(False)

        base_params = {
            "horizon_years":      self._spin_horizon.value(),
            "num_simulations":    self._spin_simulations.value(),
            "monthly_contribution": self._spin_contribution.value(),
            "target_goal_amount": self._spin_goal.value() or None,
        }
        self._thread = _MultiScenarioThread(
            self._scope_type, self._scope_id, base_params
        )
        self._thread.finished.connect(self._on_multi_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_reset_clicked(self):
        self._spin_horizon.setValue(20)
        self._spin_simulations.setValue(1000)
        self._combo_engine.setCurrentIndex(0)
        self._spin_contribution.setValue(0)
        self._spin_goal.setValue(500_000)
        self._combo_preset.setCurrentIndex(1)
        self._combo_stress.setCurrentIndex(0)
        self._set_empty_state()

    # ── Helpers scope / config ───────────────────────────────────────────

    def _read_scope_from_combo(self):
        data = self._combo_scope.currentData()
        if data:
            self._scope_type = data[0]
            self._scope_id = data[1]

    def _build_config(self):
        """Construit PrevisionConfig depuis le preset courant + widgets."""
        return _build_config_from_preset(
            self._preset_data,
            {
                "horizon_years":        self._spin_horizon.value(),
                "num_simulations":      self._spin_simulations.value(),
                "monthly_contribution": self._spin_contribution.value(),
                "target_goal_amount":   self._spin_goal.value() or None,
            }
        )

    # ── Lancement des simulations ────────────────────────────────────────

    def _run_prevision(self, config, engine: str):
        self._thread = _PrevisionThread(
            self._scope_type, self._scope_id, config, engine,
        )
        self._thread.finished.connect(self._on_prevision_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _run_stress(self, config, stress_key: str):
        from services.projection_service import ProjectionService
        scenario = ProjectionService.list_standard_stress_scenarios().get(stress_key)
        if not scenario:
            self._set_error_state(f"Scénario inconnu : {stress_key}")
            return
        self._thread = _StressThread(
            self._scope_type, self._scope_id, config, scenario,
        )
        self._thread.finished.connect(self._on_stress_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    # ── Callbacks résultats ──────────────────────────────────────────────

    def _on_prevision_finished(self, result):
        self._result = result
        self._stress_result = None
        self._update_kpis(result)
        self._update_charts(result)
        self._update_diagnostics(result)
        self._hide_stress_section()
        self._hide_multi_section()
        
        warnings_texts = getattr(result.base, "warnings", []) if hasattr(result, "base") else []
        self._show_warnings(warnings_texts)

        scope_label  = self._combo_scope.currentText()
        preset_label = self._combo_preset.currentText()
        engine_label = self._combo_engine.currentText()
        self._status_label.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._status_label.setText(
            f"✅ Simulation terminée — {scope_label}, scénario {preset_label}, "
            f"{engine_label}, horizon {result.config.horizon_years} ans."
        )
        self._set_buttons_enabled(True)

    def _on_stress_finished(self, stress_result):
        self._stress_result = stress_result
        self._result = stress_result.baseline_result
        self._update_kpis(stress_result.baseline_result)
        self._update_charts(stress_result.baseline_result)
        self._update_diagnostics(stress_result.baseline_result)
        self._show_stress_section(stress_result)
        self._hide_multi_section()
        
        warnings_texts = getattr(stress_result.baseline_result.base, "warnings", []) if hasattr(stress_result.baseline_result, "base") else []
        self._show_warnings(warnings_texts)

        scope_label = self._combo_scope.currentText()
        self._status_label.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._status_label.setText(
            f"✅ Stress test terminé — {scope_label} : {stress_result.scenario.description}"
        )
        self._set_buttons_enabled(True)

    def _on_multi_finished(self, payload):
        """Affiche le graphique de comparaison des 3 scénarios."""
        if isinstance(payload, dict) and "results" in payload:
            results = payload["results"]
            warnings_texts = payload.get("warnings", [])
        else:
            results = payload
            warnings_texts = []

        self._multi_results = results
        self._hide_stress_section()
        self._show_multi_section(results)
        self._show_warnings(warnings_texts)

        # Afficher aussi les KPIs du scénario réaliste
        realiste = results.get("realiste")
        if realiste:
            self._update_kpis(realiste)
            self._update_charts(realiste)
            self._update_diagnostics(realiste)

        scope_label = self._combo_scope.currentText()
        self._status_label.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._status_label.setText(
            f"✅ Comparaison terminée — {scope_label}, "
            f"horizon {self._spin_horizon.value()} ans. "
            f"(KPIs affichés = scénario Réaliste)"
        )
        self._set_buttons_enabled(True)

    def _on_error(self, error_msg: str):
        self._set_error_state(error_msg)
        self._set_buttons_enabled(True)

    def _show_warnings(self, warnings_texts):
        if not hasattr(self, "_warnings_label"):
            return
        if warnings_texts:
            self._warnings_label.setText(
                "⚠️ Données manquantes ou forcées à 0 (Qualité des données) :\n - " + "\n - ".join(warnings_texts)
            )
            self._warnings_label.setVisible(True)
        else:
            self._warnings_label.setVisible(False)

    # ── Mise à jour des KPIs ─────────────────────────────────────────────

    def _update_kpis(self, result):
        """Met à jour les KPI cards depuis un PrevisionResult."""
        self._kpi_final.set_content(
            "Patrimoine final (médiane)",
            money(result.final_net_worth_median),
            subtitle=f"Horizon {result.config.horizon_years} ans",
            tone="blue",
        )
        net_worth = result.base.current_net_worth
        net_subtitle = (
            "⚠️ Patrimoine non renseigné — vérifiez les données"
            if net_worth == 0.0
            else "Base de départ"
        )
        self._kpi_median.set_content(
            "Patrimoine actuel",
            money(net_worth),
            subtitle=net_subtitle,
            tone="green" if net_worth > 0.0 else "neutral",
        )

        if result.percentile_10_series is not None:
            self._kpi_p10.set_content(
                "P10 (scénario défavorable)",
                money(result.percentile_10_series.iloc[-1]),
                tone="neutral",
            )
        else:
            self._kpi_p10.set_content("P10", "—", subtitle="Déterministe", tone="neutral")

        if result.percentile_90_series is not None:
            self._kpi_p90.set_content(
                "P90 (scénario favorable)",
                money(result.percentile_90_series.iloc[-1]),
                tone="purple",
            )
        else:
            self._kpi_p90.set_content("P90", "—", subtitle="Déterministe", tone="neutral")

        if result.goal_metrics:
            proba = result.goal_metrics.probability_of_success
            tone = "success" if proba >= 0.7 else ("primary" if proba >= 0.4 else "alert")
            self._kpi_proba.set_content(
                "Probabilité d'atteinte",
                _pct(proba),
                subtitle=f"Objectif {money(result.config.target_goal_amount or 0)}",
                tone=tone,
            )
        else:
            self._kpi_proba.set_content("Probabilité", "—", tone="neutral")

        if result.risk_metrics:
            self._kpi_drawdown.set_content(
                "Max drawdown", _pct(result.risk_metrics.max_drawdown), tone="neutral",
            )
            self._kpi_var.set_content(
                "VaR 95%", money(result.risk_metrics.var_95), tone="neutral",
            )
        else:
            self._kpi_drawdown.set_content("Max drawdown", "—", tone="neutral")
            self._kpi_var.set_content("VaR 95%", "—", tone="neutral")

        # ── FIRE ─────────────────────────────────────────────────────
        self._update_kpi_fire(result)

    def _update_kpi_fire(self, result):
        """Met à jour la carte KPI Date FIRE."""
        fire = result.fire_date
        if not fire or not fire.get("fire_reached"):
            self._kpi_fire.set_content(
                "Date FIRE",
                "Non atteint",
                subtitle=f"Dans l'horizon {result.config.horizon_years} ans",
                tone="neutral",
            )
            return

        fire_years = fire.get("fire_years", 0)
        fire_year  = fire.get("fire_year_calendar", "—")
        tone = "success" if fire_years <= 15 else "primary"
        self._kpi_fire.set_content(
            "Date FIRE estimée",
            str(fire_year),
            subtitle=f"Dans {fire_years:.1f} ans",
            tone=tone,
        )

    # ── Mise à jour des graphiques ───────────────────────────────────────

    def _update_charts(self, result):
        self._chart_trajectory.set_figure(self._build_trajectory_chart(result))
        self._chart_histogram.set_figure(self._build_histogram_chart(result))

    def _build_trajectory_chart(self, result) -> go.Figure:
        """Courbe déterministe ou fan chart Monte Carlo."""
        fig = go.Figure()
        median = result.median_series
        x_years = [v / 12.0 for v in range(len(median))]

        if result.percentile_10_series is not None and result.percentile_90_series is not None:
            fig.add_trace(go.Scatter(
                x=x_years, y=result.percentile_90_series.values,
                mode="lines", line=dict(width=0), showlegend=False, name="P90",
            ))
            fig.add_trace(go.Scatter(
                x=x_years, y=result.percentile_10_series.values,
                mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(96,165,250,0.15)",
                showlegend=True, name="Intervalle P10–P90",
            ))

        fig.add_trace(go.Scatter(
            x=x_years, y=median.values,
            mode="lines", line=dict(color="#60a5fa", width=3), name="Médiane",
        ))

        # Ligne objectif
        goal = result.config.target_goal_amount
        if goal and goal > 0:
            fig.add_trace(go.Scatter(
                x=x_years, y=[goal] * len(x_years),
                mode="lines", line=dict(color="#f59e0b", width=2, dash="dash"),
                name=f"Objectif ({money(goal)})",
            ))

        # Ligne FIRE
        fire = result.fire_date
        if fire and fire.get("fire_reached"):
            fire_years_val = fire.get("fire_years", 0)
            fire_target = result.base.fire_annual_expenses * result.config.fire_multiple
            if fire_target > 0:
                fig.add_hline(
                    y=fire_target, line_dash="dot", line_color="#a78bfa",
                    annotation_text=f"Cible FIRE ({money(fire_target)})",
                    annotation_position="right",
                )
                fig.add_vline(
                    x=fire_years_val, line_dash="dot", line_color="#a78bfa",
                    annotation_text=f"FIRE an {fire.get('fire_year_calendar', '')}",
                    annotation_position="top right",
                )

        fig.update_layout(**plotly_layout(
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        ))
        fig.update_xaxes(title="Années")
        fig.update_yaxes(title="Patrimoine net (€)")
        return fig

    def _build_histogram_chart(self, result) -> go.Figure:
        """Histogramme de la distribution finale (Monte Carlo)."""
        fig = go.Figure()
        if result.trajectories_df is None or result.trajectories_df.empty:
            fig.add_annotation(
                text="Histogramme disponible en mode Monte Carlo",
                xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color=TEXT_MUTED),
            )
            fig.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=20, b=10)))
            return fig

        final_values = result.trajectories_df.iloc[-1].values
        fig.add_trace(go.Histogram(
            x=final_values, nbinsx=50,
            marker_color="rgba(96,165,250,0.6)",
            marker_line=dict(color="#60a5fa", width=1),
            name="Distribution finale",
        ))
        fig.add_vline(
            x=result.final_net_worth_median, line_dash="dash", line_color="#60a5fa",
            annotation_text=f"Médiane: {money(result.final_net_worth_median)}",
        )
        goal = result.config.target_goal_amount
        if goal and goal > 0:
            fig.add_vline(
                x=goal, line_dash="dot", line_color="#f59e0b",
                annotation_text=f"Objectif: {money(goal)}",
            )
        fig.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=20, b=10)))
        fig.update_xaxes(title="Patrimoine final (€)")
        fig.update_yaxes(title="Nombre de simulations")
        return fig

    # ── Section multi-scénarios ──────────────────────────────────────────

    def _show_multi_section(self, results: dict):
        self._multi_section_title.setVisible(True)
        self._chart_multi.setVisible(True)
        self._chart_multi.set_figure(self._build_multi_scenario_chart(results))

    def _hide_multi_section(self):
        self._multi_section_title.setVisible(False)
        self._chart_multi.setVisible(False)

    def _build_multi_scenario_chart(self, results: dict) -> go.Figure:
        """
        Graphique avec les 3 courbes médianes (Pessimiste / Réaliste / Optimiste)
        et les lignes FIRE et objectif si disponibles.
        """
        fig = go.Figure()
        goal = self._spin_goal.value() or None

        for preset_key, label_raw in _PRESET_LABELS.items():
            result = results.get(preset_key)
            if result is None:
                continue
            label = label_raw.split("  ", 1)[-1]   # retirer l'emoji
            color = _PRESET_COLORS[preset_key]
            median = result.median_series
            x_years = [v / 12.0 for v in range(len(median))]

            fig.add_trace(go.Scatter(
                x=x_years, y=median.values,
                mode="lines", line=dict(color=color, width=2.5),
                name=label,
            ))

            # Marqueur FIRE pour chaque scénario
            fire = result.fire_date
            if fire and fire.get("fire_reached"):
                fire_yr = fire.get("fire_years", 0)
                fire_val = float(result.median_series.iloc[
                    min(int(fire_yr * 12), len(result.median_series) - 1)
                ])
                fig.add_trace(go.Scatter(
                    x=[fire_yr], y=[fire_val],
                    mode="markers",
                    marker=dict(symbol="star", size=12, color=color),
                    name=f"FIRE {label} ({fire.get('fire_year_calendar', '')})",
                    showlegend=True,
                ))

        # Ligne objectif commun
        if goal and goal > 0 and results:
            first_result = next(iter(results.values()))
            x_years_full = [v / 12.0 for v in range(len(first_result.median_series))]
            fig.add_trace(go.Scatter(
                x=x_years_full, y=[goal] * len(x_years_full),
                mode="lines", line=dict(color="#f59e0b", width=2, dash="dash"),
                name=f"Objectif ({money(goal)})",
            ))

        fig.update_layout(**plotly_layout(
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        ))
        fig.update_xaxes(title="Années")
        fig.update_yaxes(title="Patrimoine net (€)")
        return fig

    # ── Section stress ───────────────────────────────────────────────────

    def _show_stress_section(self, stress_result):
        self._stress_section_title.setVisible(True)
        self._chart_stress.setVisible(True)
        self._kpi_stress_delta.setVisible(True)
        self._kpi_stress_drawdown.setVisible(True)
        self._kpi_stress_recovery.setVisible(True)

        self._kpi_stress_delta.set_content(
            "Impact sur patrimoine final",
            _pct_signed(stress_result.delta_final_pct),
            subtitle=f"Delta: {money(stress_result.delta_final_net_worth)}",
            tone="alert" if stress_result.delta_final_pct < -0.1 else "neutral",
        )
        self._kpi_stress_drawdown.set_content(
            "Drawdown max (stress)",
            _pct(stress_result.max_drawdown_pct),
            subtitle=f"Point bas: {money(stress_result.lowest_net_worth)}",
            tone="neutral",
        )
        self._kpi_stress_recovery.set_content(
            "Recovery (pré-choc)",
            _months_display(stress_result.months_to_recover_pre_shock),
            subtitle=f"Baseline: {_months_display(stress_result.months_to_recover_baseline)}",
            tone="neutral",
        )
        self._chart_stress.set_figure(self._build_stress_chart(stress_result))

    def _hide_stress_section(self):
        self._stress_section_title.setVisible(False)
        self._chart_stress.setVisible(False)
        self._kpi_stress_delta.setVisible(False)
        self._kpi_stress_drawdown.setVisible(False)
        self._kpi_stress_recovery.setVisible(False)

    def _build_stress_chart(self, stress_result) -> go.Figure:
        fig = go.Figure()
        baseline = stress_result.baseline_result.median_series
        stressed = stress_result.stressed_result.median_series
        fig.add_trace(go.Scatter(
            x=[i / 12.0 for i in range(len(baseline))], y=baseline.values,
            mode="lines", line=dict(color="#60a5fa", width=2.5), name="Baseline",
        ))
        fig.add_trace(go.Scatter(
            x=[i / 12.0 for i in range(len(stressed))], y=stressed.values,
            mode="lines", line=dict(color="#ef4444", width=2.5),
            name=f"Stress: {stress_result.scenario.name}",
        ))
        fig.update_layout(**plotly_layout(
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        ))
        fig.update_xaxes(title="Années")
        fig.update_yaxes(title="Patrimoine net (€)")
        return fig

    # ── Diagnostics ──────────────────────────────────────────────────────

    def _update_diagnostics(self, result):
        if not result.diagnostics:
            self._diagnostics_label.setText("")
            return
        lines = ["Diagnostics :"] + [f"  • {d}" for d in result.diagnostics]
        self._diagnostics_label.setText("\n".join(lines))

    # ── États d'affichage ────────────────────────────────────────────────

    def _set_empty_state(self):
        self._status_label.setStyleSheet(STYLE_STATUS)
        self._status_label.setText(
            "Configurez vos paramètres puis cliquez sur « Lancer la simulation »."
        )
        for card, label in [
            (self._kpi_final,    "Patrimoine final"),
            (self._kpi_median,   "Patrimoine actuel"),
            (self._kpi_p10,      "P10"),
            (self._kpi_p90,      "P90"),
            (self._kpi_proba,    "Probabilité"),
            (self._kpi_drawdown, "Max drawdown"),
            (self._kpi_var,      "VaR 95%"),
            (self._kpi_fire,     "Date FIRE"),
        ]:
            card.set_content(label, "—", tone="neutral")

        self._diagnostics_label.setText("")
        self._hide_stress_section()
        self._hide_multi_section()

        empty_fig = go.Figure()
        empty_fig.add_annotation(
            text="Aucune simulation lancée",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color=TEXT_MUTED),
        )
        empty_fig.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=20, b=10)))
        self._chart_trajectory.set_figure(empty_fig)
        self._chart_histogram.set_figure(empty_fig)

    def _set_loading_state(self, message: str):
        self._set_buttons_enabled(False)
        scope_label  = self._combo_scope.currentText()
        preset_label = self._combo_preset.currentText()
        self._status_label.setStyleSheet(STYLE_STATUS_WARNING)
        self._status_label.setText(
            f"⏳ {message} ({scope_label}, {preset_label})"
        )

    def _set_error_state(self, message: str):
        self._status_label.setStyleSheet(STYLE_STATUS_ERROR)
        self._status_label.setText(f"❌ Erreur : {message}")
        logger.warning("Prevision avancée — erreur: %s", message)

    def _set_buttons_enabled(self, enabled: bool):
        self._btn_run.setEnabled(enabled)
        self._btn_multi.setEnabled(enabled)
        self._btn_reset.setEnabled(enabled)
