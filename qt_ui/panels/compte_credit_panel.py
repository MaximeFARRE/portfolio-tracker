"""
Panel d'un compte Crédit — remplace ui/credit_dashboard.py
Correctif : ajout de l'onglet Configuration pour créer/éditer le crédit.
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
from qt_ui.panels.saisie_panel import SaisiePanel
from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY_BORDERED, STYLE_BTN_SUCCESS,
    STYLE_INPUT_FOCUS, STYLE_SECTION, STYLE_TITLE, STYLE_STATUS,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_TAB_INNER,
    STYLE_PROGRESS, STYLE_FORM_LABEL, COLOR_SUCCESS, plotly_layout,
)

logger = logging.getLogger(__name__)


def _now_paris_date():
    return datetime.now(pytz.timezone("Europe/Paris")).date()


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(STYLE_FORM_LABEL)
    return lbl


class CompteCreditPanel(QWidget):
    def __init__(self, conn, person_id: int, account_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._account_id = account_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        main_v = QVBoxLayout(self)
        main_v.setContentsMargins(12, 12, 12, 12)
        main_v.setSpacing(12)

        tabs = AnimatedTabWidget()
        tabs.setStyleSheet(STYLE_TAB_INNER)

        # ── Onglet 0 : Configuration (NOUVEAU) ────────────────────────────
        tabs.addTab(self._build_config_tab(), "⚙️  Configuration")

        # ── Onglet 1 : Tableau de bord ────────────────────────────────────
        dash = QWidget()
        dash.setStyleSheet(f"background: {BG_PRIMARY};")
        dash_v = QVBoxLayout(dash)
        dash_v.setContentsMargins(8, 8, 8, 8)
        dash_v.setSpacing(10)

        kpi_row = QHBoxLayout()
        self._kpi_crd     = MetricLabel("CRD actuel", "—")
        self._kpi_mensu   = MetricLabel("Mensualité théorique", "—")
        self._kpi_cout    = MetricLabel("Coût réel (mois)", "—")
        self._kpi_restant = MetricLabel("Mois restants", "—")
        for w in (self._kpi_crd, self._kpi_mensu, self._kpi_cout, self._kpi_restant):
            kpi_row.addWidget(w)
        kpi_row.addStretch()
        dash_v.addLayout(kpi_row)

        prog_row = QHBoxLayout()
        prog_row.addWidget(QLabel("Remboursement :"))
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 100)
        self._prog_bar.setStyleSheet(STYLE_PROGRESS)
        prog_row.addWidget(self._prog_bar, 1)
        self._prog_pct = QLabel("0%")
        self._prog_pct.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 12px;")
        prog_row.addWidget(self._prog_pct)
        dash_v.addLayout(prog_row)

        lbl_crd = QLabel("📉 Évolution du CRD")
        lbl_crd.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_crd)
        self._chart_crd = PlotlyView(min_height=260)
        dash_v.addWidget(self._chart_crd)

        lbl_amort = QLabel("Tableau d'amortissement")
        lbl_amort.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_amort)
        self._table_amort = DataTableWidget()
        self._table_amort.setMinimumHeight(250)
        self._table_amort.set_filter_config([
            {"col": "date_echeance", "kind": "date_range",   "label": "Date échéance"},
            {"col": "capital",       "kind": "number_range", "label": "Capital"},
        ])
        dash_v.addWidget(self._table_amort)
        dash_v.addStretch()
        tabs.addTab(dash, "📊  Tableau de bord")

        # ── Onglet 2 : Saisie ─────────────────────────────────────────────
        self._saisie = SaisiePanel(conn, person_id, account_id, "CREDIT")
        tabs.addTab(self._saisie, "✏️  Saisie")

        # ── Onglet 3 : Historique ────────────────────────────────────────────────
        hist = QWidget()
        hist.setStyleSheet(f"background: {BG_PRIMARY};")
        hist_v = QVBoxLayout(hist)
        self._hist_table = DataTableWidget()
        self._hist_table.setMinimumHeight(350)
        self._hist_table.set_filter_config([
            {"col": "type",   "kind": "combo",        "label": "Type"},
            {"col": "date",   "kind": "date_range",   "label": "Date"},
            {"col": "amount", "kind": "number_range", "label": "Montant"},
        ])
        hist_v.addWidget(self._hist_table)
        tabs.addTab(hist, "📋  Historique")

        main_v.addWidget(tabs)
        self._tabs = tabs
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Charger la config existante et le dashboard au démarrage
        self._load_config()
        self._load_dashboard()

    # ── Construction de l'onglet Configuration ────────────────────────────

    def _build_config_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}")

        container = QWidget()
        container.setStyleSheet(f"background: {BG_PRIMARY};")
        v = QVBoxLayout(container)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(14)

        title = QLabel("⚙️  Configuration du crédit")
        title.setStyleSheet(STYLE_TITLE)
        v.addWidget(title)

        hint = QLabel(
            "Renseignez les paramètres de votre crédit, puis :\n"
            "• « Enregistrer » pour sauvegarder la fiche.\n"
            "• « Générer l'amortissement » pour calculer le tableau d'échéances."
        )
        hint.setStyleSheet(STYLE_STATUS)
        hint.setWordWrap(True)
        v.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._cfg_nom = QLineEdit()
        self._cfg_nom.setPlaceholderText("Ex: Crédit immobilier résidence principale")
        self._cfg_nom.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Nom :"), self._cfg_nom)

        self._cfg_banque = QLineEdit()
        self._cfg_banque.setPlaceholderText("Ex: Crédit Agricole")
        self._cfg_banque.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Banque :"), self._cfg_banque)

        self._cfg_type = QComboBox()
        self._cfg_type.addItems(["IMMOBILIER", "CONSOMMATION", "AUTO", "PROFESSIONNEL", "AUTRE"])
        self._cfg_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Type de crédit :"), self._cfg_type)

        self._cfg_capital = QDoubleSpinBox()
        self._cfg_capital.setRange(0, 9_999_999)
        self._cfg_capital.setDecimals(2)
        self._cfg_capital.setSuffix(" €")
        self._cfg_capital.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Capital emprunté :"), self._cfg_capital)

        self._cfg_taux = QDoubleSpinBox()
        self._cfg_taux.setRange(0, 30)
        self._cfg_taux.setDecimals(4)
        self._cfg_taux.setSuffix(" %")
        self._cfg_taux.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Taux nominal annuel :"), self._cfg_taux)

        self._cfg_taeg = QDoubleSpinBox()
        self._cfg_taeg.setRange(0, 30)
        self._cfg_taeg.setDecimals(4)
        self._cfg_taeg.setSuffix(" %")
        self._cfg_taeg.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("TAEG :"), self._cfg_taeg)

        self._cfg_duree = QSpinBox()
        self._cfg_duree.setRange(1, 600)
        self._cfg_duree.setSuffix(" mois")
        self._cfg_duree.setValue(240)
        self._cfg_duree.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Durée totale :"), self._cfg_duree)

        self._cfg_mensu = QDoubleSpinBox()
        self._cfg_mensu.setRange(0, 99_999)
        self._cfg_mensu.setDecimals(2)
        self._cfg_mensu.setSuffix(" €/mois")
        self._cfg_mensu.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Mensualité théorique :"), self._cfg_mensu)

        self._cfg_assurance = QDoubleSpinBox()
        self._cfg_assurance.setRange(0, 9_999)
        self._cfg_assurance.setDecimals(2)
        self._cfg_assurance.setSuffix(" €/mois")
        self._cfg_assurance.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Assurance mensuelle :"), self._cfg_assurance)

        self._cfg_date_debut = QDateEdit()
        self._cfg_date_debut.setCalendarPopup(True)
        self._cfg_date_debut.setDate(QDate.currentDate())
        self._cfg_date_debut.setDisplayFormat("dd/MM/yyyy")
        self._cfg_date_debut.setStyleSheet(STYLE_INPUT_FOCUS)
        form.addRow(_form_label("Date de début :"), self._cfg_date_debut)

        self._cfg_actif = QCheckBox("Crédit actif")
        self._cfg_actif.setChecked(True)
        self._cfg_actif.setStyleSheet(STYLE_FORM_LABEL)
        form.addRow("", self._cfg_actif)

        v.addLayout(form)

        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾  Enregistrer le crédit")
        btn_save.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_save.clicked.connect(self._save_credit)

        btn_amort = QPushButton("📅  Générer l'amortissement")
        btn_amort.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_amort.clicked.connect(self._generate_amortissement)

        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_amort)
        btn_row.addStretch()
        v.addLayout(btn_row)

        self._cfg_status = QLabel("")
        self._cfg_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        v.addWidget(self._cfg_status)

        v.addStretch()
        scroll.setWidget(container)
        return scroll

    # ── Navigation ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._load_dashboard()

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self._load_config()
        elif idx == 1:
            self._load_dashboard()
        elif idx == 3:
            self._load_history()

    # ── Config : chargement ────────────────────────────────────────────────

    def _load_config(self) -> None:
        try:
            from services.credits import get_credit_by_account
            c = get_credit_by_account(self._conn, account_id=self._account_id)
            if c is None:
                return  # Formulaire vide = nouveau crédit
            self._cfg_nom.setText(str(c.get("nom") or ""))
            self._cfg_banque.setText(str(c.get("banque") or ""))
            type_val = str(c.get("type_credit") or "IMMOBILIER").upper()
            idx = self._cfg_type.findText(type_val)
            if idx >= 0:
                self._cfg_type.setCurrentIndex(idx)
            self._cfg_capital.setValue(float(c.get("capital_emprunte") or 0.0))
            self._cfg_taux.setValue(float(c.get("taux_nominal") or 0.0))
            self._cfg_taeg.setValue(float(c.get("taeg") or 0.0))
            self._cfg_duree.setValue(int(c.get("duree_mois") or 240))
            self._cfg_mensu.setValue(float(c.get("mensualite_theorique") or 0.0))
            self._cfg_assurance.setValue(float(c.get("assurance_mensuelle_theorique") or 0.0))
            date_str = str(c.get("date_debut") or "")
            if date_str:
                try:
                    import datetime as dt
                    d = dt.date.fromisoformat(date_str[:10])
                    self._cfg_date_debut.setDate(QDate(d.year, d.month, d.day))
                except Exception as e:
                    logger.warning("Could not parse date_debut '%s': %s", date_str, e)
            self._cfg_actif.setChecked(bool(c.get("actif", True)))
        except Exception as e:
            logger.error("CompteCreditPanel._load_config error: %s", e, exc_info=True)

    # ── Config : sauvegarde ────────────────────────────────────────────────

    def _save_credit(self) -> None:
        try:
            from services.credits import upsert_credit
            data = {
                "person_id":                     self._person_id,
                "account_id":                    self._account_id,
                "nom":                           self._cfg_nom.text().strip() or None,
                "banque":                        self._cfg_banque.text().strip() or None,
                "type_credit":                   self._cfg_type.currentText(),
                "capital_emprunte":              self._cfg_capital.value(),
                "taux_nominal":                  self._cfg_taux.value(),
                "taeg":                          self._cfg_taeg.value(),
                "duree_mois":                    self._cfg_duree.value(),
                "mensualite_theorique":          self._cfg_mensu.value(),
                "assurance_mensuelle_theorique": self._cfg_assurance.value(),
                "date_debut":                    self._cfg_date_debut.date().toString("yyyy-MM-dd"),
                "actif":                         1 if self._cfg_actif.isChecked() else 0,
                "payer_account_id":              None,
            }
            upsert_credit(self._conn, data)
            self._cfg_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._cfg_status.setText("✅  Crédit enregistré avec succès.")
        except Exception as e:
            self._cfg_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._cfg_status.setText(f"❌  Erreur : {e}")

    # ── Config : génération amortissement ──────────────────────────────────

    def _generate_amortissement(self) -> None:
        try:
            from services.credits import (
                get_credit_by_account, build_amortissement,
                replace_amortissement, CreditParams,
            )
            # Sauvegarder d'abord pour s'assurer que la fiche existe
            self._save_credit()

            c = get_credit_by_account(self._conn, account_id=self._account_id)
            if c is None:
                self._cfg_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._cfg_status.setText("❌  Crédit introuvable. Enregistrez-le d'abord.")
                return

            params = CreditParams(
                capital=float(c.get("capital_emprunte") or 0),
                taux_annuel=float(c.get("taux_nominal") or 0),
                duree_mois=int(c.get("duree_mois") or 0),
                date_debut=str(c.get("date_debut") or ""),
                assurance_mensuelle=float(c.get("assurance_mensuelle_theorique") or 0),
            )
            rows = build_amortissement(params)
            n = replace_amortissement(self._conn, int(c["id"]), rows)
            self._cfg_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._cfg_status.setText(f"✅  Amortissement généré : {n} échéances.")
            # Rafraîchir automatiquement le tableau de bord
            self._load_dashboard()
        except Exception as e:
            self._cfg_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._cfg_status.setText(f"❌  Erreur : {e}")

    # ── Tableau de bord ────────────────────────────────────────────────────

    def _load_dashboard(self) -> None:
        try:
            from services.credits import (
                get_credit_by_account, get_amortissements,
                get_crd_a_date, get_credit_dates,
                cout_reel_mois_credit_via_bankin,
            )

            today = _now_paris_date()
            mois_courant = f"{today.year:04d}-{today.month:02d}-01"

            c = get_credit_by_account(self._conn, account_id=self._account_id)
            if c is None:
                self._kpi_crd.set_content("CRD actuel", "⚙️ Configurez le crédit (1er onglet)")
                return

            credit_id = int(c["id"])
            capital_init = float(c.get("capital_emprunte") or 0.0)
            mensu_theo = (
                float(c.get("mensualite_theorique") or 0.0)
                + float(c.get("assurance_mensuelle_theorique") or 0.0)
            )

            crd_today = float(get_crd_a_date(self._conn, credit_id=credit_id, date_ref=str(today)))
            capital_rembourse = max(0.0, capital_init - crd_today)
            cout_reel = float(cout_reel_mois_credit_via_bankin(
                self._conn, credit_id=credit_id, mois_yyyy_mm_01=mois_courant
            ))
            dates = get_credit_dates(self._conn, credit_id=credit_id)
            date_fin = dates.get("date_fin")
            mois_restants = (
                max(0, (date_fin.year - today.year) * 12 + (date_fin.month - today.month))
                if date_fin else None
            )

            prog = (capital_rembourse / capital_init) if capital_init > 0 else 0.0
            prog = max(0.0, min(1.0, prog))

            self._kpi_crd.set_content("CRD actuel", f"{crd_today:,.2f} €".replace(",", " "))
            self._kpi_mensu.set_content("Mensualité théorique", f"{mensu_theo:,.2f} €".replace(",", " "))
            self._kpi_cout.set_content("Coût réel (mois)", f"{cout_reel:,.2f} €".replace(",", " "))
            self._kpi_restant.set_content(
                "Mois restants", str(mois_restants) if mois_restants is not None else "—"
            )
            self._prog_bar.setValue(int(prog * 100))
            self._prog_pct.setText(f"{prog * 100:.1f}%")

            amort = get_amortissements(self._conn, credit_id=credit_id)
            if not amort.empty and "crd" in amort.columns:
                amort["date_echeance"] = pd.to_datetime(amort["date_echeance"], errors="coerce")
                amort = amort.dropna(subset=["date_echeance"]).sort_values("date_echeance")
                amort["crd"] = pd.to_numeric(amort["crd"], errors="coerce").fillna(0.0)

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=amort["date_echeance"], y=amort["crd"],
                    mode="lines", name="CRD", line=dict(color="#60a5fa")
                ))
                fig.add_trace(go.Scatter(
                    x=[pd.to_datetime(today)], y=[crd_today],
                    mode="markers", name="Aujourd'hui",
                    marker=dict(color="red", size=10)
                ))
                fig.update_layout(**plotly_layout(
                    xaxis_title="Date", yaxis_title="CRD (€)",
                ))
                self._chart_crd.set_figure(fig)
                self._table_amort.set_dataframe(amort)

        except Exception as e:
            logger.error("CompteCreditPanel._load_dashboard error: %s", e, exc_info=True)

    # ── Historique ─────────────────────────────────────────────────────────

    def _load_history(self) -> None:
        try:
            from services import repositories as repo
            from utils.libelles import afficher_type_operation
            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=5000)
            if tx is not None and not tx.empty:
                if "type" in tx.columns:
                    tx = tx.copy()
                    tx["type"] = tx["type"].apply(lambda t: afficher_type_operation(str(t)))
                cols = [c for c in ["date", "type", "amount", "fees", "note", "id"] if c in tx.columns]
                self._hist_table.set_dataframe(tx[cols])
        except Exception as e:
            logger.error("CompteCreditPanel._load_history error: %s", e, exc_info=True)
