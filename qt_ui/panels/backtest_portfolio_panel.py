"""
Panel Backtest portefeuille (PARTIE 2 UI).

Affiche un backtest theorique portefeuille actuel vs benchmark
en consommant uniquement ProjectionService.build_current_portfolio_backtest.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qt_ui.theme import (
    CHART_BLUE,
    CHART_GREEN,
    STYLE_BTN_PRIMARY_BORDERED,
    STYLE_GROUP,
    STYLE_INPUT_FOCUS,
    STYLE_SECTION,
    STYLE_STATUS,
    STYLE_STATUS_ERROR,
    STYLE_STATUS_SUCCESS,
    STYLE_STATUS_WARNING,
    STYLE_TITLE,
    TEXT_MUTED,
    TEXT_SECONDARY,
    plotly_time_series_layout,
)
from qt_ui.widgets import KpiCard, PlotlyView
from qt_ui.widgets import DataTableWidget

logger = logging.getLogger(__name__)

_HORIZON_OPTIONS = [
    ("5 ans", "5y"),
    ("10 ans", "10y"),
    ("15 ans", "15y"),
    ("20 ans", "20y"),
    ("Max", "max"),
]

_HORIZON_LABELS = {
    "5y": "5 ans",
    "10y": "10 ans",
    "15y": "15 ans",
    "20y": "20 ans",
    "max": "max",
}

_BENCHMARK_SYMBOL = "URTH"


class _BacktestThread(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        person_id: int,
        horizon: str,
        benchmark_symbol: str,
        ignore_limiting_assets: bool,
    ):
        super().__init__()
        self._person_id = int(person_id)
        self._horizon = str(horizon)
        self._benchmark_symbol = str(benchmark_symbol)
        self._ignore_limiting_assets = bool(ignore_limiting_assets)

    def run(self) -> None:
        try:
            from services.db import get_conn
            from services.projection_service import ProjectionService

            with get_conn() as conn:
                payload = ProjectionService.build_current_portfolio_backtest(
                    conn=conn,
                    person_id=self._person_id,
                    horizon=self._horizon,
                    benchmark_symbol=self._benchmark_symbol,
                    ignore_limiting_assets=self._ignore_limiting_assets,
                )
            self.finished.emit(payload)
        except Exception as exc:
            logger.error("Erreur backtest thread: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class BacktestPortefeuillePanel(QWidget):
    """UI simple pour la comparaison portefeuille theorique vs benchmark."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._scope_type: str = "family"
        self._scope_id: Optional[int] = None

        self._thread: Optional[QThread] = None
        self._cache: dict[tuple[str, Optional[int], str, str, bool], dict] = {}
        self._active_key: tuple[str, Optional[int], str, str, bool] | None = None

        self._build_ui()
        self._set_empty_state("Sélectionnez un scope personne pour lancer le backtest.")

    # ── API publique ─────────────────────────────────────────────────────

    def set_scope(self, scope_type: str, scope_id: Optional[int]) -> None:
        self._scope_type = scope_type
        self._scope_id = scope_id

    def refresh(self) -> None:
        """Rafraîchit la vue active. Au premier affichage: auto-run horizon 10 ans."""
        self._run_backtest(force=False)

    # ── Construction UI ──────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Backtest portefeuille")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        subtitle = QLabel(
            "Portefeuille actuel projete dans le passe, compare au benchmark de marche."
        )
        subtitle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        layout.addWidget(subtitle)

        control_box = QGroupBox("Controle")
        control_box.setStyleSheet(STYLE_GROUP)
        control_row = QHBoxLayout(control_box)
        control_row.setContentsMargins(10, 8, 10, 8)
        control_row.setSpacing(10)

        lbl_horizon = QLabel("Horizon :")
        lbl_horizon.setStyleSheet(f"color: {TEXT_SECONDARY};")
        control_row.addWidget(lbl_horizon)

        self._combo_horizon = QComboBox()
        self._combo_horizon.setStyleSheet(STYLE_INPUT_FOCUS)
        for label, value in _HORIZON_OPTIONS:
            self._combo_horizon.addItem(label, value)
        default_idx = self._combo_horizon.findData("10y")
        if default_idx >= 0:
            self._combo_horizon.setCurrentIndex(default_idx)
        self._combo_horizon.currentIndexChanged.connect(self._on_horizon_changed)
        control_row.addWidget(self._combo_horizon)

        self._btn_refresh = QPushButton("Actualiser")
        self._btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        self._btn_refresh.clicked.connect(self._on_refresh_clicked)
        control_row.addWidget(self._btn_refresh)

        self._ignore_limiters_checkbox = QCheckBox("Ignorer les actifs limitants")
        self._ignore_limiters_checkbox.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._ignore_limiters_checkbox.toggled.connect(self._on_ignore_limiters_toggled)
        control_row.addWidget(self._ignore_limiters_checkbox)

        control_row.addStretch()

        self._benchmark_label = QLabel("Benchmark : MSCI World (URTH)")
        self._benchmark_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        control_row.addWidget(self._benchmark_label)

        layout.addWidget(control_box)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(STYLE_STATUS)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        chart_title = QLabel("Evolution portefeuille vs benchmark (base 100)")
        chart_title.setStyleSheet(STYLE_SECTION)
        layout.addWidget(chart_title)

        self._chart = PlotlyView(min_height=360)
        layout.addWidget(self._chart)

        self._metrics_title = QLabel("Metriques principales")
        self._metrics_title.setStyleSheet(STYLE_SECTION)
        layout.addWidget(self._metrics_title)

        kpi_row_1 = QHBoxLayout()
        kpi_row_1.setSpacing(10)
        self._kpi_perf_ptf = KpiCard(tone="green")
        self._kpi_perf_bench = KpiCard(tone="blue")
        self._kpi_ret_ptf = KpiCard(tone="neutral")
        self._kpi_vol_ptf = KpiCard(tone="neutral")
        for card in (self._kpi_perf_ptf, self._kpi_perf_bench, self._kpi_ret_ptf, self._kpi_vol_ptf):
            kpi_row_1.addWidget(card)
        layout.addLayout(kpi_row_1)

        kpi_row_2 = QHBoxLayout()
        kpi_row_2.setSpacing(10)
        self._kpi_dd_ptf = KpiCard(tone="neutral")
        self._kpi_sharpe_ptf = KpiCard(tone="neutral")
        self._kpi_excess = KpiCard(tone="primary")
        for card in (self._kpi_dd_ptf, self._kpi_sharpe_ptf, self._kpi_excess):
            kpi_row_2.addWidget(card)
        kpi_row_2.addStretch()
        layout.addLayout(kpi_row_2)

        info_box = QGroupBox("Resume")
        info_box.setStyleSheet(STYLE_GROUP)
        info_layout = QVBoxLayout(info_box)
        info_layout.setSpacing(6)
        self._summary_label = QLabel("—")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        info_layout.addWidget(self._summary_label)

        self._history_label = QLabel("—")
        self._history_label.setWordWrap(True)
        self._history_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        info_layout.addWidget(self._history_label)

        self._ignored_label = QLabel("")
        self._ignored_label.setWordWrap(True)
        self._ignored_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        info_layout.addWidget(self._ignored_label)
        layout.addWidget(info_box)

        diag_title = QLabel("Diagnostic des actifs")
        diag_title.setStyleSheet(STYLE_SECTION)
        layout.addWidget(diag_title)

        diag_box = QGroupBox("Impact des actifs (historique analysé)")
        diag_box.setStyleSheet(STYLE_GROUP)
        diag_layout = QVBoxLayout(diag_box)
        diag_layout.setSpacing(8)

        self._diag_status_label = QLabel("Le diagnostic apparaîtra après calcul.")
        self._diag_status_label.setWordWrap(True)
        self._diag_status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        diag_layout.addWidget(self._diag_status_label)

        self._diag_assets_table = DataTableWidget(searchable=False)
        self._diag_assets_table.setMinimumHeight(170)
        self._diag_assets_table.set_column_colors(
            {
                "Statut": _status_color,
            }
        )
        diag_layout.addWidget(self._diag_assets_table)

        impact_title = QLabel("Impact si retiré (poids renormalisés)")
        impact_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: bold;")
        diag_layout.addWidget(impact_title)

        self._diag_without_table = DataTableWidget(searchable=False)
        self._diag_without_table.setMinimumHeight(190)
        self._diag_without_table.set_column_colors(
            {
                "Delta Sharpe": _delta_color,
                "Delta rendement (%/an)": _delta_color,
                "Delta volatilité (%)": _delta_color_inverse,
                "Delta max drawdown (%)": _delta_color,
            }
        )
        diag_layout.addWidget(self._diag_without_table)
        layout.addWidget(diag_box)

        improved_title = QLabel("Portefeuille amélioré")
        improved_title.setStyleSheet(STYLE_SECTION)
        layout.addWidget(improved_title)

        improved_box = QGroupBox("Simulation de portefeuille amélioré")
        improved_box.setStyleSheet(STYLE_GROUP)
        improved_layout = QVBoxLayout(improved_box)
        improved_layout.setSpacing(8)

        self._improved_summary_label = QLabel("La simulation apparaîtra après calcul.")
        self._improved_summary_label.setWordWrap(True)
        self._improved_summary_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
        improved_layout.addWidget(self._improved_summary_label)

        metrics_title = QLabel("Comparaison métriques (historique identique)")
        metrics_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: bold;")
        improved_layout.addWidget(metrics_title)

        self._improved_metrics_table = DataTableWidget(searchable=False)
        self._improved_metrics_table.setMinimumHeight(170)
        self._improved_metrics_table.set_column_colors(
            {
                "Delta": _delta_color,
            }
        )
        improved_layout.addWidget(self._improved_metrics_table)

        adjust_title = QLabel("Ajustements par actif")
        adjust_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: bold;")
        improved_layout.addWidget(adjust_title)

        self._improved_adjustments_table = DataTableWidget(searchable=False)
        self._improved_adjustments_table.setMinimumHeight(220)
        self._improved_adjustments_table.set_column_colors(
            {
                "Variation (%)": _delta_color,
            }
        )
        improved_layout.addWidget(self._improved_adjustments_table)

        self._improved_constraints_label = QLabel("—")
        self._improved_constraints_label.setWordWrap(True)
        self._improved_constraints_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        improved_layout.addWidget(self._improved_constraints_label)

        self._improved_warning_label = QLabel("")
        self._improved_warning_label.setWordWrap(True)
        self._improved_warning_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        improved_layout.addWidget(self._improved_warning_label)

        layout.addWidget(improved_box)

        layout.addStretch()

    # ── Actions UI ───────────────────────────────────────────────────────

    def _on_horizon_changed(self, _index: int) -> None:
        self._run_backtest(force=False)

    def _on_ignore_limiters_toggled(self, _checked: bool) -> None:
        self._run_backtest(force=False)

    def _on_refresh_clicked(self) -> None:
        self._run_backtest(force=True)

    # ── Flux calcul / rendu ──────────────────────────────────────────────

    def _run_backtest(self, force: bool) -> None:
        if self._thread and self._thread.isRunning():
            return

        if self._scope_type != "person" or self._scope_id is None:
            self._set_empty_state("Backtest disponible uniquement en vue personne.")
            return

        horizon = str(self._combo_horizon.currentData() or "10y")
        ignore_limiters = bool(self._ignore_limiters_checkbox.isChecked())
        key = (self._scope_type, self._scope_id, horizon, _BENCHMARK_SYMBOL, ignore_limiters)

        if not force and key in self._cache:
            self._active_key = key
            self._render_payload(self._cache[key], from_cache=True)
            return

        self._active_key = key
        self._set_loading_state("Calcul du backtest en cours…")

        self._thread = _BacktestThread(
            person_id=int(self._scope_id),
            horizon=horizon,
            benchmark_symbol=_BENCHMARK_SYMBOL,
            ignore_limiting_assets=ignore_limiters,
        )
        self._thread.finished.connect(self._on_backtest_finished)
        self._thread.error.connect(self._on_backtest_error)
        self._thread.start()

    def _on_backtest_finished(self, payload: dict) -> None:
        self._set_controls_enabled(True)
        self._chart.set_loading(False)
        self._set_kpis_loading(False)
        self._set_diag_loading(False)
        self._set_improved_loading(False)

        if not isinstance(payload, dict):
            self._set_empty_state("Reponse backtest invalide.")
            return

        if self._active_key is not None and "error" not in payload:
            self._cache[self._active_key] = payload

        self._render_payload(payload, from_cache=False)

    def _on_backtest_error(self, message: str) -> None:
        self._set_controls_enabled(True)
        self._chart.set_loading(False)
        self._set_kpis_loading(False)
        self._set_diag_loading(False)
        self._set_improved_loading(False)
        self._status_label.setStyleSheet(STYLE_STATUS_ERROR)
        self._status_label.setText(f"Erreur backtest : {message}")
        self._chart.clear_figure()

    def _render_payload(self, payload: dict, from_cache: bool) -> None:
        if payload.get("error"):
            self._status_label.setStyleSheet(STYLE_STATUS_WARNING)
            self._status_label.setText(str(payload.get("error")))
            self._chart.clear_figure()
            self._set_kpi_values_none()
            self._summary_label.setText("Backtest indisponible avec les données actuelles.")
            self._history_label.setText("Vérifiez les positions bourse et l'historique weekly des prix.")
            self._ignored_label.setText("")
            self._render_asset_diagnostics({})
            self._render_improved_portfolio({})
            return

        self._render_chart(payload)
        self._render_kpis(payload)
        self._render_summary(payload)
        self._render_asset_diagnostics(payload)
        self._render_improved_portfolio(payload)

        effective = _fmt_years(payload.get("horizon_effective_years"))
        status_prefix = "Backtest chargé" if not from_cache else "Backtest chargé (cache)"
        self._status_label.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._status_label.setText(f"{status_prefix} - horizon réel: {effective}.")

    def _render_chart(self, payload: dict) -> None:
        series_df = payload.get("series_comparison")
        if series_df is None or getattr(series_df, "empty", True):
            self._chart.clear_figure()
            return

        df = series_df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        if df.empty:
            self._chart.clear_figure()
            return

        bench_symbol = str(payload.get("benchmark_symbol") or _BENCHMARK_SYMBOL)
        self._benchmark_label.setText(f"Benchmark : MSCI World ({bench_symbol})")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["portfolio_norm"],
                mode="lines",
                name="Portefeuille",
                line=dict(color=CHART_GREEN, width=2),
                hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.1f}<extra>Portefeuille</extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["benchmark_norm"],
                mode="lines",
                name=bench_symbol,
                line=dict(color=CHART_BLUE, width=2),
                hovertemplate=f"<b>%{{x|%d %b %Y}}</b><br>%{{y:.1f}}<extra>{bench_symbol}</extra>",
            )
        )
        fig.add_hline(y=100, line_dash="dash", line_color="#475569", line_width=1)
        fig.update_layout(
            **plotly_time_series_layout(margin=dict(l=10, r=10, t=34, b=10)),
            yaxis=dict(title="Base 100"),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        self._chart.set_figure(fig)

    def _render_kpis(self, payload: dict) -> None:
        m_ptf = payload.get("metrics_portfolio") or {}
        m_bench = payload.get("metrics_benchmark") or {}
        m_rel = payload.get("metrics_relative") or {}

        perf_ptf = m_ptf.get("cumulative_performance_pct")
        perf_bench = m_bench.get("cumulative_performance_pct")
        ret_ptf = m_ptf.get("annualized_return_pct")
        vol_ptf = m_ptf.get("annualized_volatility_pct")
        dd_ptf = m_ptf.get("max_drawdown_pct")
        sharpe_ptf = m_ptf.get("sharpe")
        excess_ann = m_rel.get("annualized_excess_return_pct")

        self._kpi_perf_ptf.set_content(
            "Performance cumulée portefeuille",
            _fmt_pct(perf_ptf, signed=True),
            tone="green",
        )
        self._kpi_perf_bench.set_content(
            "Performance cumulée benchmark",
            _fmt_pct(perf_bench, signed=True),
            tone="blue",
        )
        self._kpi_ret_ptf.set_content(
            "Rendement annualisé portefeuille",
            _fmt_pct(ret_ptf, signed=True),
            tone="neutral",
        )
        self._kpi_vol_ptf.set_content(
            "Volatilité portefeuille",
            _fmt_pct(vol_ptf, signed=False),
            tone="neutral",
        )
        self._kpi_dd_ptf.set_content(
            "Max drawdown portefeuille",
            _fmt_pct(dd_ptf, signed=True),
            tone="neutral",
        )
        self._kpi_sharpe_ptf.set_content(
            "Sharpe portefeuille",
            _fmt_float(sharpe_ptf),
            tone="neutral",
        )

        excess_tone = "green"
        if isinstance(excess_ann, (int, float)) and excess_ann < 0:
            excess_tone = "red"
        self._kpi_excess.set_content(
            "Sur/sous-performance annuelle",
            _fmt_pct(excess_ann, signed=True),
            tone=excess_tone,
        )

    def _render_summary(self, payload: dict) -> None:
        m_ptf = payload.get("metrics_portfolio") or {}
        m_rel = payload.get("metrics_relative") or {}
        history_limits = payload.get("history_limits") or {}
        benchmark_symbol = str(payload.get("benchmark_symbol") or _BENCHMARK_SYMBOL)
        horizon_key = str(payload.get("horizon_requested") or "10y")
        horizon_requested = _HORIZON_LABELS.get(horizon_key, horizon_key)
        effective_years = _fmt_years(payload.get("horizon_effective_years"))

        excess_ann = m_rel.get("annualized_excess_return_pct")
        vol_ptf = m_ptf.get("annualized_volatility_pct")
        limiting_assets = history_limits.get("limiting_start_assets") or []
        if not limiting_assets:
            fallback_limiter = (
                history_limits.get("limiting_start_asset")
                or (payload.get("summary") or {}).get("limiting_asset")
            )
            if fallback_limiter:
                limiting_assets = [str(fallback_limiter)]
        ignored_limiting_assets = payload.get("ignored_limiting_assets") or []
        ignore_mode = bool(payload.get("ignore_limiting_assets"))
        limiters_text = _format_symbols_list(limiting_assets)

        if isinstance(excess_ann, (int, float)):
            if excess_ann >= 0:
                summary = (
                    f"Le portefeuille aurait battu le MSCI World ({benchmark_symbol}) "
                    f"de {excess_ann:+.2f} %/an sur {horizon_requested}."
                )
            else:
                summary = (
                    f"Le portefeuille aurait sous-performe le MSCI World ({benchmark_symbol}) "
                    f"de {abs(excess_ann):.2f} %/an sur {horizon_requested}."
                )
        else:
            summary = "Comparaison portefeuille vs benchmark disponible, sans estimation d'ecart annualise."

        if vol_ptf is not None:
            summary += f" Volatilite portefeuille: {vol_ptf:.2f} %."
        self._summary_label.setText(summary)

        history_text = f"Horizon demandé: {horizon_requested}. Horizon réellement disponible: {effective_years}."
        requested_years = payload.get("horizon_requested_years")
        effective_raw = payload.get("horizon_effective_years")
        history_truncated = False
        if isinstance(requested_years, (int, float)) and isinstance(effective_raw, (int, float)):
            if float(effective_raw) + 0.01 < float(requested_years):
                history_truncated = True
                history_text += (
                    f" {int(requested_years)} ans demandés, {effective_raw:.1f} ans disponibles."
                )

        if history_truncated and limiting_assets:
            if len(limiting_assets) == 1:
                history_text += f" Actif limitant: {limiters_text}."
            else:
                history_text += f" Actifs limitants: {limiters_text}."

        if ignore_mode and ignored_limiting_assets:
            history_text += (
                " Option \"ignorer les actifs limitants\" appliquée: "
                f"{_format_symbols_list(ignored_limiting_assets)} retiré(s) du calcul."
            )
        elif ignore_mode and not ignored_limiting_assets:
            history_text += " Option \"ignorer les actifs limitants\" activée, sans exclusion possible."

        self._history_label.setText(history_text)

        ignored_assets = payload.get("assets_ignored") or []
        if ignored_assets:
            symbols = [str(x.get("symbol") or "?") for x in ignored_assets[:6]]
            suffix = "…" if len(ignored_assets) > 6 else ""
            self._ignored_label.setText(
                f"Actifs ignorés ({len(ignored_assets)}): {', '.join(symbols)}{suffix}"
            )
        else:
            self._ignored_label.setText("Actifs ignorés: aucun.")

    def _render_asset_diagnostics(self, payload: dict) -> None:
        diagnostics = payload.get("asset_diagnostics") or []
        if not diagnostics:
            self._diag_status_label.setText(
                "Diagnostic indisponible pour ce calcul (données insuffisantes ou portefeuille vide)."
            )
            self._diag_assets_table.set_dataframe(pd.DataFrame(columns=[
                "Actif", "Poids (%)", "Statut", "Contribution perf (%)",
                "Volatilité actif (%)", "Corr. portefeuille", "Corr. benchmark",
                "Diversification", "Commentaire",
            ]))
            self._diag_without_table.set_dataframe(pd.DataFrame(columns=[
                "Actif", "Delta rendement (%/an)", "Delta volatilité (%)",
                "Delta max drawdown (%)", "Delta Sharpe", "Lecture",
            ]))
            return

        self._diag_status_label.setText(
            "Lecture prudente : ces diagnostics décrivent uniquement l'historique analysé, "
            "et ne constituent pas une recommandation d'investissement."
        )

        rows_assets = []
        rows_without = []
        for item in diagnostics:
            symbol = str(item.get("symbol") or "?")
            name = str(item.get("name") or "").strip()
            display_name = f"{symbol} - {name}" if name else symbol

            rows_assets.append(
                {
                    "Actif": display_name,
                    "Poids (%)": _to_num(item.get("weight_pct")),
                    "Statut": str(item.get("status_label") or "Neutre"),
                    "Contribution perf (%)": _to_num(item.get("contribution_cumulative_pct")),
                    "Volatilité actif (%)": _to_num(item.get("asset_annualized_volatility_pct")),
                    "Corr. portefeuille": _to_num(item.get("correlation_to_portfolio")),
                    "Corr. benchmark": _to_num(item.get("correlation_to_benchmark")),
                    "Diversification": str(item.get("diversification_role") or "—"),
                    "Commentaire": str(item.get("diagnostic_comment") or "—"),
                }
            )

            without = item.get("without_asset") or {}
            deltas = without.get("deltas") or {}
            rows_without.append(
                {
                    "Actif": display_name,
                    "Delta rendement (%/an)": _to_num(deltas.get("annualized_return_pct")),
                    "Delta volatilité (%)": _to_num(deltas.get("annualized_volatility_pct")),
                    "Delta max drawdown (%)": _to_num(deltas.get("max_drawdown_pct")),
                    "Delta Sharpe": _to_num(deltas.get("sharpe")),
                    "Lecture": str(without.get("interpretation") or "—"),
                }
            )

        self._diag_assets_table.set_dataframe(pd.DataFrame(rows_assets))
        self._diag_without_table.set_dataframe(pd.DataFrame(rows_without))

    def _render_improved_portfolio(self, payload: dict) -> None:
        improved = payload.get("improved_portfolio") or {}
        if not improved:
            self._improved_summary_label.setText("Simulation indisponible.")
            self._improved_metrics_table.set_dataframe(pd.DataFrame(columns=["Métrique", "Actuel", "Amélioré", "Delta"]))
            self._improved_adjustments_table.set_dataframe(
                pd.DataFrame(columns=["Actif", "Poids actuel (%)", "Poids amélioré (%)", "Variation (%)", "Action"])
            )
            self._improved_constraints_label.setText("—")
            self._improved_warning_label.setText("")
            return

        if not improved.get("available"):
            message = str(improved.get("message") or "Aucune simulation améliorée crédible n'a été trouvée.")
            self._improved_summary_label.setText(message)
            self._improved_metrics_table.set_dataframe(pd.DataFrame(columns=["Métrique", "Actuel", "Amélioré", "Delta"]))
            self._improved_adjustments_table.set_dataframe(
                pd.DataFrame(columns=["Actif", "Poids actuel (%)", "Poids amélioré (%)", "Variation (%)", "Action"])
            )
            constraints = improved.get("constraints") or {}
            self._improved_constraints_label.setText(_format_constraints_text(constraints))
            self._improved_warning_label.setText(
                "Analyse historique indicative uniquement. Pas de recommandation d'investissement."
            )
            return

        self._improved_summary_label.setText(str(improved.get("summary") or "Version plus équilibrée simulée."))

        m_current = improved.get("metrics_current") or {}
        m_improved = improved.get("metrics_improved") or {}
        m_diff = improved.get("metrics_differences") or {}
        rows_metrics = [
            _metric_row("Rendement annualisé (%)", m_current.get("annualized_return_pct"), m_improved.get("annualized_return_pct"), m_diff.get("annualized_return_pct")),
            _metric_row("Volatilité annualisée (%)", m_current.get("annualized_volatility_pct"), m_improved.get("annualized_volatility_pct"), m_diff.get("annualized_volatility_pct")),
            _metric_row("Max drawdown (%)", m_current.get("max_drawdown_pct"), m_improved.get("max_drawdown_pct"), m_diff.get("max_drawdown_pct")),
            _metric_row("Sharpe", m_current.get("sharpe"), m_improved.get("sharpe"), m_diff.get("sharpe")),
            _metric_row("Performance cumulée (%)", m_current.get("cumulative_performance_pct"), m_improved.get("cumulative_performance_pct"), m_diff.get("cumulative_performance_pct")),
        ]
        self._improved_metrics_table.set_dataframe(pd.DataFrame(rows_metrics))

        adjustments = improved.get("adjustments") or []
        rows_adjust = []
        for row in adjustments:
            symbol = str(row.get("symbol") or "?")
            name = str(row.get("name") or "").strip()
            label = f"{symbol} - {name}" if name else symbol
            rows_adjust.append(
                {
                    "Actif": label,
                    "Poids actuel (%)": _to_num(row.get("weight_current_pct")),
                    "Poids amélioré (%)": _to_num(row.get("weight_improved_pct")),
                    "Variation (%)": _to_num(row.get("delta_weight_pct")),
                    "Action": str(row.get("action") or "—"),
                }
            )
        self._improved_adjustments_table.set_dataframe(pd.DataFrame(rows_adjust))

        constraints = improved.get("constraints") or {}
        applied_flags = improved.get("applied_adjustments") or []
        constraints_txt = _format_constraints_text(constraints)
        if applied_flags:
            constraints_txt += " Ajustements principaux: " + "; ".join(str(x) for x in applied_flags[:5]) + "."
        self._improved_constraints_label.setText(constraints_txt)

        warning = str(
            improved.get("warning")
            or "Simulation historique indicative, non prédictive et non assimilable à un conseil financier."
        )
        self._improved_warning_label.setText(warning)

    # ── Etats ────────────────────────────────────────────────────────────

    def _set_loading_state(self, message: str) -> None:
        self._status_label.setStyleSheet(STYLE_STATUS_WARNING)
        self._status_label.setText(message)
        self._set_controls_enabled(False)
        self._chart.set_loading(True)
        self._set_kpis_loading(True)
        self._set_diag_loading(True)
        self._set_improved_loading(True)

    def _set_empty_state(self, message: str) -> None:
        self._set_controls_enabled(True)
        self._status_label.setStyleSheet(STYLE_STATUS)
        self._status_label.setText(message)
        self._chart.set_loading(False)
        self._chart.clear_figure()
        self._set_kpi_values_none()
        self._summary_label.setText("—")
        self._history_label.setText("—")
        self._ignored_label.setText("")
        self._set_diag_loading(False)
        self._render_asset_diagnostics({})
        self._set_improved_loading(False)
        self._render_improved_portfolio({})

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._combo_horizon.setEnabled(enabled)
        self._btn_refresh.setEnabled(enabled)
        self._ignore_limiters_checkbox.setEnabled(enabled)

    def _set_kpis_loading(self, loading: bool) -> None:
        for card in (
            self._kpi_perf_ptf,
            self._kpi_perf_bench,
            self._kpi_ret_ptf,
            self._kpi_vol_ptf,
            self._kpi_dd_ptf,
            self._kpi_sharpe_ptf,
            self._kpi_excess,
        ):
            card.set_loading(loading)

    def _set_diag_loading(self, loading: bool) -> None:
        self._diag_assets_table.set_loading(loading)
        self._diag_without_table.set_loading(loading)

    def _set_improved_loading(self, loading: bool) -> None:
        self._improved_metrics_table.set_loading(loading)
        self._improved_adjustments_table.set_loading(loading)

    def _set_kpi_values_none(self) -> None:
        self._kpi_perf_ptf.set_content("Performance cumulée portefeuille", "—", tone="green")
        self._kpi_perf_bench.set_content("Performance cumulée benchmark", "—", tone="blue")
        self._kpi_ret_ptf.set_content("Rendement annualisé portefeuille", "—")
        self._kpi_vol_ptf.set_content("Volatilité portefeuille", "—")
        self._kpi_dd_ptf.set_content("Max drawdown portefeuille", "—")
        self._kpi_sharpe_ptf.set_content("Sharpe portefeuille", "—")
        self._kpi_excess.set_content("Sur/sous-performance annuelle", "—", tone="primary")


def _fmt_pct(value, signed: bool) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "—"
    if signed:
        return f"{value:+.2f} %"
    return f"{value:.2f} %"


def _fmt_float(value) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "—"
    return f"{value:.3f}"


def _fmt_years(value) -> str:
    if value is None or not isinstance(value, (int, float)):
        return "—"
    return f"{value:.1f} ans"


def _format_symbols_list(symbols, max_items: int = 4) -> str:
    cleaned = []
    for symbol in symbols or []:
        s = str(symbol or "").strip()
        if s and s not in cleaned:
            cleaned.append(s)
    if not cleaned:
        return "—"
    if len(cleaned) <= max_items:
        return ", ".join(cleaned)
    shown = ", ".join(cleaned[:max_items])
    return f"{shown}, +{len(cleaned) - max_items}"


def _to_num(value):
    if value is None or not isinstance(value, (int, float)):
        return None
    return float(value)


def _metric_row(name: str, current, improved, delta) -> dict[str, object]:
    return {
        "Métrique": name,
        "Actuel": _to_num(current),
        "Amélioré": _to_num(improved),
        "Delta": _to_num(delta),
    }


def _format_constraints_text(constraints: dict) -> str:
    if not constraints:
        return "Contraintes: non disponibles."
    max_weight = constraints.get("max_weight_pct")
    min_weight = constraints.get("min_weight_if_selected_pct")
    leverage = constraints.get("leverage_allowed")
    short = constraints.get("short_allowed")
    return (
        "Contraintes appliquées: "
        f"poids max {max_weight}%, poids min {min_weight}% (si actif retenu), "
        f"short {'autorisé' if short else 'interdit'}, "
        f"levier {'autorisé' if leverage else 'interdit'}."
    )


def _status_color(value) -> str | None:
    text = str(value or "").strip().lower()
    if "moteur" in text:
        return "#22c55e"
    if "penalisant" in text:
        return "#ef4444"
    if "surveiller" in text:
        return "#f59e0b"
    return None


def _delta_color(value) -> str | None:
    if value is None or not isinstance(value, (int, float)):
        return None
    if value > 0:
        return "#22c55e"
    if value < 0:
        return "#ef4444"
    return None


def _delta_color_inverse(value) -> str | None:
    # Pour la volatilité: plus bas est généralement mieux.
    if value is None or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return "#22c55e"
    if value > 0:
        return "#ef4444"
    return None
