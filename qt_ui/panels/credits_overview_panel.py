"""
Panel Crédits — remplace ui/credits_overview.py
"""
import logging
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
)

from qt_ui.widgets import PlotlyView, DataTableWidget, MetricLabel
from qt_ui.theme import (
    BG_PRIMARY, STYLE_GROUP, STYLE_SECTION, STYLE_TITLE,
    STYLE_STATUS, STYLE_PROGRESS, COLOR_SUCCESS, plotly_layout,
)

logger = logging.getLogger(__name__)


def _now_paris_date():
    return datetime.now(pytz.timezone("Europe/Paris")).date()


class CreditsOverviewPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)

        title = QLabel("Crédits actifs")
        title.setStyleSheet(STYLE_TITLE)
        self._layout.addWidget(title)

        # KPI row
        kpi_row = QHBoxLayout()
        self._kpi_crd = MetricLabel("CRD total", "—")
        self._kpi_remb = MetricLabel("Capital remboursé", "—")
        self._kpi_mensu = MetricLabel("Mensualités théoriques", "—")
        self._kpi_reel = MetricLabel("Coût réel (mois)", "—")
        self._kpi_nb = MetricLabel("Crédits actifs", "—")
        kpi_row.addWidget(self._kpi_crd)
        kpi_row.addWidget(self._kpi_remb)
        kpi_row.addWidget(self._kpi_mensu)
        kpi_row.addWidget(self._kpi_reel)
        kpi_row.addWidget(self._kpi_nb)
        self._layout.addLayout(kpi_row)

        self._tps_restant = QLabel()
        self._tps_restant.setStyleSheet(STYLE_STATUS)
        self._layout.addWidget(self._tps_restant)

        # Graphique CRD
        lbl_crd = QLabel("📉 Évolution du capital restant dû (CRD)")
        lbl_crd.setStyleSheet(STYLE_SECTION)
        self._layout.addWidget(lbl_crd)
        self._chart_crd = PlotlyView(min_height=280)
        self._layout.addWidget(self._chart_crd)

        # Table synthèse
        lbl_table = QLabel("Synthèse des crédits")
        lbl_table.setStyleSheet(STYLE_SECTION)
        self._layout.addWidget(lbl_table)
        self._table = DataTableWidget()
        self._table.setMinimumHeight(200)
        self._layout.addWidget(self._table)

        # Barres de progression
        self._prog_label = QLabel("Progression de remboursement")
        self._prog_label.setStyleSheet(STYLE_SECTION)
        self._layout.addWidget(self._prog_label)
        self._prog_container = QWidget()
        self._prog_container.setStyleSheet("background: transparent;")
        self._prog_v = QVBoxLayout(self._prog_container)
        self._prog_v.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._prog_container)

        self._layout.addStretch()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    def _load_data(self) -> None:
        try:
            from services.credits import (
                list_credits_by_person, get_amortissements,
                get_crd_a_date, get_credit_dates,
                cout_reel_mois_credit_via_bankin
            )

            today = _now_paris_date()
            mois_courant = f"{today.year:04d}-{today.month:02d}-01"

            dfc = list_credits_by_person(self._conn, person_id=self._person_id, only_active=True)
            if dfc.empty:
                self._kpi_nb.set_content("Crédits actifs", "0")
                self._table.set_dataframe(pd.DataFrame([{"Info": "Aucun crédit actif."}]))
                return

            total_crd = 0.0
            total_capital_init = 0.0
            total_capital_rembourse = 0.0
            total_mensualite_theo = 0.0
            total_cout_reel = 0.0
            somme_poids = 0.0
            somme_mois_pond = 0.0
            lignes_table = []
            amorts_by_credit = {}

            # Vider les barres existantes
            for i in reversed(range(self._prog_v.count())):
                item = self._prog_v.itemAt(i)
                if item and item.widget():
                    item.widget().deleteLater()

            for _, c in dfc.iterrows():
                credit_id = int(c["id"])
                nom = str(c.get("nom") or f"Crédit {credit_id}")
                banque = str(c.get("banque") or "")
                capital_init = float(c.get("capital_emprunte") or 0.0)

                crd_today = float(get_crd_a_date(self._conn, credit_id=credit_id, date_ref=str(today)))
                capital_rembourse = max(0.0, capital_init - crd_today)
                mensu_theo = float(c.get("mensualite_theorique") or 0.0) + float(c.get("assurance_mensuelle_theorique") or 0.0)
                cout_reel = float(cout_reel_mois_credit_via_bankin(self._conn, credit_id=credit_id, mois_yyyy_mm_01=mois_courant))
                dates = get_credit_dates(self._conn, credit_id=credit_id)
                date_fin = dates.get("date_fin")
                date_debut_remb = dates.get("date_debut_remboursement")

                if date_fin is not None:
                    mois_restants = max(0, (date_fin.year - today.year) * 12 + (date_fin.month - today.month))
                else:
                    mois_restants = None

                total_crd += crd_today
                total_capital_init += capital_init
                total_capital_rembourse += capital_rembourse
                total_mensualite_theo += mensu_theo
                total_cout_reel += cout_reel

                if mois_restants is not None:
                    poids = max(crd_today, 0.0)
                    somme_poids += poids
                    somme_mois_pond += poids * mois_restants

                prog = (capital_rembourse / capital_init) if capital_init > 0 else 0.0
                prog = max(0.0, min(1.0, prog))

                lignes_table.append({
                    "Crédit": nom,
                    "Banque": banque,
                    "CRD actuel": f"{crd_today:,.2f} €".replace(",", " "),
                    "Capital remboursé": f"{capital_rembourse:,.2f} €".replace(",", " "),
                    "Mensualité théorique": f"{mensu_theo:,.2f} €".replace(",", " "),
                    "Coût réel (mois)": f"{cout_reel:,.2f} €".replace(",", " "),
                    "Fin": date_fin.isoformat() if date_fin else "—",
                    "Mois restants": mois_restants or "—",
                    "% remboursé": f"{prog * 100:.1f}%",
                })

                # Barre de progression
                prog_row = QHBoxLayout()
                prog_lbl = QLabel(f"{nom}")
                prog_lbl.setStyleSheet(STYLE_STATUS + " min-width: 120px;")
                prog_bar = QProgressBar()
                prog_bar.setRange(0, 100)
                prog_bar.setValue(int(prog * 100))
                prog_bar.setStyleSheet(STYLE_PROGRESS)
                prog_row.addWidget(prog_lbl)
                prog_row.addWidget(prog_bar, 1)
                prog_pct = QLabel(f"{prog * 100:.1f}%")
                prog_pct.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 11px; min-width: 40px;")
                prog_row.addWidget(prog_pct)
                prog_w = QWidget()
                prog_w.setLayout(prog_row)
                self._prog_v.addWidget(prog_w)

                # Amortissement pour graphe
                amort = get_amortissements(self._conn, credit_id=credit_id)
                if not amort.empty:
                    amort["date_echeance"] = pd.to_datetime(amort["date_echeance"], errors="coerce")
                    amort = amort.dropna(subset=["date_echeance"]).sort_values("date_echeance")
                    amort["crd"] = pd.to_numeric(amort["crd"], errors="coerce").fillna(0.0)
                    amorts_by_credit[credit_id] = amort

            # KPIs
            self._kpi_crd.set_content("CRD total", f"{total_crd:,.2f} €".replace(",", " "))
            self._kpi_remb.set_content("Capital remboursé", f"{total_capital_rembourse:,.2f} €".replace(",", " "))
            self._kpi_mensu.set_content("Mensualités théoriques", f"{total_mensualite_theo:,.2f} €".replace(",", " "))
            self._kpi_reel.set_content("Coût réel (mois)", f"{total_cout_reel:,.2f} €".replace(",", " "))
            self._kpi_nb.set_content("Crédits actifs", str(len(dfc)))

            if somme_poids > 0:
                mois_moy = int(round(somme_mois_pond / somme_poids))
                self._tps_restant.setText(f"Temps restant moyen (pondéré CRD) : {mois_moy} mois")

            # Graphique CRD
            if amorts_by_credit:
                bornes = []
                for amort in amorts_by_credit.values():
                    bornes.append(amort["date_echeance"].min())
                    bornes.append(amort["date_echeance"].max())
                start = min(bornes).to_period("M").to_timestamp()
                end = max(bornes).to_period("M").to_timestamp()
                months = pd.date_range(start=start, end=end, freq="MS")
                rows = []
                for m in months:
                    month_end = (m + pd.offsets.MonthBegin(1)) - pd.Timedelta(seconds=1)
                    total = 0.0
                    for amort in amorts_by_credit.values():
                        past = amort[amort["date_echeance"] <= month_end]
                        if past.empty:
                            total += float(amort.iloc[0]["crd"])
                        else:
                            total += float(past.iloc[-1]["crd"])
                    rows.append({"date": m, "crd_total": total})
                df_total = pd.DataFrame(rows).sort_values("date")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_total["date"], y=df_total["crd_total"],
                                         mode="lines", name="CRD total", line=dict(color="#60a5fa")))
                fig.add_trace(go.Scatter(x=[pd.to_datetime(today)], y=[total_crd],
                                         mode="markers", name="Aujourd'hui",
                                         marker=dict(color="red", size=10)))
                fig.update_layout(**plotly_layout(
                    xaxis_title="Mois", yaxis_title="CRD total (€)"))
                self._chart_crd.set_figure(fig)

            # Table
            if lignes_table:
                self._table.set_dataframe(pd.DataFrame(lignes_table))

        except Exception as e:
            logger.error("CreditsOverviewPanel._load_data error: %s", e, exc_info=True)
