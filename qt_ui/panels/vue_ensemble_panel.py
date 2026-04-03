"""
Panel Vue d'ensemble — remplace ui/vue_ensemble_overview.py
Affiche le patrimoine net, les allocations, l'évolution hebdomadaire.
"""
import logging
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY, STYLE_GROUP, STYLE_SECTION,
    STYLE_STATUS, CHART_GREEN, CHART_RED, plotly_layout,
)
from qt_ui.widgets import PlotlyView, DataTableWidget, KpiCard, MetricLabel
from utils.format_monnaie import money

logger = logging.getLogger(__name__)


class SnapshotRebuildThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, person_id: int):
        super().__init__()
        self._person_id = person_id

    def run(self):
        try:
            from services import snapshots as wk_snap
            from services.db import get_conn
            with get_conn() as local_conn:
                res = wk_snap.rebuild_snapshots_person_from_last(
                    local_conn, person_id=self._person_id,
                    safety_weeks=4, fallback_lookback_days=90
                )
            self.finished.emit(str(res))
        except Exception as e:
            self.error.emit(str(e))


class VueEnsemblePanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._thread = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header + Rebuild
        top_row = QHBoxLayout()
        self._btn_rebuild = QPushButton("📸  Rebuild snapshots (90j)")
        self._btn_rebuild.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_rebuild.clicked.connect(self._on_rebuild)
        top_row.addWidget(self._btn_rebuild)
        self._rebuild_status = QLabel()
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        top_row.addWidget(self._rebuild_status)
        top_row.addStretch()
        layout.addLayout(top_row)

        # KPI cards row 1
        kpi_row1 = QHBoxLayout()
        self._kpi_net = KpiCard("Patrimoine net", "—", tone="blue")
        self._kpi_brut = KpiCard("Patrimoine brut", "—", tone="green")
        self._kpi_liq = KpiCard("Liquidités", "—", tone="primary")
        self._kpi_bourse = KpiCard("Holdings bourse", "—", tone="broker")
        self._kpi_credits = KpiCard("Crédits restants", "—", tone="red")
        for k in [self._kpi_net, self._kpi_brut, self._kpi_liq, self._kpi_bourse, self._kpi_credits]:
            kpi_row1.addWidget(k)
        layout.addLayout(kpi_row1)

        # KPI perfs
        kpi_row2 = QHBoxLayout()
        self._kpi_3m = MetricLabel("Évolution 3 mois", "—")
        self._kpi_12m = MetricLabel("Évolution 12 mois", "—")
        self._kpi_cagr = MetricLabel("Rendement annualisé", "—")
        kpi_row2.addWidget(self._kpi_3m)
        kpi_row2.addWidget(self._kpi_12m)
        kpi_row2.addWidget(self._kpi_cagr)
        kpi_row2.addStretch()
        layout.addLayout(kpi_row2)

        # Graphique évolution
        lbl_ev = QLabel("📈 Évolution du patrimoine net (weekly)")
        lbl_ev.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_ev)
        self._chart_line = PlotlyView(min_height=300)
        layout.addWidget(self._chart_line)

        # Graphiques de répartition (côte à côte)
        pie_row = QHBoxLayout()

        left_box = QGroupBox("Répartition par catégorie")
        left_box.setStyleSheet(STYLE_GROUP)
        left_v = QVBoxLayout(left_box)
        self._chart_alloc = PlotlyView(min_height=260)
        left_v.addWidget(self._chart_alloc)

        right_box = QGroupBox("Dépenses vs Revenus (12 mois)")
        right_box.setStyleSheet(STYLE_GROUP)
        right_v = QVBoxLayout(right_box)
        self._chart_cashflow = PlotlyView(min_height=260)
        right_v.addWidget(self._chart_cashflow)

        pie_row.addWidget(left_box)
        pie_row.addWidget(right_box)
        layout.addLayout(pie_row)

        # Semaine info
        self._semaine_label = QLabel()
        self._semaine_label.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._semaine_label)

        layout.addStretch()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    def _on_rebuild(self) -> None:
        self._btn_rebuild.setEnabled(False)
        self._rebuild_status.setText("Rebuild en cours...")
        self._thread = SnapshotRebuildThread(self._person_id)
        self._thread.finished.connect(self._on_rebuild_done)
        self._thread.error.connect(lambda e: self._rebuild_status.setText(f"Erreur : {e}"))
        self._thread.start()

    def _on_rebuild_done(self, result: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._rebuild_status.setText(f"Rebuild terminé ✅")
        self._load_data()

    def _load_data(self) -> None:
        try:
            rows = self._conn.execute(
                "SELECT * FROM patrimoine_snapshots_weekly WHERE person_id = ? ORDER BY week_date",
                (self._person_id,)
            ).fetchall()
            df_snap = pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()

            if df_snap is None or df_snap.empty:
                self._semaine_label.setText("Aucune donnée weekly — lancez un rebuild.")
                return

            # Dernière semaine
            last = df_snap.iloc[-1]
            net = float(last.get("patrimoine_net", 0))
            brut = float(last.get("patrimoine_brut", 0))
            liq = float(last.get("liquidites_total", 0))
            bourse = float(last.get("bourse_holdings", 0))
            credits = float(last.get("credits_remaining", 0))
            week_date = str(last.get("week_date", "—"))

            self._semaine_label.setText(f"Données au : {week_date}")
            self._kpi_net.set_content("Patrimoine net", money(net), tone="blue")
            self._kpi_brut.set_content("Patrimoine brut", money(brut), tone="green")
            self._kpi_liq.set_content("Liquidités", money(liq), tone="primary")
            self._kpi_bourse.set_content("Holdings bourse", money(bourse), tone="broker")
            self._kpi_credits.set_content("Crédits restants", money(credits), tone="red")

            # Perfs
            try:
                df_snap["week_date"] = pd.to_datetime(df_snap["week_date"], errors="coerce")
                df_snap = df_snap.dropna(subset=["week_date"]).sort_values("week_date")
                today = pd.Timestamp.today()

                def perf_pct(weeks_back):
                    target = today - pd.Timedelta(weeks=weeks_back)
                    past = df_snap[df_snap["week_date"] <= target]
                    if past.empty:
                        return None
                    val_past = float(past.iloc[-1]["patrimoine_net"])
                    if abs(val_past) < 1:
                        return None
                    return (net - val_past) / abs(val_past) * 100

                p3m = perf_pct(13)
                p12m = perf_pct(52)
                self._kpi_3m.set_content("Évolution 3 mois", f"{p3m:.1f}%" if p3m is not None else "—",
                                          delta=f"{p3m:.1f}%" if p3m is not None else None, delta_positive=(p3m or 0) >= 0)
                self._kpi_12m.set_content("Évolution 12 mois", f"{p12m:.1f}%" if p12m is not None else "—",
                                           delta=f"{p12m:.1f}%" if p12m is not None else None, delta_positive=(p12m or 0) >= 0)

                # CAGR
                if len(df_snap) >= 2:
                    first = df_snap.iloc[0]
                    val_first = float(first["patrimoine_net"])
                    n_years = (today - df_snap.iloc[0]["week_date"]).days / 365.25
                    if abs(val_first) > 1 and n_years > 0.1:
                        cagr = ((net / val_first) ** (1 / n_years) - 1) * 100
                        self._kpi_cagr.set_content("Rendement annualisé", f"{cagr:.1f}%",
                                                    delta=f"{cagr:.1f}%", delta_positive=cagr >= 0)
            except Exception as e:
                logger.warning("Calcul des performances échoué : %s", e)

            # Graphique ligne
            fig_line = px.line(df_snap, x="week_date", y="patrimoine_net",
                               template="plotly_dark",
                               labels={"week_date": "Semaine", "patrimoine_net": "Patrimoine net (€)"})
            fig_line.update_layout(**plotly_layout())
            self._chart_line.set_figure(fig_line)

            # Répartition
            alloc_data = [
                {"Catégorie": "Liquidités", "Valeur": max(0, liq)},
                {"Catégorie": "Holdings bourse", "Valeur": max(0, bourse)},
                {"Catégorie": "PE", "Valeur": max(0, float(last.get("pe_value", 0)))},
                {"Catégorie": "Entreprises", "Valeur": max(0, float(last.get("ent_value", 0)))},
            ]
            alloc_df = pd.DataFrame([a for a in alloc_data if a["Valeur"] > 0])
            if not alloc_df.empty:
                fig_alloc = px.pie(alloc_df, names="Catégorie", values="Valeur", hole=0.45,
                                   template="plotly_dark")
                fig_alloc.update_layout(**plotly_layout())
                self._chart_alloc.set_figure(fig_alloc)

            # Cashflow
            try:
                self._load_cashflow_chart()
            except Exception as e:
                logger.warning("Chargement du graphique cashflow échoué : %s", e)

        except Exception as e:
            self._semaine_label.setText(f"Erreur : {e}")

    def _load_cashflow_chart(self) -> None:
        try:
            from services.depenses_repository import depenses_par_mois
            from services.revenus_repository import revenus_par_mois

            df_dep = depenses_par_mois(self._conn, self._person_id)
            df_rev = revenus_par_mois(self._conn, self._person_id)

            if (df_dep is None or df_dep.empty) and (df_rev is None or df_rev.empty):
                return

            rows = []
            mois_set = set()
            if df_dep is not None and not df_dep.empty and "mois" in df_dep.columns:
                dep_cols = [c for c in df_dep.columns if c not in ("mois", "person_id", "person_name")]
                df_dep["total"] = df_dep[dep_cols].sum(axis=1) if dep_cols else 0
                for _, r in df_dep.iterrows():
                    mois_set.add(str(r["mois"]))

            if df_rev is not None and not df_rev.empty and "mois" in df_rev.columns:
                rev_cols = [c for c in df_rev.columns if c not in ("mois", "person_id", "person_name")]
                df_rev["total"] = df_rev[rev_cols].sum(axis=1) if rev_cols else 0

            for m in sorted(mois_set)[-12:]:
                d = 0.0
                r_val = 0.0
                if df_dep is not None and not df_dep.empty:
                    row_d = df_dep[df_dep["mois"] == m]
                    if not row_d.empty:
                        d = float(row_d.iloc[0].get("total", 0))
                if df_rev is not None and not df_rev.empty:
                    row_r = df_rev[df_rev["mois"] == m]
                    if not row_r.empty:
                        r_val = float(row_r.iloc[0].get("total", 0))
                rows.append({"Mois": m, "Revenus": r_val, "Dépenses": d})

            if rows:
                df_cf = pd.DataFrame(rows)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df_cf["Mois"], y=df_cf["Revenus"], name="Revenus", marker_color=CHART_GREEN))
                fig.add_trace(go.Bar(x=df_cf["Mois"], y=df_cf["Dépenses"], name="Dépenses", marker_color=CHART_RED))
                fig.update_layout(**plotly_layout(barmode="group",
                                  xaxis_title="Mois", yaxis_title="Montant (€)"))
                self._chart_cashflow.set_figure(fig)
        except Exception as e:
            logger.error("Erreur chargement graphique cashflow : %s", e)
