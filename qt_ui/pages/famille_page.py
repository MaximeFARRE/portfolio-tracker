"""
Page Famille — remplace pages/1_Famille.py
Contient 3 onglets : Snapshots weekly, Diagnostic, Flux (V1)
"""
import logging
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from time import monotonic
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
    STYLE_TITLE, STYLE_SECTION, STYLE_SECTION_MARGIN, STYLE_STATUS,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_WARNING, STYLE_STATUS_ERROR, COLOR_SUCCESS,
    plotly_layout,
)
from utils.format_monnaie import money

logger = logging.getLogger(__name__)


def _empty_figure(msg: str = "Aucune donnée disponible") -> go.Figure:
    """Figure Plotly vide avec un message centré — remplace un widget blank."""
    fig = go.Figure()
    fig.add_annotation(
        text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, font=dict(size=13, color="#64748b"),
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


def _compute_var_pct(current: float, previous: float) -> float | None:
    try:
        cur = float(current)
        prev = float(previous)
    except Exception:
        return None
    if prev <= 0:
        return None
    return (cur / prev - 1.0) * 100.0


def _fmt_var_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):+.1f}%"


# ─── Worker threads ──────────────────────────────────────────────────────────

class RebuildFamilleThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, person_ids: list):
        super().__init__()
        self._person_ids = person_ids
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.progress.emit("Rebuild famille en cours...")
            from services import family_snapshots as fs
            from services.db import get_conn
            with get_conn() as local_conn:
                if self._is_cancelled:
                    self.finished.emit("Annulé")
                    return
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
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            from services import snapshots as wk_snap
            from services import family_snapshots as fs
            from services.db import get_conn
            msgs = []
            total = len(self._person_ids)
            with get_conn() as local_conn:
                for i, pid in enumerate(self._person_ids):
                    if self._is_cancelled:
                        msgs.append("Annulé")
                        break
                    self.progress.emit(f"Rebuild personne {i+1}/{total}...")
                    r = wk_snap.rebuild_snapshots_person_from_last(
                        local_conn, person_id=pid,
                        safety_weeks=self._safety_weeks,
                        fallback_lookback_days=90,
                        cancel_check=lambda: self._is_cancelled
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


class FamilyFullHistoryRebuildThread(QThread):
    """Reconstruit tous les snapshots famille depuis la premiere transaction."""
    progress = pyqtSignal(str)          # message lisible pour le label UI
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, person_ids: list):
        super().__init__()
        self._person_ids = person_ids
        self._cancelled = False

    def cancel(self) -> None:
        """Demande l'arret propre."""
        self._cancelled = True

    def run(self):
        try:
            from services import family_snapshots as fs
            from services.db import get_conn
            with get_conn() as local_conn:
                res = fs.rebuild_family_weekly_full_history(
                    local_conn,
                    person_ids=self._person_ids,
                    cancel_check=lambda: self._cancelled,
                    progress_callback=self._on_progress,
                    family_id=1,
                )
            self.finished.emit(str(res))
        except Exception as exc:
            self.error.emit(str(exc))

    def _on_progress(
        self,
        current_week: str,
        current_year: int,
        week_index: int,
        total_weeks: int,
        person_index: int,
        total_people: int,
    ) -> None:
        pct = int(week_index / total_weeks * 100) if total_weeks > 0 else 0
        msg = (
            f"⏳ Reconstruction {current_year}… "
            f"Personne {person_index + 1}/{total_people} — "
            f"{week_index}/{total_weeks} semaines ({pct}%)"
        )
        self.progress.emit(msg)


# ─── Panel : Famille Dashboard ────────────────────────────────────────────────

class FamilleDashboardPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._thread = None
        self._last_refresh_ts = 0.0
        self._refresh_ttl_s = 8.0

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

        self._btn_rebuild_full = QPushButton("🗓️  Rebuild complet (dès la 1re tx)")
        self._btn_rebuild_full.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_rebuild_full.setToolTip(
            "Reconstruit l'historique complet famille depuis la date de la première "
            "transaction de l'une ou l'autre personne.\nPeut prendre plusieurs minutes."
        )
        self._btn_rebuild_full.clicked.connect(self._on_rebuild_full)
        top_row.addWidget(self._btn_rebuild_full)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # Mode indéterminé
        self._progress_bar.setStyleSheet(STYLE_PROGRESS)
        self._progress_bar.setMaximumWidth(200)
        self._progress_bar.hide()
        top_row.addWidget(self._progress_bar)

        self._rebuild_status = QLabel("Vue Famille = snapshots famille weekly (fallback: somme snapshots personnes).")
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        top_row.addWidget(self._rebuild_status, 1)
        self._layout.addLayout(top_row)

        # Thread rebuild complet
        self._thread_full: FamilyFullHistoryRebuildThread | None = None

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

        # Allocation patrimoniale : évolution + détail
        alloc_row = QHBoxLayout()

        area_box = QGroupBox("📊 Évolution allocation patrimoniale")
        area_box.setStyleSheet(STYLE_GROUP)
        area_v = QVBoxLayout(area_box)
        self._chart_alloc_area = PlotlyView(min_height=300)
        area_v.addWidget(self._chart_alloc_area)

        tree_box = QGroupBox("🧭 Treemap allocation détaillée")
        tree_box.setStyleSheet(STYLE_GROUP)
        tree_v = QVBoxLayout(tree_box)
        self._chart_alloc_treemap = PlotlyView(min_height=300)
        tree_v.addWidget(self._chart_alloc_treemap)

        alloc_row.addWidget(area_box)
        alloc_row.addWidget(tree_box)
        self._layout.addLayout(alloc_row)

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

        # Alerte personnes sans snapshot (DQ-08)
        self._missing_persons_label = QLabel()
        self._missing_persons_label.setStyleSheet(STYLE_STATUS_WARNING)
        self._missing_persons_label.setWordWrap(True)
        self._missing_persons_label.setVisible(False)
        self._layout.addWidget(self._missing_persons_label)

        self._layout.addStretch()

    def _build_line_chart(self, df_family: pd.DataFrame) -> None:
        """Courbe net avec tooltip enrichi (détail + variation hebdo)."""
        df_plot = df_family.copy()
        df_plot["week_date"] = pd.to_datetime(df_plot["week_date"], errors="coerce")
        df_plot = df_plot.dropna(subset=["week_date"]).sort_values("week_date").reset_index(drop=True)
        if df_plot.empty:
            self._chart_line.set_figure(_empty_figure("Aucune donnée d'évolution disponible"))
            return

        for col in [
            "patrimoine_brut",
            "liquidites_total",
            "bourse_holdings",
            "pe_value",
            "ent_value",
            "immobilier_value",
            "credits_remaining",
        ]:
            if col not in df_plot.columns:
                df_plot[col] = 0.0

        df_plot["var_net_pct"] = df_plot["patrimoine_net"].shift(0).combine(
            df_plot["patrimoine_net"].shift(1),
            lambda cur, prev: _compute_var_pct(cur, prev),
        )
        df_plot["var_net_txt"] = df_plot["var_net_pct"].apply(_fmt_var_pct)

        custom = df_plot[
            [
                "patrimoine_brut",
                "liquidites_total",
                "bourse_holdings",
                "pe_value",
                "ent_value",
                "immobilier_value",
                "credits_remaining",
                "var_net_txt",
            ]
        ].to_numpy()

        fig_line = go.Figure()
        fig_line.add_trace(
            go.Scatter(
                x=df_plot["week_date"],
                y=df_plot["patrimoine_net"],
                mode="lines+markers",
                line=dict(width=2.4),
                marker=dict(size=6),
                customdata=custom,
                hovertemplate=(
                    "<b>%{x|%d/%m/%Y}</b>"
                    "<br>Net: %{y:,.0f} €"
                    "<br>Brut: %{customdata[0]:,.0f} €"
                    "<br>Liquidités: %{customdata[1]:,.0f} €"
                    "<br>Bourse: %{customdata[2]:,.0f} €"
                    "<br>Private Equity: %{customdata[3]:,.0f} €"
                    "<br>Entreprises: %{customdata[4]:,.0f} €"
                    "<br>Immobilier: %{customdata[5]:,.0f} €"
                    "<br>Crédits restants: %{customdata[6]:,.0f} €"
                    "<br>Variation hebdo: %{customdata[7]}"
                    "<extra></extra>"
                ),
            )
        )
        fig_line.update_layout(
            **plotly_layout(
                margin=dict(l=0, r=0, t=20, b=0),
                xaxis_title="Semaine",
                yaxis_title="Patrimoine net (€)",
                hovermode="x unified",
            )
        )
        self._chart_line.set_figure(fig_line)

    def _build_alloc_chart(self, alloc: dict, df_family: pd.DataFrame) -> None:
        """Pie allocation enrichi avec part + variation hebdo par catégorie."""
        from services import family_dashboard as fd

        alloc_df = fd.prepare_family_alloc_pie_data(df_family, alloc)
        if alloc_df.empty:
            self._chart_alloc.set_figure(_empty_figure("Aucune allocation disponible"))
            return

        alloc_df["var_txt"] = alloc_df["var_pct"].apply(_fmt_var_pct)

        fig_alloc = px.pie(alloc_df, names="Catégorie", values="Valeur", hole=0.45)
        fig_alloc.update_traces(
            customdata=alloc_df[["part_pct", "var_txt"]].to_numpy(),
            hovertemplate=(
                "<b>%{label}</b>"
                "<br>Montant: %{value:,.0f} €"
                "<br>Part: %{customdata[0]:.1f}%"
                "<br>Variation hebdo: %{customdata[1]}"
                "<extra></extra>"
            ),
        )
        fig_alloc.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=10, b=10)))
        self._chart_alloc.set_figure(fig_alloc)

    def _build_people_pie(self, df_people: pd.DataFrame) -> None:
        """Pie par personne enrichi avec part + exposition bourse."""
        person_alloc = df_people[["Personne", "Net (€)", "Bourse (€)", "% Expo Bourse"]].copy()
        person_alloc = person_alloc[person_alloc["Net (€)"] > 0]
        if person_alloc.empty:
            self._chart_people.set_figure(_empty_figure("Aucune donnée personne disponible"))
            return

        total_net = float(person_alloc["Net (€)"].sum())
        person_alloc["part_famille_pct"] = (
            person_alloc["Net (€)"] / total_net * 100.0
        ).round(2) if total_net > 0 else 0.0

        fig_p = px.pie(person_alloc, names="Personne", values="Net (€)", hole=0.45)
        fig_p.update_traces(
            customdata=person_alloc[["part_famille_pct", "Bourse (€)", "% Expo Bourse"]].to_numpy(),
            hovertemplate=(
                "<b>%{label}</b>"
                "<br>Patrimoine net: %{value:,.0f} €"
                "<br>Part famille: %{customdata[0]:.1f}%"
                "<br>Bourse: %{customdata[1]:,.0f} €"
                "<br>Expo bourse: %{customdata[2]:.1f}%"
                "<extra></extra>"
            ),
        )
        fig_p.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=10, b=10)))
        self._chart_people.set_figure(fig_p)

    def _build_allocation_area_chart(self, df_family: pd.DataFrame) -> None:
        """AM-05 : Stacked area allocation patrimoniale avec tooltips enrichis."""
        from services import family_dashboard as fd

        melt = fd.prepare_family_area_chart_data(df_family)
        if melt.empty:
            self._chart_alloc_area.set_figure(_empty_figure("Aucune donnée d'allocation disponible"))
            return

        melt["var_txt"] = melt["var_pct"].apply(_fmt_var_pct)

        fig_area = px.area(
            melt,
            x="week_date",
            y="Valeur",
            color="Catégorie",
            category_orders={"Catégorie": list(fd.ALLOC_CATEGORY_MAP.keys())},
            labels={"week_date": "Semaine", "Valeur": "Montant (€)"},
        )

        for trace in fig_area.data:
            cat = trace.name
            dcat = melt[melt["Catégorie"] == cat].sort_values("week_date")
            trace.customdata = dcat[["part_pct", "var_txt"]].to_numpy()
            trace.hovertemplate = (
                "<b>%{x|%d/%m/%Y}</b>"
                "<br>%{fullData.name}: %{y:,.0f} €"
                "<br>Part du total: %{customdata[0]:.1f}%"
                "<br>Variation hebdo: %{customdata[1]}"
                "<extra></extra>"
            )

        fig_area.update_layout(
            **plotly_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Semaine",
                yaxis_title="Montant (€)",
                hovermode="x unified",
                legend_title_text="Catégorie",
            )
        )
        self._chart_alloc_area.set_figure(fig_area)

    def _build_allocation_treemap(
        self,
        df_people: pd.DataFrame,
        df_people_prev: pd.DataFrame | None = None,
    ) -> None:
        """AM-06 : Treemap allocation détaillée par personne et catégorie."""
        from services import family_dashboard as fd

        tree_df = fd.prepare_family_treemap_data(df_people, df_people_prev)
        if tree_df.empty:
            self._chart_alloc_treemap.set_figure(_empty_figure("Aucune donnée de répartition disponible"))
            return

        tree_df["var_txt"] = tree_df["var_pct"].apply(_fmt_var_pct)

        fig_tree = px.treemap(
            tree_df,
            path=["Portefeuille", "Personne", "Catégorie"],
            values="Valeur",
            color="Catégorie",
            custom_data=["Part famille (%)", "Part personne (%)", "var_txt"],
        )
        fig_tree.update_traces(
            hovertemplate=(
                "<b>%{label}</b>"
                "<br>Montant: %{value:,.0f} €"
                "<br>Part parent: %{percentParent}"
                "<br>Part famille: %{customdata[0]}%"
                "<br>Part personne: %{customdata[1]}%"
                "<br>Variation hebdo: %{customdata[2]}"
                "<extra></extra>"
            ),
        )
        fig_tree.update_layout(**plotly_layout(margin=dict(l=10, r=10, t=10, b=10)))
        self._chart_alloc_treemap.set_figure(fig_tree)

    def refresh(self, force: bool = False) -> None:
        if not force and (monotonic() - self._last_refresh_ts) <= self._refresh_ttl_s:
            return
        try:
            from services import family_dashboard as fd
            people = fd.get_people(self._conn)
            if people.empty:
                self._title_label.setStyleSheet(STYLE_STATUS_WARNING)
                self._title_label.setText("⚠️  Aucune personne en base.")
                self._people_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucune donnée personne à afficher."}]))
                return
            person_ids = [int(x) for x in people["id"].tolist()]

            df_family = fd.get_family_series(self._conn, person_ids=person_ids, family_id=1)
            if df_family.empty:
                self._title_label.setStyleSheet(STYLE_STATUS_WARNING)
                self._title_label.setText("⚠️  Aucune donnée weekly — lancez un rebuild.")
                self._people_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucune donnée weekly disponible."}]))
                return

            self._title_label.setStyleSheet(STYLE_TITLE)

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

            # Courbe (tooltips enrichis)
            self._build_line_chart(df_family)

            # Pie allocation (tooltips enrichis)
            alloc = fd.compute_allocations_family(df_family)
            self._build_alloc_chart(alloc, df_family)
            self._build_allocation_area_chart(df_family)

            # Pie personnes
            df_people = pd.DataFrame()
            people_by_week: dict[pd.Timestamp, pd.DataFrame] = {}

            def _people_for_week(week: pd.Timestamp) -> pd.DataFrame:
                cached_df = people_by_week.get(week)
                if cached_df is not None:
                    return cached_df
                built_df = fd.compute_people_table(self._conn, people, week)
                people_by_week[week] = built_df
                return built_df

            if common_week is not None:
                df_people = _people_for_week(common_week)
                if not df_people.empty:
                    self._build_people_pie(df_people)
                    self._people_table.set_dataframe(df_people)
                else:
                    self._people_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucune donnée personne sur la semaine commune."}]))
                # Alerte DQ-08 : personnes sans snapshot à la semaine commune
                missing = fd.get_people_without_snapshot(people, df_people)
                if missing:
                    self._missing_persons_label.setText(
                        f"⚠️  Snapshot manquant pour : {', '.join(missing)} — "
                        f"ces personnes sont exclues du tableau et des graphiques."
                    )
                    self._missing_persons_label.setVisible(True)
                else:
                    self._missing_persons_label.setVisible(False)
            else:
                self._people_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Semaine commune introuvable."}]))
                self._missing_persons_label.setVisible(False)

            # Treemap détaillée (avec variation hebdo si semaine précédente dispo)
            if not df_people.empty:
                prev_week = None
                if len(df_family) >= 2:
                    df_dates = pd.to_datetime(df_family["week_date"], errors="coerce").dropna().sort_values().unique()
                    if len(df_dates) >= 2:
                        prev_week = pd.Timestamp(df_dates[-2])
                df_people_prev = _people_for_week(prev_week) if prev_week is not None else pd.DataFrame()
                self._build_allocation_treemap(df_people, df_people_prev)

            # Leaderboards
            if common_week is not None:
                boards = fd.compute_leaderboards(self._conn, people, person_ids, common_week)
                html_parts = []
                medals = ["🥇", "🥈", "🥉"]

                top_net = boards.get("top_net")
                if top_net is not None and len(top_net) > 0:
                    html_parts.append("<b>🥇 Patrimoine net (Top 3)</b><br>")
                    for i, row in top_net.iterrows():
                        import html
                        m = medals[i] if i < 3 else "•"
                        html_parts.append(f"{m} <b>{html.escape(str(row['Personne']))}</b> — {money(float(row['Net (€)']))}<br>")

                top3 = boards.get("top_perf_3m", [])
                if top3:
                    html_parts.append("<br><b>🚀 Progression 3 mois (Top 3)</b><br>")
                    for i, (name, val) in enumerate(top3):
                        import html
                        m = medals[i]
                        html_parts.append(f"{m} <b>{html.escape(str(name))}</b> — {val:.1f}%<br>")

                self._leaderboard_label.setText("".join(html_parts))

            self._last_refresh_ts = monotonic()
        except Exception as e:
            self._title_label.setStyleSheet(STYLE_STATUS_ERROR)
            self._title_label.setText(f"❌ Erreur de chargement : {e}")

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
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        self._rebuild_status.setText("⏳ Rebuild en cours...")

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
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
        self._rebuild_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._rebuild_status.setText(f"✅ Rebuild terminé — {result}")
        self.refresh(force=True)

    def _on_rebuild_error(self, err: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._progress_bar.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
        self._rebuild_status.setText(f"❌ Erreur : {err}")

    # ── Rebuild complet (depuis la première transaction) ──────────────────

    def _on_rebuild_full(self) -> None:
        """Lance le rebuild complet famille depuis la premiere transaction."""
        if self._thread_full and self._thread_full.isRunning():
            self._thread_full.cancel()
            self._btn_rebuild_full.setText("🗓️  Rebuild complet (dès la 1re tx)")
            self._btn_rebuild_full.setEnabled(False)
            self._rebuild_status.setText("⏸ Annulation en cours…")
            return

        try:
            from services import family_dashboard as fd
            people = fd.get_people(self._conn)
            person_ids = [int(x) for x in people["id"].tolist()]
        except Exception as exc:
            logger.error("Erreur récupération personnes rebuild complet : %s", exc)
            person_ids = []

        if not person_ids:
            self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._rebuild_status.setText("❌ Aucune personne trouvée.")
            return

        self._btn_rebuild.setEnabled(False)
        self._btn_rebuild_full.setText("⏹ Annuler le rebuild")
        self._progress_bar.show()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_WARNING)
        self._rebuild_status.setText("⏳ Démarrage du rebuild complet famille…")

        self._thread_full = FamilyFullHistoryRebuildThread(person_ids)
        self._thread_full.progress.connect(self._on_rebuild_full_progress)
        self._thread_full.finished.connect(self._on_rebuild_full_done)
        self._thread_full.error.connect(self._on_rebuild_full_error)
        self._thread_full.start()

    def _on_rebuild_full_progress(self, msg: str) -> None:
        self._rebuild_status.setText(msg)

    def _on_rebuild_full_done(self, result: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._btn_rebuild_full.setText("🗓️  Rebuild complet (dès la 1re tx)")
        self._btn_rebuild_full.setEnabled(True)
        self._progress_bar.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._rebuild_status.setText("✅ Rebuild complet famille terminé")
        self.refresh(force=True)

    def _on_rebuild_full_error(self, err: str) -> None:
        self._btn_rebuild.setEnabled(True)
        self._btn_rebuild_full.setText("🗓️  Rebuild complet (dès la 1re tx)")
        self._btn_rebuild_full.setEnabled(True)
        self._progress_bar.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
        self._rebuild_status.setText(f"❌ Erreur rebuild complet : {err}")


# ─── Panel : Data Health ──────────────────────────────────────────────────────

class DataHealthPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._thread = None
        self._last_refresh_ts = 0.0
        self._refresh_ttl_s = 8.0

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
        self._safety_combo.currentIndexChanged.connect(lambda _: self.refresh(force=True))
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
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        btn_row.addWidget(self._rebuild_status)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Marché
        mkt_label = QLabel("📡 Marché (weekly)")
        mkt_label.setStyleSheet(STYLE_SECTION_MARGIN)
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
        snap_label.setStyleSheet(STYLE_SECTION_MARGIN)
        layout.addWidget(snap_label)
        self._snap_table = DataTableWidget()
        self._snap_table.setMinimumHeight(150)
        layout.addWidget(self._snap_table)

        # Tickers sans prix
        tick_label = QLabel("🧾 Tickers sans prix weekly")
        tick_label.setStyleSheet(STYLE_SECTION_MARGIN)
        layout.addWidget(tick_label)
        self._ticker_table = DataTableWidget()
        self._ticker_table.setMinimumHeight(120)
        layout.addWidget(self._ticker_table)

        layout.addStretch()

    def refresh(self, force: bool = False) -> None:
        if not force and (monotonic() - self._last_refresh_ts) <= self._refresh_ttl_s:
            return
        try:
            from services import diagnostics_global as dg

            safety_weeks = int(self._safety_combo.currentText())

            # Tableau de statuts par personne
            health = dg.get_family_health_summary(self._conn, safety_weeks=safety_weeks)
            status_df = health["status_df"]
            if not status_df.empty:
                self._status_table.set_dataframe(status_df)
            else:
                self._status_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucun statut de diagnostic disponible."}]))

            # Marché
            dates = dg.last_market_dates(self._conn)
            self._mkt_prix.set_content("Dernière semaine prix", dates.get("last_price_week") or "—")
            self._mkt_fx.set_content("Dernière semaine FX", dates.get("last_fx_week") or "—")

            # Snapshots
            df_last = dg.last_snapshot_week_by_person(self._conn)
            if not df_last.empty:
                self._snap_table.set_dataframe(df_last)
            else:
                self._snap_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucun snapshot personne disponible."}]))

            # Tickers
            df_t = dg.tickers_missing_weekly_prices(self._conn, max_show=30)
            if not df_t.empty:
                self._ticker_table.set_dataframe(df_t)
            else:
                self._ticker_table.set_dataframe(pd.DataFrame([{"Statut": "✅ Tous les tickers ont un prix weekly"}]))
            self._last_refresh_ts = monotonic()
        except Exception as e:
            logger.error("Erreur refresh DataHealth : %s", e)
            self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._rebuild_status.setText(f"❌ Erreur : {e}")

    def _on_rebuild_all(self) -> None:
        try:
            from services import diagnostics_global as dg
            people = dg.list_people(self._conn)
            person_ids = [int(x) for x in people["id"].tolist()] if not people.empty else []
        except Exception as e:
            logger.error("Erreur récupération personnes pour rebuild all : %s", e)
            person_ids = []

        safety_weeks = int(self._safety_combo.currentText())
        self._btn_rebuild_all.setEnabled(False)
        self._rebuild_progress.show()
        self._rebuild_status.setStyleSheet(STYLE_STATUS)
        self._rebuild_status.setText("⏳ Rebuild en cours...")

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        self._thread = RebuildAllThread(person_ids, safety_weeks)
        self._thread.progress.connect(lambda msg: self._rebuild_status.setText(msg))
        self._thread.finished.connect(self._on_rebuild_done)
        self._thread.error.connect(self._on_rebuild_error)
        self._thread.start()

    def _on_rebuild_done(self, result: str) -> None:
        self._btn_rebuild_all.setEnabled(True)
        self._rebuild_progress.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._rebuild_status.setText(f"✅ Rebuild terminé — {result}")
        self.refresh(force=True)

    def _on_rebuild_error(self, err: str) -> None:
        self._btn_rebuild_all.setEnabled(True)
        self._rebuild_progress.hide()
        self._rebuild_status.setStyleSheet(STYLE_STATUS_ERROR)
        self._rebuild_status.setText(f"❌ Erreur : {err}")


# ─── Panel : Flux V1 ──────────────────────────────────────────────────────────

class FluxPanel(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._last_refresh_ts = 0.0
        self._refresh_ttl_s = 8.0
        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("📒 Flux — Vue globale (basé sur les opérations)")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        self._status_label = QLabel("Prêt.")
        self._status_label.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._status_label)

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

    def refresh(self, force: bool = False) -> None:
        if not force and (monotonic() - self._last_refresh_ts) <= self._refresh_ttl_s:
            return
        try:
            from services import cashflow as cf
            self._status_label.setStyleSheet(STYLE_STATUS)
            self._status_label.setText("⏳ Chargement des flux...")

            today = pd.Timestamp.today()
            summary = cf.get_family_flux_summary(
                self._conn, year=int(today.year), month=int(today.month)
            )

            solde_total = summary["solde_total"]
            cashflow_mois = summary["cashflow_mois"]
            self._kpi_solde.set_content("Solde famille (flux)", f"{solde_total:,.2f} €".replace(",", " "))
            self._kpi_cashflow.set_content("Cashflow du mois", f"{cashflow_mois:,.2f} €".replace(",", " "))
            self._kpi_ops.set_content("Opérations", str(summary["n_operations"]))

            df_par_personne = summary["par_personne"]
            if not df_par_personne.empty:
                self._people_table.set_dataframe(df_par_personne)
            else:
                self._people_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucune opération par personne."}]))

            df_par_compte = summary["par_compte"]
            if not df_par_compte.empty:
                self._accounts_table.set_dataframe(df_par_compte)
            else:
                self._accounts_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucune opération par compte."}]))

            df_dernieres = summary["dernieres_operations"]
            if not df_dernieres.empty:
                self._last_table.set_dataframe(df_dernieres)
            else:
                self._last_table.set_dataframe(pd.DataFrame([{"Statut": "⚠️ Aucune opération récente."}]))

            if int(summary.get("n_operations", 0)) == 0:
                self._status_label.setStyleSheet(STYLE_STATUS_WARNING)
                self._status_label.setText("⚠️ Aucune opération trouvée pour la période.")
            else:
                self._status_label.setStyleSheet(STYLE_STATUS_SUCCESS)
                self._status_label.setText("✅ Flux chargés.")
            self._last_refresh_ts = monotonic()

        except Exception as e:
            logger.error("Erreur chargement Flux : %s", e)
            self._status_label.setStyleSheet(STYLE_STATUS_ERROR)
            self._status_label.setText(f"❌ Erreur de chargement : {e}")


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
