"""
Panel d'un compte Bourse (PEA/CTO/CRYPTO) — remplace ui/compte_bourse.py
"""
import logging
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFormLayout, QDoubleSpinBox, QComboBox, QDateEdit, QScrollArea,
)
from qt_ui.components.animated_tab import AnimatedTabWidget
from PyQt6.QtCore import QDate, QThread, pyqtSignal, Qt

from qt_ui.widgets import PlotlyView, DataTableWidget, MetricLabel, LoadingOverlay
from qt_ui.panels.saisie_panel import SaisiePanel, ASSET_TYPES, _ASSET_TYPES_NON_COTES
from qt_ui.theme import (
    BG_PRIMARY, BORDER_SUBTLE, STYLE_BTN_PRIMARY, STYLE_BTN_SUCCESS, STYLE_SECTION, STYLE_STATUS,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_STATUS_WARNING, STYLE_INPUT_FOCUS, STYLE_FORM_LABEL,
    STYLE_TAB_INNER, STYLE_SCROLLAREA, TEXT_SECONDARY, TEXT_MUTED, plotly_layout,
)

logger = logging.getLogger(__name__)


def _fmt_eur(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.2f} €".replace(",", " ")


def _finite_sum(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.sum())


class PriceRefreshThread(QThread):
    finished = pyqtSignal(int, int)

    def __init__(self, account_id: int, account_ccy: str):
        super().__init__()
        self._account_id = account_id
        self._account_ccy = account_ccy
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        from services import repositories as repo
        from services import pricing, fx
        from services import panel_data_access as pda
        from services.db import get_conn
        n_ok, n_fail = 0, 0
        with get_conn() as local_conn:
            asset_ids = repo.list_account_asset_ids(local_conn, account_id=self._account_id)
            sym_cache: dict[str, tuple[float | None, str | None]] = {}
            for aid in asset_ids:
                if self._is_cancelled:
                    break
                a = pda.get_asset_symbol(local_conn, aid)
                if not a:
                    continue
                sym = a[0] if not hasattr(a, '__getitem__') else a["symbol"]
                sym_u = str(sym or "").strip().upper()
                if not sym_u:
                    continue
                if sym_u not in sym_cache:
                    sym_cache[sym_u] = pricing.fetch_last_price_auto(sym_u)
                px_val, ccy = sym_cache[sym_u]
                if px_val is not None:
                    repo.upsert_price(local_conn, asset_id=aid, date=pricing.today_str(),
                                      price=px_val, currency=ccy, source="AUTO")
                    if ccy:
                        repo.update_asset_currency(local_conn, aid, str(ccy).upper())
                        if str(ccy).upper() != self._account_ccy:
                            fx.ensure_fx_rate(local_conn, str(ccy).upper(), self._account_ccy)
                    n_ok += 1
                else:
                    n_fail += 1
        self.finished.emit(n_ok, n_fail)


class CompteBoursePanel(QWidget):
    def __init__(self, conn, person_id: int, account_id: int, account_type: str, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._account_id = account_id
        self._account_type = account_type
        self._thread = None
        self._dashboard_cache_ttl_sec = 12.0
        self._history_cache_ttl_sec = 20.0
        self._prix_manuels_cache_ttl_sec = 20.0
        self._saisie_assets_cache_ttl_sec = 20.0
        self._last_dashboard_load_ts = 0.0
        self._last_history_load_ts = 0.0
        self._last_prix_manuels_load_ts = 0.0
        self._last_saisie_assets_load_ts = 0.0
        self._last_tab_idx = 0

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        main_v = QVBoxLayout(self)
        main_v.setContentsMargins(12, 12, 12, 12)
        main_v.setSpacing(12)

        # Onglets internes : Tableau de bord / Saisie / Historique
        tabs = AnimatedTabWidget()
        tabs.setStyleSheet(STYLE_TAB_INNER)

        # Onglet dashboard
        dash = QWidget()
        dash.setStyleSheet(f"background: {BG_PRIMARY};")
        dash_v = QVBoxLayout(dash)
        dash_v.setContentsMargins(8, 8, 8, 8)
        dash_v.setSpacing(10)

        # Refresh btn
        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("↻  Rafraîchir les prix")
        self._btn_refresh.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_refresh.clicked.connect(self._on_refresh_prices)
        btn_row.addWidget(self._btn_refresh)
        self._refresh_status = QLabel()
        self._refresh_status.setStyleSheet(STYLE_STATUS)
        btn_row.addWidget(self._refresh_status)
        btn_row.addStretch()
        dash_v.addLayout(btn_row)

        # KPIs
        kpi_row = QHBoxLayout()
        self._kpi_holdings = MetricLabel("Holdings (EUR)", "—")
        self._kpi_pnl = MetricLabel("PnL latent", "—")
        self._kpi_nb = MetricLabel("Positions", "—")
        kpi_row.addWidget(self._kpi_holdings)
        kpi_row.addWidget(self._kpi_pnl)
        kpi_row.addWidget(self._kpi_nb)
        kpi_row.addStretch()
        dash_v.addLayout(kpi_row)

        # Tableau positions
        lbl_pos = QLabel("📌 Positions")
        lbl_pos.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_pos)
        self._table_pos = DataTableWidget()
        self._table_pos.setMinimumHeight(220)
        self._table_pos.set_combo_delegate("asset_type", ASSET_TYPES)
        self._table_pos.hide_column("asset_id")
        self._table_pos.cell_changed.connect(self._on_asset_type_changed)
        dash_v.addWidget(self._table_pos)

        # Graphique répartition
        lbl_alloc = QLabel("Répartition")
        lbl_alloc.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_alloc)
        self._chart_alloc = PlotlyView(min_height=280)
        dash_v.addWidget(self._chart_alloc)

        dash_v.addStretch()
        tabs.addTab(dash, "📊  Tableau de bord")

        # Onglet saisie
        self._saisie = SaisiePanel(conn, person_id, account_id, account_type)
        tabs.addTab(self._saisie, "✏️  Saisie")

        # Onglet historique
        hist = QWidget()
        hist.setStyleSheet(f"background: {BG_PRIMARY};")
        hist_v = QVBoxLayout(hist)
        hist_v.setContentsMargins(8, 8, 8, 8)
        self._hist_table = DataTableWidget()
        self._hist_table.setMinimumHeight(400)
        self._hist_table.set_filter_config([
            {"col": "type",         "kind": "combo",        "label": "Type"},
            {"col": "asset_symbol", "kind": "combo",        "label": "Actif"},
            {"col": "date",         "kind": "date_range",   "label": "Date"},
            {"col": "amount",       "kind": "number_range", "label": "Montant"},
        ])
        hist_v.addWidget(self._hist_table)
        tabs.addTab(hist, "📋  Historique")

        # Onglet prix manuels (actifs non cotés)
        tabs.addTab(self._build_prix_manuels_tab(), "✏️  Prix manuels")

        main_v.addWidget(tabs)
        self._tabs = tabs
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # ── Overlay de chargement ──────────────────────────────────────────
        self._overlay = LoadingOverlay(self)
        # self._load_dashboard() # Sera appelé par le parent ou via refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    def refresh(self) -> None:
        self._load_dashboard()
        if self._tabs.currentIndex() == 2:
            self._load_history()

    def _on_tab_changed(self, idx: int) -> None:
        prev_idx = self._last_tab_idx
        self._last_tab_idx = idx

        # La saisie peut avoir modifié transactions/actifs/prix : invalider en sortie de l'onglet.
        if prev_idx == 1 and idx != 1:
            self._invalidate_local_cache(dashboard=True, history=True, prix_manuels=True)

        if idx == 0:
            self._load_dashboard()
        elif idx == 1:
            self._load_saisie_assets()
        elif idx == 2:
            self._load_history()
        elif idx == 3:
            self._load_prix_manuels()

    def _invalidate_local_cache(
        self,
        *,
        dashboard: bool = False,
        history: bool = False,
        prix_manuels: bool = False,
        saisie_assets: bool = False,
    ) -> None:
        if dashboard:
            self._last_dashboard_load_ts = 0.0
        if history:
            self._last_history_load_ts = 0.0
        if prix_manuels:
            self._last_prix_manuels_load_ts = 0.0
        if saisie_assets:
            self._last_saisie_assets_load_ts = 0.0

    @staticmethod
    def _is_cache_fresh(last_ts: float, ttl_sec: float) -> bool:
        if last_ts <= 0:
            return False
        return (time.monotonic() - last_ts) <= ttl_sec

    def _load_saisie_assets(self, *, force: bool = False) -> None:
        if not force and self._is_cache_fresh(self._last_saisie_assets_load_ts, self._saisie_assets_cache_ttl_sec):
            return
        self._saisie._load_assets()
        self._last_saisie_assets_load_ts = time.monotonic()

    def _on_refresh_prices(self) -> None:
        self._btn_refresh.setEnabled(False)
        self._refresh_status.setStyleSheet(STYLE_STATUS_WARNING)
        self._refresh_status.setText("⏳ Rafraîchissement...")
        try:
            from services import repositories as repo
            acc = repo.get_account(self._conn, self._account_id)
            acc_ccy = (acc["currency"] if acc and acc["currency"] else "EUR").upper()
        except Exception as e:
            logger.warning("Could not fetch account currency: %s", e)
            acc_ccy = "EUR"
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.quit()
            self._thread.wait()
        self._thread = PriceRefreshThread(self._account_id, acc_ccy)
        self._thread.finished.connect(self._on_refresh_done)
        self._thread.start()

    def _on_refresh_done(self, n_ok: int, n_fail: int) -> None:
        self._btn_refresh.setEnabled(True)
        if n_fail > 0:
            self._refresh_status.setStyleSheet(STYLE_STATUS_WARNING)
            self._refresh_status.setText(f"⚠️ {n_ok} OK, {n_fail} non trouvés")
        else:
            self._refresh_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._refresh_status.setText(f"✅ {n_ok} OK")
        self._invalidate_local_cache(dashboard=True, prix_manuels=True)
        self._load_dashboard(force=True)

    def _load_dashboard(self, *, force: bool = False) -> None:
        if not force and self._is_cache_fresh(self._last_dashboard_load_ts, self._dashboard_cache_ttl_sec):
            return

        # ── 1. Activation des Skeletons ──────────────────────────────────
        all_widgets = [self._kpi_holdings, self._kpi_pnl, self._kpi_nb, self._table_pos]
        for w in all_widgets:
            if hasattr(w, "set_loading"):
                w.set_loading(True)
        self._chart_alloc.set_loading(True)

        self._overlay.start("Chargement du portefeuille…", blur=True)
        loaded_ok = False
        try:
            from services.bourse_analytics import get_live_bourse_positions_for_account

            pos = get_live_bourse_positions_for_account(self._conn, self._account_id)

            if pos.empty:
                self._table_pos.set_dataframe(pd.DataFrame([{"Info": "Aucune position (ACHAT/VENTE)."}]))
                return

            total_val = _finite_sum(pos["value"]) if "value" in pos.columns else None
            total_pnl = _finite_sum(pos["pnl_latent"]) if "pnl_latent" in pos.columns else None
            nb_pos = len(pos[pos["quantity"] > 0]) if "quantity" in pos.columns else len(pos)
            missing_reasons: list[str] = []
            if "valuation_status" in pos.columns:
                status_counts = pos["valuation_status"].fillna("ok").astype(str).value_counts()
                for status, count in status_counts.items():
                    if status != "ok":
                        missing_reasons.append(f"{count} position(s) {status}")

            if missing_reasons:
                self._refresh_status.setStyleSheet(STYLE_STATUS_WARNING)
                self._refresh_status.setText("⚠️ Valorisation partielle : " + " · ".join(missing_reasons[:3]))
            else:
                self._refresh_status.setStyleSheet(STYLE_STATUS)
                self._refresh_status.setText("")

            self._kpi_holdings.set_content("Holdings", _fmt_eur(total_val))
            pnl_text = "—" if total_pnl is None or pd.isna(total_pnl) else f"{float(total_pnl):+,.2f} €".replace(",", " ")
            self._kpi_pnl.set_content(
                "PnL latent",
                pnl_text,
                delta=None if total_pnl is None or pd.isna(total_pnl) else f"{float(total_pnl):+.2f}",
                delta_positive=None if total_pnl is None or pd.isna(total_pnl) else float(total_pnl) >= 0,
            )
            self._kpi_nb.set_content("Positions", str(nb_pos))

            display_cols = [
                "asset_id", "symbol", "name", "asset_type", "quantity", "pru",
                "last_price", "value", "pnl_latent", "valuation_status", "asset_ccy",
            ]
            display_cols = [c for c in display_cols if c in pos.columns]
            self._table_pos.set_dataframe(pos[display_cols])

            # Graphique
            if "value" in pos.columns and "symbol" in pos.columns:
                df_pie = pos[pos["value"] > 0][["symbol", "value"]].copy()
                if not df_pie.empty:
                    fig = px.pie(df_pie, names="symbol", values="value", hole=0.4,
                                 template="plotly_dark",
                                 labels={"symbol": "Actif", "value": "Valeur (€)"})
                    fig.update_layout(**plotly_layout())
                    self._chart_alloc.set_figure(fig)
                else:
                    self._chart_alloc.clear_figure()
            else:
                self._chart_alloc.clear_figure()
            loaded_ok = True

        except Exception as e:
            logger.error("CompteBoursePanel._load_dashboard error: %s", e, exc_info=True)
        finally:
            # ── 2. Désactivation des Skeletons ──────────────────────────────
            for w in all_widgets:
                if hasattr(w, "set_loading"):
                    w.set_loading(False)
            self._chart_alloc.set_loading(False)

            self._overlay.stop()
            if loaded_ok:
                self._last_dashboard_load_ts = time.monotonic()

    def _on_asset_type_changed(self, row: int, col_name: str, new_value) -> None:
        if col_name != "asset_type":
            return
        df = self._table_pos.get_dataframe()
        if row < len(df) and "asset_id" in df.columns:
            try:
                asset_id = int(df.iloc[row]["asset_id"])
                from services import repositories as repo
                repo.update_asset_type(self._conn, asset_id, str(new_value))
            except Exception as e:
                logger.error("Erreur mise à jour asset_type: %s", e, exc_info=True)

    def _load_history(self, *, force: bool = False) -> None:
        if not force and self._is_cache_fresh(self._last_history_load_ts, self._history_cache_ttl_sec):
            return
        try:
            from services import repositories as repo
            from utils.libelles import afficher_type_operation

            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=5000)
            if tx is None or tx.empty:
                self._hist_table.set_dataframe(pd.DataFrame([{"Info": "Aucune opération."}]))
                return
            if "type" in tx.columns:
                tx = tx.copy()
                tx["type"] = tx["type"].apply(lambda t: afficher_type_operation(str(t)))
            cols = ["date", "type", "asset_symbol", "amount", "fees", "category", "note", "id"]
            cols = [c for c in cols if c in tx.columns]
            self._hist_table.set_dataframe(tx[cols])
            self._last_history_load_ts = time.monotonic()
        except Exception as e:
            logger.error("CompteBoursePanel._load_history error: %s", e, exc_info=True)

    # ── Onglet Prix manuels ────────────────────────────────────────────────

    def _build_prix_manuels_tab(self) -> QWidget:
        """Construit l'onglet de mise à jour manuelle des prix (actifs non cotés)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(STYLE_SCROLLAREA)

        container = QWidget()
        container.setStyleSheet(f"background: {BG_PRIMARY};")
        v = QVBoxLayout(container)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(16)

        # Titre + hint
        from PyQt6.QtWidgets import QLabel as _QLabel
        hint = _QLabel(
            "Mise à jour manuelle des prix pour les actifs sans cotation automatique\n"
            "(SCPI, fonds euros, private equity, fonds, non cotés…).\n"
            "Le prix saisi devient immédiatement le dernier prix connu utilisé dans les positions."
        )
        hint.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        # Formulaire de saisie de prix
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def _flbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(STYLE_FORM_LABEL)
            return lbl

        self._pm_combo = QComboBox()
        self._pm_combo.setStyleSheet(STYLE_INPUT_FOCUS)
        self._pm_combo.currentIndexChanged.connect(self._on_pm_asset_selected)
        form.addRow(_flbl("Actif :"), self._pm_combo)

        self._pm_prix = QDoubleSpinBox()
        self._pm_prix.setRange(0, 999_999_999)
        self._pm_prix.setDecimals(4)
        self._pm_prix.setSuffix(" €")
        self._pm_prix.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_flbl("Nouveau prix unitaire :"), self._pm_prix)

        self._pm_date = QDateEdit()
        self._pm_date.setCalendarPopup(True)
        self._pm_date.setDate(QDate.currentDate())
        self._pm_date.setDisplayFormat("dd/MM/yyyy")
        self._pm_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_flbl("Date effective :"), self._pm_date)

        v.addLayout(form)

        # Dernier prix connu (affiché sous le formulaire)
        self._pm_last_price_lbl = QLabel("")
        self._pm_last_price_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        v.addWidget(self._pm_last_price_lbl)

        # Bouton + statut
        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾  Enregistrer le prix")
        btn_save.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_save.clicked.connect(self._save_prix_manuel)
        self._pm_status = QLabel("")
        self._pm_status.setStyleSheet(STYLE_STATUS)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(self._pm_status)
        btn_row.addStretch()
        v.addLayout(btn_row)

        # Séparateur
        sep = QLabel()
        sep.setStyleSheet(f"background: {BORDER_SUBTLE}; min-height: 1px; max-height: 1px;")
        v.addWidget(sep)

        # Tableau récapitulatif : derniers prix connus par actif non coté
        recap_lbl = QLabel("Derniers prix connus — actifs non cotés de ce compte")
        recap_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; font-weight: bold;")
        v.addWidget(recap_lbl)

        self._pm_table = DataTableWidget()
        self._pm_table.setMinimumHeight(220)
        v.addWidget(self._pm_table)

        v.addStretch()
        scroll.setWidget(container)
        return scroll

    def _load_prix_manuels(self, *, force: bool = False) -> None:
        """Charge les actifs non cotés du compte dans le combo et le tableau récap."""
        if not force and self._is_cache_fresh(self._last_prix_manuels_load_ts, self._prix_manuels_cache_ttl_sec):
            return
        try:
            from services import repositories as repo
            from services import panel_data_access as pda

            asset_ids = repo.list_account_asset_ids(self._conn, account_id=self._account_id)
            if not asset_ids:
                self._pm_combo.clear()
                self._pm_table.set_dataframe(pd.DataFrame([{"Info": "Aucun actif dans ce compte."}]))
                return

            rows = pda.list_non_coted_assets_with_last_price(self._conn, asset_ids)

            # Remplir le combo
            self._pm_combo.blockSignals(True)
            self._pm_combo.clear()
            for r in rows:
                label = f"{r['symbol']} — {r['name'] or ''} ({r['asset_type']})"
                self._pm_combo.addItem(label, int(r["asset_id"]))
            self._pm_combo.blockSignals(False)

            if self._pm_combo.count() > 0:
                self._on_pm_asset_selected(0)
            else:
                self._pm_last_price_lbl.setText("Aucun actif non coté dans ce compte.")

            # Tableau récap
            if rows:
                df = pd.DataFrame([dict(r) for r in rows])
                df = df.rename(columns={
                    "symbol":         "Ticker",
                    "name":           "Nom",
                    "asset_type":     "Type",
                    "currency":       "Devise",
                    "last_price":     "Dernier prix",
                    "last_price_date":"Date du prix",
                })
                df = df.drop(columns=["asset_id"], errors="ignore")
                self._pm_table.set_dataframe(df)
            else:
                self._pm_table.set_dataframe(pd.DataFrame([{
                    "Info": "Aucun actif non coté (SCPI, PE, fonds euros…) dans ce compte."
                }]))
            self._last_prix_manuels_load_ts = time.monotonic()

        except Exception as e:
            logger.error("CompteBoursePanel._load_prix_manuels error: %s", e, exc_info=True)

    def _on_pm_asset_selected(self, _idx: int) -> None:
        """Pré-remplit le prix avec le dernier prix connu de l'actif sélectionné."""
        try:
            from services import panel_data_access as pda

            asset_id = self._pm_combo.currentData()
            if asset_id is None:
                return
            row = pda.get_latest_asset_price(self._conn, asset_id)

            if row and row["price"] is not None:
                self._pm_prix.setValue(float(row["price"]))
                self._pm_last_price_lbl.setText(
                    f"Dernier prix connu : {float(row['price']):.4f} {row['currency'] or 'EUR'}"
                    f" — au {row['date']}"
                )
            else:
                self._pm_prix.setValue(0.0)
                self._pm_last_price_lbl.setText("Aucun prix enregistré pour cet actif.")
        except Exception as e:
            logger.warning("Erreur pré-remplissage prix: %s", e)

    def _save_prix_manuel(self) -> None:
        """Enregistre le prix manuel et rafraîchit le tableau récap."""
        try:
            from services import repositories as repo
            from services import panel_data_access as pda

            asset_id = self._pm_combo.currentData()
            if asset_id is None:
                self._pm_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._pm_status.setText("❌  Sélectionnez un actif.")
                return

            prix = self._pm_prix.value()
            if prix <= 0:
                self._pm_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._pm_status.setText("❌  Le prix doit être supérieur à 0.")
                return

            date_str = self._pm_date.date().toString("yyyy-MM-dd")

            # Récupérer la devise de l'actif
            row = pda.get_asset_currency(self._conn, asset_id)
            currency = (row["currency"] if row and row["currency"] else "EUR").upper()

            repo.upsert_price(
                self._conn,
                asset_id=int(asset_id),
                date=date_str,
                price=prix,
                currency=currency,
                source="MANUEL",
            )

            nom = self._pm_combo.currentText()
            self._pm_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._pm_status.setText(f"✅  Prix enregistré : {prix:.4f} {currency} au {date_str}")

            # Mettre à jour le hint + rafraîchir le tableau
            self._pm_last_price_lbl.setText(
                f"Dernier prix connu : {prix:.4f} {currency} — au {date_str}"
            )
            self._invalidate_local_cache(dashboard=True, prix_manuels=True)
            self._load_prix_manuels(force=True)

            # Rafraîchir aussi le dashboard pour refléter la nouvelle valeur
            self._load_dashboard(force=True)

        except Exception as e:
            logger.error("CompteBoursePanel._save_prix_manuel error: %s", e, exc_info=True)
            self._pm_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._pm_status.setText(f"❌  Erreur : {e}")
