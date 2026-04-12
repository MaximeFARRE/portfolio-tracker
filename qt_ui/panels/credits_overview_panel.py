"""
Panel Crédits — Vue d'ensemble + Créer / Modifier.
Permet de gérer les crédits directement depuis la page Personnes,
sans passer par un compte crédit dédié.
"""
import logging
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
    QDateEdit, QCheckBox, QScrollArea,
)
from qt_ui.components.animated_tab import AnimatedTabWidget
from PyQt6.QtCore import QDate, Qt

from qt_ui.widgets import PlotlyView, DataTableWidget, MetricLabel
from qt_ui.theme import (
    BG_PRIMARY, ACCENT_BLUE, STYLE_BTN_PRIMARY_BORDERED, STYLE_BTN_SUCCESS,
    STYLE_INPUT_FOCUS, STYLE_FORM_LABEL, STYLE_GROUP, STYLE_SECTION,
    STYLE_TITLE, STYLE_STATUS, STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR,
    STYLE_TAB_INNER, STYLE_SCROLLAREA, STYLE_PROGRESS,
    COLOR_SUCCESS, BORDER_SUBTLE, plotly_layout, plotly_time_series_layout,
)

logger = logging.getLogger(__name__)

_CREDIT_TYPES = ["IMMOBILIER", "CONSOMMATION", "AUTO", "PROFESSIONNEL", "AUTRE"]


def _now_paris_date():
    return datetime.now(pytz.timezone("Europe/Paris")).date()


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(STYLE_FORM_LABEL)
    return lbl


class CreditsOverviewPanel(QWidget):
    def __init__(self, conn, person_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = AnimatedTabWidget()
        tabs.setStyleSheet(STYLE_TAB_INNER)
        tabs.addTab(self._build_overview_tab(), "📊  Vue d'ensemble")
        tabs.addTab(self._build_edit_tab(),     "✏️  Créer / Modifier")
        tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(tabs)
        self._tabs = tabs

    # ── Onglet Vue d'ensemble ──────────────────────────────────────────────

    def _build_overview_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {BG_PRIMARY};")
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)

        title = QLabel("Crédits actifs")
        title.setStyleSheet(STYLE_TITLE)
        v.addWidget(title)

        # KPIs
        kpi_row = QHBoxLayout()
        self._kpi_crd   = MetricLabel("CRD total", "—")
        self._kpi_remb  = MetricLabel("Capital remboursé", "—")
        self._kpi_mensu = MetricLabel("Mensualités théoriques", "—")
        self._kpi_reel  = MetricLabel("Coût réel (mois)", "—")
        self._kpi_nb    = MetricLabel("Crédits actifs", "—")
        for kpi in (self._kpi_crd, self._kpi_remb, self._kpi_mensu, self._kpi_reel, self._kpi_nb):
            kpi_row.addWidget(kpi)
        kpi_row.addStretch()
        v.addLayout(kpi_row)

        self._tps_restant = QLabel()
        self._tps_restant.setStyleSheet(STYLE_STATUS)
        v.addWidget(self._tps_restant)

        # Graphique CRD
        lbl_crd = QLabel("📉 Évolution du capital restant dû (CRD)")
        lbl_crd.setStyleSheet(STYLE_SECTION)
        v.addWidget(lbl_crd)
        self._chart_crd = PlotlyView(min_height=350)
        v.addWidget(self._chart_crd)

        # Tableau synthèse
        lbl_table = QLabel("Synthèse des crédits")
        lbl_table.setStyleSheet(STYLE_SECTION)
        v.addWidget(lbl_table)
        self._table = DataTableWidget()
        self._table.setMinimumHeight(200)
        v.addWidget(self._table)

        # Barres de progression
        self._prog_label = QLabel("Progression de remboursement")
        self._prog_label.setStyleSheet(STYLE_SECTION)
        v.addWidget(self._prog_label)
        self._prog_container = QWidget()
        self._prog_container.setStyleSheet("background: transparent;")
        self._prog_v = QVBoxLayout(self._prog_container)
        self._prog_v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._prog_container)

        v.addStretch()
        return w

    # ── Onglet Créer / Modifier ────────────────────────────────────────────

    def _build_edit_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(STYLE_SCROLLAREA)

        container = QWidget()
        container.setStyleSheet(f"background: {BG_PRIMARY};")
        v = QVBoxLayout(container)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(20)

        # ── Section 1 : Créer un nouveau crédit ───────────────────────────
        lbl_new = QLabel("➕  Créer un nouveau crédit")
        lbl_new.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl_new)

        hint = QLabel(
            "Un compte crédit sera créé automatiquement.\n"
            "Renseignez les paramètres, enregistrez, puis générez le tableau d'amortissement."
        )
        hint.setStyleSheet(STYLE_STATUS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        form_new = QFormLayout()
        form_new.setSpacing(10)
        form_new.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._new_nom = QLineEdit()
        self._new_nom.setPlaceholderText("Ex : Crédit immobilier résidence principale")
        self._new_nom.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Nom :"), self._new_nom)

        self._new_banque = QLineEdit()
        self._new_banque.setPlaceholderText("Ex : Crédit Agricole")
        self._new_banque.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Banque :"), self._new_banque)

        self._new_type = QComboBox()
        self._new_type.addItems(_CREDIT_TYPES)
        self._new_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Type de crédit :"), self._new_type)

        self._new_capital = QDoubleSpinBox()
        self._new_capital.setRange(0, 9_999_999)
        self._new_capital.setDecimals(2)
        self._new_capital.setSuffix(" €")
        self._new_capital.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Capital emprunté :"), self._new_capital)

        self._new_taux = QDoubleSpinBox()
        self._new_taux.setRange(0, 30)
        self._new_taux.setDecimals(4)
        self._new_taux.setSuffix(" %")
        self._new_taux.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Taux nominal annuel :"), self._new_taux)

        self._new_taeg = QDoubleSpinBox()
        self._new_taeg.setRange(0, 30)
        self._new_taeg.setDecimals(4)
        self._new_taeg.setSuffix(" %")
        self._new_taeg.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("TAEG :"), self._new_taeg)

        self._new_duree = QSpinBox()
        self._new_duree.setRange(1, 600)
        self._new_duree.setSuffix(" mois")
        self._new_duree.setValue(240)
        self._new_duree.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Durée totale :"), self._new_duree)

        self._new_mensu = QDoubleSpinBox()
        self._new_mensu.setRange(0, 99_999)
        self._new_mensu.setDecimals(2)
        self._new_mensu.setSuffix(" €/mois")
        self._new_mensu.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Mensualité théorique :"), self._new_mensu)

        self._new_assurance = QDoubleSpinBox()
        self._new_assurance.setRange(0, 9_999)
        self._new_assurance.setDecimals(2)
        self._new_assurance.setSuffix(" €/mois")
        self._new_assurance.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Assurance mensuelle :"), self._new_assurance)

        self._new_date_debut = QDateEdit()
        self._new_date_debut.setCalendarPopup(True)
        self._new_date_debut.setDate(QDate.currentDate())
        self._new_date_debut.setDisplayFormat("dd/MM/yyyy")
        self._new_date_debut.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Date de début :"), self._new_date_debut)

        self._new_actif = QCheckBox("Crédit actif")
        self._new_actif.setChecked(True)
        self._new_actif.setStyleSheet(STYLE_FORM_LABEL)
        form_new.addRow("", self._new_actif)

        v.addLayout(form_new)

        row_new = QHBoxLayout()
        btn_save_new = QPushButton("💾  Enregistrer le crédit")
        btn_save_new.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_save_new.clicked.connect(self._save_new_credit)

        btn_amort_new = QPushButton("📅  Générer l'amortissement")
        btn_amort_new.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_amort_new.clicked.connect(self._generate_amort_new)

        self._new_status = QLabel("")
        self._new_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row_new.addWidget(btn_save_new)
        row_new.addWidget(btn_amort_new)
        row_new.addWidget(self._new_status)
        row_new.addStretch()
        v.addLayout(row_new)

        # Séparateur
        sep = QLabel()
        sep.setStyleSheet(f"background: {BORDER_SUBTLE}; min-height: 1px; max-height: 1px;")
        v.addWidget(sep)

        # ── Section 2 : Modifier un crédit existant ────────────────────────
        lbl_upd = QLabel("📝  Modifier un crédit existant")
        lbl_upd.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl_upd)

        form_sel = QFormLayout()
        form_sel.setSpacing(10)
        form_sel.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._upd_combo = QComboBox()
        self._upd_combo.setStyleSheet(STYLE_INPUT_FOCUS)
        self._upd_combo.currentIndexChanged.connect(self._on_credit_selected)
        form_sel.addRow(_form_label("Crédit :"), self._upd_combo)

        v.addLayout(form_sel)

        form_upd = QFormLayout()
        form_upd.setSpacing(10)
        form_upd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._upd_nom = QLineEdit()
        self._upd_nom.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Nom :"), self._upd_nom)

        self._upd_banque = QLineEdit()
        self._upd_banque.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Banque :"), self._upd_banque)

        self._upd_type = QComboBox()
        self._upd_type.addItems(_CREDIT_TYPES)
        self._upd_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Type de crédit :"), self._upd_type)

        self._upd_capital = QDoubleSpinBox()
        self._upd_capital.setRange(0, 9_999_999)
        self._upd_capital.setDecimals(2)
        self._upd_capital.setSuffix(" €")
        self._upd_capital.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Capital emprunté :"), self._upd_capital)

        self._upd_taux = QDoubleSpinBox()
        self._upd_taux.setRange(0, 30)
        self._upd_taux.setDecimals(4)
        self._upd_taux.setSuffix(" %")
        self._upd_taux.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Taux nominal annuel :"), self._upd_taux)

        self._upd_taeg = QDoubleSpinBox()
        self._upd_taeg.setRange(0, 30)
        self._upd_taeg.setDecimals(4)
        self._upd_taeg.setSuffix(" %")
        self._upd_taeg.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("TAEG :"), self._upd_taeg)

        self._upd_duree = QSpinBox()
        self._upd_duree.setRange(1, 600)
        self._upd_duree.setSuffix(" mois")
        self._upd_duree.setValue(240)
        self._upd_duree.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Durée totale :"), self._upd_duree)

        self._upd_mensu = QDoubleSpinBox()
        self._upd_mensu.setRange(0, 99_999)
        self._upd_mensu.setDecimals(2)
        self._upd_mensu.setSuffix(" €/mois")
        self._upd_mensu.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Mensualité théorique :"), self._upd_mensu)

        self._upd_assurance = QDoubleSpinBox()
        self._upd_assurance.setRange(0, 9_999)
        self._upd_assurance.setDecimals(2)
        self._upd_assurance.setSuffix(" €/mois")
        self._upd_assurance.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Assurance mensuelle :"), self._upd_assurance)

        self._upd_date_debut = QDateEdit()
        self._upd_date_debut.setCalendarPopup(True)
        self._upd_date_debut.setDate(QDate.currentDate())
        self._upd_date_debut.setDisplayFormat("dd/MM/yyyy")
        self._upd_date_debut.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Date de début :"), self._upd_date_debut)

        self._upd_actif = QCheckBox("Crédit actif")
        self._upd_actif.setChecked(True)
        self._upd_actif.setStyleSheet(STYLE_FORM_LABEL)
        form_upd.addRow("", self._upd_actif)

        v.addLayout(form_upd)

        row_upd = QHBoxLayout()
        btn_save_upd = QPushButton("💾  Enregistrer les modifications")
        btn_save_upd.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_save_upd.clicked.connect(self._save_updated_credit)

        btn_amort_upd = QPushButton("📅  Regénérer l'amortissement")
        btn_amort_upd.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_amort_upd.clicked.connect(self._generate_amort_upd)

        self._upd_status = QLabel("")
        self._upd_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row_upd.addWidget(btn_save_upd)
        row_upd.addWidget(btn_amort_upd)
        row_upd.addWidget(self._upd_status)
        row_upd.addStretch()
        v.addLayout(row_upd)

        v.addStretch()
        scroll.setWidget(container)
        return scroll

    # ── Navigation ─────────────────────────────────────────────────────────

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self._load_data()
        elif idx == 1:
            self._refresh_credit_combo()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    # ── Vue d'ensemble : chargement ────────────────────────────────────────

    def _load_data(self) -> None:
        try:
            from services.credits import (
                list_credits_by_person, get_amortissements,
                get_crd_a_date, get_credit_dates,
                cout_reel_mois_credit_via_bankin,
            )

            today = _now_paris_date()
            mois_courant = f"{today.year:04d}-{today.month:02d}-01"

            dfc = list_credits_by_person(self._conn, person_id=self._person_id, only_active=True)
            if dfc.empty:
                self._kpi_nb.set_content("Crédits actifs", "0")
                self._table.set_dataframe(pd.DataFrame([{"Info": "Aucun crédit actif."}]))
                return

            total_crd = 0.0
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
                credit_id   = int(c["id"])
                nom         = str(c.get("nom") or f"Crédit {credit_id}")
                banque      = str(c.get("banque") or "")
                capital_init = float(c.get("capital_emprunte") or 0.0)

                crd_today        = float(get_crd_a_date(self._conn, credit_id=credit_id, date_ref=str(today)))
                capital_rembourse = max(0.0, capital_init - crd_today)
                mensu_theo       = (float(c.get("mensualite_theorique") or 0.0)
                                    + float(c.get("assurance_mensuelle_theorique") or 0.0))
                cout_reel        = float(cout_reel_mois_credit_via_bankin(
                    self._conn, credit_id=credit_id, mois_yyyy_mm_01=mois_courant
                ))
                dates     = get_credit_dates(self._conn, credit_id=credit_id)
                date_fin  = dates.get("date_fin")

                mois_restants = (
                    max(0, (date_fin.year - today.year) * 12 + (date_fin.month - today.month))
                    if date_fin else None
                )

                total_crd              += crd_today
                total_capital_rembourse += capital_rembourse
                total_mensualite_theo  += mensu_theo
                total_cout_reel        += cout_reel

                if mois_restants is not None:
                    poids = max(crd_today, 0.0)
                    somme_poids     += poids
                    somme_mois_pond += poids * mois_restants

                prog = max(0.0, min(1.0, (capital_rembourse / capital_init) if capital_init > 0 else 0.0))

                lignes_table.append({
                    "Crédit":               nom,
                    "Banque":               banque,
                    "CRD actuel":           f"{crd_today:,.2f} €".replace(",", " "),
                    "Capital remboursé":    f"{capital_rembourse:,.2f} €".replace(",", " "),
                    "Mensualité théorique": f"{mensu_theo:,.2f} €".replace(",", " "),
                    "Coût réel (mois)":     f"{cout_reel:,.2f} €".replace(",", " "),
                    "Fin":                  date_fin.isoformat() if date_fin else "—",
                    "Mois restants":        mois_restants if mois_restants is not None else "—",
                    "% remboursé":          f"{prog * 100:.1f}%",
                })

                # Barre de progression par crédit
                prog_row = QHBoxLayout()
                prog_lbl = QLabel(nom)
                prog_lbl.setStyleSheet(STYLE_STATUS + " min-width: 120px;")
                prog_bar = QProgressBar()
                prog_bar.setRange(0, 100)
                prog_bar.setValue(int(prog * 100))
                prog_bar.setStyleSheet(STYLE_PROGRESS)
                prog_pct = QLabel(f"{prog * 100:.1f}%")
                prog_pct.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 11px; min-width: 40px;")
                prog_row.addWidget(prog_lbl)
                prog_row.addWidget(prog_bar, 1)
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

            # KPIs globaux
            self._kpi_crd.set_content("CRD total",               f"{total_crd:,.2f} €".replace(",", " "))
            self._kpi_remb.set_content("Capital remboursé",       f"{total_capital_rembourse:,.2f} €".replace(",", " "))
            self._kpi_mensu.set_content("Mensualités théoriques", f"{total_mensualite_theo:,.2f} €".replace(",", " "))
            self._kpi_reel.set_content("Coût réel (mois)",        f"{total_cout_reel:,.2f} €".replace(",", " "))
            self._kpi_nb.set_content("Crédits actifs",            str(len(dfc)))

            if somme_poids > 0:
                mois_moy = int(round(somme_mois_pond / somme_poids))
                self._tps_restant.setText(f"Temps restant moyen (pondéré CRD) : {mois_moy} mois")

            # Graphique CRD cumulé
            if amorts_by_credit:
                bornes = []
                for amort in amorts_by_credit.values():
                    bornes += [amort["date_echeance"].min(), amort["date_echeance"].max()]
                months = pd.date_range(
                    start=min(bornes).to_period("M").to_timestamp(),
                    end=max(bornes).to_period("M").to_timestamp(),
                    freq="MS",
                )
                rows_chart = []
                for m in months:
                    month_end = (m + pd.offsets.MonthBegin(1)) - pd.Timedelta(seconds=1)
                    total = 0.0
                    for amort in amorts_by_credit.values():
                        past = amort[amort["date_echeance"] <= month_end]
                        total += float(past.iloc[-1]["crd"]) if not past.empty else float(amort.iloc[0]["crd"])
                    rows_chart.append({"date": m, "crd_total": total})
                df_total = pd.DataFrame(rows_chart).sort_values("date")
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_total["date"], y=df_total["crd_total"],
                    mode="lines", name="CRD total", line=dict(color=ACCENT_BLUE),
                ))
                fig.add_trace(go.Scatter(
                    x=[pd.to_datetime(today)], y=[total_crd],
                    mode="markers", name="Aujourd'hui",
                    marker=dict(color="red", size=10),
                ))
                fig.update_layout(**plotly_time_series_layout(xaxis_title="Mois", yaxis_title="CRD total (€)"))
                self._chart_crd.set_figure(fig)

            if lignes_table:
                self._table.set_dataframe(pd.DataFrame(lignes_table))

        except Exception as e:
            logger.error("CreditsOverviewPanel._load_data error: %s", e, exc_info=True)

    # ── Combo crédits existants ────────────────────────────────────────────

    def _refresh_credit_combo(self) -> None:
        try:
            from services.credits import list_credits_by_person
            # Tous crédits (actifs + inactifs) pour permettre la modification
            df = list_credits_by_person(self._conn, person_id=self._person_id, only_active=False)
            self._upd_combo.blockSignals(True)
            self._upd_combo.clear()
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    label = str(r.get("nom") or f"Crédit {int(r['id'])}")
                    self._upd_combo.addItem(label, int(r["id"]))
            self._upd_combo.blockSignals(False)
            if self._upd_combo.count() > 0:
                self._on_credit_selected(0)
        except Exception as e:
            logger.error("Erreur rafraîchissement combo crédits : %s", e, exc_info=True)

    def _on_credit_selected(self, _idx: int) -> None:
        """Pré-remplit le formulaire de modification avec les valeurs du crédit sélectionné."""
        try:
            from services import panel_data_access as pda

            credit_id = self._upd_combo.currentData()
            if credit_id is None:
                return
            row = pda.get_credit_by_id(self._conn, credit_id)
            if not row:
                return

            self._upd_nom.setText(str(row["nom"] or ""))
            self._upd_banque.setText(str(row["banque"] or ""))

            tidx = self._upd_type.findText(str(row["type_credit"] or "IMMOBILIER").upper())
            if tidx >= 0:
                self._upd_type.setCurrentIndex(tidx)

            self._upd_capital.setValue(float(row["capital_emprunte"] or 0.0))
            self._upd_taux.setValue(float(row["taux_nominal"] or 0.0))
            self._upd_taeg.setValue(float(row["taeg"] or 0.0))
            self._upd_duree.setValue(int(row["duree_mois"] or 240))
            self._upd_mensu.setValue(float(row["mensualite_theorique"] or 0.0))
            self._upd_assurance.setValue(float(row["assurance_mensuelle_theorique"] or 0.0))
            self._upd_actif.setChecked(bool(row["actif"]))

            date_str = str(row["date_debut"] or "")
            if date_str:
                try:
                    import datetime as dt
                    d = dt.date.fromisoformat(date_str[:10])
                    self._upd_date_debut.setDate(QDate(d.year, d.month, d.day))
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Erreur pré-remplissage crédit : %s", e, exc_info=True)

    # ── Créer un nouveau crédit ────────────────────────────────────────────

    def _save_new_credit(self) -> None:
        try:
            from services import repositories as repo
            from services.credits import upsert_credit

            nom = self._new_nom.text().strip()
            if not nom:
                self._new_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._new_status.setText("❌  Le nom est obligatoire.")
                return

            banque = self._new_banque.text().strip() or None

            # Crée un compte CREDIT dédié (nom = nom du crédit)
            account_id = repo.create_account(
                self._conn,
                person_id=self._person_id,
                name=nom,
                account_type="CREDIT",
                institution=banque,
                currency="EUR",
            )

            data = {
                "person_id":                     self._person_id,
                "account_id":                    account_id,
                "nom":                           nom,
                "banque":                        banque,
                "type_credit":                   self._new_type.currentText(),
                "capital_emprunte":              self._new_capital.value(),
                "taux_nominal":                  self._new_taux.value(),
                "taeg":                          self._new_taeg.value(),
                "duree_mois":                    self._new_duree.value(),
                "mensualite_theorique":          self._new_mensu.value(),
                "assurance_mensuelle_theorique": self._new_assurance.value(),
                "date_debut":                    self._new_date_debut.date().toString("yyyy-MM-dd"),
                "actif":                         1 if self._new_actif.isChecked() else 0,
                "payer_account_id":              None,
            }
            credit_id = upsert_credit(self._conn, data)

            self._new_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._new_status.setText(f"✅  Crédit « {nom} » créé (id={credit_id}).")

            # Mémoriser le dernier credit_id créé pour la génération d'amortissement
            self._last_new_credit_id = credit_id

            # Réinitialiser le formulaire
            self._new_nom.clear()
            self._new_banque.clear()
            self._new_capital.setValue(0)
            self._new_taux.setValue(0)
            self._new_taeg.setValue(0)
            self._new_duree.setValue(240)
            self._new_mensu.setValue(0)
            self._new_assurance.setValue(0)

            self._refresh_credit_combo()

        except Exception as e:
            logger.error("Erreur création crédit : %s", e, exc_info=True)
            self._new_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._new_status.setText(f"❌  Erreur : {e}")

    def _generate_amort_new(self) -> None:
        """Génère le tableau d'amortissement pour le dernier crédit créé."""
        credit_id = getattr(self, "_last_new_credit_id", None)
        if credit_id is None:
            self._new_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._new_status.setText("❌  Enregistrez d'abord le crédit.")
            return
        self._generate_amortissement(credit_id, self._new_status)

    # ── Modifier un crédit existant ────────────────────────────────────────

    def _save_updated_credit(self) -> None:
        try:
            from services.credits import upsert_credit
            from services import panel_data_access as pda

            credit_id = self._upd_combo.currentData()
            if credit_id is None:
                self._upd_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._upd_status.setText("❌  Sélectionnez un crédit.")
                return

            # Récupérer l'account_id existant
            row = pda.get_credit_account_and_person(self._conn, credit_id)
            if not row:
                self._upd_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._upd_status.setText("❌  Crédit introuvable en base.")
                return

            data = {
                "person_id":                     int(row["person_id"]),
                "account_id":                    int(row["account_id"]),
                "nom":                           self._upd_nom.text().strip() or None,
                "banque":                        self._upd_banque.text().strip() or None,
                "type_credit":                   self._upd_type.currentText(),
                "capital_emprunte":              self._upd_capital.value(),
                "taux_nominal":                  self._upd_taux.value(),
                "taeg":                          self._upd_taeg.value(),
                "duree_mois":                    self._upd_duree.value(),
                "mensualite_theorique":          self._upd_mensu.value(),
                "assurance_mensuelle_theorique": self._upd_assurance.value(),
                "date_debut":                    self._upd_date_debut.date().toString("yyyy-MM-dd"),
                "actif":                         1 if self._upd_actif.isChecked() else 0,
                "payer_account_id":              None,
            }
            upsert_credit(self._conn, data)

            nom = self._upd_nom.text().strip() or self._upd_combo.currentText()
            self._upd_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._upd_status.setText(f"✅  « {nom} » mis à jour.")

        except Exception as e:
            logger.error("Erreur mise à jour crédit : %s", e, exc_info=True)
            self._upd_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._upd_status.setText(f"❌  Erreur : {e}")

    def _generate_amort_upd(self) -> None:
        """Régénère le tableau d'amortissement pour le crédit sélectionné."""
        credit_id = self._upd_combo.currentData()
        if credit_id is None:
            self._upd_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._upd_status.setText("❌  Sélectionnez un crédit.")
            return
        # Sauvegarder d'abord pour s'assurer que les données sont à jour
        self._save_updated_credit()
        self._generate_amortissement(int(credit_id), self._upd_status)

    # ── Génération d'amortissement (partagée) ─────────────────────────────

    def _generate_amortissement(self, credit_id: int, status_label: QLabel) -> None:
        try:
            from services.credits import (
                build_amortissement, replace_amortissement, CreditParams,
            )
            from services import panel_data_access as pda

            row = pda.get_credit_by_id(self._conn, credit_id)
            if not row:
                status_label.setStyleSheet(STYLE_STATUS_ERROR)
                status_label.setText("❌  Crédit introuvable.")
                return

            params = CreditParams(
                capital=float(row["capital_emprunte"] or 0),
                taux_annuel=float(row["taux_nominal"] or 0),
                duree_mois=int(row["duree_mois"] or 0),
                date_debut=str(row["date_debut"] or ""),
                assurance_mensuelle=float(row["assurance_mensuelle_theorique"] or 0),
            )
            rows = build_amortissement(params)
            n = replace_amortissement(self._conn, credit_id, rows)

            status_label.setStyleSheet(STYLE_STATUS_SUCCESS)
            status_label.setText(f"✅  Amortissement généré : {n} échéances.")

        except Exception as e:
            logger.error("Erreur génération amortissement : %s", e, exc_info=True)
            status_label.setStyleSheet(STYLE_STATUS_ERROR)
            status_label.setText(f"❌  Erreur : {e}")
