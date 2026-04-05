"""
Panel Vue d'ensemble — dashboard patrimonial complet.
4 lignes de KPI + 4 graphiques.
"""
import logging
import math
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY, STYLE_GROUP, STYLE_SECTION,
    STYLE_SECTION_MARGIN, STYLE_STATUS, CHART_GREEN, CHART_RED,
    plotly_layout, plotly_time_series_layout, COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR, TEXT_MUTED,
)
from qt_ui.widgets import PlotlyView, KpiCard, MetricLabel, LoadingOverlay
from utils.format_monnaie import money

logger = logging.getLogger(__name__)


# ─── Helpers de formatage ──────────────────────────────────────────────────

def _pct(v) -> str:
    """Retourne 'XX.X %' ou '—'."""
    if v is None:
        return "—"
    try:
        f = float(v)
        return "—" if math.isnan(f) else f"{f:.1f} %"
    except (TypeError, ValueError):
        return "—"


def _signed_money(v) -> str:
    """Retourne '+XX XXX €' / '-XX XXX €' ou '—'."""
    if v is None:
        return "—"
    try:
        f = float(v)
        if math.isnan(f):
            return "—"
        sign = "+" if f >= 0 else ""
        return f"{sign}{f:,.0f} €".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _months_str(v) -> str:
    """Retourne 'X,X mois' ou '—'."""
    if v is None:
        return "—"
    try:
        f = float(v)
        return "—" if math.isnan(f) else f"{f:.1f} mois"
    except (TypeError, ValueError):
        return "—"


def _tone_gain(v) -> str:
    if v is None:
        return "neutral"
    return "success" if v >= 0 else "alert"


def _tone_reserve(v) -> str:
    if v is None:
        return "neutral"
    if v >= 3:
        return "success"
    if v < 1:
        return "alert"
    return "neutral"


def _tone_for_rate(rate) -> str:
    if rate is None:
        return "neutral"
    if rate >= 20:
        return "success"
    if rate >= 10:
        return "green"
    if rate >= 0:
        return "neutral"
    return "alert"


def _color_for_rate(rate) -> str:
    if rate is None:
        return "#64748b"
    if rate >= 20:
        return COLOR_SUCCESS
    if rate >= 10:
        return "#86efac"
    if rate >= 0:
        return COLOR_WARNING
    return COLOR_ERROR


# ─── Thread rebuild ────────────────────────────────────────────────────────

class SnapshotRebuildThread(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

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
                    safety_weeks=4, fallback_lookback_days=90,
                )
            self.finished.emit(str(res))
        except Exception as exc:
            self.error.emit(str(exc))


# ─── Panel principal ───────────────────────────────────────────────────────

class VueEnsemblePanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn      = conn
        self._person_id = person_id
        self._thread    = None

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────
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

        # ── Ligne 1 — KPI patrimoine ──────────────────────────────────────
        kpi_row1 = QHBoxLayout()
        self._kpi_net    = KpiCard("Patrimoine net",    "—", tone="blue")
        self._kpi_brut   = KpiCard("Patrimoine brut",   "—", tone="green")
        self._kpi_liq    = KpiCard("Liquidités",        "—", tone="primary")
        self._kpi_bourse   = KpiCard("Holdings bourse",   "—", tone="broker")
        self._kpi_immo     = KpiCard("Immobilier",        "—", tone="neutral")
        self._kpi_credits  = KpiCard("Crédits restants", "—", tone="red")
        self._kpis = [self._kpi_net, self._kpi_brut, self._kpi_liq,
                      self._kpi_bourse, self._kpi_immo, self._kpi_credits]
        for k in self._kpis:
            kpi_row1.addWidget(k)
        layout.addLayout(kpi_row1)

        # Métriques de perf (sous la ligne 1)
        kpi_perf = QHBoxLayout()
        self._kpi_3m   = MetricLabel("Évolution 3 mois",     "—")
        self._kpi_12m  = MetricLabel("Évolution 12 mois",    "—")
        self._kpi_cagr = MetricLabel("Rendement annualisé",  "—")
        kpi_perf.addWidget(self._kpi_3m)
        kpi_perf.addWidget(self._kpi_12m)
        kpi_perf.addWidget(self._kpi_cagr)
        kpi_perf.addStretch()
        layout.addLayout(kpi_perf)

        # ── Ligne 2 — Santé patrimoniale ──────────────────────────────────
        lbl_sante = QLabel("Santé patrimoniale")
        lbl_sante.setStyleSheet(STYLE_SECTION_MARGIN)
        layout.addWidget(lbl_sante)

        kpi_row2 = QHBoxLayout()
        self._kpi_endettement   = KpiCard("Taux d'endettement", "—", tone="neutral")
        self._kpi_part_liquide  = KpiCard("Part liquide",       "—", tone="neutral")
        self._kpi_expo_marches  = KpiCard("Exposition marchés", "—", tone="neutral")
        self._kpi_illiquides    = KpiCard("Actifs illiquides",  "—", tone="neutral")
        self._kpis_sante = [self._kpi_endettement, self._kpi_part_liquide,
                            self._kpi_expo_marches, self._kpi_illiquides]
        for k in self._kpis_sante:
            kpi_row2.addWidget(k)
        kpi_row2.addStretch()
        layout.addLayout(kpi_row2)

        # ── Ligne 3 — Progression réelle ──────────────────────────────────
        lbl_prog = QLabel("Progression réelle")
        lbl_prog.setStyleSheet(STYLE_SECTION_MARGIN)
        layout.addWidget(lbl_prog)

        kpi_row3 = QHBoxLayout()
        self._kpi_gain_3m          = KpiCard("Gain patrimonial 3 mois",    "—", tone="neutral")
        self._kpi_gain_12m         = KpiCard("Gain patrimonial 12 mois",   "—", tone="neutral")
        self._kpi_epargne_12m      = KpiCard("Épargne cumulée 12 mois",    "—", tone="neutral")
        self._kpi_effet_valo       = KpiCard("Effet valorisation 12 mois", "—", tone="neutral")
        self._kpis_prog = [self._kpi_gain_3m, self._kpi_gain_12m,
                           self._kpi_epargne_12m, self._kpi_effet_valo]
        for k in self._kpis_prog:
            kpi_row3.addWidget(k)
        kpi_row3.addStretch()
        layout.addLayout(kpi_row3)

        # ── Ligne 4 — Pilotage personnel ──────────────────────────────────
        lbl_pilotage = QLabel("Pilotage personnel")
        lbl_pilotage.setStyleSheet(STYLE_SECTION_MARGIN)
        layout.addWidget(lbl_pilotage)

        kpi_row4 = QHBoxLayout()
        self._kpi_avg12       = KpiCard("Taux moy. épargne 12 mois",   "—", tone="neutral")
        self._kpi_avg12_ep    = KpiCard("Capacité d'épargne moyenne",  "—", tone="neutral")
        self._kpi_reserve     = KpiCard("Réserve de sécurité",         "—", tone="neutral")
        self._kpis_pilot = [self._kpi_avg12, self._kpi_avg12_ep, self._kpi_reserve]
        for k in self._kpis_pilot:
            kpi_row4.addWidget(k)
        kpi_row4.addStretch()
        layout.addLayout(kpi_row4)

        # ── Graphique évolution ───────────────────────────────────────────
        lbl_ev = QLabel("📈 Évolution du patrimoine net (weekly)")
        lbl_ev.setStyleSheet(STYLE_SECTION_MARGIN)
        layout.addWidget(lbl_ev)
        self._chart_line = PlotlyView(min_height=350)
        layout.addWidget(self._chart_line)

        # ── Graphiques allocation + cashflow côte à côte ──────────────────
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

        # ── Graphique taux d'épargne ──────────────────────────────────────
        epargne_box = QGroupBox("Taux d'épargne (24 derniers mois)")
        epargne_box.setStyleSheet(STYLE_GROUP)
        epargne_box_v = QVBoxLayout(epargne_box)
        self._chart_epargne = PlotlyView(min_height=280)
        epargne_box_v.addWidget(self._chart_epargne)
        layout.addWidget(epargne_box)

        # ── Statut semaine ────────────────────────────────────────────────
        self._semaine_label = QLabel()
        self._semaine_label.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._semaine_label)

        # ── Alerte FX manquants ───────────────────────────────────────────
        self._fx_alert_label = QLabel()
        self._fx_alert_label.setStyleSheet(
            "color: #f59e0b; background: #1c1a10; border: 1px solid #f59e0b; "
            "border-radius: 4px; padding: 4px 8px; font-size: 12px;"
        )
        self._fx_alert_label.setVisible(False)
        layout.addWidget(self._fx_alert_label)

        layout.addStretch()

        self._overlay = LoadingOverlay(self)

    # ── Resize ────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    # ── API publique ──────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    # ── Rebuild ───────────────────────────────────────────────────────────

    def _on_rebuild(self) -> None:
        self._btn_rebuild.setEnabled(False)
        self._rebuild_status.setText("Rebuild en cours...")
        self._thread = SnapshotRebuildThread(self._person_id)
        self._thread.finished.connect(self._on_rebuild_done)
        self._thread.error.connect(
            lambda e: self._rebuild_status.setText(f"Erreur : {e}")
        )
        self._thread.start()

    def _on_rebuild_done(self, result: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._rebuild_status.setText("Rebuild terminé ✅")
        self._load_data()

    # ── Chargement principal ──────────────────────────────────────────────

    def _load_data(self) -> None:
        # ── 1. Activation des Skeletons ───────────────────────────────────
        all_widgets = (self._kpis + self._kpis_sante + self._kpis_prog + 
                       self._kpis_pilot + [self._kpi_3m, self._kpi_12m, self._kpi_cagr])
        for w in all_widgets:
            if hasattr(w, "set_loading"):
                w.set_loading(True)
        
        self._chart_line.set_loading(True)
        self._chart_alloc.set_loading(True)
        self._chart_cashflow.set_loading(True)
        self._chart_epargne.set_loading(True)

        self._overlay.start("Chargement des données…", blur=True)
        try:
            from services.vue_ensemble_metrics import get_vue_ensemble_metrics
            m = get_vue_ensemble_metrics(self._conn, self._person_id)

            if not m:
                self._semaine_label.setText(
                    "Aucune donnée weekly — lancez un rebuild."
                )
                return

            self._semaine_label.setText(f"Données au : {m.get('week_date', '—')}")

            # ── Ligne 1 ───────────────────────────────────────────────────
            self._kpi_net.set_content(
                "Patrimoine net", money(m["net"]), tone="blue"
            )
            self._kpi_brut.set_content(
                "Patrimoine brut", money(m["brut"]), tone="green"
            )
            self._kpi_liq.set_content(
                "Liquidités", money(m["liq"]), tone="primary"
            )
            self._kpi_bourse.set_content(
                "Holdings bourse", money(m["bourse"]), tone="broker"
            )
            self._kpi_immo.set_content(
                "Immobilier", money(m["immo_value"]), tone="neutral"
            )
            self._kpi_credits.set_content(
                "Crédits restants", money(m["credits"]), tone="red"
            )

            # Perfs (MetricLabel)
            self._fill_perfs(m)

            # ── Ligne 2 — Santé patrimoniale ──────────────────────────────
            self._kpi_endettement.set_content(
                "Taux d'endettement",
                _pct(m.get("taux_endettement")),
                subtitle="Crédits / Patrimoine brut",
                tone="neutral",
            )
            self._kpi_part_liquide.set_content(
                "Part liquide",
                _pct(m.get("part_liquide")),
                subtitle="Liquidités / Patrimoine brut",
                tone="neutral",
            )
            self._kpi_expo_marches.set_content(
                "Exposition marchés",
                _pct(m.get("exposition_marches")),
                subtitle="(Bourse + PE) / Patrimoine brut",
                tone="neutral",
            )
            self._kpi_illiquides.set_content(
                "Actifs illiquides",
                _pct(m.get("actifs_illiquides")),
                subtitle="(Entreprises + PE + Immobilier) / Patrimoine brut",
                tone="neutral",
            )

            # ── Ligne 3 — Progression réelle ──────────────────────────────
            gain_3m  = m.get("gain_3m")
            gain_12m = m.get("gain_12m")
            ep_12m   = m.get("epargne_12m")
            effet    = m.get("effet_valorisation_12m")

            self._kpi_gain_3m.set_content(
                "Gain patrimonial 3 mois",
                _signed_money(gain_3m),
                subtitle="Patrimoine net vs −13 semaines",
                tone=_tone_gain(gain_3m),
            )
            self._kpi_gain_12m.set_content(
                "Gain patrimonial 12 mois",
                _signed_money(gain_12m),
                subtitle="Patrimoine net vs −52 semaines",
                tone=_tone_gain(gain_12m),
            )
            self._kpi_epargne_12m.set_content(
                "Épargne cumulée 12 mois",
                _signed_money(ep_12m),
                subtitle="Σ (Revenus − Dépenses) sur 12 mois",
                tone=_tone_gain(ep_12m),
            )
            self._kpi_effet_valo.set_content(
                "Effet valorisation 12 mois",
                _signed_money(effet),
                subtitle="Gain 12m − Épargne 12m",
                tone=_tone_gain(effet),
            )

            # ── Ligne 4 — Pilotage personnel ──────────────────────────────
            taux_avg = m.get("taux_epargne_avg")
            cap_avg  = m.get("capacite_epargne_avg")
            reserve  = m.get("reserve_securite")

            self._kpi_avg12.set_content(
                "Taux moy. épargne 12 mois",
                _pct(taux_avg),
                subtitle="Taux moyen d'épargne",
                tone=_tone_for_rate(taux_avg),
            )
            self._kpi_avg12_ep.set_content(
                "Capacité d'épargne moyenne",
                _signed_money(cap_avg),
                subtitle="Revenus − Dépenses / mois (moy.)",
                tone=_tone_gain(cap_avg),
            )
            self._kpi_reserve.set_content(
                "Réserve de sécurité",
                _months_str(reserve),
                subtitle="Liquidités / Dépenses mensuelles moy.",
                tone=_tone_reserve(reserve),
            )

            # ── Graphiques ────────────────────────────────────────────────
            self._build_line_chart(m)
            self._build_alloc_chart(m)
            self._build_cashflow_chart(m)
            self._build_epargne_chart(m)

            # ── Alerte taux FX manquants ──────────────────────────────────
            from services import market_history as _mh
            missing_fx = _mh.get_and_clear_missing_fx()
            if missing_fx:
                pairs_str = ", ".join(f"{a}→{b}" for a, b in sorted(missing_fx))
                self._fx_alert_label.setText(
                    f"⚠️  Taux FX manquants — certains actifs valorisés à 0 € : {pairs_str}"
                )
                self._fx_alert_label.setVisible(True)
            else:
                self._fx_alert_label.setVisible(False)

        except Exception as exc:
            logger.exception("VueEnsemblePanel._load_data error")
            self._semaine_label.setText(f"Erreur : {exc}")
        finally:
            # ── 2. Désactivation des Skeletons ──────────────────────────────
            for w in all_widgets:
                if hasattr(w, "set_loading"):
                    w.set_loading(False)
            
            self._chart_line.set_loading(False)
            self._chart_alloc.set_loading(False)
            self._chart_cashflow.set_loading(False)
            self._chart_epargne.set_loading(False)

            self._overlay.stop()

    # ── Métriques de performance (MetricLabel) ────────────────────────────

    def _fill_perfs(self, m: dict) -> None:
        try:
            p3m = m.get("perf_3m_pct")
            p12m = m.get("perf_12m_pct")
            cagr = m.get("cagr_pct")

            self._kpi_3m.set_content(
                "Évolution 3 mois",
                _pct(p3m),
                delta=_pct(p3m) if p3m is not None else "",
                delta_positive=(p3m or 0) >= 0,
            )
            self._kpi_12m.set_content(
                "Évolution 12 mois",
                _pct(p12m),
                delta=_pct(p12m) if p12m is not None else "",
                delta_positive=(p12m or 0) >= 0,
            )

            if cagr is not None:
                self._kpi_cagr.set_content(
                    "Rendement annualisé",
                    _pct(cagr),
                    delta=_pct(cagr),
                    delta_positive=cagr >= 0,
                )
            else:
                self._kpi_cagr.set_content("Rendement annualisé", "—")
        except Exception as exc:
            logger.warning("_fill_perfs error: %s", exc)

    # ── Graphique ligne ───────────────────────────────────────────────────

    def _build_line_chart(self, m: dict) -> None:
        try:
            df = m.get("df_snap")
            if df is None or df.empty:
                return
            fig = px.line(
                df, x="_dt", y="patrimoine_net",
                template="plotly_dark",
                labels={"_dt": "Semaine", "patrimoine_net": "Patrimoine net (€)"},
            )
            fig.update_layout(**plotly_time_series_layout())
            self._chart_line.set_figure(fig)
        except Exception as exc:
            logger.warning("_build_line_chart error: %s", exc)

    # ── Graphique allocation ──────────────────────────────────────────────

    def _build_alloc_chart(self, m: dict) -> None:
        try:
            alloc_data = [
                {"Catégorie": "Liquidités",     "Valeur": max(0.0, m["liq"])},
                {"Catégorie": "Holdings bourse","Valeur": max(0.0, m["bourse"])},
                {"Catégorie": "Immobilier",     "Valeur": max(0.0, m["immo_value"])},
                {"Catégorie": "PE",             "Valeur": max(0.0, m["pe_value"])},
                {"Catégorie": "Entreprises",    "Valeur": max(0.0, m["ent_value"])},
            ]
            alloc_df = pd.DataFrame([a for a in alloc_data if a["Valeur"] > 0])
            if alloc_df.empty:
                return
            fig = px.pie(
                alloc_df, names="Catégorie", values="Valeur",
                hole=0.45, template="plotly_dark",
            )
            fig.update_layout(**plotly_layout())
            self._chart_alloc.set_figure(fig)
        except Exception as exc:
            logger.warning("_build_alloc_chart error: %s", exc)

    # ── Graphique cashflow ────────────────────────────────────────────────

    def _build_cashflow_chart(self, m: dict) -> None:
        try:
            df_cf = m.get("df_cashflow", pd.DataFrame())
            if df_cf is None or df_cf.empty:
                return
            last12 = df_cf.tail(12).copy()
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=last12["mois"], y=last12["revenus"],
                name="Revenus", marker_color=CHART_GREEN,
            ))
            fig.add_trace(go.Bar(
                x=last12["mois"], y=last12["depenses"],
                name="Dépenses", marker_color=CHART_RED,
            ))
            fig.update_layout(
                **plotly_layout(barmode="group",
                                xaxis_title="Mois", yaxis_title="Montant (€)")
            )
            self._chart_cashflow.set_figure(fig)
        except Exception as exc:
            logger.warning("_build_cashflow_chart error: %s", exc)

    # ── Graphique taux d'épargne ──────────────────────────────────────────

    def _build_epargne_chart(self, m: dict) -> None:
        try:
            df_cf = m.get("df_cashflow", pd.DataFrame())
            if df_cf is None or df_cf.empty:
                return
            df = df_cf.copy()
            df["mois_label"] = (
                pd.to_datetime(df["mois"], errors="coerce")
                .dt.strftime("%b %Y")
            )

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df["mois_label"], y=df["revenus"],
                name="Revenus",
                marker_color="rgba(96,165,250,0.25)",
                hovertemplate="<b>%{x}</b><br>Revenus : %{y:,.0f} €<extra></extra>",
            ))
            fig.add_trace(go.Bar(
                x=df["mois_label"], y=df["depenses"],
                name="Dépenses",
                marker_color="rgba(239,68,68,0.35)",
                hovertemplate="<b>%{x}</b><br>Dépenses : %{y:,.0f} €<extra></extra>",
            ))

            df_valid = df.dropna(subset=["taux_epargne"])
            if not df_valid.empty:
                fig.add_trace(go.Scatter(
                    x=df_valid["mois_label"], y=df_valid["taux_epargne"],
                    name="Taux d'épargne", yaxis="y2",
                    mode="lines+markers",
                    line=dict(color=COLOR_SUCCESS, width=2.5),
                    marker=dict(
                        size=7,
                        color=df_valid["taux_epargne"].apply(_color_for_rate),
                    ),
                    hovertemplate="<b>%{x}</b><br>Taux : %{y:.1f} %<extra></extra>",
                ))

            fig.add_hline(
                y=20, yref="y2",
                line=dict(color="#4ade80", width=1.5, dash="dot"),
                annotation_text="Objectif 20 %",
                annotation_font_color="#4ade80",
                annotation_position="top right",
            )
            fig.add_hline(
                y=0, yref="y2",
                line=dict(color="#64748b", width=1, dash="solid"),
            )
            fig.update_layout(
                **plotly_layout(
                    barmode="group",
                    margin=dict(l=10, r=10, t=10, b=10),
                ),
                xaxis=dict(title="", showgrid=False, tickangle=-35),
                yaxis=dict(
                    title="Montant (€)", showgrid=True, gridcolor="#1e2538",
                    tickformat=",.0f", ticksuffix=" €",
                ),
                yaxis2=dict(
                    title="Taux (%)", overlaying="y", side="right",
                    showgrid=False, ticksuffix=" %",
                    zeroline=True, zerolinecolor="#334155", zerolinewidth=1,
                ),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=11),
                ),
                hovermode="x unified",
            )
            self._chart_epargne.set_figure(fig)
        except Exception as exc:
            logger.warning("_build_epargne_chart error: %s", exc)
