"""
Panel Taux d'Épargne — AM-26
Affiche le taux d'épargne mensuel (Revenus - Dépenses) / Revenus × 100
comme KPI principal + graphique historique sur 24 mois.
"""
import logging
import datetime
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt

from qt_ui.theme import (
    BG_PRIMARY, STYLE_TITLE, STYLE_SECTION, STYLE_STATUS, STYLE_GROUP,
    COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR, CHART_GREEN, CHART_RED,
    TEXT_MUTED, plotly_layout, plotly_time_series_layout,
)
from qt_ui.widgets import KpiCard, PlotlyView, DataTableWidget, LoadingOverlay

logger = logging.getLogger(__name__)


def _tone_for_rate(rate: float | None) -> str:
    """Couleur KPI selon le taux d'épargne."""
    if rate is None:
        return "neutral"
    if rate >= 20:
        return "success"
    if rate >= 10:
        return "green"
    if rate >= 0:
        return "neutral"
    return "alert"


def _color_for_rate(rate: float | None) -> str:
    """Couleur barre selon le taux."""
    if rate is None:
        return "#64748b"
    if rate >= 20:
        return COLOR_SUCCESS
    if rate >= 10:
        return "#86efac"   # vert clair
    if rate >= 0:
        return COLOR_WARNING
    return COLOR_ERROR


class TauxEpargnePanel(QWidget):
    """
    Panneau Taux d'Épargne (AM-26).

    Affiche :
    - KPI du mois courant + 3 derniers mois
    - Graphique barre historique (24 mois) avec zone objectif 20%
    - Tableau récapitulatif mensuel
    """

    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── Titre ─────────────────────────────────────────────────────────────
        title = QLabel("💰  Taux d'Épargne")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        subtitle = QLabel(
            "Taux = (Revenus − Dépenses) / Revenus × 100  •  Objectif FIRE : ≥ 20 %"
        )
        subtitle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(subtitle)

        # ── KPI row : mois courant + 3 mois précédents ────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self._kpi_current  = KpiCard("Mois courant",        "—", tone="neutral")
        self._kpi_m1       = KpiCard("Mois M-1",            "—", tone="neutral")
        self._kpi_m2       = KpiCard("Mois M-2",            "—", tone="neutral")
        self._kpi_avg12    = KpiCard("Moyenne 12 mois",     "—", tone="neutral")
        self._kpi_avg12_ep = KpiCard("Épargne moy. 12 mois","—", tone="neutral")

        for k in [self._kpi_current, self._kpi_m1, self._kpi_m2,
                  self._kpi_avg12, self._kpi_avg12_ep]:
            kpi_row.addWidget(k, stretch=1)

        layout.addLayout(kpi_row)

        # ── Graphique historique ───────────────────────────────────────────────
        box_hist = QGroupBox("Historique du taux d'épargne (24 derniers mois)")
        box_hist.setStyleSheet(STYLE_GROUP)
        box_hist_v = QVBoxLayout(box_hist)
        self._chart_hist = PlotlyView(min_height=360)
        box_hist_v.addWidget(self._chart_hist)
        layout.addWidget(box_hist)

        # ── Tableau récapitulatif ─────────────────────────────────────────────
        lbl_tab = QLabel("Récapitulatif mensuel")
        lbl_tab.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_tab)
        self._table = DataTableWidget()
        self._table.setMinimumHeight(220)
        layout.addWidget(self._table)

        layout.addStretch()

        # ── Overlay de chargement ─────────────────────────────────────────────
        self._overlay = LoadingOverlay(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.resize(self.size())

    # ── API ───────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    # ── Chargement ────────────────────────────────────────────────────────────

    def _load_data(self) -> None:
        self._overlay.start("Calcul du taux d'épargne…")
        try:
            from services.cashflow import compute_savings_metrics

            result = compute_savings_metrics(self._conn, self._person_id, n_mois=24)
            df = result.get("monthly_series")

            if df is None or df.empty:
                self._clear_all()
                return

            # ── KPI : mois courant et M-1, M-2 ──────────────────────────────
            today = datetime.date.today()

            def _row_for_offset(months_back: int) -> dict | None:
                """Retourne la ligne pour un mois donné."""
                d = today.replace(day=1)
                for _ in range(months_back):
                    d = (d - datetime.timedelta(days=1)).replace(day=1)
                key = d.strftime("%Y-%m-01")
                hit = df[df["mois"] == key]
                if not hit.empty:
                    return hit.iloc[0].to_dict()
                return None

            def _apply_kpi(card: KpiCard, row: dict | None, label: str, is_partial: bool = False) -> None:
                if row is None:
                    card.set_content(label, "Aucune donnée", tone="neutral")
                    return
                rate = row.get("taux_epargne")
                ep  = row.get("epargne", 0.0)
                tone = _tone_for_rate(rate)
                val  = f"{rate:.1f} %" if rate is not None else "—"
                sub  = f"Épargnés : {ep:+,.0f} €".replace(",", " ")
                if is_partial:
                    sub += "  ·  mois en cours"
                card.set_content(label, val, subtitle=sub, tone=tone)

            _apply_kpi(self._kpi_current, _row_for_offset(0), "Mois courant", is_partial=(today.day < 25))
            _apply_kpi(self._kpi_m1,       _row_for_offset(1), "Mois M-1")
            _apply_kpi(self._kpi_m2,       _row_for_offset(2), "Mois M-2")

            # ── KPI : moyenne 12 mois (depuis le service) ────────────────────
            last12 = df.tail(12)
            n_covered = int((
                (pd.to_numeric(last12["revenus"], errors="coerce").fillna(0.0) != 0.0)
                | (pd.to_numeric(last12["depenses"], errors="coerce").fillna(0.0) != 0.0)
            ).sum())
            coverage_suffix = f" ({n_covered}/12 mois couverts)"

            avg_rate = result.get("avg_rate_12m", 0.0)
            if avg_rate:
                tone_avg = _tone_for_rate(avg_rate)
                if n_covered < 8:
                    tone_avg = "neutral"
                self._kpi_avg12.set_content(
                    "Moyenne 12 mois", f"{avg_rate} %",
                    subtitle=f"Taux moyen d'épargne{coverage_suffix}", tone=tone_avg,
                )
            else:
                self._kpi_avg12.set_content(
                    "Moyenne 12 mois", "—",
                    subtitle=f"Aucune donnée{coverage_suffix}", tone="neutral",
                )

            avg_ep = result.get("avg_savings_12m", 0.0)
            tone_ep = "success" if avg_ep >= 0 else "alert"
            self._kpi_avg12_ep.set_content(
                "Épargne moy. 12 mois",
                f"{avg_ep:+,.0f} €".replace(",", " "),
                subtitle="Revenus − Dépenses / mois", tone=tone_ep,
            )

            # ── Graphique historique ─────────────────────────────────────────
            self._build_chart(df)

            # ── Tableau ──────────────────────────────────────────────────────
            df_display = df[["mois", "revenus", "depenses", "epargne", "taux_epargne"]].copy()
            df_display = df_display.sort_values("mois", ascending=False)
            df_display.columns = ["Mois", "Revenus (€)", "Dépenses (€)", "Épargne (€)", "Taux (%)"]

            for col in ["Revenus (€)", "Dépenses (€)", "Épargne (€)"]:
                df_display[col] = df_display[col].map(
                    lambda v: f"{v:,.2f}".replace(",", " ") if pd.notna(v) else "—"
                )
            df_display["Taux (%)"] = df_display["Taux (%)"].map(
                lambda v: f"{v:.1f} %" if pd.notna(v) else "—"
            )

            self._table.set_dataframe(df_display)

            # Colorier la colonne Taux
            def _color_taux(val_str):
                try:
                    v = float(str(val_str).replace(" %", "").replace(",", "."))
                    return _color_for_rate(v)
                except Exception:
                    return TEXT_MUTED

            self._table.set_column_colors({"Taux (%)": _color_taux})

        except Exception as e:
            logger.error("TauxEpargnePanel._load_data error: %s", e, exc_info=True)
        finally:
            self._overlay.stop()

    def _build_chart(self, df: pd.DataFrame) -> None:
        """Construit le graphique barre + ligne taux + zone objectif 20%."""
        try:
            df["_dt"] = pd.to_datetime(df["mois"], errors="coerce")
            df["bar_color"] = df["taux_epargne"].apply(_color_for_rate)

            fig = go.Figure()

            # Barres revenus (fond semi-transparent)
            fig.add_trace(go.Bar(
                x=df["_dt"], y=df["revenus"],
                name="Revenus", marker_color="rgba(96,165,250,0.25)",
                hovertemplate="<b>%{x|%b %Y}</b><br>Revenus : %{y:,.0f} €<extra></extra>",
            ))

            # Barres dépenses
            fig.add_trace(go.Bar(
                x=df["_dt"], y=df["depenses"],
                name="Dépenses", marker_color="rgba(239,68,68,0.35)",
                hovertemplate="<b>%{x|%b %Y}</b><br>Dépenses : %{y:,.0f} €<extra></extra>",
            ))

            # Ligne taux d'épargne (axe secondaire Y2)
            df_valid = df.dropna(subset=["taux_epargne"])
            if not df_valid.empty:
                fig.add_trace(go.Scatter(
                    x=df_valid["_dt"], y=df_valid["taux_epargne"],
                    name="Taux d'épargne", yaxis="y2",
                    mode="lines+markers",
                    line=dict(color=COLOR_SUCCESS, width=2.5),
                    marker=dict(size=7, color=df_valid["taux_epargne"].apply(_color_for_rate)),
                    hovertemplate="<b>%{x|%b %Y}</b><br>Taux : %{y:.1f} %<extra></extra>",
                ))

            # Ligne objectif 20% (en pointillés)
            if len(df) > 0:
                fig.add_hline(
                    y=20, yref="y2",
                    line=dict(color="#4ade80", width=1.5, dash="dot"),
                    annotation_text="Objectif 20 %",
                    annotation_font_color="#4ade80",
                    annotation_position="top right",
                )

            # Ligne 0% (taux neutre)
            fig.add_hline(
                y=0, yref="y2",
                line=dict(color="#64748b", width=1, dash="solid"),
            )

            fig.update_layout(
                **plotly_time_series_layout(barmode="group", margin=dict(l=10, r=10, t=40, b=10)),
                xaxis=dict(title="", showgrid=False, tickformat="%b %Y"),
                yaxis=dict(
                    title="Montant (€)", showgrid=True, gridcolor="#1e2538",
                    tickformat=",.0f", ticksuffix=" €",
                ),
                yaxis2=dict(
                    title="Taux (%)", overlaying="y", side="right",
                    showgrid=False, ticksuffix=" %",
                    zeroline=True, zerolinecolor="#334155", zerolinewidth=1,
                    range=[-10, 100]
                ),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=11),
                ),
                hovermode="x unified",
            )
            self._chart_hist.set_figure(fig)
        except Exception as e:
            logger.warning("TauxEpargnePanel._build_chart error: %s", e)

    def _clear_all(self) -> None:
        for k in [self._kpi_current, self._kpi_m1, self._kpi_m2,
                  self._kpi_avg12, self._kpi_avg12_ep]:
            k.set_content(k._title_label.text() or "—", "Aucune donnée", tone="neutral")
        self._chart_hist.clear_figure()
        self._table.set_dataframe(pd.DataFrame())
