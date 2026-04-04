"""
Panel Immobilier — Vue d'ensemble + Créer / Modifier.
Gère l'immobilier direct (RP, locatif, parking, SCI…)
et remonte automatiquement les SCPI détenues dans les comptes existants.
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

_PROPERTY_TYPES = ["RP", "LOCATIF", "SCPI", "PARKING", "TERRAIN", "IMMEUBLE", "SCI_IMMO", "AUTRE"]

_FMT = lambda v: f"{v:,.0f} €".replace(",", " ")
_FMT2 = lambda v: f"{v:,.2f} €".replace(",", " ")
_DASH = "—"


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(STYLE_FORM_LABEL)
    return lbl


class ImmobilierPanel(QWidget):
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
        tabs.addTab(self._build_overview_tab(), "🏠  Vue d'ensemble")
        tabs.addTab(self._build_edit_tab(),     "🏗️  Créer / Modifier")
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

        title = QLabel("Immobilier")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        # KPI ligne 1 — patrimoine
        kpi1 = QHBoxLayout()
        self._kpi_nb         = MetricLabel("Nb biens / projets",     _DASH)
        self._kpi_brut        = MetricLabel("Valeur brute détenue",   _DASH)
        self._kpi_dette       = MetricLabel("Dette imputable",        _DASH)
        self._kpi_net         = MetricLabel("Valeur nette immo",      _DASH)
        for w2 in (self._kpi_nb, self._kpi_brut, self._kpi_dette, self._kpi_net):
            kpi1.addWidget(w2)
        kpi1.addStretch()
        layout.addLayout(kpi1)

        # KPI ligne 2 — rendement
        kpi2 = QHBoxLayout()
        self._kpi_loyers      = MetricLabel("Loyers annuels bruts",   _DASH)
        self._kpi_rendement   = MetricLabel("Rendement brut moyen",   _DASH)
        self._kpi_ltv         = MetricLabel("LTV moyen",              _DASH)
        for w2 in (self._kpi_loyers, self._kpi_rendement, self._kpi_ltv):
            kpi2.addWidget(w2)
        kpi2.addStretch()
        layout.addLayout(kpi2)

        # Tableau détail
        lbl_detail = QLabel("Détail des biens immobiliers")
        lbl_detail.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_detail)
        self._table = DataTableWidget()
        self._table.setMinimumHeight(260)
        layout.addWidget(self._table)

        # Historique
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

        # ── Section : Créer un nouveau bien ───────────────────────────────
        lbl_new = QLabel("🏠  Créer un nouveau bien immobilier")
        lbl_new.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl_new)

        form_new = QFormLayout()
        form_new.setSpacing(8)
        form_new.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("Ex : Appartement Lyon, SCI Les Pins…")
        self._new_name.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Nom :"), self._new_name)

        self._new_type = QComboBox()
        self._new_type.addItems(_PROPERTY_TYPES)
        self._new_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Type de bien :"), self._new_type)

        self._new_valo = QDoubleSpinBox()
        self._new_valo.setRange(0, 999_999_999)
        self._new_valo.setDecimals(2)
        self._new_valo.setSuffix(" €")
        self._new_valo.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Valeur actuelle :"), self._new_valo)

        self._new_debt = QDoubleSpinBox()
        self._new_debt.setRange(0, 999_999_999)
        self._new_debt.setDecimals(2)
        self._new_debt.setSuffix(" €")
        self._new_debt.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Dette restante :"), self._new_debt)

        self._new_loyer = QDoubleSpinBox()
        self._new_loyer.setRange(0, 999_999)
        self._new_loyer.setDecimals(2)
        self._new_loyer.setSuffix(" €/mois")
        self._new_loyer.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Loyer mensuel brut :"), self._new_loyer)

        self._new_charges = QDoubleSpinBox()
        self._new_charges.setRange(0, 999_999)
        self._new_charges.setDecimals(2)
        self._new_charges.setSuffix(" €/an")
        self._new_charges.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Charges annuelles :"), self._new_charges)

        self._new_taxe = QDoubleSpinBox()
        self._new_taxe.setRange(0, 999_999)
        self._new_taxe.setDecimals(2)
        self._new_taxe.setSuffix(" €/an")
        self._new_taxe.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Taxe foncière annuelle :"), self._new_taxe)

        self._new_note = QLineEdit()
        self._new_note.setPlaceholderText("Note optionnelle")
        self._new_note.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Note :"), self._new_note)

        self._new_date = QDateEdit()
        self._new_date.setCalendarPopup(True)
        self._new_date.setDate(QDate.currentDate())
        self._new_date.setDisplayFormat("dd/MM/yyyy")
        self._new_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form_new.addRow(_form_label("Date effective :"), self._new_date)

        v.addLayout(form_new)

        # Quote-part de la personne courante
        lbl_share = QLabel("Quote-part de cette personne")
        lbl_share.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 13px; font-weight: bold; margin-top: 6px;"
        )
        v.addWidget(lbl_share)

        form_share = QFormLayout()
        form_share.setSpacing(8)
        form_share.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._new_pct = QDoubleSpinBox()
        self._new_pct.setRange(0, 100)
        self._new_pct.setDecimals(2)
        self._new_pct.setSuffix(" %")
        self._new_pct.setValue(100.0)
        self._new_pct.setStyleSheet(STYLE_INPUT_FOCUS)
        form_share.addRow(_form_label("% détenu :"), self._new_pct)

        self._new_initial = QDoubleSpinBox()
        self._new_initial.setRange(0, 999_999_999)
        self._new_initial.setDecimals(2)
        self._new_initial.setSuffix(" €")
        self._new_initial.setStyleSheet(STYLE_INPUT_FOCUS)
        form_share.addRow(_form_label("Investissement initial :"), self._new_initial)

        self._new_invest_date = QDateEdit()
        self._new_invest_date.setCalendarPopup(True)
        self._new_invest_date.setDate(QDate.currentDate())
        self._new_invest_date.setDisplayFormat("dd/MM/yyyy")
        self._new_invest_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form_share.addRow(_form_label("Date d'investissement :"), self._new_invest_date)

        v.addLayout(form_share)

        row_new = QHBoxLayout()
        btn_create = QPushButton("🏠  Créer le bien")
        btn_create.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_create.clicked.connect(self._save_new_property)
        self._create_status = QLabel("")
        self._create_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row_new.addWidget(btn_create)
        row_new.addWidget(self._create_status)
        row_new.addStretch()
        v.addLayout(row_new)

        # Séparateur
        sep = QLabel()
        sep.setStyleSheet(
            f"background: {BORDER_SUBTLE}; min-height: 1px; max-height: 1px;"
        )
        v.addWidget(sep)

        # ── Section : Mettre à jour un bien existant ───────────────────────
        lbl_upd = QLabel("📈  Mettre à jour un bien existant")
        lbl_upd.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl_upd)

        form_upd = QFormLayout()
        form_upd.setSpacing(8)
        form_upd.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._upd_combo = QComboBox()
        self._upd_combo.setStyleSheet(STYLE_INPUT_FOCUS)
        self._upd_combo.currentIndexChanged.connect(self._on_property_selected)
        form_upd.addRow(_form_label("Bien :"), self._upd_combo)

        self._upd_type = QComboBox()
        self._upd_type.addItems(_PROPERTY_TYPES)
        self._upd_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Type de bien :"), self._upd_type)

        self._upd_valo = QDoubleSpinBox()
        self._upd_valo.setRange(0, 999_999_999)
        self._upd_valo.setDecimals(2)
        self._upd_valo.setSuffix(" €")
        self._upd_valo.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Nouvelle valeur :"), self._upd_valo)

        self._upd_debt = QDoubleSpinBox()
        self._upd_debt.setRange(0, 999_999_999)
        self._upd_debt.setDecimals(2)
        self._upd_debt.setSuffix(" €")
        self._upd_debt.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Dette restante :"), self._upd_debt)

        self._upd_loyer = QDoubleSpinBox()
        self._upd_loyer.setRange(0, 999_999)
        self._upd_loyer.setDecimals(2)
        self._upd_loyer.setSuffix(" €/mois")
        self._upd_loyer.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Loyer mensuel brut :"), self._upd_loyer)

        self._upd_charges = QDoubleSpinBox()
        self._upd_charges.setRange(0, 999_999)
        self._upd_charges.setDecimals(2)
        self._upd_charges.setSuffix(" €/an")
        self._upd_charges.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Charges annuelles :"), self._upd_charges)

        self._upd_taxe = QDoubleSpinBox()
        self._upd_taxe.setRange(0, 999_999)
        self._upd_taxe.setDecimals(2)
        self._upd_taxe.setSuffix(" €/an")
        self._upd_taxe.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Taxe foncière :"), self._upd_taxe)

        self._upd_note = QLineEdit()
        self._upd_note.setPlaceholderText("Note optionnelle")
        self._upd_note.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Note :"), self._upd_note)

        self._upd_date = QDateEdit()
        self._upd_date.setCalendarPopup(True)
        self._upd_date.setDate(QDate.currentDate())
        self._upd_date.setDisplayFormat("dd/MM/yyyy")
        self._upd_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form_upd.addRow(_form_label("Date effective :"), self._upd_date)

        v.addLayout(form_upd)

        row_upd = QHBoxLayout()
        btn_upd = QPushButton("💾  Enregistrer la mise à jour")
        btn_upd.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_upd.clicked.connect(self._update_property)
        self._update_status = QLabel("")
        self._update_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row_upd.addWidget(btn_upd)
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
            self._refresh_property_combo()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    # ── Chargement des données ─────────────────────────────────────────────

    def _load_data(self) -> None:
        try:
            from services import immobilier_repository as immo_repo

            df = immo_repo.aggregate_positions(self._conn, self._person_id)

            if df is None or df.empty:
                self._table.set_dataframe(pd.DataFrame([{
                    "Info": "Aucun bien immobilier. Créez-en un dans l'onglet 🏗️ Créer / Modifier."
                }]))
                self._reset_kpis()
                self._hist_table.set_dataframe(pd.DataFrame())
                return

            # ── KPIs ──────────────────────────────────────────────────────
            try:
                self._compute_kpis(df)
            except Exception as e:
                logger.warning("Erreur calcul KPIs immobilier : %s", e, exc_info=True)

            # ── Tableau principal ─────────────────────────────────────────
            # Formater les colonnes numériques pour l'affichage
            display_df = df.copy()
            display_df = self._format_display_df(display_df)
            self._table.set_dataframe(display_df)

            # ── Historique (biens directs uniquement) ─────────────────────
            try:
                prop_ids = df[df["property_id"].notna()]["property_id"].unique()
                hist_frames = []
                for pid in prop_ids:
                    h = immo_repo.list_history(self._conn, property_id=int(pid))
                    if h is not None and not h.empty:
                        h = h.copy()
                        # Récupérer le nom du bien
                        name = df[df["property_id"] == pid]["nom"].values
                        h["bien"] = name[0] if len(name) > 0 else str(int(pid))
                        hist_frames.append(h)
                if hist_frames:
                    self._hist_table.set_dataframe(
                        pd.concat(hist_frames, ignore_index=True)
                    )
                else:
                    self._hist_table.set_dataframe(pd.DataFrame())
            except Exception as e:
                logger.warning("Erreur chargement historique immo : %s", e, exc_info=True)

        except Exception as e:
            logger.error("Erreur chargement immobilier : %s", e, exc_info=True)
            self._table.set_dataframe(pd.DataFrame([{"Erreur": str(e)}]))

    def _compute_kpis(self, df: pd.DataFrame) -> None:
        nb = len(df)

        brut_total   = df["valeur_detenue"].sum()
        dette_total  = df["dette_imputable"].sum()
        net_total    = df["valeur_nette"].sum()
        loyers_total = df["loyers_annuels"].sum()

        # Rendement moyen pondéré par la valeur totale
        df_rdt = df[df["valeur_totale"] > 0].copy()
        if not df_rdt.empty and brut_total > 0:
            rdt_moyen = (
                (df_rdt["loyers_annuels"] / df_rdt["valeur_totale"] * 100)
                * df_rdt["valeur_detenue"]
            ).sum() / brut_total
            rdt_str = f"{rdt_moyen:.2f} %"
        else:
            rdt_str = _DASH

        # LTV moyen
        ltv_str = (
            f"{dette_total / brut_total * 100:.1f} %"
            if brut_total > 0 else _DASH
        )

        self._kpi_nb.set_content("Nb biens / projets",    str(nb))
        self._kpi_brut.set_content("Valeur brute détenue", _FMT(brut_total))
        self._kpi_dette.set_content("Dette imputable",     _FMT(dette_total))
        self._kpi_net.set_content("Valeur nette immo",     _FMT(net_total))
        self._kpi_loyers.set_content("Loyers annuels bruts", _FMT(loyers_total))
        self._kpi_rendement.set_content("Rendement brut moyen", rdt_str)
        self._kpi_ltv.set_content("LTV moyen", ltv_str)

    def _reset_kpis(self) -> None:
        for kpi in (
            self._kpi_nb, self._kpi_brut, self._kpi_dette, self._kpi_net,
            self._kpi_loyers, self._kpi_rendement, self._kpi_ltv,
        ):
            kpi.set_content(kpi._label_lbl.text(), _DASH)

    @staticmethod
    def _format_display_df(df: pd.DataFrame) -> pd.DataFrame:
        """Prépare un DataFrame propre pour l'affichage dans DataTableWidget."""
        cols_eur = ["valeur_totale", "valeur_detenue", "dette_totale",
                    "dette_imputable", "valeur_nette", "loyer_mensuel", "loyers_annuels"]
        for c in cols_eur:
            if c in df.columns:
                df[c] = df[c].apply(
                    lambda v: _FMT(v) if pd.notna(v) else _DASH
                )
        if "rendement_brut" in df.columns:
            df["rendement_brut"] = df["rendement_brut"].apply(
                lambda v: f"{v:.2f} %" if pd.notna(v) and v is not None else _DASH
            )
        if "pct" in df.columns:
            df["pct"] = df["pct"].apply(
                lambda v: f"{v:.1f} %" if pd.notna(v) else _DASH
            )
        # Supprimer les colonnes techniques pas utiles dans le tableau
        return df.drop(columns=["property_id"], errors="ignore")

    # ── Combo biens (section Mise à jour) ─────────────────────────────────

    def _refresh_property_combo(self) -> None:
        try:
            from services import immobilier_repository as immo_repo
            df = immo_repo.list_properties(self._conn)
            self._upd_combo.blockSignals(True)
            self._upd_combo.clear()
            if df is not None and not df.empty:
                for _, r in df.iterrows():
                    self._upd_combo.addItem(str(r["name"]), int(r["id"]))
            self._upd_combo.blockSignals(False)
            if self._upd_combo.count() > 0:
                self._on_property_selected(0)
        except Exception as e:
            logger.error("Erreur rafraîchissement combo biens : %s", e, exc_info=True)

    def _on_property_selected(self, _idx: int) -> None:
        """Pré-remplit les champs de mise à jour avec les valeurs actuelles."""
        try:
            from services import immobilier_repository as immo_repo
            pid = self._upd_combo.currentData()
            if pid is None:
                return
            row = immo_repo.get_property(self._conn, property_id=int(pid))
            if not row:
                return
            self._upd_valo.setValue(float(row["valuation_eur"] or 0))
            self._upd_debt.setValue(float(row["debt_eur"] or 0))
            self._upd_loyer.setValue(float(row["monthly_rent_eur"] or 0))
            self._upd_charges.setValue(float(row["annual_charges_eur"] or 0))
            self._upd_taxe.setValue(float(row["annual_tax_eur"] or 0))
            self._upd_note.setText(str(row["note"] or ""))

            tidx = self._upd_type.findText(str(row["property_type"] or "AUTRE"))
            if tidx >= 0:
                self._upd_type.setCurrentIndex(tidx)

            try:
                d = QDate.fromString(str(row["effective_date"] or ""), "yyyy-MM-dd")
                if d.isValid():
                    self._upd_date.setDate(d)
            except Exception:
                pass
        except Exception as e:
            logger.warning("Erreur pré-remplissage bien : %s", e, exc_info=True)

    # ── Sauvegarde : nouveau bien ──────────────────────────────────────────

    def _save_new_property(self) -> None:
        try:
            from services import immobilier_repository as immo_repo

            name = self._new_name.text().strip()
            if not name:
                self._create_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._create_status.setText("❌  Le nom est obligatoire.")
                return

            effective_date = self._new_date.date().toString("yyyy-MM-dd")

            pid = immo_repo.create_property(
                self._conn,
                name=name,
                property_type=self._new_type.currentText(),
                valuation_eur=self._new_valo.value(),
                debt_eur=self._new_debt.value(),
                monthly_rent_eur=self._new_loyer.value(),
                annual_charges_eur=self._new_charges.value(),
                annual_tax_eur=self._new_taxe.value(),
                note=self._new_note.text().strip() or None,
                effective_date=effective_date,
            )

            # Associer la quote-part de la personne courante
            pct = self._new_pct.value()
            if self._person_id and pct > 0:
                immo_repo.replace_shares(
                    self._conn,
                    property_id=pid,
                    person_id=self._person_id,
                    pct=pct,
                    initial_invest_eur=self._new_initial.value(),
                    initial_date=self._new_invest_date.date().toString("yyyy-MM-dd"),
                )

            self._create_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._create_status.setText(f"✅  Bien « {name} » créé (id={pid}).")

            # Réinitialiser le formulaire
            self._new_name.clear()
            self._new_note.clear()
            self._new_valo.setValue(0)
            self._new_debt.setValue(0)
            self._new_loyer.setValue(0)
            self._new_charges.setValue(0)
            self._new_taxe.setValue(0)
            self._new_pct.setValue(100.0)
            self._new_initial.setValue(0)

            self._refresh_property_combo()

        except Exception as e:
            logger.error("Erreur création bien immo : %s", e, exc_info=True)
            self._create_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._create_status.setText(f"❌  Erreur : {e}")

    # ── Mise à jour d'un bien ──────────────────────────────────────────────

    def _update_property(self) -> None:
        try:
            from services import immobilier_repository as immo_repo

            pid = self._upd_combo.currentData()
            if pid is None:
                self._update_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._update_status.setText("❌  Sélectionnez un bien.")
                return

            effective_date = self._upd_date.date().toString("yyyy-MM-dd")

            immo_repo.update_property(
                self._conn,
                property_id=int(pid),
                property_type=self._upd_type.currentText(),
                valuation_eur=self._upd_valo.value(),
                debt_eur=self._upd_debt.value(),
                monthly_rent_eur=self._upd_loyer.value(),
                annual_charges_eur=self._upd_charges.value(),
                annual_tax_eur=self._upd_taxe.value(),
                note=self._upd_note.text().strip() or None,
                effective_date=effective_date,
            )

            name = self._upd_combo.currentText()
            self._update_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._update_status.setText(
                f"✅  « {name} » mis à jour → {_FMT2(self._upd_valo.value())}."
            )

        except Exception as e:
            logger.error("Erreur mise à jour bien immo : %s", e, exc_info=True)
            self._update_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._update_status.setText(f"❌  Erreur : {e}")
