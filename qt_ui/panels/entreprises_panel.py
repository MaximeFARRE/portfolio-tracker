"""
Panel Entreprises — remplace ui/entreprises_overview.py
Correctif : ajout d'un onglet "Créer / Modifier" permettant de :
  - créer une nouvelle entreprise avec ses parts,
  - mettre à jour la valorisation d'une entreprise existante.
"""
import logging
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFormLayout, QLineEdit, QDoubleSpinBox, QComboBox, QPushButton,
    QDateEdit, QScrollArea,
)
from qt_ui.components.animated_tab import AnimatedTabWidget
from PyQt6.QtCore import QDate, Qt
from qt_ui.widgets import DataTableWidget, MetricLabel
from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY_BORDERED, STYLE_BTN_SUCCESS,
    STYLE_INPUT_FOCUS, STYLE_FORM_LABEL, STYLE_TITLE, STYLE_SECTION,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_TAB_INNER,
    STYLE_SCROLLAREA, BORDER_SUBTLE, TEXT_SECONDARY,
)

logger = logging.getLogger(__name__)

_ENTITY_TYPES = ["SCI", "SARL", "SAS", "SA", "SASU", "EURL", "HOLDING", "AUTRE"]


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(STYLE_FORM_LABEL)
    return lbl


class EntreprisesPanel(QWidget):
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
        tabs.addTab(self._build_edit_tab(),     "🏢  Créer / Modifier")
        tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(tabs)
        self._tabs = tabs

    # ── Onglet Vue d'ensemble ──────────────────────────────────────────────

    def _build_overview_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Entreprises")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        # ── Ligne 1 de KPIs : valorisation ────────────────────────────────
        kpi_row1 = QHBoxLayout()
        self._kpi_nb          = MetricLabel("Nb entreprises", "—")
        self._kpi_valo_brute  = MetricLabel("Valorisation brute (part)", "—")
        self._kpi_nette       = MetricLabel("Valeur nette des parts", "—")
        self._kpi_pv          = MetricLabel("Plus-value latente", "—")
        for w2 in (self._kpi_nb, self._kpi_valo_brute, self._kpi_nette, self._kpi_pv):
            kpi_row1.addWidget(w2)
        kpi_row1.addStretch()
        layout.addLayout(kpi_row1)

        # ── Ligne 2 de KPIs : investissement & dettes ─────────────────────
        kpi_row2 = QHBoxLayout()
        self._kpi_invest = MetricLabel("Investi initial total", "—")
        self._kpi_cca    = MetricLabel("CCA total", "—")
        self._kpi_dette  = MetricLabel("Dettes totales", "—")
        self._kpi_total  = MetricLabel("Total engagé (invest+CCA)", "—")
        for w2 in (self._kpi_invest, self._kpi_cca, self._kpi_dette, self._kpi_total):
            kpi_row2.addWidget(w2)
        kpi_row2.addStretch()
        layout.addLayout(kpi_row2)

        lbl = QLabel("Détail des entreprises")
        lbl.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl)
        self._table = DataTableWidget()
        self._table.setMinimumHeight(250)
        layout.addWidget(self._table)

        lbl_hist = QLabel("Historique de valorisation")
        lbl_hist.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_hist)
        self._hist_table = DataTableWidget()
        self._hist_table.setMinimumHeight(180)
        layout.addWidget(self._hist_table)

        layout.addStretch()
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

        # ── Section 1 : Nouvelle entreprise ───────────────────────────────
        lbl_new = QLabel("🏢  Créer une nouvelle entreprise")
        lbl_new.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl_new)

        form_new = QFormLayout()
        form_new.setSpacing(8)
        form_new.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ent_name = QLineEdit()
        self._ent_name.setPlaceholderText("Ex: SCI Les Oliviers")
        self._ent_name.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Nom :"), self._ent_name)

        self._ent_type = QComboBox()
        self._ent_type.addItems(_ENTITY_TYPES)
        self._ent_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Type d'entité :"), self._ent_type)

        self._ent_valo = QDoubleSpinBox()
        self._ent_valo.setRange(0, 999_999_999)
        self._ent_valo.setDecimals(2)
        self._ent_valo.setSuffix(" €")
        self._ent_valo.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Valorisation :"), self._ent_valo)

        self._ent_debt = QDoubleSpinBox()
        self._ent_debt.setRange(0, 999_999_999)
        self._ent_debt.setDecimals(2)
        self._ent_debt.setSuffix(" €")
        self._ent_debt.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Dettes :"), self._ent_debt)

        self._ent_note = QLineEdit()
        self._ent_note.setPlaceholderText("Note optionnelle")
        self._ent_note.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Note :"), self._ent_note)

        self._ent_effective_date = QDateEdit()
        self._ent_effective_date.setCalendarPopup(True)
        self._ent_effective_date.setDate(QDate.currentDate())
        self._ent_effective_date.setDisplayFormat("dd/MM/yyyy")
        self._ent_effective_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Date effective :"), self._ent_effective_date)

        v.addLayout(form_new)

        # Parts de la personne courante
        lbl_shares = QLabel("Parts de cette personne dans l'entreprise")
        lbl_shares.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px; font-weight: bold; margin-top: 6px;")
        v.addWidget(lbl_shares)

        form_shares = QFormLayout()
        form_shares.setSpacing(8)
        form_shares.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ent_pct = QDoubleSpinBox()
        self._ent_pct.setRange(0, 100)
        self._ent_pct.setDecimals(2)
        self._ent_pct.setSuffix(" %")
        self._ent_pct.setStyleSheet(STYLE_INPUT_FOCUS)
        form_shares.addRow(_form_label("Pourcentage détenu :"), self._ent_pct)

        self._ent_initial = QDoubleSpinBox()
        self._ent_initial.setRange(0, 999_999_999)
        self._ent_initial.setDecimals(2)
        self._ent_initial.setSuffix(" €")
        self._ent_initial.setStyleSheet(STYLE_INPUT_FOCUS)
        form_shares.addRow(_form_label("Investissement initial :"), self._ent_initial)

        self._ent_cca = QDoubleSpinBox()
        self._ent_cca.setRange(0, 999_999_999)
        self._ent_cca.setDecimals(2)
        self._ent_cca.setSuffix(" €")
        self._ent_cca.setStyleSheet(STYLE_INPUT_FOCUS)
        form_shares.addRow(_form_label("CCA (compte courant associé) :"), self._ent_cca)

        self._ent_invest_date = QDateEdit()
        self._ent_invest_date.setCalendarPopup(True)
        self._ent_invest_date.setDate(QDate.currentDate())
        self._ent_invest_date.setDisplayFormat("dd/MM/yyyy")
        self._ent_invest_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form_shares.addRow(_form_label("Date d'investissement :"), self._ent_invest_date)

        v.addLayout(form_shares)

        row_new = QHBoxLayout()
        btn_create = QPushButton("🏢  Créer l'entreprise")
        btn_create.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_create.clicked.connect(self._save_new_enterprise)
        self._create_status = QLabel("")
        self._create_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row_new.addWidget(btn_create)
        row_new.addWidget(self._create_status)
        row_new.addStretch()
        v.addLayout(row_new)

        # Séparateur
        sep = QLabel()
        sep.setStyleSheet(f"background: {BORDER_SUBTLE}; min-height: 1px; max-height: 1px;")
        v.addWidget(sep)

        # ── Section 2 : Mettre à jour la valorisation ──────────────────────
        lbl_upd = QLabel("📈  Mettre à jour la valorisation")
        lbl_upd.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl_upd)

        form_upd = QFormLayout()
        form_upd.setSpacing(8)
        form_upd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._upd_enterprise = QComboBox()
        self._upd_enterprise.setStyleSheet(STYLE_INPUT_FOCUS)
        # Connexion unique ici — pas dans _refresh_enterprise_combo
        self._upd_enterprise.currentIndexChanged.connect(self._on_enterprise_selected)
        form_upd.addRow(_form_label("Entreprise :"), self._upd_enterprise)

        self._upd_type = QComboBox()
        self._upd_type.addItems(_ENTITY_TYPES)
        self._upd_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Type d'entité :"), self._upd_type)

        self._upd_valo = QDoubleSpinBox()
        self._upd_valo.setRange(0, 999_999_999)
        self._upd_valo.setDecimals(2)
        self._upd_valo.setSuffix(" €")
        self._upd_valo.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Nouvelle valorisation :"), self._upd_valo)

        self._upd_debt = QDoubleSpinBox()
        self._upd_debt.setRange(0, 999_999_999)
        self._upd_debt.setDecimals(2)
        self._upd_debt.setSuffix(" €")
        self._upd_debt.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Dettes :"), self._upd_debt)

        self._upd_note = QLineEdit()
        self._upd_note.setPlaceholderText("Note optionnelle")
        self._upd_note.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Note :"), self._upd_note)

        v.addLayout(form_upd)

        row_upd = QHBoxLayout()
        btn_update = QPushButton("💾  Enregistrer la mise à jour")
        btn_update.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_update.clicked.connect(self._update_enterprise_valo)
        self._update_status = QLabel("")
        self._update_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row_upd.addWidget(btn_update)
        row_upd.addWidget(self._update_status)
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
            self._refresh_enterprise_combo()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    # ── Chargement des données ─────────────────────────────────────────────

    def _load_data(self) -> None:
        try:
            from services import entreprises_repository as ent_repo

            df = ent_repo.list_positions_for_person(self._conn, person_id=self._person_id)
            if df is None or df.empty:
                self._table.set_dataframe(pd.DataFrame([{
                    "Info": "Aucune entreprise. Créez-en une dans l'onglet 🏢 Créer / Modifier."
                }]))
                self._kpi_nb.set_content("Nb entreprises", "0")
                self._kpi_total.set_content("Valeur totale des parts", "0,00 €")
                return

            self._table.set_dataframe(df)
            self._kpi_nb.set_content("Nb entreprises", str(len(df)))

            try:
                d = df.copy()
                # Convertir les colonnes numériques
                for col in ("valuation_eur", "debt_eur", "pct",
                            "initial_invest_eur", "cca_eur"):
                    if col in d.columns:
                        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)

                pct_frac = d["pct"] / 100.0  # ex: 0.60 pour 60 %

                # Valorisation brute pondérée par la part détenue
                valo_brute = float((d["valuation_eur"] * pct_frac).sum())
                # Dettes pondérées par la part détenue
                dette_part = float((d["debt_eur"] * pct_frac).sum())
                # Valeur nette = valorisation - dettes (quote-part)
                valo_nette = valo_brute - dette_part
                # Engagements de la personne
                total_invest = float(d["initial_invest_eur"].sum())
                total_cca    = float(d["cca_eur"].sum())
                total_engage = total_invest + total_cca
                # Plus-value latente = valeur nette - total engagé
                pv = valo_nette - total_engage

                fmt = lambda v: f"{v:,.2f} €".replace(",", " ")

                self._kpi_valo_brute.set_content("Valorisation brute (part)", fmt(valo_brute))
                self._kpi_nette.set_content("Valeur nette des parts", fmt(valo_nette))
                self._kpi_pv.set_content(
                    "Plus-value latente", f"{pv:+,.2f} €".replace(",", " "),
                    delta=f"{pv:+.2f}", delta_positive=pv >= 0,
                )
                self._kpi_invest.set_content("Investi initial total", fmt(total_invest))
                self._kpi_cca.set_content("CCA total", fmt(total_cca))
                self._kpi_dette.set_content("Dettes totales", fmt(dette_part))
                self._kpi_total.set_content("Total engagé (invest+CCA)", fmt(total_engage))

            except Exception as e:
                logger.warning("Erreur calcul KPIs entreprises: %s", e, exc_info=True)

            try:
                hist_frames = []
                for eid in df["enterprise_id"].dropna().unique():
                    h = ent_repo.list_history(self._conn, enterprise_id=int(eid))
                    if h is not None and not h.empty:
                        h = h.copy()
                        h["enterprise_id"] = eid
                        hist_frames.append(h)
                if hist_frames:
                    self._hist_table.set_dataframe(
                        pd.concat(hist_frames, ignore_index=True)
                    )
            except Exception as e:
                logger.warning("Erreur chargement historique entreprises: %s", e, exc_info=True)

        except Exception as e:
            logger.error("Erreur chargement données entreprises: %s", e, exc_info=True)
            self._table.set_dataframe(pd.DataFrame([{"Erreur": str(e)}]))

    # ── Combo entreprises (section Mise à jour) ────────────────────────────

    def _refresh_enterprise_combo(self) -> None:
        try:
            from services import entreprises_repository as ent_repo
            df = ent_repo.list_enterprises(self._conn)
            # Bloquer les signaux pendant le remplissage pour éviter les appels multiples
            self._upd_enterprise.blockSignals(True)
            self._upd_enterprise.clear()
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    self._upd_enterprise.addItem(str(r["name"]), int(r["id"]))
            self._upd_enterprise.blockSignals(False)
            # Pré-remplir avec la première entreprise
            if self._upd_enterprise.count() > 0:
                self._on_enterprise_selected(0)
        except Exception as e:
            logger.error("Erreur rafraîchissement combo entreprises: %s", e, exc_info=True)

    def _on_enterprise_selected(self, _idx: int) -> None:
        """Pré-remplit les champs de mise à jour avec les valeurs actuelles."""
        try:
            from services import entreprises_repository as ent_repo
            eid = self._upd_enterprise.currentData()
            if eid is None:
                return
            row = ent_repo.get_enterprise(self._conn, enterprise_id=int(eid))
            if row:
                self._upd_valo.setValue(float(row["valuation_eur"] or 0))
                self._upd_debt.setValue(float(row["debt_eur"] or 0))
                type_val = str(row["entity_type"] or "AUTRE")
                tidx = self._upd_type.findText(type_val)
                if tidx >= 0:
                    self._upd_type.setCurrentIndex(tidx)
                self._upd_note.setText(str(row["note"] or ""))
        except Exception as e:
            logger.warning("Erreur pré-remplissage entreprise: %s", e, exc_info=True)

    # ── Sauvegarde : nouvelle entreprise ──────────────────────────────────

    def _save_new_enterprise(self) -> None:
        try:
            from services import entreprises_repository as ent_repo

            name = self._ent_name.text().strip()
            if not name:
                self._create_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._create_status.setText("❌  Le nom est obligatoire.")
                return

            effective_date = self._ent_effective_date.date().toString("yyyy-MM-dd")

            eid = ent_repo.create_enterprise(
                self._conn,
                name=name,
                entity_type=self._ent_type.currentText(),
                valuation_eur=self._ent_valo.value(),
                debt_eur=self._ent_debt.value(),
                note=self._ent_note.text().strip() or None,
                effective_date=effective_date,
            )

            # Associer les parts à la personne courante si un % est renseigné
            pct = self._ent_pct.value()
            if pct > 0 and self._person_id:
                ent_repo.replace_shares(
                    self._conn,
                    enterprise_id=eid,
                    shares_by_person_id={
                        self._person_id: {
                            "pct":          pct,
                            "initial":      self._ent_initial.value(),
                            "cca":          self._ent_cca.value(),
                            "initial_date": self._ent_invest_date.date().toString("yyyy-MM-dd"),
                        }
                    },
                )

            self._create_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._create_status.setText(f"✅  Entreprise « {name} » créée (id={eid}).")

            # Réinitialiser le formulaire
            self._ent_name.clear()
            self._ent_note.clear()
            self._ent_valo.setValue(0)
            self._ent_debt.setValue(0)
            self._ent_pct.setValue(0)
            self._ent_initial.setValue(0)
            self._ent_cca.setValue(0)

            self._refresh_enterprise_combo()

        except Exception as e:
            logger.error("Erreur création entreprise: %s", e, exc_info=True)
            self._create_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._create_status.setText(f"❌  Erreur : {e}")

    # ── Mise à jour de la valorisation ────────────────────────────────────

    def _update_enterprise_valo(self) -> None:
        try:
            from services import entreprises_repository as ent_repo

            eid = self._upd_enterprise.currentData()
            if eid is None:
                self._update_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._update_status.setText("❌  Sélectionnez une entreprise.")
                return

            ent_repo.update_enterprise(
                self._conn,
                enterprise_id=int(eid),
                entity_type=self._upd_type.currentText(),
                valuation_eur=self._upd_valo.value(),
                debt_eur=self._upd_debt.value(),
                note=self._upd_note.text().strip() or None,
            )
            name = self._upd_enterprise.currentText()
            self._update_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._update_status.setText(
                f"✅  « {name} » mise à jour → {self._upd_valo.value():,.2f} €."
            )
        except Exception as e:
            logger.error("Erreur mise à jour entreprise: %s", e, exc_info=True)
            self._update_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._update_status.setText(f"❌  Erreur : {e}")
