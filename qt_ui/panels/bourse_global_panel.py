"""
Panel Bourse Global — remplace ui/bourse_global_overview.py
"""
import logging
import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QDateEdit,
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QDate

from qt_ui.widgets import PlotlyView, DataTableWidget, KpiCard, LoadingOverlay
from qt_ui.theme import (
    BG_PRIMARY, BORDER_SUBTLE, TEXT_SECONDARY, TEXT_MUTED,
    STYLE_BTN_PRIMARY, STYLE_TITLE_XL, STYLE_SECTION,
    STYLE_STATUS, COLOR_SUCCESS, COLOR_ERROR,
    plotly_layout, plotly_time_series_layout,
)

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
    "compte":     "Compte",
    "type":       "Type",
}

# ── Couleurs du graphe revenus ────────────────────────────────────────────────
_INCOME_COLORS = {
    "DIVIDENDE": "#4ade80",
    "INTERETS":  "#60a5fa",
}


def _fmt_eur(value: float, decimals: int = 0) -> str:
    """Formate un montant en € avec espace fine comme séparateur de milliers."""
    fmt = f"{value:,.{decimals}f}".replace(",", "\u202f")
    return f"{fmt} €"


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
            from services.db import get_conn

            with get_conn() as local_conn:
                df_acc = repo.list_accounts(local_conn, person_id=self._person_id)
                if df_acc is None or df_acc.empty:
                    self.finished.emit("Aucun compte bourse.")
                    return

                bourse_types = {"PEA", "CTO", "CRYPTO"}
                df_b = df_acc[df_acc["account_type"].astype(str).str.upper().isin(bourse_types)]
                n_ok, n_fail = 0, 0
                for _, row in df_b.iterrows():
                    account_id = int(row["id"])
                    acc_ccy = str(row.get("currency") or "EUR").upper()
                    asset_ids = repo.list_account_asset_ids(local_conn, account_id=account_id)
                    for aid in asset_ids:
                        a = local_conn.execute("SELECT symbol FROM assets WHERE id = ?", (aid,)).fetchone()
                        if not a:
                            continue
                        sym = a[0] if not hasattr(a, '__getitem__') else a["symbol"]
                        px_val, ccy = pricing.fetch_last_price_auto(sym)
                        if px_val is not None:
                            repo.upsert_price(local_conn, asset_id=aid, date=pricing.today_str(),
                                              price=px_val, currency=ccy, source="AUTO")
                            if ccy and str(ccy).upper() != acc_ccy:
                                repo.update_asset_currency(local_conn, aid, str(ccy).upper())
                                fx.ensure_fx_rate(local_conn, str(ccy).upper(), acc_ccy)
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
        self._kpi_nb  = KpiCard("Positions ouvertes", "—", emoji="🎯", tone="neutral")
        self._kpi_div = KpiCard("Dividendes perçus",  "—", emoji="💵", tone="success")
        self._kpi_int = KpiCard("Intérêts perçus",    "—", emoji="🏦", tone="success")
        self._kpis_bot = [self._kpi_nb, self._kpi_div, self._kpi_int]
        for card in self._kpis_bot:
            kpi_row2.addWidget(card, stretch=1)
        kpi_row2.addStretch(1)
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
        self._load_data()

    def _on_refresh(self) -> None:
        self._btn_refresh.setEnabled(False)
        self._refresh_status.setText("En cours…")
        self._thread = RefreshPricesThread(self._person_id)
        self._thread.finished.connect(self._on_refresh_done)
        self._thread.start()

    def _on_refresh_done(self, msg: str) -> None:
        self._btn_refresh.setEnabled(True)
        self._refresh_status.setText(f"✅ {msg}")
        self._load_data()

    def _on_date_applied(self) -> None:
        qdt = self._date_picker.date()
        date_str = qdt.toString("yyyy-MM-dd")
        # Si c'est aujourd'hui, on reste en live
        if date_str == datetime.date.today().isoformat():
            self._on_reset_live()
            return
        
        self._selected_date = date_str
        self._lbl_mode.setText(f"🕒 Historique : {qdt.toString('dd/MM/yyyy')}")
        self._lbl_mode.setStyleSheet(f"color: #f97316; font-weight: bold;") # Orange
        self._btn_reset_live.setVisible(True)
        self._load_data()

    def _on_reset_live(self) -> None:
        self._selected_date = None
        self._lbl_mode.setText("🕒 Mode : Live")
        self._lbl_mode.setStyleSheet(f"color: {COLOR_SUCCESS}; font-weight: bold;")
        self._btn_reset_live.setVisible(False)
        self._date_picker.setDate(QDate.currentDate())
        self._load_data()

    def _on_rebuild(self) -> None:
        self._btn_rebuild.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._rebuild_status.setText("Démarrage…")
        self._thread_rebuild = RebuildHistoryThread(self._person_id)
        self._thread_rebuild.progress.connect(self._rebuild_status.setText)
        self._thread_rebuild.finished.connect(self._on_rebuild_done)
        self._thread_rebuild.start()

    def _on_rebuild_done(self, msg: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._rebuild_status.setText(msg)
        self._load_data()

    # ── Chargement des données ────────────────────────────────────────────────

    def _load_data(self) -> None:
        # ── 1. Activation des Skeletons ──────────────────────────────────
        all_widgets = self._kpis_top + self._kpis_bot + [self._table_pos, self._table_diag]
        for w in all_widgets:
            if hasattr(w, "set_loading"):
                w.set_loading(True)
        
        self._chart_history.set_loading(True)
        self._chart_income.set_loading(True)
        self._chart_alloc.set_loading(True)

        self._overlay.start("Analyse du portefeuille global…", blur=True)
        try:
            from services import repositories as repo
            from services import portfolio
            from services.bourse_analytics import (
                get_bourse_performance_metrics, compute_invested_series,
                get_tickers_diagnostic_df, get_bourse_state_asof
            )

            # ── Comptes bourse ──────────────────────────────────────────────
            df_acc = repo.list_accounts(self._conn, person_id=self._person_id)
            if df_acc is None or df_acc.empty:
                return

            bourse_types = {"PEA", "CTO", "CRYPTO"}
            df_b = df_acc[df_acc["account_type"].astype(str).str.upper().isin(bourse_types)]
            if df_b.empty:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucun compte bourse."}]))
                return

            if self._selected_date:
                # ── MODE HISTORIQUE ──
                state = get_bourse_state_asof(self._conn, self._person_id, self._selected_date)
                df_all = state.get("df", pd.DataFrame())
                total_val = float(state.get("total_val", 0.0))
                nb_pos = len(df_all[df_all["quantity"] > 0]) if not df_all.empty else 0
                nb_acc = len(df_b)
                inv_eur = float(state.get("total_invested", 0.0))
                total_pnl = float(state.get("total_pnl", 0.0))
                g_perf = (total_val / inv_eur - 1.0) * 100.0 if inv_eur > 0 else 0.0
                y_perf = 0.0 # pas calculé en historique simple
                t_div = 0.0 # pas filtré par date ici
                t_int = 0.0
                
            else:
                # ── MODE LIVE ──
                all_pos = []
                for _, row in df_b.iterrows():
                    account_id = int(row["id"])
                    acc_ccy    = str(row.get("currency") or "EUR").upper()
                    tx_acc     = repo.list_transactions(self._conn, account_id=account_id, limit=10000)
                    asset_ids  = repo.list_account_asset_ids(self._conn, account_id=account_id)
                    prices     = repo.get_latest_prices(self._conn, asset_ids)
                    pos        = portfolio.compute_positions_v2_fx(self._conn, tx_acc, prices, acc_ccy)
                    if not pos.empty:
                        pos["compte"] = str(row["name"])
                        pos["type"]   = str(row["account_type"])
                        all_pos.append(pos)

                if not all_pos:
                    self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucune position ouverte."}]))
                    return

                df_all    = pd.concat(all_pos, ignore_index=True)
                total_val = float(df_all["value"].sum())       if "value"      in df_all.columns else 0.0
                total_pnl = float(df_all["pnl_latent"].sum())  if "pnl_latent" in df_all.columns else 0.0
                nb_pos    = len(df_all[df_all["quantity"] > 0]) if "quantity"  in df_all.columns else len(df_all)
                nb_acc    = len(df_b)

                # ── Métriques analytiques ──
                metrics = get_bourse_performance_metrics(self._conn, self._person_id, current_live_value=total_val)
                inv_eur = metrics.get("invested_eur",    0.0)
                g_perf  = metrics.get("global_perf_pct", 0.0)
                y_perf  = metrics.get("ytd_perf_pct",    0.0)
                t_div   = metrics.get("total_dividends",  0.0)
                t_int   = metrics.get("total_interests",  0.0)

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
            s_g = "+" if g_perf > 0 else ""
            s_y = "+" if y_perf > 0 else ""
            self._kpi_perf.set_content(
                "Perf Globale",
                f"{s_g}{g_perf:.2f} %",
                subtitle=f"YTD : {s_y}{y_perf:.2f} %",
                emoji="📈",
                tone="success" if g_perf >= 0 else "alert",
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
                    if not older.empty:
                        val_12m_ago = float(older.iloc[-1]["bourse_holdings"])
                        pnl_delta_12m = total_val - val_12m_ago
                        sign = "+" if pnl_delta_12m >= 0 else ""
                        pnl_12m_pct = ((total_val / val_12m_ago) - 1.0) * 100.0 if val_12m_ago > 0 else 0.0
                        s_pct = "+" if pnl_12m_pct >= 0 else ""
                        pnl_details.extend([
                            ("Δ 12 derniers mois",  f"{sign}{_fmt_eur(pnl_delta_12m)}"),
                            ("Perf 12 m",           f"{s_pct}{pnl_12m_pct:.2f} %"),
                        ])

            # Valeur principale des cartes de revenus = all-time
            self._kpi_div.set_content(
                "Dividendes (all time)", _fmt_eur(t_div),
                emoji="💵", tone="success",
                details=div_details or None,
            )
            self._kpi_int.set_content(
                "Intérêts (all time)", _fmt_eur(t_int),
                emoji="🏦", tone="success",
                details=int_details or None,
            )
            self._kpi_pnl.set_content(
                "PnL Latent",
                f"{'+'  if total_pnl >= 0 else ''}{_fmt_eur(total_pnl)}",
                emoji="⚡",
                tone="success" if total_pnl >= 0 else "alert",
                details=pnl_details or None,
            )

            # ── Table des positions (U5) ──────────────────────────────────────
            # On adapte les colonnes selon le mode
            if self._selected_date:
                display_cols = ["symbol", "quantity", "last_price", "currency", "fx_rate", "value", "compte"]
                _LABELS = {**_COL_LABELS, "last_price": "Prix (Date)", "fx_rate": "Taux FX"}
            else:
                display_cols = ["symbol", "name", "asset_type", "quantity", "pru", "last_price",
                                "value", "pnl_latent", "compte", "type"]
                _LABELS = _COL_LABELS

            display_cols = [c for c in display_cols if c in df_all.columns]
            if total_val > 0 and "value" in df_all.columns:
                df_all["poids_%"] = (df_all["value"] / total_val * 100.0).round(2)
                if "value" in display_cols:
                    idx = display_cols.index("value")
                    display_cols.insert(idx + 1, "poids_%")

            df_display = df_all[display_cols].copy().sort_values("value", ascending=False)
            df_display.rename(columns=_LABELS, inplace=True)

            pnl_col = _LABELS.get("pnl_latent", "PnL (€)")
            self._table_pos.set_dataframe(df_display)
            if not self._selected_date:
                self._table_pos.set_column_colors({
                    pnl_col: lambda v: COLOR_SUCCESS if _safe_float(v) >= 0 else COLOR_ERROR
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


def _safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0
