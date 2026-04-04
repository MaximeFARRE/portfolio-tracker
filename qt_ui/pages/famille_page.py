"""
Page Famille — remplace pages/1_Famille.py
Contient 3 onglets : Snapshots weekly, Diagnostic, Flux (V1)
"""
import logging
import pandas as pd
import plotly.express as px
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QPushButton, QScrollArea, QGroupBox, QComboBox, QSizePolicy,
    QMessageBox, QFrame, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from qt_ui.components.animated_tab import AnimatedTabWidget

from qt_ui.widgets import PlotlyView, DataTableWidget, KpiCard, MetricLabel
from qt_ui.theme import (
    BG_PRIMARY, BG_SIDEBAR, BORDER_SUBTLE, TEXT_PRIMARY, TEXT_SECONDARY,
    TEXT_MUTED, ACCENT_BLUE, STYLE_BTN_PRIMARY, STYLE_TAB, STYLE_GROUP,
    STYLE_INPUT, STYLE_SCROLLAREA, STYLE_PROGRESS, STYLE_TITLE_LARGE,
    STYLE_TITLE, STYLE_SECTION, STYLE_STATUS, STYLE_STATUS_SUCCESS,
    STYLE_STATUS_ERROR, COLOR_SUCCESS,
    plotly_layout,
)
from utils.format_monnaie import money

logger = logging.getLogger(__name__)


# ─── Worker threads ──────────────────────────────────────────────────────────

class RebuildFamilleThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, person_ids: list):
        super().__init__()
        self._person_ids = person_ids

    def run(self):
        try:
            self.progress.emit("Rebuild famille en cours...")
            from services import family_snapshots as fs
            from services.db import get_conn
            with get_conn() as local_conn:
                res = fs.rebuild_family_weekly(
                    local_conn, person_ids=self._person_ids,
                    lookback_days=90, family_id=1
                )
            self.finished.emit(str(res))
        except Exception as e:
            logger.error("Erreur rebuild famille : %s", e)
            self.error.emit(str(e))


class RebuildAllThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, person_ids: list, safety_weeks: int):
        super().__init__()
        self._person_ids = person_ids
        self._safety_weeks = safety_weeks

    def run(self):
        try:
            from services import snapshots as wk_snap
            from services import family_snapshots as fs
            from services.db import get_conn
            msgs = []
            total = len(self._person_ids)
            with get_conn() as local_conn:
                for i, pid in enumerate(self._person_ids):
                    self.progress.emit(f"Rebuild personne {i+1}/{total}...")
                    r = wk_snap.rebuild_snapshots_person_from_last(
                        local_conn, person_id=pid,
                        safety_weeks=self._safety_weeks,
                        fallback_lookback_days=90
                    )
                    msgs.append(str(r))
                try:
                    self.progress.emit("Rebuild famille...")
                    fs.rebuild_family_weekly_from_last(
                        local_conn, person_ids=self._person_ids,
                        safety_weeks=self._safety_weeks,
                        fallback_lookback_days=90, family_id=1
                    )
                    msgs.append("famille OK")
                except Exception as e:
                    logger.warning("Erreur rebuild famille agrégé : %s", e)
                    msgs.append(f"famille erreur: {e}")
            self.finished.emit(" | ".join(msgs))
        except Exception as e:
            logger.error("Erreur rebuild all : %s", e)
            self.error.emit(str(e))


# ─── Panel : Famille Dashboard ────────────────────────────────────────────────

class FamilleDashboardPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._thread = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setSpacing(16)

        # Bouton rebuild + progress bar
        top_row = QHBoxLayout()
        self._btn_rebuild = QPushButton("📸  Rebuild Famille (90j)")
        self._btn_rebuild.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_rebuild.clicked.connect(self._on_rebuild)
        top_row.addWidget(self._btn_rebuild)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # Mode indéterminé
        self._progress_bar.setStyleSheet(STYLE_PROGRESS)
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.hide()
        top_row.addWidget(self._progress_bar)

        self._rebuild_status = QLabel("Vue Famille = somme des snapshots weekly des personnes.")
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        top_row.addWidget(self._rebuild_status, 1)
        self._layout.addLayout(top_row)

        # Titre semaine
        self._title_label = QLabel("Chargement...")
        self._title_label.setStyleSheet(STYLE_TITLE)
        self._layout.addWidget(self._title_label)

        # KPI row 1
        kpi_row1 = QHBoxLayout()
        self._kpi_net = KpiCard(tone="blue")
        self._kpi_brut = KpiCard(tone="green")
        self._kpi_liq = KpiCard(tone="primary")
        self._kpi_credits = KpiCard(tone="red")
        for k in [self._kpi_net, self._kpi_brut, self._kpi_liq, self._kpi_credits]:
            kpi_row1.addWidget(k)
        self._layout.addLayout(kpi_row1)

        # KPI row 2 (perfs)
        kpi_row2 = QHBoxLayout()
        self._kpi_3m = MetricLabel()
        self._kpi_12m = MetricLabel()
        self._kpi_cagr = MetricLabel()
        for k in [self._kpi_3m, self._kpi_12m, self._kpi_cagr]:
            kpi_row2.addWidget(k)
        kpi_row2.addStretch()
        self._layout.addLayout(kpi_row2)

        # Graphique évolution
        lbl_chart = QLabel("📈 Évolution — Patrimoine net (weekly)")
        lbl_chart.setStyleSheet(STYLE_SECTION)
        self._layout.addWidget(lbl_chart)
        self._chart_line = PlotlyView(min_height=320)
        self._layout.addWidget(self._chart_line)

        # Répartition pie charts
        pie_row = QHBoxLayout()
        left_box = QGroupBox("Répartition par catégories")
        left_box.setStyleSheet(STYLE_GROUP)
        left_v = QVBoxLayout(left_box)
        self._chart_alloc = PlotlyView(min_height=280)
        left_v.addWidget(self._chart_alloc)

        right_box = QGroupBox("Répartition par personne (Net)")
        right_box.setStyleSheet(STYLE_GROUP)
        right_v = QVBoxLayout(right_box)
        self._chart_people = PlotlyView(min_height=280)
        right_v.addWidget(self._chart_people)

        pie_row.addWidget(left_box)
        pie_row.addWidget(right_box)
        self._layout.addLayout(pie_row)

        # Leaderboards
        lbl_lead = QLabel("🏆 Classements (famille)")
        lbl_lead.setStyleSheet(STYLE_SECTION)
        self._layout.addWidget(lbl_lead)
        self._leaderboard_label = QLabel()
        self._leaderboard_label.setWordWrap(True)
        self._leaderboard_label.setTextFormat(Qt.TextFormat.RichText)
        self._leaderboard_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; padding: 8px; background: {BG_SIDEBAR}; border-radius: 6px;")
        self._layout.addWidget(self._leaderboard_label)

        # Table personnes
        lbl_detail = QLabel("🧾 Détails par personne")
        lbl_detail.setStyleSheet(STYLE_SECTION)
        self._layout.addWidget(lbl_detail)
        self._people_table = DataTableWidget()
        self._people_table.setMinimumHeight(160)
        self._layout.addWidget(self._people_table)

        self._layout.addStretch()

    def refresh(self) -> None:
        try:
            from services import family_dashboard as fd
            people = fd.get_people(self._conn)
            if people.empty:
                self._title_label.setText("Aucune personne en base.")
                return
            person_ids = [int(x) for x in people["id"].tolist()]

            df_family = fd.get_family_series_from_people_snapshots(self._conn, person_ids)
            if df_family.empty:
                self._title_label.setText("Aucune donnée weekly — lancez un rebuild.")
                return

            common_week = fd.get_last_common_week(self._conn, person_ids)

            kpis = fd.compute_family_kpis(df_family)
            asof = kpis.get("asof")
            asof_txt = asof.strftime("%Y-%m-%d") if asof is not None else "—"
            self._title_label.setText(f"👨‍👩‍👧‍👦  Famille — Semaine : {asof_txt}")

            self._kpi_net.set_content("Patrimoine net", money(kpis.get("patrimoine_net", 0)), tone="blue")
            self._kpi_brut.set_content("Patrimoine brut", money(kpis.get("patrimoine_brut", 0)), tone="green")
            self._kpi_liq.set_content("Liquidités", money(kpis.get("liquidites_total", 0)), tone="primary")
            self._kpi_credits.set_content("Crédits restants", money(kpis.get("credits_remaining", 0)), tone="red")

            p3m = kpis.get("perf_3m")
            p12m = kpis.get("perf_12m")
            cagr = kpis.get("cagr")
            self._kpi_3m.set_content("Évolution 3 mois", f"{p3m:.1f}%" if p3m is not None else "—")
            self._kpi_12m.set_content("Évolution 12 mois", f"{p12m:.1f}%" if p12m is not None else "—")
            self._kpi_cagr.set_content("Rendement annualisé", f"{cagr:.1f}%" if cagr is not None else "—")

            # Courbe
            df_plot = df_family.copy()
            df_plot["week_date"] = pd.to_datetime(df_plot["week_date"])
            fig_line = px.line(df_plot, x="week_date", y="patrimoine_net",
                               template="plotly_dark",
                               labels={"week_date": "Semaine", "patrimoine_net": "Patrimoine net (€)"})
            fig_line.update_layout(**plotly_layout(margin=dict(l=0, r=0, t=20, b=0)))
            self._chart_line.set_figure(fig_line)

            # Pie allocation
            alloc = fd.compute_allocations_family(df_family)
            alloc_df = pd.DataFrame([{"Catégorie": k, "Valeur": v} for k, v in alloc.items() if v > 0])
            if not alloc_df.empty:
                fig_alloc = px.pie(alloc_df, names="Catégorie", values="Valeur", hole=0.45, template="plotly_dark")
                fig_alloc.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=10, b=10)))
                self._chart_alloc.set_figure(fig_alloc)

            # Pie personnes
            if common_week is not None:
                df_people = fd.compute_people_table(self._conn, people, common_week)
                if not df_people.empty:
                    person_alloc = df_people[["Personne", "Net (€)"]].copy()
                    person_alloc = person_alloc[person_alloc["Net (€)"] > 0]
                    if not person_alloc.empty:
                        fig_p = px.pie(person_alloc, names="Personne", values="Net (€)", hole=0.45, template="plotly_dark")
                        fig_p.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=10, b=10)))
                        self._chart_people.set_figure(fig_p)
                    self._people_table.set_dataframe(df_people)

            # Leaderboards
            if common_week is not None:
                boards = fd.compute_leaderboards(self._conn, people, person_ids, common_week)
                html_parts = []
                medals = ["🥇", "🥈", "🥉"]

                top_net = boards.get("top_net")
                if top_net is not None and len(top_net) > 0:
                    html_parts.append("<b>🥇 Patrimoine net (Top 3)</b><br>")
                    for i, row in top_net.iterrows():
                        m = medals[i] if i < 3 else "•"
                        html_parts.append(f"{m} <b>{row['Personne']}</b> — {money(float(row['Net (€)']))}<br>")

                top3 = boards.get("top_perf_3m", [])
                if top3:
                    html_parts.append("<br><b>🚀 Progression 3 mois (Top 3)</b><br>")
                    for i, (name, val) in enumerate(top3):
                        m = medals[i]
                        html_parts.append(f"{m} <b>{name}</b> — {val:.1f}%<br>")

                self._leaderboard_label.setText("".join(html_parts))

        except Exception as e:
            self._title_label.setText(f"Erreur chargement : {e}")

    def _on_rebuild(self) -> None:
        try:
            from services import family_dashboard as fd
            people = fd.get_people(self._conn)
            person_ids = [int(x) for x in people["id"].tolist()]
        except Exception as e:
            logger.error("Erreur récupération personnes pour rebuild : %s", e)
            person_ids = []

        self._btn_rebuild.setEnabled(False)
        self._progress_bar.show()
        self._rebuild_status.setText("Rebuild en cours...")

        self._thread = RebuildFamilleThread(person_ids)
        self._thread.progress.connect(self._on_rebuild_progress)
        self._thread.finished.connect(self._on_rebuild_done)
        self._thread.error.connect(self._on_rebuild_error)
        self._thread.start()

    def _on_rebuild_progress(self, msg: str) -> None:
        self._rebuild_status.setText(msg)

    def _on_rebuild_done(self, result: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._progress_bar.hide()
        self._rebuild_status.setText(f"Rebuild terminé ✅ {result}")
        self.refresh()

    def _on_rebuild_error(self, err: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._progress_bar.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
        self._rebuild_status.setText(f"Erreur : {err}")


# ─── Panel : Data Health ──────────────────────────────────────────────────────

class DataHealthPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._thread = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("🛠️ Diagnostic — Data Health")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        # Fenêtre sécurité
        sw_row = QHBoxLayout()
        sw_row.addWidget(QLabel("Fenêtre sécurité (semaines) :"))
        self._safety_combo = QComboBox()
        self._safety_combo.addItems(["2", "4", "8"])
        self._safety_combo.setCurrentIndex(1)
        self._safety_combo.setStyleSheet(STYLE_INPUT)
        sw_row.addWidget(self._safety_combo)
        sw_row.addStretch()
        layout.addLayout(sw_row)

        # Tableau statuts
        self._status_table = DataTableWidget()
        self._status_table.setMinimumHeight(150)
        layout.addWidget(self._status_table)

        # Boutons rebuild
        btn_row = QHBoxLayout()
        self._btn_rebuild_all = QPushButton("🚀  Rebuild nécessaire (tout)")
        self._btn_rebuild_all.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_rebuild_all.clicked.connect(self._on_rebuild_all)
        btn_row.addWidget(self._btn_rebuild_all)

        self._rebuild_progress = QProgressBar()
        self._rebuild_progress.setRange(0, 0)
        self._rebuild_progress.setStyleSheet(STYLE_PROGRESS)
        self._rebuild_progress.setMaximumWidth(200)
        self._rebuild_progress.hide()
        btn_row.addWidget(self._rebuild_progress)

        self._rebuild_status = QLabel()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        btn_row.addWidget(self._rebuild_status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Marché
        mkt_label = QLabel("📡 Marché (weekly)")
        mkt_label.setStyleSheet(STYLE_SECTION + " margin-top: 12px;")
        layout.addWidget(mkt_label)
        mkt_row = QHBoxLayout()
        self._mkt_prix = MetricLabel("Dernière semaine prix", "—")
        self._mkt_fx = MetricLabel("Dernière semaine FX", "—")
        mkt_row.addWidget(self._mkt_prix)
        mkt_row.addWidget(self._mkt_fx)
        mkt_row.addStretch()
        layout.addLayout(mkt_row)

        # Snapshots personnes
        snap_label = QLabel("👤 Snapshots — Personnes (dernières semaines)")
        snap_label.setStyleSheet(STYLE_SECTION + " margin-top: 12px;")
        layout.addWidget(snap_label)
        self._snap_table = DataTableWidget()
        self._snap_table.setMinimumHeight(150)
        layout.addWidget(self._snap_table)

        # Tickers sans prix
        tick_label = QLabel("🧾 Tickers sans prix weekly")
        tick_label.setStyleSheet(STYLE_SECTION + " margin-top: 12px;")
        layout.addWidget(tick_label)
        self._ticker_table = DataTableWidget()
        self._ticker_table.setMinimumHeight(120)
        layout.addWidget(self._ticker_table)

        layout.addStretch()

    def refresh(self) -> None:
        try:
            from services import diagnostics_global as dg
            from services import repositories as repo

            people = repo.list_people(self._conn)
            person_ids = [int(x) for x in people["id"].tolist()] if people is not None and not people.empty else []
            safety_weeks = int(self._safety_combo.currentText())

            rows = []
            for pid in person_ids:
                name = str(people.loc[people["id"] == pid, "name"].iloc[0])
                stt = dg.person_weekly_status(self._conn, person_id=pid, safety_weeks=safety_weeks)
                rows.append({
                    "Personne": name,
                    "Dernière semaine": stt.get("last_week") or "—",
                    "Cible": stt.get("target_week") or "—",
                    "Statut": "✅ À jour" if stt.get("suggested") == "UP_TO_DATE" else "⚠️ À rebuild",
                })
            if rows:
                self._status_table.set_dataframe(pd.DataFrame(rows))

            # Marché
            dates = dg.last_market_dates(self._conn)
            self._mkt_prix.set_content("Dernière semaine prix", dates.get("last_price_week") or "—")
            self._mkt_fx.set_content("Dernière semaine FX", dates.get("last_fx_week") or "—")

            # Snapshots
            df_last = dg.last_snapshot_week_by_person(self._conn)
            if not df_last.empty:
                self._snap_table.set_dataframe(df_last)

            # Tickers
            df_t = dg.tickers_missing_weekly_prices(self._conn, max_show=30)
            if not df_t.empty:
                self._ticker_table.set_dataframe(df_t)
            else:
                self._ticker_table.set_dataframe(pd.DataFrame([{"Statut": "Tous les tickers ont un prix weekly ✅"}]))
        except Exception as e:
            logger.error("Erreur refresh DataHealth : %s", e)
            self._rebuild_status.setText(f"Erreur : {e}")

    def _on_rebuild_all(self) -> None:
        try:
            from services import repositories as repo
            people = repo.list_people(self._conn)
            person_ids = [int(x) for x in people["id"].tolist()]
        except Exception as e:
            logger.error("Erreur récupération personnes pour rebuild all : %s", e)
            person_ids = []

        safety_weeks = int(self._safety_combo.currentText())
        self._btn_rebuild_all.setEnabled(False)
        self._rebuild_progress.show()
        self._rebuild_status.setText("Rebuild en cours...")

        self._thread = RebuildAllThread(person_ids, safety_weeks)
        self._thread.progress.connect(lambda msg: self._rebuild_status.setText(msg))
        self._thread.finished.connect(self._on_rebuild_done)
        self._thread.error.connect(self._on_rebuild_error)
        self._thread.start()

    def _on_rebuild_done(self, result: str) -> None:
        self._btn_rebuild_all.setEnabled(True)
        self._rebuild_progress.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._rebuild_status.setText("Rebuild terminé ✅")
        self.refresh()

    def _on_rebuild_error(self, err: str) -> None:
        self._btn_rebuild_all.setEnabled(True)
        self._rebuild_progress.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
        self._rebuild_status.setText(f"Erreur : {err}")


# ─── Panel : Flux V1 ──────────────────────────────────────────────────────────

class FluxPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("📒 Flux — Vue globale (basé sur les opérations)")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        kpi_row = QHBoxLayout()
        self._kpi_solde = MetricLabel("Solde famille (flux)", "—")
        self._kpi_cashflow = MetricLabel("Cashflow du mois (flux)", "—")
        self._kpi_ops = MetricLabel("Nombre d'opérations", "—")
        kpi_row.addWidget(self._kpi_solde)
        kpi_row.addWidget(self._kpi_cashflow)
        kpi_row.addWidget(self._kpi_ops)
        kpi_row.addStretch()
        layout.addLayout(kpi_row)

        lbl_people = QLabel("Répartition par personne")
        lbl_people.setStyleSheet(STYLE_SECTION + " margin-top: 8px;")
        layout.addWidget(lbl_people)
        self._people_table = DataTableWidget()
        self._people_table.setMinimumHeight(150)
        layout.addWidget(self._people_table)

        lbl_accounts = QLabel("Comptes — aperçu")
        lbl_accounts.setStyleSheet(STYLE_SECTION + " margin-top: 8px;")
        layout.addWidget(lbl_accounts)
        self._accounts_table = DataTableWidget()
        self._accounts_table.setMinimumHeight(180)
        layout.addWidget(self._accounts_table)

        lbl_last = QLabel("Dernières opérations (50)")
        lbl_last.setStyleSheet(STYLE_SECTION + " margin-top: 8px;")
        layout.addWidget(lbl_last)
        self._last_table = DataTableWidget()
        self._last_table.setMinimumHeight(200)
        layout.addWidget(self._last_table)

        layout.addStretch()

    def refresh(self) -> None:
        try:
            from services import repositories as repo
            from services import calculations as calc

            people = repo.list_people(self._conn)
            accounts = repo.list_accounts(self._conn)
            tx_all = repo.list_transactions(self._conn, limit=20000)

            if people.empty:
                return

            solde_total = calc.solde_compte(tx_all)
            today = pd.Timestamp.today()
            cashflow_mois = calc.cashflow_mois(tx_all, int(today.year), int(today.month))

            self._kpi_solde.set_content("Solde famille (flux)", f"{solde_total:,.2f} €".replace(",", " "))
            self._kpi_cashflow.set_content("Cashflow du mois", f"{cashflow_mois:,.2f} €".replace(",", " "))
            self._kpi_ops.set_content("Opérations", str(len(tx_all)))

            # Tableau personnes
            lignes = []
            for _, p in people.iterrows():
                pid = int(p["id"])
                tx_p = tx_all[tx_all["person_id"] == pid].copy() if not tx_all.empty else pd.DataFrame()
                lignes.append({"Personne": str(p["name"]), "Solde (flux)": calc.solde_compte(tx_p), "Opérations": len(tx_p)})
            df_people = pd.DataFrame(lignes).sort_values("Solde (flux)", ascending=False)
            self._people_table.set_dataframe(df_people)

            # Tableau comptes
            if not accounts.empty:
                lignes_c = []
                for _, a in accounts.iterrows():
                    acc_id = int(a["id"])
                    pid = int(a["person_id"])
                    person_name = str(people.loc[people["id"] == pid, "name"].iloc[0]) if pid in people["id"].values else "?"
                    tx_c = tx_all[tx_all["account_id"] == acc_id].copy() if not tx_all.empty else pd.DataFrame()
                    lignes_c.append({"Personne": person_name, "Compte": str(a["name"]),
                                     "Solde (flux)": calc.solde_compte(tx_c), "Opérations": len(tx_c)})
                df_accounts = pd.DataFrame(lignes_c).sort_values("Solde (flux)", ascending=False)
                self._accounts_table.set_dataframe(df_accounts)

            # Dernières ops
            if not tx_all.empty:
                cols = ["date", "person_name", "account_name", "type", "asset_symbol", "amount", "fees", "category", "note"]
                cols = [c for c in cols if c in tx_all.columns]
                df_last = tx_all[cols].head(50).copy()
                self._last_table.set_dataframe(df_last)

        except Exception as e:
            logger.error("Erreur chargement Flux : %s", e)


# ─── Page Famille ─────────────────────────────────────────────────────────────

class FamillePage(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self.setStyleSheet(f"background: {BG_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setStyleSheet(f"background: {BG_SIDEBAR}; border-bottom: 1px solid {BORDER_SUBTLE};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)
        title = QLabel("Vue d'ensemble — Famille")
        title.setStyleSheet(STYLE_TITLE_LARGE)
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addWidget(header)

        # Onglets
        self._tabs = AnimatedTabWidget()
        self._tabs.setStyleSheet(STYLE_TAB)

        self._panel_dashboard = FamilleDashboardPanel(conn)
        self._panel_health = DataHealthPanel(conn)
        self._panel_flux = FluxPanel(conn)

        self._tabs.addTab(self._panel_dashboard, "👨‍👩‍👧‍👦  Snapshots weekly")
        self._tabs.addTab(self._panel_health, "🛠️  Diagnostic")
        self._tabs.addTab(self._panel_flux, "📒  Flux (V1)")

        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Un seul QScrollArea pour toute la page
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(STYLE_SCROLLAREA)
        scroll.setWidget(self._tabs)
        layout.addWidget(scroll, 1)  # stretch=1 pour occuper tout l'espace restant

    def refresh(self) -> None:
        """Rafraîchit l'onglet actif."""
        idx = self._tabs.currentIndex()
        self._on_tab_changed(idx)

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self._panel_dashboard.refresh()
        elif index == 1:
            self._panel_health.refresh()
        elif index == 2:
            self._panel_flux.refresh()
