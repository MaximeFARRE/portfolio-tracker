"""
Panel Private Equity — remplace ui/private_equity_overview.py
Correctifs :
  - Affiche les positions calculées (invested/value/pnl) au lieu des projets bruts.
  - Ajoute un onglet Saisie pour créer des projets et enregistrer des transactions
    (avec champs quantité et prix unitaire).
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
from qt_ui.widgets import PlotlyView, DataTableWidget, MetricLabel
from qt_ui.theme import (
    BG_PRIMARY, STYLE_BTN_PRIMARY_BORDERED, STYLE_BTN_SUCCESS,
    STYLE_INPUT_FOCUS, STYLE_FORM_LABEL, STYLE_TITLE, STYLE_SECTION,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_TAB_INNER,
    STYLE_SCROLLAREA, BORDER_SUBTLE,
)

logger = logging.getLogger(__name__)


def _form_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(STYLE_FORM_LABEL)
    return lbl


class PrivateEquityPanel(QWidget):
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
        tabs.addTab(self._build_saisie_tab(),   "➕  Saisie")
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

        title = QLabel("Private Equity")
        title.setStyleSheet(STYLE_TITLE)
        layout.addWidget(title)

        # ── Ligne 1 de KPIs : vue financière ──────────────────────────────
        kpi_row1 = QHBoxLayout()
        self._kpi_value    = MetricLabel("Valeur PE totale", "—")
        self._kpi_invested = MetricLabel("Investi total", "—")
        self._kpi_pnl      = MetricLabel("PnL latent", "—")
        self._kpi_moic     = MetricLabel("MOIC global", "—")
        for w2 in (self._kpi_value, self._kpi_invested, self._kpi_pnl, self._kpi_moic):
            kpi_row1.addWidget(w2)
        kpi_row1.addStretch()
        layout.addLayout(kpi_row1)

        # ── Ligne 2 de KPIs : activité & performance ───────────────────────
        kpi_row2 = QHBoxLayout()
        self._kpi_cash_out   = MetricLabel("Distributions reçues", "—")
        self._kpi_fees       = MetricLabel("Frais totaux", "—")
        self._kpi_projets    = MetricLabel("Projets", "—")
        self._kpi_success    = MetricLabel("Taux de réussite", "—")
        self._kpi_holding    = MetricLabel("Durée moy. détention", "—")
        for w2 in (self._kpi_cash_out, self._kpi_fees, self._kpi_projets,
                   self._kpi_success, self._kpi_holding):
            kpi_row2.addWidget(w2)
        kpi_row2.addStretch()
        layout.addLayout(kpi_row2)

        lbl_proj = QLabel("Positions PE (projets)")
        lbl_proj.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_proj)
        self._table_projects = DataTableWidget()
        self._table_projects.setMinimumHeight(220)
        layout.addWidget(self._table_projects)

        lbl_tx = QLabel("Historique des transactions")
        lbl_tx.setStyleSheet(STYLE_SECTION)
        layout.addWidget(lbl_tx)
        self._table_tx = DataTableWidget()
        self._table_tx.setMinimumHeight(180)
        layout.addWidget(self._table_tx)

        layout.addStretch()
        return w

    # ── Onglet Saisie ──────────────────────────────────────────────────────

    def _build_saisie_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(STYLE_SCROLLAREA)

        container = QWidget()
        container.setStyleSheet(f"background: {BG_PRIMARY};")
        v = QVBoxLayout(container)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(20)

        # ── Section 1 : Nouveau projet ─────────────────────────────────────
        lbl1 = QLabel("🌱  Créer un nouveau projet PE")
        lbl1.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl1)

        form1 = QFormLayout()
        form1.setSpacing(8)

        self._pe_proj_name = QLineEdit()
        self._pe_proj_name.setPlaceholderText("Ex: Crowdfunding Immo Paris 2024")
        self._pe_proj_name.setStyleSheet(STYLE_INPUT_FOCUS)
        form1.addRow(_form_label("Nom du projet :"), self._pe_proj_name)

        self._pe_proj_platform = QLineEdit()
        self._pe_proj_platform.setPlaceholderText("Ex: Homunity, Anaxago, ...")
        self._pe_proj_platform.setStyleSheet(STYLE_INPUT_FOCUS)
        form1.addRow(_form_label("Plateforme :"), self._pe_proj_platform)

        self._pe_proj_type = QComboBox()
        self._pe_proj_type.addItems(["IMMO", "STARTUP", "PME", "DETTE", "AUTRE"])
        self._pe_proj_type.setStyleSheet(STYLE_INPUT_FOCUS)
        form1.addRow(_form_label("Type :"), self._pe_proj_type)

        self._pe_proj_note = QLineEdit()
        self._pe_proj_note.setPlaceholderText("Note optionnelle")
        self._pe_proj_note.setStyleSheet(STYLE_INPUT_FOCUS)
        form1.addRow(_form_label("Note :"), self._pe_proj_note)

        v.addLayout(form1)

        row1 = QHBoxLayout()
        btn_add_proj = QPushButton("➕  Créer le projet")
        btn_add_proj.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_add_proj.clicked.connect(self._save_project)
        self._pe_proj_status = QLabel("")
        self._pe_proj_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row1.addWidget(btn_add_proj)
        row1.addWidget(self._pe_proj_status)
        row1.addStretch()
        v.addLayout(row1)

        # Séparateur visuel
        sep = QLabel()
        sep.setStyleSheet(f"background: {BORDER_SUBTLE}; min-height: 1px; max-height: 1px;")
        v.addWidget(sep)

        # ── Section 2 : Nouvelle transaction ──────────────────────────────
        lbl2 = QLabel("💸  Saisir une transaction PE")
        lbl2.setStyleSheet(STYLE_TITLE)
        v.addWidget(lbl2)

        form2 = QFormLayout()
        form2.setSpacing(8)

        self._pe_tx_project = QComboBox()
        self._pe_tx_project.setStyleSheet(STYLE_INPUT_FOCUS)
        form2.addRow(_form_label("Projet :"), self._pe_tx_project)

        self._pe_tx_date = QDateEdit()
        self._pe_tx_date.setCalendarPopup(True)
        self._pe_tx_date.setDate(QDate.currentDate())
        self._pe_tx_date.setDisplayFormat("dd/MM/yyyy")
        self._pe_tx_date.setStyleSheet(STYLE_INPUT_FOCUS)
        form2.addRow(_form_label("Date :"), self._pe_tx_date)

        self._pe_tx_type = QComboBox()
        self._pe_tx_type.addItems(["INVEST", "VALO", "DISTRIB", "VENTE"])
        self._pe_tx_type.setStyleSheet(STYLE_INPUT_FOCUS)
        self._pe_tx_type.currentTextChanged.connect(self._on_pe_tx_type_changed)
        form2.addRow(_form_label("Type :"), self._pe_tx_type)

        self._pe_tx_amount = QDoubleSpinBox()
        self._pe_tx_amount.setRange(0, 9_999_999)
        self._pe_tx_amount.setDecimals(2)
        self._pe_tx_amount.setSuffix(" €")
        self._pe_tx_amount.setStyleSheet(STYLE_INPUT_FOCUS)
        form2.addRow(_form_label("Montant :"), self._pe_tx_amount)

        # Quantité et prix unitaire (visible pour INVEST et VENTE uniquement)
        self._pe_tx_qty_lbl = _form_label("Quantité (parts) :")
        self._pe_tx_quantity = QDoubleSpinBox()
        self._pe_tx_quantity.setRange(0, 9_999_999)
        self._pe_tx_quantity.setDecimals(4)
        self._pe_tx_quantity.setStyleSheet(STYLE_INPUT_FOCUS)
        form2.addRow(self._pe_tx_qty_lbl, self._pe_tx_quantity)

        self._pe_tx_price_lbl = _form_label("Prix unitaire (€/part) :")
        self._pe_tx_unitprice = QDoubleSpinBox()
        self._pe_tx_unitprice.setRange(0, 9_999_999)
        self._pe_tx_unitprice.setDecimals(4)
        self._pe_tx_unitprice.setSuffix(" €")
        self._pe_tx_unitprice.setStyleSheet(STYLE_INPUT_FOCUS)
        form2.addRow(self._pe_tx_price_lbl, self._pe_tx_unitprice)

        self._pe_tx_note = QLineEdit()
        self._pe_tx_note.setPlaceholderText("Note optionnelle")
        self._pe_tx_note.setStyleSheet(STYLE_INPUT_FOCUS)
        form2.addRow(_form_label("Note :"), self._pe_tx_note)

        v.addLayout(form2)

        row2 = QHBoxLayout()
        btn_add_tx = QPushButton("💾  Enregistrer la transaction")
        btn_add_tx.setStyleSheet(STYLE_BTN_SUCCESS)
        btn_add_tx.clicked.connect(self._save_pe_transaction)
        self._pe_tx_status = QLabel("")
        self._pe_tx_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        row2.addWidget(btn_add_tx)
        row2.addWidget(self._pe_tx_status)
        row2.addStretch()
        v.addLayout(row2)

        v.addStretch()
        scroll.setWidget(container)

        # Initialiser la visibilité des champs quantité/prix
        self._on_pe_tx_type_changed("INVEST")
        return scroll

    # ── Visibilité quantité / prix selon le type ──────────────────────────

    def _on_pe_tx_type_changed(self, tx_type: str) -> None:
        """Affiche quantité et prix unitaire seulement pour INVEST et VENTE."""
        show = tx_type in ("INVEST", "VENTE")
        for widget in (self._pe_tx_qty_lbl, self._pe_tx_quantity,
                       self._pe_tx_price_lbl, self._pe_tx_unitprice):
            widget.setVisible(show)

    # ── Navigation ─────────────────────────────────────────────────────────

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self._load_data()
        elif idx == 1:
            self._refresh_project_combo()

    def refresh(self) -> None:
        self._load_data()

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id
        self._load_data()

    # ── Chargement vue d'ensemble ──────────────────────────────────────────

    def _load_data(self) -> None:
        try:
            from services import private_equity_repository as pe_repo
            from services import private_equity as pe

            projects = pe_repo.list_pe_projects(self._conn, person_id=self._person_id)
            if projects is None or projects.empty:
                self._table_projects.set_dataframe(pd.DataFrame([{
                    "Info": "Aucun projet PE. Créez-en un dans l'onglet ➕ Saisie."
                }]))
                self._table_tx.set_dataframe(pd.DataFrame())
                self._kpi_value.set_content("Valeur PE totale", "0,00 €")
                self._kpi_invested.set_content("Investi total", "0,00 €")
                self._kpi_pnl.set_content("PnL latent", "—")
                return

            tx = pe_repo.list_pe_transactions(self._conn, person_id=self._person_id)

            if tx is not None and not tx.empty:
                # ── Afficher les POSITIONS calculées (avec invested, value, pnl, moic)
                try:
                    positions = pe.build_pe_positions(projects, tx)
                    self._table_projects.set_dataframe(positions)
                    kpis = pe.compute_pe_kpis(positions)

                    total_val  = float(kpis.get("value", 0))
                    total_inv  = float(kpis.get("invested", 0))
                    pnl        = float(kpis.get("pnl", 0))
                    moic       = kpis.get("moic")
                    cash_out   = float(kpis.get("cash_out", 0))
                    fees       = float(kpis.get("fees", 0))
                    n_total    = int(kpis.get("n_total", 0))
                    n_en_cours = int(kpis.get("n_en_cours", 0))
                    n_sortis   = int(kpis.get("n_sortis", 0))
                    n_faillite = int(kpis.get("n_faillite", 0))
                    success    = kpis.get("success_rate")
                    avg_days   = kpis.get("avg_holding_days")

                    # Ligne 1
                    self._kpi_value.set_content(
                        "Valeur PE totale", f"{total_val:,.2f} €".replace(",", " ")
                    )
                    self._kpi_invested.set_content(
                        "Investi total", f"{total_inv:,.2f} €".replace(",", " ")
                    )
                    self._kpi_pnl.set_content(
                        "PnL latent", f"{pnl:+,.2f} €".replace(",", " "),
                        delta=f"{pnl:+.2f}", delta_positive=pnl >= 0,
                    )
                    self._kpi_moic.set_content(
                        "MOIC global",
                        f"{moic:.2f}x" if moic is not None else "—",
                    )

                    # Ligne 2
                    self._kpi_cash_out.set_content(
                        "Distributions reçues", f"{cash_out:,.2f} €".replace(",", " ")
                    )
                    self._kpi_fees.set_content(
                        "Frais totaux", f"{fees:,.2f} €".replace(",", " ")
                    )
                    proj_label = (
                        f"{n_en_cours} en cours"
                        + (f" · {n_sortis} sortis" if n_sortis else "")
                        + (f" · {n_faillite} ⚠" if n_faillite else "")
                    )
                    self._kpi_projets.set_content(f"Projets ({n_total})", proj_label)
                    self._kpi_success.set_content(
                        "Taux de réussite",
                        f"{success * 100:.0f}%" if success is not None else "—",
                    )
                    self._kpi_holding.set_content(
                        "Durée moy. détention",
                        f"{avg_days:.0f} j" if avg_days is not None else "—",
                    )

                except Exception as e:
                    logger.error("Erreur build_pe_positions: %s", e, exc_info=True)
                    # Fallback : projets bruts si build_pe_positions échoue
                    self._table_projects.set_dataframe(projects)

                # ── Historique des transactions
                try:
                    wanted_cols = [
                        "project_name", "date", "tx_type",
                        "amount", "quantity", "unit_price", "note",
                    ]
                    cols = [c for c in wanted_cols if c in tx.columns]
                    self._table_tx.set_dataframe(tx[cols] if cols else tx)
                except Exception as e:
                    logger.warning("Erreur affichage transactions PE: %s", e, exc_info=True)
                    self._table_tx.set_dataframe(tx)
            else:
                # Pas encore de transactions → projets bruts
                self._table_projects.set_dataframe(projects)
                self._table_tx.set_dataframe(pd.DataFrame([{
                    "Info": "Aucune transaction. Saisissez-en une dans l'onglet ➕ Saisie."
                }]))

        except Exception as e:
            logger.error("Erreur chargement données PE: %s", e, exc_info=True)
            self._table_projects.set_dataframe(pd.DataFrame([{"Erreur": str(e)}]))

    # ── Rafraîchissement du combo projets ─────────────────────────────────

    def _refresh_project_combo(self) -> None:
        try:
            from services import private_equity_repository as pe_repo
            projects = pe_repo.list_pe_projects(self._conn, person_id=self._person_id)
            self._pe_tx_project.blockSignals(True)
            self._pe_tx_project.clear()
            if projects is not None and not projects.empty:
                for _, r in projects.iterrows():
                    self._pe_tx_project.addItem(str(r["name"]), int(r["id"]))
            self._pe_tx_project.blockSignals(False)
        except Exception as e:
            logger.error("Erreur rafraîchissement combo projets PE: %s", e, exc_info=True)

    # ── Sauvegarde : nouveau projet ────────────────────────────────────────

    def _save_project(self) -> None:
        try:
            from services import private_equity_repository as pe_repo
            name = self._pe_proj_name.text().strip()
            if not name:
                self._pe_proj_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._pe_proj_status.setText("❌  Le nom du projet est obligatoire.")
                return

            pe_repo.create_pe_project(
                self._conn,
                person_id=self._person_id,
                name=name,
                platform=self._pe_proj_platform.text().strip() or None,
                project_type=self._pe_proj_type.currentText(),
                note=self._pe_proj_note.text().strip() or None,
            )
            self._pe_proj_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._pe_proj_status.setText(f"✅  Projet « {name} » créé.")
            self._pe_proj_name.clear()
            self._pe_proj_platform.clear()
            self._pe_proj_note.clear()
            self._refresh_project_combo()
        except Exception as e:
            logger.error("Erreur création projet PE: %s", e, exc_info=True)
            self._pe_proj_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._pe_proj_status.setText(f"❌  Erreur : {e}")

    # ── Sauvegarde : nouvelle transaction PE ──────────────────────────────

    def _save_pe_transaction(self) -> None:
        try:
            from services import private_equity_repository as pe_repo
            project_id = self._pe_tx_project.currentData()
            if project_id is None:
                self._pe_tx_status.setStyleSheet(STYLE_STATUS_ERROR)
                self._pe_tx_status.setText("❌  Sélectionnez un projet.")
                return

            tx_type  = self._pe_tx_type.currentText()
            date_str = self._pe_tx_date.date().toString("yyyy-MM-dd")
            amount   = self._pe_tx_amount.value()

            # Quantité et prix unitaire : seulement pour INVEST / VENTE
            quantity   = None
            unit_price = None
            if self._pe_tx_quantity.isVisible():
                q = self._pe_tx_quantity.value()
                quantity = q if q > 0 else None
            if self._pe_tx_unitprice.isVisible():
                p = self._pe_tx_unitprice.value()
                unit_price = p if p > 0 else None

            note = self._pe_tx_note.text().strip() or None

            pe_repo.add_pe_transaction(
                self._conn,
                project_id=int(project_id),
                date=date_str,
                tx_type=tx_type,
                amount=amount,
                quantity=quantity,
                unit_price=unit_price,
                note=note,
            )
            self._pe_tx_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._pe_tx_status.setText(f"✅  Transaction {tx_type} enregistrée ({amount:,.2f} €).")
            # Remettre à zéro les champs numériques
            self._pe_tx_amount.setValue(0.0)
            self._pe_tx_quantity.setValue(0.0)
            self._pe_tx_unitprice.setValue(0.0)
            self._pe_tx_note.clear()
        except Exception as e:
            logger.error("Erreur enregistrement transaction PE: %s", e, exc_info=True)
            self._pe_tx_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._pe_tx_status.setText(f"❌  Erreur : {e}")
