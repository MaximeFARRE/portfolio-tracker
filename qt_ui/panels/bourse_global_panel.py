"""
Panel Bourse Global — remplace ui/bourse_global_overview.py
"""
import logging
import datetime
import time

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QDateEdit, QComboBox, QDoubleSpinBox,
    QSpinBox, QCheckBox,
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QDate

from qt_ui.widgets import (
    PlotlyView, DataTableWidget, KpiCard, LoadingOverlay, CollapsibleSection,
)
from qt_ui.theme import (
    BG_PRIMARY, BG_CARD, BORDER_SUBTLE, TEXT_SECONDARY, TEXT_MUTED, TEXT_PRIMARY,
    STYLE_BTN_PRIMARY, STYLE_TITLE_XL, STYLE_SECTION,
    STYLE_STATUS, STYLE_STATUS_SUCCESS, STYLE_STATUS_WARNING, STYLE_STATUS_ERROR,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    STYLE_INPUT_FOCUS, STYLE_INPUT,
    plotly_layout, plotly_time_series_layout,
)
from services.common_utils import safe_float
from services.asset_panel_mapping import INVESTMENT_ACCOUNT_TYPES

logger = logging.getLogger(__name__)

# ── Mapping colonnes internes → libellés affichage ────────────────────────────
_COL_LABELS = {
    "symbol":     "Symbole",
    "name":       "Nom",
    "asset_type": "Type actif",
    "quantity":   "Qté",
    "pru":        "PRU (€)",
    "last_price": "Prix (€)",
    "value":      "Valeur (€)",
    "poids_%":    "Poids %",
    "pnl_latent": "PnL (€)",
    "valuation_status": "Statut valorisation",
    "compte":     "Compte",
    "type":       "Type",
}

# ── Couleurs du graphe revenus ────────────────────────────────────────────────
_INCOME_COLORS = {
    "DIVIDENDE": "#4ade80",
    "INTERETS":  "#60a5fa",
}


def _fmt_eur(value: float | None, decimals: int = 0) -> str:
    """Formate un montant en € avec espace fine comme séparateur de milliers."""
    if value is None or pd.isna(value):
        return "—"
    fmt = f"{value:,.{decimals}f}".replace(",", "\u202f")
    return f"{fmt} €"


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    sign = "+" if float(value) > 0 else ""
    return f"{sign}{float(value):.2f} %"


def _finite_sum(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.sum())


def _sep() -> QFrame:
    """Séparateur horizontal discret."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {BORDER_SUBTLE}; max-height: 1px;")
    return line


# ─────────────────────────────────────────────────────────────────────────────

class RebuildHistoryThread(QThread):
    """
    Thread de fond pour :
      1. Corriger les transactions TR mal typées (VENTE → DEPOT/INTERETS/DIVIDENDE)
      2. Reconstruire les snapshots hebdomadaires depuis l'historique complet
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, person_id: int):
        super().__init__()
        self._person_id = person_id

    def run(self):
        try:
            from services.db import get_conn
            from services.tr_import import fix_misclassified_tr_transactions
            # rebuild_snapshots_person est utilisé (pas la version backdated_aware)
            # car backdated_aware respecte le watermark → ne remonte pas avant la
            # dernière exécution. rebuild_snapshots_person force le recalcul de
            # TOUTES les semaines sur la fenêtre demandée, sans condition.
            from services.snapshots import rebuild_snapshots_person

            with get_conn() as conn:
                # Étape 1 — Correction des types de transactions
                self.progress.emit("Étape 1/2 : Correction des types de transactions TR…")
                fix_res = fix_misclassified_tr_transactions(conn, self._person_id)
                n_fixed = fix_res.get("total", 0)
                detail = (
                    f"depot={fix_res['fixed_depot']} "
                    f"intérêts={fix_res['fixed_interets']} "
                    f"dividendes={fix_res['fixed_dividende']}"
                )

                # Étape 2 — Reconstruction complète sur ~4 ans (ignore le watermark)
                self.progress.emit(
                    f"Étape 2/2 : Reconstruction des snapshots depuis 2023 ({n_fixed} tx corrigées)…"
                )
                reb_res = rebuild_snapshots_person(
                    conn, self._person_id, lookback_days=1500
                )
                n_weeks = reb_res.get("n_ok", 0)
                start   = reb_res.get("start", "?")

            self.finished.emit(
                f"✅ {n_fixed} tx corrigées ({detail}) · "
                f"{n_weeks} semaines reconstruites depuis {start}"
            )
        except Exception as e:
            logger.error("RebuildHistoryThread error: %s", e, exc_info=True)
            self.finished.emit(f"Erreur : {e}")


# ─────────────────────────────────────────────────────────────────────────────

class RefreshPricesThread(QThread):
    finished = pyqtSignal(str)

    def __init__(self, person_id: int):
        super().__init__()
        self._person_id = person_id

    def run(self):
        try:
            from services import repositories as repo
            from services import pricing, fx
            from services import panel_data_access as pda
            from services.db import get_conn

            with get_conn() as local_conn:
                df_acc = repo.list_accounts(local_conn, person_id=self._person_id)
                if df_acc is None or df_acc.empty:
                    self.finished.emit("Aucun compte bourse.")
                    return

                df_b = df_acc[
                    df_acc["account_type"].astype(str).str.upper().isin(INVESTMENT_ACCOUNT_TYPES)
                ]
                n_ok, n_fail = 0, 0
                assets_to_refresh: dict[int, str] = {}
                asset_target_ccy: dict[int, str] = {}
                for _, row in df_b.iterrows():
                    account_id = int(row["id"])
                    acc_ccy = str(row.get("currency") or "EUR").upper()
                    asset_ids = repo.list_account_asset_ids(local_conn, account_id=account_id)
                    for aid in asset_ids:
                        aid_i = int(aid)
                        if aid_i in assets_to_refresh:
                            continue
                        a = pda.get_asset_symbol(local_conn, aid)
                        if not a:
                            continue
                        sym = a[0] if not hasattr(a, '__getitem__') else a["symbol"]
                        sym = str(sym or "").strip().upper()
                        if sym:
                            assets_to_refresh[aid_i] = sym
                            asset_target_ccy[aid_i] = acc_ccy

                sym_cache: dict[str, tuple[float | None, str]] = {}
                ensured_fx_pairs: set[tuple[str, str]] = set()
                for aid, sym in assets_to_refresh.items():
                    acc_ccy = asset_target_ccy.get(aid, "EUR")
                    if sym not in sym_cache:
                        sym_cache[sym] = pricing.fetch_last_price_auto(sym)
                    px_val, ccy = sym_cache[sym]
                    if px_val is not None:
                        repo.upsert_price(local_conn, asset_id=aid, date=pricing.today_str(),
                                          price=px_val, currency=ccy, source="AUTO")
                        if ccy and str(ccy).upper() != acc_ccy:
                            repo.update_asset_currency(local_conn, aid, str(ccy).upper())
                            pair = (str(ccy).upper(), acc_ccy)
                            if pair not in ensured_fx_pairs:
                                fx.ensure_fx_rate(local_conn, pair[0], pair[1])
                                ensured_fx_pairs.add(pair)
                        n_ok += 1
                    else:
                        n_fail += 1
            self.finished.emit(f"{n_ok} OK, {n_fail} non trouvés")
        except Exception as e:
            logger.error("RefreshPricesThread error: %s", e, exc_info=True)
            self.finished.emit(f"Erreur : {e}")


# ─────────────────────────────────────────────────────────────────────────────

class BourseGlobalPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._thread = None
        self._thread_rebuild = None
        self._selected_date = None  # None = Live
        self._cache_ttl_sec = 20.0
        self._last_load_key: tuple[int, str | None] | None = None
        self._last_load_monotonic = 0.0

        self.setStyleSheet(f"background: {BG_PRIMARY};")

        # ── Scroll area ──────────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}")
        outer.addWidget(scroll)

        inner = QWidget()
        inner.setStyleSheet(f"background: {BG_PRIMARY};")
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)

        # ── En-tête ──────────────────────────────────────────────────────────
        header_row = QHBoxLayout()

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        lbl_title = QLabel("📈  Bourse — Vue Globale")
        lbl_title.setStyleSheet(STYLE_TITLE_XL)
        self._lbl_subtitle = QLabel("Portefeuille consolidé")
        self._lbl_subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        title_col.addWidget(lbl_title)
        title_col.addWidget(self._lbl_subtitle)
        header_row.addLayout(title_col)
        header_row.addStretch()

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        self._btn_refresh = QPushButton("↻  Rafraîchir les prix")
        self._btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_refresh.setFixedWidth(175)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._refresh_status = QLabel()
        self._refresh_status.setStyleSheet(STYLE_STATUS)
        self._refresh_status.setAlignment(Qt.AlignmentFlag.AlignRight)

        self._btn_rebuild = QPushButton("🔧  Reconstruire l'historique")
        self._btn_rebuild.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_rebuild.setFixedWidth(210)
        self._btn_rebuild.setToolTip(
            "Corrige les transactions TR mal importées et reconstruit\n"
            "les snapshots hebdomadaires depuis l'historique complet."
        )
        self._btn_rebuild.clicked.connect(self._on_rebuild)
        self._rebuild_status = QLabel()
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        self._rebuild_status.setAlignment(Qt.AlignmentFlag.AlignRight)

        btn_col.addWidget(self._btn_refresh, alignment=Qt.AlignmentFlag.AlignRight)
        btn_col.addWidget(self._refresh_status, alignment=Qt.AlignmentFlag.AlignRight)
        btn_col.addWidget(self._btn_rebuild, alignment=Qt.AlignmentFlag.AlignRight)
        btn_col.addWidget(self._rebuild_status, alignment=Qt.AlignmentFlag.AlignRight)
        header_row.addLayout(btn_col)

        layout.addLayout(header_row)
        layout.addWidget(_sep())

        # ── KPI Row 1 — métriques principales ────────────────────────────────
        kpi_row1 = QHBoxLayout()
        kpi_row1.setSpacing(10)
        self._kpi_invested = KpiCard("Capital investi", "—", emoji="💰", tone="neutral")
        self._kpi_holdings = KpiCard("Valeur actuelle", "—", emoji="💹", tone="primary")
        self._kpi_perf     = KpiCard("Performance",      "—", emoji="📊", tone="neutral")
        self._kpi_pnl      = KpiCard("Plus-value latente", "—", emoji="✨", tone="success")

        self._kpis_top = [self._kpi_invested, self._kpi_holdings, self._kpi_perf, self._kpi_pnl]
        for card in self._kpis_top:
            kpi_row1.addWidget(card)
        layout.addLayout(kpi_row1)

        # ── KPI Row 2 — revenus & positions ──────────────────────────────────
        kpi_row2 = QHBoxLayout()
        kpi_row2.setSpacing(10)
        self._kpi_nb     = KpiCard("Positions ouvertes", "—", emoji="🎯", tone="neutral")
        self._kpi_div    = KpiCard("Dividendes perçus",  "—", emoji="💵", tone="success")
        self._kpi_int    = KpiCard("Intérêts perçus",    "—", emoji="🏦", tone="success")
        self._kpi_fx_pnl = KpiCard("Effet change",       "—", emoji="💱", tone="neutral")
        self._kpi_fx_pnl.setToolTip(
            "Impact de la variation des devises sur la valorisation en euros des actifs non libelles en EUR"
        )
        self._kpis_bot = [self._kpi_nb, self._kpi_div, self._kpi_int, self._kpi_fx_pnl]
        for card in self._kpis_bot:
            kpi_row2.addWidget(card, stretch=1)
        layout.addLayout(kpi_row2)

        layout.addWidget(_sep())

        # ── Graphiques ───────────────────────────────────────────────────────
        lbl_charts = QLabel("Évolution & Revenus")
        lbl_charts.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_charts)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        vbox_hist = QVBoxLayout()
        vbox_hist.setSpacing(4)
        lbl_hist = QLabel("Évolution du portefeuille")
        lbl_hist.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._chart_history = PlotlyView(min_height=320)
        vbox_hist.addWidget(lbl_hist)
        vbox_hist.addWidget(self._chart_history)
        charts_row.addLayout(vbox_hist, stretch=3)

        vbox_inc = QVBoxLayout()
        vbox_inc.setSpacing(4)
        lbl_inc = QLabel("Revenus passifs (Dividendes & Intérêts)")
        lbl_inc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._chart_income = PlotlyView(min_height=280)
        vbox_inc.addWidget(lbl_inc)
        vbox_inc.addWidget(self._chart_income)
        charts_row.addLayout(vbox_inc, stretch=2)

        layout.addLayout(charts_row)
        layout.addWidget(_sep())

        # ── Table + Répartition ───────────────────────────────────────────────
        lbl_pos_section = QLabel("Positions détaillées")
        lbl_pos_section.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_pos_section)

        # ── Sélecteur de date (Historique) ───────────────────────────────────
        self._diag_header = QHBoxLayout()
        self._diag_header.setSpacing(10)
        self._lbl_mode = QLabel("🕒 Mode : Live")
        self._lbl_mode.setStyleSheet(f"color: {COLOR_SUCCESS}; font-weight: bold;")
        self._diag_header.addWidget(self._lbl_mode)
        
        self._diag_header.addStretch()
        
        self._lbl_date_picker = QLabel("Analyser à la date :")
        self._lbl_date_picker.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._diag_header.addWidget(self._lbl_date_picker)
        
        self._date_picker = QDateEdit()
        self._date_picker.setCalendarPopup(True)
        self._date_picker.setDate(QDate.currentDate())
        self._date_picker.setStyleSheet(f"background: #1e2538; color: white; padding: 4px; border-radius: 4px;")
        self._diag_header.addWidget(self._date_picker)
        
        self._btn_set_date = QPushButton("Appliquer")
        self._btn_set_date.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_set_date.clicked.connect(self._on_date_applied)
        self._diag_header.addWidget(self._btn_set_date)
        
        self._btn_reset_live = QPushButton("Revenir au Live")
        self._btn_reset_live.setStyleSheet("background: #374151; color: white; padding: 6px 12px; border: none; border-radius: 4px;")
        self._btn_reset_live.setVisible(False)
        self._btn_reset_live.clicked.connect(self._on_reset_live)
        self._diag_header.addWidget(self._btn_reset_live)
        
        layout.addLayout(self._diag_header)

        self._quality_label = QLabel("")
        self._quality_label.setStyleSheet(
            f"color: {COLOR_WARNING}; background: {BG_CARD}; border: 1px solid {COLOR_WARNING}; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px;"
        )
        self._quality_label.setVisible(False)
        layout.addWidget(self._quality_label)

        table_area = QHBoxLayout()
        table_area.setSpacing(12)

        self._table_pos = DataTableWidget()
        self._table_pos.setMinimumHeight(260)
        self._table_pos.set_filter_config([
            {"col": "Type actif", "kind": "combo", "label": "Type actif"},
            {"col": "Compte",     "kind": "combo", "label": "Compte"},
            {"col": "Type",       "kind": "combo", "label": "PEA/CTO"},
        ])
        table_area.addWidget(self._table_pos, stretch=3)

        vbox_alloc = QVBoxLayout()
        vbox_alloc.setSpacing(4)
        lbl_alloc = QLabel("Répartition par actif")
        lbl_alloc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._chart_alloc = PlotlyView(min_height=260)
        vbox_alloc.addWidget(lbl_alloc)
        vbox_alloc.addWidget(self._chart_alloc)
        table_area.addLayout(vbox_alloc, stretch=2)

        layout.addLayout(table_area)
        layout.addWidget(_sep())

        # ── Diagnostic Tickers (Debug) ────────────────────────────────────────
        lbl_diag = QLabel("🛠  Diagnostic — Statut des Tickers")
        lbl_diag.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_diag)

        self._table_diag = DataTableWidget()
        self._table_diag.setMinimumHeight(240)
        self._table_diag.set_filter_config([
            {"col": "Statut", "kind": "combo", "label": "Statut"},
        ])
        layout.addWidget(self._table_diag)

        # ── Analytics Avancés (accordéons, tout fermé par défaut) ──────────
        layout.addWidget(_sep())
        lbl_analytics = QLabel("📊  Analytics Avancés")
        lbl_analytics.setStyleSheet(STYLE_TITLE_XL)
        layout.addWidget(lbl_analytics)
        lbl_analytics_sub = QLabel(
            "Métriques d'ingénierie financière — cliquez sur une section pour l'ouvrir"
        )
        lbl_analytics_sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(lbl_analytics_sub)

        # État de chargement lazy : une seule fois par section
        self._analytics_loaded: dict[str, bool] = {}
        self._frontier_controls_ready = False
        self._frontier_presets: list[dict] = []
        self._frontier_result_container: QWidget | None = None
        self._frontier_result_layout: QVBoxLayout | None = None

        self._section_risk = self._build_analytics_section(
            layout, "📈 Rendement & Risque", "risk_return"
        )
        self._section_corr = self._build_analytics_section(
            layout, "🔗 Corrélations & Diversification", "correlation"
        )
        self._section_contrib = self._build_analytics_section(
            layout, "⚖️ Contribution au Risque", "risk_contribution"
        )
        self._section_var = self._build_analytics_section(
            layout, "🎯 VaR & Expected Shortfall", "var_es"
        )
        self._section_frontier = self._build_analytics_section(
            layout, "🌐 Frontière Efficiente", "efficient_frontier"
        )
        self._section_benchmark = self._build_analytics_section(
            layout, "📊 Comparaison Benchmark", "benchmark"
        )

        layout.addStretch()

        # ── Overlay de chargement (sur le widget externe, pas le scroll) ───
        self._overlay = LoadingOverlay(self)

    # ── Contrôles ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._invalidate_view_cache(reset_analytics=True)
        self._load_data(force=True)

    def _on_refresh(self) -> None:
        self._btn_refresh.setEnabled(False)
        self._refresh_status.setStyleSheet(STYLE_STATUS_WARNING)
        self._refresh_status.setText("⏳ En cours…")
        self._thread = RefreshPricesThread(self._person_id)
        self._thread.finished.connect(self._on_refresh_done)
        self._thread.start()

    def _on_refresh_done(self, msg: str) -> None:
        self._btn_refresh.setEnabled(True)
        if msg.startswith("Erreur"):
            self._refresh_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._refresh_status.setText(f"❌ {msg}")
        elif "non trouvés" in msg:
            self._refresh_status.setStyleSheet(STYLE_STATUS_WARNING)
            self._refresh_status.setText(f"⚠️ {msg}")
        else:
            self._refresh_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._refresh_status.setText(f"✅ {msg}")
        self._invalidate_view_cache(reset_analytics=True)
        self._load_data(force=True)

    def _on_date_applied(self) -> None:
        qdt = self._date_picker.date()
        date_str = qdt.toString("yyyy-MM-dd")
        # Si c'est aujourd'hui, on reste en live
        if date_str == datetime.date.today().isoformat():
            self._on_reset_live()
            return
        
        self._selected_date = date_str
        self._lbl_mode.setText(f"🕒 Historique : {qdt.toString('dd/MM/yyyy')}")
        self._lbl_mode.setStyleSheet(f"color: {COLOR_WARNING}; font-weight: bold;")
        self._btn_reset_live.setVisible(True)
        self._invalidate_view_cache(reset_analytics=True)
        self._load_data(force=True)

    def _on_reset_live(self) -> None:
        self._selected_date = None
        self._lbl_mode.setText("🕒 Mode : Live")
        self._lbl_mode.setStyleSheet(f"color: {COLOR_SUCCESS}; font-weight: bold;")
        self._btn_reset_live.setVisible(False)
        self._date_picker.setDate(QDate.currentDate())
        self._invalidate_view_cache(reset_analytics=True)
        self._load_data(force=True)

    def _on_rebuild(self) -> None:
        self._btn_rebuild.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._rebuild_status.setStyleSheet(STYLE_STATUS_WARNING)
        self._rebuild_status.setText("⏳ Démarrage…")
        self._thread_rebuild = RebuildHistoryThread(self._person_id)
        self._thread_rebuild.progress.connect(self._on_rebuild_progress)
        self._thread_rebuild.finished.connect(self._on_rebuild_done)
        self._thread_rebuild.start()

    def _on_rebuild_progress(self, msg: str) -> None:
        self._rebuild_status.setStyleSheet(STYLE_STATUS_WARNING)
        self._rebuild_status.setText(f"⏳ {msg}")

    def _on_rebuild_done(self, msg: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        if msg.startswith("Erreur"):
            self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._rebuild_status.setText(f"❌ {msg}")
        else:
            self._rebuild_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._rebuild_status.setText(msg)
        self._invalidate_view_cache(reset_analytics=True)
        self._load_data(force=True)

    # ── Chargement des données ────────────────────────────────────────────────

    def _invalidate_view_cache(self, *, reset_analytics: bool = False) -> None:
        """Invalide le dernier rendu local pour forcer un prochain chargement complet."""
        self._last_load_key = None
        self._last_load_monotonic = 0.0
        if reset_analytics:
            self._analytics_loaded = {}

    def _is_view_cache_valid(self, load_key: tuple[int, str | None]) -> bool:
        if self._last_load_key != load_key:
            return False
        age = time.monotonic() - self._last_load_monotonic
        return age <= self._cache_ttl_sec

    def _load_data(self, *, force: bool = False) -> None:
        load_key = (self._person_id, self._selected_date)
        if not force and self._is_view_cache_valid(load_key):
            return

        # ── 1. Activation des Skeletons ──────────────────────────────────
        all_widgets = self._kpis_top + self._kpis_bot + [self._table_pos, self._table_diag]
        for w in all_widgets:
            if hasattr(w, "set_loading"):
                w.set_loading(True)
        
        self._chart_history.set_loading(True)
        self._chart_income.set_loading(True)
        self._chart_alloc.set_loading(True)

        self._overlay.start("Analyse du portefeuille global…", blur=True)
        loaded_ok = False
        try:
            from services import repositories as repo
            from services.bourse_analytics import (
                get_live_bourse_positions,
                get_bourse_performance_metrics, compute_invested_series,
                get_tickers_diagnostic_df, get_bourse_state_asof,
                compute_fx_pnl_summary,
            )

            # ── Comptes bourse ──────────────────────────────────────────────
            df_acc = repo.list_accounts(self._conn, person_id=self._person_id)
            if df_acc is None or df_acc.empty:
                return

            df_b = df_acc[
                df_acc["account_type"].astype(str).str.upper().isin(INVESTMENT_ACCOUNT_TYPES)
            ]
            if df_b.empty:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucun compte bourse."}]))
                return

            metrics = {}
            missing_reasons: list[str] = []
            fx_pnl_summary: dict = {}
            if self._selected_date:
                # ── MODE HISTORIQUE ──
                state = get_bourse_state_asof(self._conn, self._person_id, self._selected_date)
                df_all = state.get("df", pd.DataFrame())
                total_val = state.get("total_val")
                nb_pos = len(df_all[df_all["quantity"] > 0]) if not df_all.empty else 0
                nb_acc = len(df_b)
                inv_eur = state.get("total_invested")
                total_pnl = state.get("total_pnl")
                g_perf = (
                    (float(total_val) / float(inv_eur) - 1.0) * 100.0
                    if total_val is not None and inv_eur is not None and float(inv_eur) > 0
                    else None
                )
                y_perf = None  # pas calculé en historique simple
                t_div = None   # pas filtré par date ici
                t_int = None
                missing_prices = state.get("missing_prices", [])
                missing_fx = state.get("missing_fx", [])
                if missing_prices:
                    missing_reasons.append(f"prix absent(s): {', '.join(map(str, missing_prices[:5]))}")
                if missing_fx:
                    fx_labels = sorted({str(item.get("currency", "?")) for item in missing_fx})
                    missing_reasons.append(f"FX absent(s): {', '.join(fx_labels)}")
                
            else:
                # ── MODE LIVE ──
                df_all = get_live_bourse_positions(self._conn, self._person_id)

                if df_all.empty:
                    self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucune position ouverte."}]))
                    return
                total_val = _finite_sum(df_all["value"])       if "value"      in df_all.columns else None
                total_pnl = _finite_sum(df_all["pnl_latent"])  if "pnl_latent" in df_all.columns else None
                fx_pnl_summary = compute_fx_pnl_summary(df_all)
                nb_pos    = len(df_all[df_all["quantity"] > 0]) if "quantity"  in df_all.columns else len(df_all)
                nb_acc    = len(df_b)
                if "valuation_status" in df_all.columns:
                    status_counts = df_all["valuation_status"].fillna("ok").astype(str).value_counts()
                    for status, count in status_counts.items():
                        if status != "ok":
                            missing_reasons.append(f"{count} position(s) {status}")

                # ── Métriques analytiques ──
                metrics = get_bourse_performance_metrics(self._conn, self._person_id, current_live_value=total_val)
                inv_eur = metrics.get("invested_eur")
                g_perf  = metrics.get("global_perf_pct")
                y_perf  = metrics.get("ytd_perf_pct")
                t_div   = metrics.get("total_dividends")
                t_int   = metrics.get("total_interests")
                if total_val is None:
                    g_perf = None
                    y_perf = None
                    missing_reasons.append("valeur courante non calculable")
                if metrics.get("missing_income_fx"):
                    fx_labels = sorted({str(item.get("currency", "?")) for item in metrics.get("missing_income_fx", [])})
                    missing_reasons.append(f"revenus FX incomplets: {', '.join(fx_labels)}")
                missing_reasons.extend([str(w) for w in metrics.get("perf_warnings", [])])

            if missing_reasons:
                self._quality_label.setText("⚠️ Données partielles : " + " · ".join(missing_reasons[:4]))
                self._quality_label.setVisible(True)
            else:
                self._quality_label.setVisible(False)

            # ── Sous-titre dynamique ─────────────────────────────────────────
            today_str = datetime.date.today().strftime("%d/%m/%Y")
            self._lbl_subtitle.setText(
                f"{nb_pos} position(s) · {nb_acc} compte(s) · màj le {today_str}"
            )

            # ── KPI — ligne 1 ────────────────────────────────────────────────
            self._kpi_invested.set_content(
                "Total Investi", _fmt_eur(inv_eur),
                emoji="💰", tone="neutral",
            )
            self._kpi_holdings.set_content(
                "Valeur Actuelle", _fmt_eur(total_val),
                emoji="📊", tone="broker",
            )
            self._kpi_perf.set_content(
                "Perf Globale",
                _fmt_pct(g_perf),
                subtitle=f"YTD : {_fmt_pct(y_perf)}",
                emoji="📈",
                tone="neutral" if g_perf is None or pd.isna(g_perf) else ("success" if float(g_perf) >= 0 else "alert"),
            )
            # ── KPI — ligne 2 ────────────────────────────────────────────────
            self._kpi_nb.set_content(
                "Positions", str(nb_pos),
                subtitle=f"{nb_acc} compte(s)",
                emoji="🎯", tone="neutral",
            )

            # ── Sous-métriques Dividendes / Intérêts / PnL ───────────────────
            # Calculées uniquement en mode live depuis income_df + snapshots_df
            div_details: list[tuple[str, str]] = []
            int_details: list[tuple[str, str]] = []
            pnl_details: list[tuple[str, str]] = []

            if not self._selected_date:
                _today = datetime.date.today()
                _date_12m = _today - datetime.timedelta(days=365)

                df_inc: pd.DataFrame | None = metrics.get("income_df")
                if df_inc is not None and not df_inc.empty and "date" in df_inc.columns:
                    # Normalise la colonne date en datetime pour le filtre
                    df_inc = df_inc.copy()
                    df_inc["_dt"] = pd.to_datetime(df_inc["date"], errors="coerce")

                    for (income_type, alltime_total, details_list) in [
                        ("DIVIDENDE", t_div, div_details),
                        ("INTERETS",  t_int, int_details),
                    ]:
                        sub = df_inc[df_inc["type"].str.upper() == income_type]
                        # All-time est déjà dans t_div / t_int ; on l'utilise comme valeur principale
                        # 12 derniers mois
                        m12 = sub[sub["_dt"] >= pd.Timestamp(_date_12m)]["amount_eur"].sum()
                        # Moyenne mensuelle sur les 12 derniers mois
                        avg_m = m12 / 12.0
                        details_list.extend([
                            ("12 derniers mois",     _fmt_eur(m12)),
                            ("Moy. / mois (12 m)",   _fmt_eur(avg_m)),
                        ])

                # PnL : variation sur 12 mois via les snapshots
                df_snap_m: pd.DataFrame | None = metrics.get("snapshots_df")
                if df_snap_m is not None and not df_snap_m.empty and "date" in df_snap_m.columns:
                    df_snap_m = df_snap_m.copy()
                    df_snap_m["_dt"] = pd.to_datetime(df_snap_m["date"], errors="coerce")
                    older = df_snap_m[df_snap_m["_dt"] <= pd.Timestamp(_date_12m)]
                    if not older.empty and total_val is not None:
                        val_12m_ago = float(older.iloc[-1]["bourse_holdings"])
                        pnl_delta_12m = total_val - val_12m_ago
                        sign = "+" if pnl_delta_12m >= 0 else ""
                        pnl_12m_pct = ((total_val / val_12m_ago) - 1.0) * 100.0 if val_12m_ago > 0 else None
                        pnl_details.extend([
                            ("Δ 12 derniers mois",  f"{sign}{_fmt_eur(pnl_delta_12m)}"),
                            ("Perf 12 m",           _fmt_pct(pnl_12m_pct)),
                        ])

            # Valeur principale des cartes de revenus = all-time
            income_fx_missing = bool(metrics.get("missing_income_fx"))
            div_value = "—" if income_fx_missing and (t_div is None or float(t_div or 0.0) == 0.0) else _fmt_eur(t_div)
            int_value = "—" if income_fx_missing and (t_int is None or float(t_int or 0.0) == 0.0) else _fmt_eur(t_int)
            pnl_value = "—" if total_pnl is None or pd.isna(total_pnl) else f"{'+' if float(total_pnl) >= 0 else ''}{_fmt_eur(total_pnl)}"
            self._kpi_div.set_content(
                "Dividendes (all time)", div_value,
                subtitle="FX incomplet" if income_fx_missing else None,
                emoji="💵", tone="success",
                details=div_details or None,
            )
            self._kpi_int.set_content(
                "Intérêts (all time)", int_value,
                subtitle="FX incomplet" if income_fx_missing else None,
                emoji="🏦", tone="success",
                details=int_details or None,
            )
            self._kpi_pnl.set_content(
                "PnL Latent",
                pnl_value,
                emoji="⚡",
                tone="neutral" if total_pnl is None or pd.isna(total_pnl) else ("success" if float(total_pnl) >= 0 else "alert"),
                details=pnl_details or None,
            )

            # ── KPI Effet change (FX) ─────────────────────────────────────────
            total_fx_pnl = fx_pnl_summary.get("total_fx_pnl")
            fx_by_ccy: dict = fx_pnl_summary.get("by_currency", {})
            missing_fx_breakdown = int(fx_pnl_summary.get("missing_breakdown_count", 0) or 0)
            if total_fx_pnl is None or (not fx_pnl_summary):
                self._kpi_fx_pnl.set_content(
                    "Effet change", "—",
                    subtitle="Non disponible en mode historique",
                    emoji="💱", tone="neutral",
                )
            else:
                fx_sign = "+" if float(total_fx_pnl) >= 0 else ""
                fx_value = f"{fx_sign}{_fmt_eur(total_fx_pnl)}"
                fx_details = [
                    (f"Impact {ccy}", f"{'+' if v >= 0 else ''}{_fmt_eur(v)}")
                    for ccy, v in sorted(fx_by_ccy.items())
                ]
                self._kpi_fx_pnl.set_content(
                    "Effet change",
                    fx_value,
                    subtitle="Calcul partiel" if missing_fx_breakdown > 0 else "Impact devise",
                    emoji="💱",
                    tone="neutral" if float(total_fx_pnl) == 0 else ("success" if float(total_fx_pnl) > 0 else "alert"),
                    details=fx_details or None,
                )

            # ── Table des positions (U5) ──────────────────────────────────────
            # On adapte les colonnes selon le mode
            if self._selected_date:
                display_cols = ["symbol", "quantity", "last_price", "currency", "fx_rate", "value", "valuation_status", "compte"]
                _LABELS = {**_COL_LABELS, "last_price": "Prix (Date)", "fx_rate": "Taux FX"}
            else:
                display_cols = ["symbol", "name", "asset_type", "quantity", "pru", "last_price",
                                "value", "pnl_latent", "valuation_status", "compte", "type"]
                _LABELS = _COL_LABELS

            display_cols = [c for c in display_cols if c in df_all.columns]
            if total_val is not None and float(total_val) > 0 and "value" in df_all.columns:
                df_all["poids_%"] = (df_all["value"] / total_val * 100.0).round(2)
                if "value" in display_cols:
                    idx = display_cols.index("value")
                    display_cols.insert(idx + 1, "poids_%")

            df_display = df_all[display_cols].copy()
            if "value" in df_display.columns:
                df_display = df_display.sort_values("value", ascending=False, na_position="last")
            df_display.rename(columns=_LABELS, inplace=True)

            pnl_col = _LABELS.get("pnl_latent", "PnL (€)")
            self._table_pos.set_dataframe(df_display)
            if not self._selected_date:
                self._table_pos.set_column_colors({
                pnl_col: lambda v: COLOR_SUCCESS if pd.notna(v) and safe_float(v) >= 0 else COLOR_ERROR
                })
            
            if not self._selected_date:
                # ── Graphe historique (U3) ──
                # metrics est déjà calculé plus haut dans le bloc live
                df_snap = metrics.get("snapshots_df")
                if df_snap is not None and not df_snap.empty and "date" in df_snap.columns:
                    fig_hist = go.Figure()

                    # Courbe principale
                    fig_hist.add_trace(go.Scatter(
                        x=df_snap["date"], y=df_snap["bourse_holdings"],
                        mode="lines", name="Portefeuille",
                        line=dict(color="#4ade80", width=2),
                        fill="tozeroy", fillcolor="rgba(74,222,128,0.07)",
                        hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:,.0f} €<extra>Portefeuille</extra>",
                    ))

                    # Point live mis en évidence
                    last_row = df_snap.iloc[-1]
                    live_val = float(last_row["bourse_holdings"])
                    fig_hist.add_trace(go.Scatter(
                        x=[last_row["date"]], y=[live_val],
                        mode="markers", name="Valeur actuelle",
                        marker=dict(color="#4ade80", size=10, symbol="circle",
                                    line=dict(color="#ffffff", width=2)),
                        hovertemplate=f"<b>Aujourd'hui</b><br>{_fmt_eur(live_val)}<extra></extra>",
                        showlegend=False,
                    ))

                    # Courbe montant investi cumulé
                    df_invested = compute_invested_series(self._conn, self._person_id)
                    if not df_invested.empty:
                        fig_hist.add_trace(go.Scatter(
                            x=df_invested["date"], y=df_invested["invested_eur"],
                            mode="lines", name="Montant investi",
                            line=dict(color="#94a3b8", width=1.5, dash="dot"),
                            hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:,.0f} €<extra>Investi</extra>",
                        ))

                    fig_hist.update_layout(
                        **plotly_time_series_layout(
                            margin=dict(l=10, r=10, t=40, b=10),
                            # xaxis passé ici pour être fusionné avec le xaxis de
                            # plotly_time_series_layout (rangeselector, rangeslider…)
                            # plutôt qu'en argument séparé de update_layout() ce qui
                            # provoquerait un TypeError "multiple values for keyword 'xaxis'".
                            xaxis=dict(
                                title="", showgrid=True, gridcolor="#1e2538", gridwidth=1,
                                tickformat="%b %Y",
                            ),
                        ),
                        yaxis=dict(
                            title="", showgrid=True, gridcolor="#1e2538", gridwidth=1,
                            tickformat=",.0f", ticksuffix=" €",
                        ),
                        legend=dict(
                            orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1, font=dict(size=11),
                        ),
                        hovermode="x unified",
                    )
                    self._chart_history.set_figure(fig_hist)
                else:
                    self._chart_history.clear_figure()

                # ── Graphe revenus (U4) ──
                df_inc = metrics.get("income_df")
                if df_inc is not None and not df_inc.empty:
                    df_inc_grp = df_inc.groupby(["month", "type"], as_index=False)["amount_eur"].sum()
                    fig_inc = px.bar(
                        df_inc_grp, x="month", y="amount_eur", color="type",
                        barmode="stack", template="plotly_dark",
                        color_discrete_map=_INCOME_COLORS,
                        labels={"amount_eur": "", "month": "", "type": "Type"},
                    )
                    fig_inc.update_traces(
                        hovertemplate="<b>%{x}</b><br>%{y:,.2f} €<extra>%{fullData.name}</extra>"
                    )
                    fig_inc.update_layout(
                        **plotly_layout(margin=dict(l=10, r=10, t=36, b=10)),
                        xaxis=dict(showgrid=False, tickangle=-45),
                        yaxis=dict(
                            showgrid=True, gridcolor="#1e2538",
                            tickformat=",.0f", ticksuffix=" €",
                        ),
                        legend=dict(
                            orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1, font=dict(size=11),
                        ),
                    )
                    self._chart_income.set_figure(fig_inc)
                else:
                    self._chart_income.clear_figure()
            else:
                # Masquer les graphes en mode historique pour éviter la confusion
                self._chart_history.clear_figure()
                self._chart_income.clear_figure()

            # ── Pie chart répartition (U6) ────────────────────────────────────
            if "value" in df_all.columns and "symbol" in df_all.columns:
                df_pie = df_all[df_all["value"] > 0][["symbol", "value"]].copy()
                if not df_pie.empty:
                    fig_pie = px.pie(
                        df_pie, names="symbol", values="value", hole=0.42,
                        template="plotly_dark",
                        color_discrete_sequence=px.colors.qualitative.Set3,
                    )
                    fig_pie.update_traces(
                        textinfo="label+percent",
                        textposition="outside",
                        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>%{percent}<extra></extra>",
                        pull=[0.04] + [0.0] * (len(df_pie) - 1),
                    )
                    fig_pie.update_layout(
                        **plotly_layout(margin=dict(l=24, r=24, t=24, b=24)),
                        showlegend=False,
                    )
                    self._chart_alloc.set_figure(fig_pie)
                else:
                    self._chart_alloc.clear_figure()
            else:
                self._chart_alloc.clear_figure()

            # ── Diagnostic Tickers ───────────────────────────────────────────
            df_diag = get_tickers_diagnostic_df(self._conn, self._person_id)
            if df_diag is not None and not df_diag.empty:
                self._table_diag.set_dataframe(df_diag)
                # Coloration du statut
                self._table_diag.set_column_colors({
                    "Statut": lambda v: COLOR_SUCCESS if "✅" in str(v) else (
                        "#f97316" if "⚠️" in str(v) else COLOR_ERROR
                    )
                })
            else:
                self._table_diag.set_dataframe(pd.DataFrame([{"Info": "Aucune position pour le diagnostic."}]))

            loaded_ok = True

        except Exception as e:
            logger.error("BourseGlobalPanel._load_data error: %s", e, exc_info=True)
        finally:
            # ── 2. Désactivation des Skeletons ──────────────────────────────
            for w in all_widgets:
                if hasattr(w, "set_loading"):
                    w.set_loading(False)
            
            self._chart_history.set_loading(False)
            self._chart_income.set_loading(False)
            self._chart_alloc.set_loading(False)

            self._overlay.stop()
            if loaded_ok:
                self._last_load_key = load_key
                self._last_load_monotonic = time.monotonic()

    # ── Analytics — construction et chargement lazy ─────────────────────────

    def _build_analytics_section(
        self, parent_layout: QVBoxLayout, title: str, section_key: str
    ) -> CollapsibleSection:
        """Crée une section accordéon et connecte le signal d'ouverture."""
        section = CollapsibleSection(title)
        content_layout = QVBoxLayout()

        # Placeholder "Chargement…"
        placeholder = QLabel("⏳ Ouvrez la section pour charger les données…")
        placeholder.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 8px;")
        placeholder.setObjectName(f"placeholder_{section_key}")
        content_layout.addWidget(placeholder)

        section.set_content_layout(content_layout)
        section.toggled.connect(lambda opened, k=section_key: self._on_analytics_toggled(k, opened))
        parent_layout.addWidget(section)
        return section

    def _on_analytics_toggled(self, section_key: str, opened: bool) -> None:
        """Charge les données la première fois qu'une section est ouverte."""
        if not opened:
            return
        if self._analytics_loaded.get(section_key, False):
            return

        self._analytics_loaded[section_key] = True

        loaders = {
            "risk_return": self._load_risk_return_section,
            "correlation": self._load_correlation_section,
            "risk_contribution": self._load_risk_contribution_section,
            "var_es": self._load_var_es_section,
            "efficient_frontier": self._load_efficient_frontier_section,
            "benchmark": self._load_benchmark_section,
        }
        loader = loaders.get(section_key)
        if loader:
            try:
                loader()
            except Exception as e:
                logger.error("Erreur chargement analytics '%s': %s", section_key, e, exc_info=True)

    def _get_section_content_layout(self, section: CollapsibleSection) -> QVBoxLayout:
        """Retourne le layout de contenu d'une section et supprime le placeholder."""
        content = section._content_widget
        layout = content.layout()
        # Supprimer le placeholder
        for i in reversed(range(layout.count())):
            widget = layout.itemAt(i).widget()
            if widget and widget.objectName().startswith("placeholder_"):
                widget.deleteLater()
        return layout

    @staticmethod
    def _analytics_error_label(message: str) -> QLabel:
        """Crée un label d'erreur/état vide pour les sections analytics."""
        lbl = QLabel(f"⚠️ {message}")
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
        lbl.setWordWrap(True)
        return lbl

    @staticmethod
    def _analytics_kpi_row(items: list[tuple[str, str]]) -> QHBoxLayout:
        """Crée une ligne de KPIs simples (label : valeur)."""
        row = QHBoxLayout()
        row.setSpacing(20)
        for label_text, value_text in items:
            pair = QVBoxLayout()
            pair.setSpacing(2)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            val = QLabel(str(value_text))
            val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
            pair.addWidget(lbl)
            pair.addWidget(val)
            row.addLayout(pair)
        row.addStretch()
        return row

    @staticmethod
    def _clear_layout(layout: QVBoxLayout | QHBoxLayout) -> None:
        """Nettoie récursivement un layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                BourseGlobalPanel._clear_layout(child_layout)  # type: ignore[arg-type]

    def _ensure_frontier_controls(self, parent_layout: QVBoxLayout) -> None:
        """Construit les contrôles Frontier (preset + avancé) une seule fois."""
        if self._frontier_controls_ready:
            return

        from services.bourse_advanced_analytics import get_efficient_frontier_presets_payload

        presets_payload = get_efficient_frontier_presets_payload()
        self._frontier_presets = presets_payload.get("presets", []) or []

        controls_box = QFrame()
        controls_box.setStyleSheet(
            f"background: {BG_CARD}; border: 1px solid {BORDER_SUBTLE}; border-radius: 8px; padding: 8px;"
        )
        controls_layout = QVBoxLayout(controls_box)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(8)

        row_mode = QHBoxLayout()
        row_mode.setSpacing(8)
        lbl_mode = QLabel("Mode de diversification")
        lbl_mode.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        row_mode.addWidget(lbl_mode)

        self._frontier_preset_combo = QComboBox()
        self._frontier_preset_combo.setStyleSheet(STYLE_INPUT_FOCUS)
        self._frontier_preset_combo.setMinimumWidth(220)
        for preset in self._frontier_presets:
            self._frontier_preset_combo.addItem(str(preset.get("label", "")), preset.get("key"))
        row_mode.addWidget(self._frontier_preset_combo)

        self._btn_frontier_recompute = QPushButton("↻ Recalculer")
        self._btn_frontier_recompute.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_frontier_recompute.clicked.connect(self._on_frontier_recompute_clicked)
        row_mode.addWidget(self._btn_frontier_recompute)
        row_mode.addStretch()
        controls_layout.addLayout(row_mode)

        self._lbl_frontier_preset_help = QLabel("")
        self._lbl_frontier_preset_help.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._lbl_frontier_preset_help.setWordWrap(True)
        controls_layout.addWidget(self._lbl_frontier_preset_help)

        self._btn_frontier_advanced = QPushButton("Paramètres avancés ▸")
        self._btn_frontier_advanced.setCheckable(True)
        self._btn_frontier_advanced.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_frontier_advanced.toggled.connect(self._on_frontier_advanced_toggled)
        controls_layout.addWidget(self._btn_frontier_advanced)

        self._frontier_advanced_box = QFrame()
        self._frontier_advanced_box.setVisible(False)
        self._frontier_advanced_box.setStyleSheet(
            f"background: transparent; border: 1px dashed {BORDER_SUBTLE}; border-radius: 6px; padding: 8px;"
        )
        adv_layout = QVBoxLayout(self._frontier_advanced_box)
        adv_layout.setContentsMargins(8, 8, 8, 8)
        adv_layout.setSpacing(6)

        row_a = QHBoxLayout()
        row_a.setSpacing(8)
        lbl_max_w = QLabel("Poids max / actif (%)")
        lbl_max_w.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._spin_frontier_max_weight = QDoubleSpinBox()
        self._spin_frontier_max_weight.setRange(1.0, 100.0)
        self._spin_frontier_max_weight.setDecimals(1)
        self._spin_frontier_max_weight.setSuffix(" %")
        self._spin_frontier_max_weight.setSingleStep(1.0)
        self._spin_frontier_max_weight.setStyleSheet(STYLE_INPUT)
        self._spin_frontier_max_weight.setFixedWidth(120)
        row_a.addWidget(lbl_max_w)
        row_a.addWidget(self._spin_frontier_max_weight)

        lbl_min_assets = QLabel("Actifs min")
        lbl_min_assets.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._spin_frontier_min_assets = QSpinBox()
        self._spin_frontier_min_assets.setRange(2, 30)
        self._spin_frontier_min_assets.setStyleSheet(STYLE_INPUT)
        self._spin_frontier_min_assets.setFixedWidth(80)
        row_a.addWidget(lbl_min_assets)
        row_a.addWidget(self._spin_frontier_min_assets)
        row_a.addStretch()
        adv_layout.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.setSpacing(8)
        lbl_min_line = QLabel("Poids min ligne active (%)")
        lbl_min_line.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._spin_frontier_min_line = QDoubleSpinBox()
        self._spin_frontier_min_line.setRange(0.0, 20.0)
        self._spin_frontier_min_line.setDecimals(1)
        self._spin_frontier_min_line.setSuffix(" %")
        self._spin_frontier_min_line.setSingleStep(0.5)
        self._spin_frontier_min_line.setStyleSheet(STYLE_INPUT)
        self._spin_frontier_min_line.setFixedWidth(120)
        row_b.addWidget(lbl_min_line)
        row_b.addWidget(self._spin_frontier_min_line)

        lbl_max_assets = QLabel("Actifs max (0 = sans limite)")
        lbl_max_assets.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self._spin_frontier_max_assets = QSpinBox()
        self._spin_frontier_max_assets.setRange(0, 30)
        self._spin_frontier_max_assets.setStyleSheet(STYLE_INPUT)
        self._spin_frontier_max_assets.setFixedWidth(80)
        row_b.addWidget(lbl_max_assets)
        row_b.addWidget(self._spin_frontier_max_assets)
        row_b.addStretch()
        adv_layout.addLayout(row_b)

        row_c = QHBoxLayout()
        row_c.setSpacing(8)
        self._chk_frontier_allow_residual = QCheckBox("Autoriser des lignes résiduelles très faibles")
        self._chk_frontier_allow_residual.setChecked(True)
        self._chk_frontier_allow_residual.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        row_c.addWidget(self._chk_frontier_allow_residual)
        row_c.addStretch()
        adv_layout.addLayout(row_c)

        controls_layout.addWidget(self._frontier_advanced_box)

        help_label = QLabel(
            "ℹ️ Sans contraintes, l'optimisation peut produire des portefeuilles très concentrés. "
            "Utilisez les modes de diversification pour obtenir des allocations plus investissables."
        )
        help_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        help_label.setWordWrap(True)
        controls_layout.addWidget(help_label)

        parent_layout.addWidget(controls_box)

        self._frontier_result_container = QFrame()
        self._frontier_result_layout = QVBoxLayout(self._frontier_result_container)
        self._frontier_result_layout.setContentsMargins(0, 0, 0, 0)
        self._frontier_result_layout.setSpacing(10)
        parent_layout.addWidget(self._frontier_result_container)

        self._frontier_preset_combo.currentIndexChanged.connect(self._on_frontier_preset_changed)
        if self._frontier_presets:
            self._frontier_preset_combo.blockSignals(True)
            self._frontier_preset_combo.setCurrentIndex(0)
            self._frontier_preset_combo.blockSignals(False)
            self._apply_frontier_preset_values(str(self._frontier_preset_combo.currentData()))
        self._frontier_controls_ready = True

    def _on_frontier_advanced_toggled(self, opened: bool) -> None:
        self._frontier_advanced_box.setVisible(opened)
        self._btn_frontier_advanced.setText("Paramètres avancés ▾" if opened else "Paramètres avancés ▸")

    def _on_frontier_preset_changed(self, *_args) -> None:
        preset_key = str(self._frontier_preset_combo.currentData() or "free")
        self._apply_frontier_preset_values(preset_key)
        self._refresh_efficient_frontier_results()

    def _on_frontier_recompute_clicked(self, *_args) -> None:
        self._refresh_efficient_frontier_results()

    def _apply_frontier_preset_values(self, preset_key: str) -> None:
        preset = next((p for p in self._frontier_presets if str(p.get("key")) == preset_key), None)
        if not preset:
            return
        constraints = preset.get("constraints", {}) or {}
        self._lbl_frontier_preset_help.setText(str(preset.get("description", "")))

        self._spin_frontier_max_weight.setValue(
            float(constraints.get("max_weight_per_asset", 1.0)) * 100.0
        )
        self._spin_frontier_min_assets.setValue(int(constraints.get("min_assets", 2)))
        self._spin_frontier_min_line.setValue(
            float(constraints.get("min_active_weight", 0.0)) * 100.0
        )
        max_assets = constraints.get("max_assets")
        self._spin_frontier_max_assets.setValue(int(max_assets) if max_assets else 0)
        self._chk_frontier_allow_residual.setChecked(bool(constraints.get("allow_tiny_residuals", True)))

    def _collect_frontier_settings(self) -> dict:
        max_assets = int(self._spin_frontier_max_assets.value())
        return {
            "preset": str(self._frontier_preset_combo.currentData() or "free"),
            "advanced": {
                "max_weight_per_asset": float(self._spin_frontier_max_weight.value()) / 100.0,
                "min_assets": int(self._spin_frontier_min_assets.value()),
                "min_active_weight": float(self._spin_frontier_min_line.value()) / 100.0,
                "max_assets": max_assets if max_assets > 0 else None,
                "allow_tiny_residuals": bool(self._chk_frontier_allow_residual.isChecked()),
                "allow_short": False,
                "n_points": 30,
            },
        }

    def _refresh_efficient_frontier_results(self) -> None:
        if self._frontier_result_layout is None:
            return
        self._clear_layout(self._frontier_result_layout)

        from services.bourse_advanced_analytics import get_efficient_frontier_payload

        settings = self._collect_frontier_settings()
        payload = get_efficient_frontier_payload(
            self._conn,
            self._person_id,
            settings=settings,
        )
        if "error" in payload:
            self._frontier_result_layout.addWidget(self._analytics_error_label(payload["error"]))
            return

        frontier = payload.get("frontier_points", [])
        current = payload.get("current_portfolio", {})
        min_var = payload.get("min_variance", {})
        max_sharpe = payload.get("max_sharpe", {})
        max_sharpe_div = max_sharpe.get("diversification", {}) or {}

        self._frontier_result_layout.addLayout(self._analytics_kpi_row([
            (
                "Portefeuille actuel",
                f"Vol {float(current.get('vol', 0.0)):.1f}% / Ret {float(current.get('ret', 0.0)):.1f}%",
            ),
            (
                "Variance minimale",
                f"Vol {float(min_var.get('vol', 0.0)):.1f}% / Ret {float(min_var.get('ret', 0.0)):.1f}%",
            ),
            (
                "Portefeuille optimisé (Sharpe)",
                f"Vol {float(max_sharpe.get('vol', 0.0)):.1f}% / Ret {float(max_sharpe.get('ret', 0.0)):.1f}% / S {float(max_sharpe.get('sharpe', 0.0)):.2f}",
            ),
        ]))

        self._frontier_result_layout.addLayout(self._analytics_kpi_row([
            ("Actifs retenus", str(int(max_sharpe_div.get("n_assets", 0)))),
            ("Plus grosse ligne", f"{float(max_sharpe_div.get('largest_position_pct', 0.0)):.1f}%"),
            ("Top 3 cumulé", f"{float(max_sharpe_div.get('top3_weight_pct', 0.0)):.1f}%"),
            ("HHI", f"{float(max_sharpe_div.get('hhi', 0.0)):.4f}"),
            ("Score diversification", f"{float(max_sharpe_div.get('diversification_score', 0.0)):.1f}/100"),
        ]))

        chart_frontier = PlotlyView(min_height=380)
        fig = go.Figure()

        if frontier:
            frontier_vol = [p["vol"] for p in frontier]
            frontier_ret = [p["ret"] for p in frontier]
            fig.add_trace(go.Scatter(
                x=frontier_vol, y=frontier_ret,
                mode="lines", name="Frontière efficiente",
                line=dict(color="#60a5fa", width=2),
                hovertemplate="Vol: %{x:.1f}%<br>Ret: %{y:.1f}%<extra>Frontière</extra>",
            ))

        fig.add_trace(go.Scatter(
            x=[float(current.get("vol", 0.0))], y=[float(current.get("ret", 0.0))],
            mode="markers", name="Portefeuille actuel",
            marker=dict(color="#f59e0b", size=14, symbol="star", line=dict(color="white", width=2)),
            hovertemplate=(
                f"<b>Actuel</b><br>Vol: {float(current.get('vol', 0.0)):.1f}%"
                f"<br>Ret: {float(current.get('ret', 0.0)):.1f}%<extra></extra>"
            ),
        ))
        fig.add_trace(go.Scatter(
            x=[float(min_var.get("vol", 0.0))], y=[float(min_var.get("ret", 0.0))],
            mode="markers", name="Variance minimale",
            marker=dict(color="#22c55e", size=12, symbol="diamond", line=dict(color="white", width=2)),
            hovertemplate=(
                f"<b>Min Variance</b><br>Vol: {float(min_var.get('vol', 0.0)):.1f}%"
                f"<br>Ret: {float(min_var.get('ret', 0.0)):.1f}%<extra></extra>"
            ),
        ))
        fig.add_trace(go.Scatter(
            x=[float(max_sharpe.get("vol", 0.0))], y=[float(max_sharpe.get("ret", 0.0))],
            mode="markers", name="Sharpe maximal",
            marker=dict(color="#ef4444", size=12, symbol="triangle-up", line=dict(color="white", width=2)),
            hovertemplate=(
                f"<b>Max Sharpe</b><br>Vol: {float(max_sharpe.get('vol', 0.0)):.1f}%"
                f"<br>Ret: {float(max_sharpe.get('ret', 0.0)):.1f}%<extra></extra>"
            ),
        ))

        fig.update_layout(
            **plotly_layout(margin=dict(l=50, r=20, t=30, b=50)),
            xaxis=dict(title="Volatilité annualisée (%)", showgrid=True, gridcolor="#1e2538"),
            yaxis=dict(title="Rendement annualisé (%)", showgrid=True, gridcolor="#1e2538"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        chart_frontier.set_figure(fig)
        self._frontier_result_layout.addWidget(chart_frontier)

        weights_text_parts = []
        for label, data in [("Min Var", min_var), ("Max Sharpe", max_sharpe)]:
            weights = data.get("weights", {}) or {}
            top_weights = sorted(weights.items(), key=lambda x: -float(x[1]))[:6]
            parts = ", ".join([f"{t}: {float(w):.0f}%" for t, w in top_weights])
            weights_text_parts.append(f"{label} → {parts}" if parts else f"{label} → N/A")
        weights_info = QLabel("🏆 " + " | ".join(weights_text_parts))
        weights_info.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        weights_info.setWordWrap(True)
        self._frontier_result_layout.addWidget(weights_info)

        constraints = payload.get("constraints_applied", {}) or {}
        constraints_info = QLabel(
            "Contraintes appliquées : "
            f"max {float(constraints.get('max_weight_per_asset_pct', 100.0)):.1f}% par actif, "
            f"min {int(constraints.get('min_assets', 2))} actifs, "
            f"min ligne {float(constraints.get('min_active_weight_pct', 0.0)):.1f}%, "
            f"max actifs {int(constraints.get('max_assets', len(payload.get('tickers', []))))}."
        )
        constraints_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        constraints_info.setWordWrap(True)
        self._frontier_result_layout.addWidget(constraints_info)

        warnings = payload.get("warnings", []) or []
        if warnings:
            warn_label = QLabel("⚠️ " + " ".join(str(w) for w in warnings))
            warn_label.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 10px;")
            warn_label.setWordWrap(True)
            self._frontier_result_layout.addWidget(warn_label)

        info = QLabel(
            "ℹ️ Un portefeuille mathématiquement optimal peut être peu diversifié. "
            "Ces contraintes rendent la solution plus investissable et pédagogique."
        )
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        info.setWordWrap(True)
        self._frontier_result_layout.addWidget(info)

    # ── 1. Rendement & Risque ─────────────────────────────────────────────

    def _load_risk_return_section(self) -> None:
        """Charge les KPIs rendement/risque dans la section accordéon."""
        from services.bourse_advanced_analytics import get_risk_return_payload

        payload = get_risk_return_payload(self._conn, self._person_id)
        layout = self._get_section_content_layout(self._section_risk)

        if "error" in payload:
            layout.addWidget(self._analytics_error_label(payload["error"]))
            return

        # Ligne 1 — Rendement
        cagr = payload.get("cagr_pct")
        cagr_text = f"{cagr:+.2f} %" if cagr is not None else "N/A"
        mean_ret = payload.get("mean_return_ann_pct", 0)
        layout.addLayout(self._analytics_kpi_row([
            ("CAGR", cagr_text),
            ("Rendement moy. annualisé", f"{mean_ret:+.2f} %"),
            ("Points de données", str(payload.get("data_points", 0))),
            ("Période", f"{payload.get('period_start', '?')} → {payload.get('period_end', '?')}"),
        ]))

        # Ligne 2 — Risque
        vol = payload.get("volatility_ann_pct", 0)
        sharpe = payload.get("sharpe")
        sharpe_text = f"{sharpe:.3f}" if sharpe is not None else "N/A"
        beta = payload.get("beta")
        beta_text = f"{beta:.3f}" if beta is not None else "N/A (benchmark absent)"
        layout.addLayout(self._analytics_kpi_row([
            ("Volatilité annualisée", f"{vol:.2f} %"),
            ("Ratio de Sharpe", sharpe_text),
            ("Beta vs MSCI World", beta_text),
        ]))

        # Ligne 3 — Drawdown
        dd = payload.get("max_drawdown_pct", 0)
        dd_start = payload.get("drawdown_start", "—")
        dd_end = payload.get("drawdown_end", "—")
        recovery = payload.get("recovery_days")
        recovery_text = f"{recovery} jours" if recovery is not None else "Non récupéré"
        layout.addLayout(self._analytics_kpi_row([
            ("Max Drawdown", f"{dd:.2f} %"),
            ("Drawdown", f"{dd_start} → {dd_end}"),
            ("Récupération", recovery_text),
        ]))

        # Info méthodologique
        info = QLabel("ℹ️ Sharpe calculé avec Rf=3%. Volatilité = σ weekly × √52. Beta vs URTH (MSCI World).")
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; padding-top: 6px;")
        info.setWordWrap(True)
        layout.addWidget(info)

    # ── 2. Corrélations & Diversification ─────────────────────────────────

    def _load_correlation_section(self) -> None:
        """Charge la heatmap de corrélation dans la section accordéon."""
        from services.bourse_advanced_analytics import get_correlation_payload

        payload = get_correlation_payload(self._conn, self._person_id)
        layout = self._get_section_content_layout(self._section_corr)

        if "error" in payload:
            layout.addWidget(self._analytics_error_label(payload["error"]))
            return

        corr_matrix = payload["matrix"]
        tickers = payload["tickers"]
        avg_corr = payload.get("avg_correlation", 0)
        div_ratio = payload.get("diversification_ratio")

        # KPIs
        div_text = f"{div_ratio:.2f}" if div_ratio is not None else "N/A"
        layout.addLayout(self._analytics_kpi_row([
            ("Corrélation moyenne", f"{avg_corr:.3f}"),
            ("Ratio de diversification", div_text),
            ("Actifs analysés", str(payload.get("n_assets", 0))),
        ]))

        # Top paires corrélées
        top_pairs = payload.get("top_correlated_pairs", [])
        if top_pairs:
            pairs_text = " · ".join([f"{a}/{b}: {c:.2f}" for a, b, c in top_pairs[:5]])
            lbl_pairs = QLabel(f"🔗 Top corrélations : {pairs_text}")
            lbl_pairs.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; padding: 4px 0;")
            lbl_pairs.setWordWrap(True)
            layout.addWidget(lbl_pairs)

        # Heatmap Plotly
        chart_corr = PlotlyView(min_height=350)
        fig = go.Figure(data=go.Heatmap(
            z=corr_matrix.values,
            x=tickers,
            y=tickers,
            colorscale="RdBu_r",
            zmin=-1, zmax=1,
            text=np.round(corr_matrix.values, 2),
            texttemplate="%{text}",
            textfont=dict(size=10),
            hovertemplate="%{x} / %{y}<br>Corrélation: %{z:.3f}<extra></extra>",
        ))
        fig.update_layout(
            **plotly_layout(margin=dict(l=60, r=20, t=20, b=60)),
            xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
            yaxis=dict(tickfont=dict(size=10)),
        )
        chart_corr.set_figure(fig)
        layout.addWidget(chart_corr)

        info = QLabel("ℹ️ Corrélation de Pearson sur rendements log-weekly. Ratio diversification > 1 = bonne diversification.")
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

    # ── 3. Contribution au Risque ─────────────────────────────────────────

    def _load_risk_contribution_section(self) -> None:
        """Charge la contribution au risque de chaque actif."""
        from services.bourse_advanced_analytics import get_risk_contribution_payload

        payload = get_risk_contribution_payload(self._conn, self._person_id)
        layout = self._get_section_content_layout(self._section_contrib)

        if "error" in payload:
            layout.addWidget(self._analytics_error_label(payload["error"]))
            return

        contrib_df = payload["contributions"]
        vol_ann = payload.get("portfolio_vol_ann_pct", 0)

        layout.addLayout(self._analytics_kpi_row([
            ("Volatilité portefeuille (ann.)", f"{vol_ann:.2f} %"),
        ]))

        # Bar chart horizontal — contribution au risque vs poids
        chart_contrib = PlotlyView(min_height=max(250, len(contrib_df) * 28))
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=contrib_df["ticker"], x=contrib_df["weight_pct"],
            name="Poids (%)", orientation="h",
            marker_color="#60a5fa",
            hovertemplate="%{y}<br>Poids: %{x:.1f}%<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            y=contrib_df["ticker"], x=contrib_df["risk_contrib_pct"],
            name="Contribution risque (%)", orientation="h",
            marker_color="#f87171",
            hovertemplate="%{y}<br>Risque: %{x:.1f}%<extra></extra>",
        ))
        fig.update_layout(
            **plotly_layout(margin=dict(l=80, r=20, t=30, b=10)),
            barmode="group",
            yaxis=dict(autorange="reversed"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        chart_contrib.set_figure(fig)
        layout.addWidget(chart_contrib)

        info = QLabel(
            "ℹ️ La contribution au risque montre qu'un actif peut représenter "
            "peu en poids mais beaucoup en risque (et inversement)."
        )
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

    # ── 4. VaR & Expected Shortfall ───────────────────────────────────────

    def _load_var_es_section(self) -> None:
        """Charge les métriques VaR et ES."""
        from services.bourse_advanced_analytics import get_var_es_payload

        payload = get_var_es_payload(self._conn, self._person_id)
        layout = self._get_section_content_layout(self._section_var)

        if "error" in payload:
            layout.addWidget(self._analytics_error_label(payload["error"]))
            return

        ptf_val = payload.get("portfolio_value_eur", 0)
        horizon = payload.get("horizon", "1 semaine")

        # Ligne 1 — VaR
        layout.addLayout(self._analytics_kpi_row([
            (f"VaR 95% ({horizon})", f"{payload['var_95_pct']:.2f} %"),
            (f"VaR 99% ({horizon})", f"{payload['var_99_pct']:.2f} %"),
            ("VaR 95% (EUR)", f"{payload['var_95_eur']:,.0f} €"),
            ("VaR 99% (EUR)", f"{payload['var_99_eur']:,.0f} €"),
        ]))

        # Ligne 2 — ES / CVaR
        layout.addLayout(self._analytics_kpi_row([
            (f"ES/CVaR 95% ({horizon})", f"{payload['es_95_pct']:.2f} %"),
            (f"ES/CVaR 99% ({horizon})", f"{payload['es_99_pct']:.2f} %"),
        ]))

        # Ligne 3 — Paramétrique
        layout.addLayout(self._analytics_kpi_row([
            ("VaR 95% (param.)", f"{payload.get('var_95_param_pct', 0):.2f} %"),
            ("VaR 99% (param.)", f"{payload.get('var_99_param_pct', 0):.2f} %"),
            ("Observations", str(payload.get("n_observations", 0))),
        ]))

        info = QLabel(
            f"ℹ️ Méthode primaire : historique (percentile des rendements observés). "
            f"Paramétrique : hypothèse de distribution normale. "
            f"Horizon : {horizon}. Valeur portefeuille : {ptf_val:,.0f} €."
        )
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

    # ── 5. Frontière Efficiente ────────────────────────────────────────────

    def _load_efficient_frontier_section(self) -> None:
        """Charge la frontière efficiente (preset + paramètres avancés)."""
        layout = self._get_section_content_layout(self._section_frontier)
        self._ensure_frontier_controls(layout)
        self._refresh_efficient_frontier_results()

    # ── 6. Comparaison Benchmark ──────────────────────────────────────────

    def _load_benchmark_section(self) -> None:
        """Charge la comparaison avec le benchmark."""
        from services.bourse_advanced_analytics import get_benchmark_comparison_payload

        payload = get_benchmark_comparison_payload(self._conn, self._person_id)
        layout = self._get_section_content_layout(self._section_benchmark)

        if "error" in payload:
            layout.addWidget(self._analytics_error_label(payload["error"]))
            return

        bench_sym = payload.get("benchmark_symbol", "URTH")

        # KPIs comparatifs
        ptf_ret = payload.get("portfolio_return_ann_pct", 0)
        bench_ret = payload.get("benchmark_return_ann_pct", 0)
        ptf_vol = payload.get("portfolio_vol_ann_pct", 0)
        bench_vol = payload.get("benchmark_vol_ann_pct", 0)
        alpha = payload.get("alpha_pct", 0)
        te = payload.get("tracking_error_pct", 0)

        layout.addLayout(self._analytics_kpi_row([
            ("Rendement portefeuille", f"{ptf_ret:+.2f} %/an"),
            (f"Rendement {bench_sym}", f"{bench_ret:+.2f} %/an"),
            ("Alpha", f"{alpha:+.2f} %"),
        ]))
        layout.addLayout(self._analytics_kpi_row([
            ("Volatilité portefeuille", f"{ptf_vol:.2f} %"),
            (f"Volatilité {bench_sym}", f"{bench_vol:.2f} %"),
            ("Tracking Error", f"{te:.2f} %"),
            ("Semaines comparées", str(payload.get("n_weeks", 0))),
        ]))

        # Line chart normalisé base 100
        norm_series = payload.get("series")
        if norm_series is not None and not norm_series.empty:
            chart_bench = PlotlyView(min_height=320)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=norm_series["date"], y=norm_series["portfolio_norm"],
                mode="lines", name="Portefeuille",
                line=dict(color="#4ade80", width=2),
                hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.1f}<extra>Portefeuille</extra>",
            ))
            fig.add_trace(go.Scatter(
                x=norm_series["date"], y=norm_series["benchmark_norm"],
                mode="lines", name=bench_sym,
                line=dict(color="#60a5fa", width=2, dash="dot"),
                hovertemplate="<b>%{x|%d %b %Y}</b><br>%{y:.1f}<extra>" + bench_sym + "</extra>",
            ))
            # Ligne base 100
            fig.add_hline(y=100, line_dash="dash", line_color="#475569", line_width=1)
            fig.update_layout(
                **plotly_time_series_layout(margin=dict(l=10, r=10, t=30, b=10)),
                yaxis=dict(title="Base 100", showgrid=True, gridcolor="#1e2538"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified",
            )
            chart_bench.set_figure(fig)
            layout.addWidget(chart_bench)

        info = QLabel(
            f"ℹ️ Comparaison vs {bench_sym} (MSCI World). "
            f"Performance normalisée base 100. Alpha = excès de rendement annualisé."
        )
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)


