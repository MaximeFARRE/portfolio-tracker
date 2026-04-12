"""
Page Import — orchestrateur.
Les panels dépenses/revenus/Bankin sont dans _import_panels.py.
Le panel Trade Republic est dans _tr_panel.py.
"""
import time
from services import import_lookup_service as lookup
from qt_ui.pages._import_panels import (
    BTN_STYLE as _BTN_STYLE, INPUT_STYLE as _INPUT_STYLE,
    LABEL_STYLE as _LABEL_STYLE, GROUP_STYLE as _GROUP_STYLE,
    make_label as _make_label, build_depenses_panel, build_bankin_panel,
)
from qt_ui.pages._tr_panel import TrImportPanel
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QGroupBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QScrollArea, QDateEdit, QStackedWidget, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from qt_ui.theme import (
    BG_PRIMARY, BG_CARD, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DISABLED,
    COLOR_SUCCESS, COLOR_WARNING,
    STYLE_TITLE_XL, STYLE_STATUS, STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_STATUS_WARNING,
)


class ImportPage(QScrollArea):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._csv_path: str | None = None
        self._people_cache_ttl_sec = 30.0
        self._accounts_cache_ttl_sec = 20.0
        self._history_cache_ttl_sec = 10.0
        self._people_cache_df = None
        self._person_id_by_name: dict[str, int] = {}
        self._accounts_cache_by_person: dict[int, tuple[float, object]] = {}
        self._last_people_refresh_ts = 0.0
        self._last_history_refresh_ts = 0.0

        self.setWidgetResizable(True)
        self.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}")

        container = QWidget()
        container.setStyleSheet(f"background: {BG_PRIMARY};")
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)
        self.setWidget(container)

        # Header
        header = QLabel("📥  Importer / Configurer")
        header.setStyleSheet(STYLE_TITLE_XL)
        main_layout.addWidget(header)

        # Sélecteurs
        sel_row = QHBoxLayout()

        person_grp = QGroupBox("Personne")
        person_grp.setStyleSheet(_GROUP_STYLE)
        pv = QVBoxLayout(person_grp)
        self._person_combo = QComboBox()
        self._person_combo.setStyleSheet(_INPUT_STYLE)
        pv.addWidget(self._person_combo)
        sel_row.addWidget(person_grp)

        type_grp = QGroupBox("Type d'import")
        type_grp.setStyleSheet(_GROUP_STYLE)
        tv = QVBoxLayout(type_grp)
        self._mode_combo = QComboBox()
        self._mode_combo.addItems([
            "Dépenses (mensuel)",
            "Revenus (mensuel)",
            "Bankin (transactions)",
            "Trade Republic (PEA / CTO)",
            "Crédit (config + génération)",
        ])
        self._mode_combo.setStyleSheet(_INPUT_STYLE)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        tv.addWidget(self._mode_combo)
        sel_row.addWidget(type_grp)

        main_layout.addLayout(sel_row)

        # Stack des sous-panneaux
        self._stack = QStackedWidget()
        self._panel_depenses = build_depenses_panel(
            self._conn, self._person_combo.currentText, self._refresh_history, "depenses"
        )
        self._panel_revenus = build_depenses_panel(
            self._conn, self._person_combo.currentText, self._refresh_history, "revenus"
        )
        self._panel_bankin = build_bankin_panel(
            self._conn, self._person_combo.currentText, self._refresh_history
        )
        self._panel_tr = TrImportPanel(
            self._conn, self._person_combo.currentText, self._refresh_history
        )
        self._panel_credit = self._build_credit_panel()

        self._stack.addWidget(self._panel_depenses)
        self._stack.addWidget(self._panel_revenus)
        self._stack.addWidget(self._panel_bankin)
        self._stack.addWidget(self._panel_tr)
        self._stack.addWidget(self._panel_credit)

        main_layout.addWidget(self._stack)

        # ── Historique des imports ───────────────────────────────────────────
        self._history_panel = self._build_history_panel()
        main_layout.addWidget(self._history_panel)

        main_layout.addStretch()

        self._refresh_people()

    # ------------------------------------------------------------------
    # Panel Historique des imports
    # ------------------------------------------------------------------

    _HISTORY_COLS = ["#", "Type", "Personne", "Compte / Fichier", "Date", "Lignes", "Statut", "Action"]
    _TYPE_ICONS = {"TR": "📈", "BANKIN": "🏦", "DEPENSES": "💸", "REVENUS": "💰", "CREDIT": "🏠"}

    def _build_history_panel(self) -> QGroupBox:
        grp = QGroupBox("📋  Historique des imports")
        grp.setStyleSheet(_GROUP_STYLE)
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        toolbar = QHBoxLayout()
        btn_refresh = QPushButton("🔄  Rafraîchir")
        btn_refresh.setStyleSheet(_BTN_STYLE)
        btn_refresh.setFixedWidth(130)
        btn_refresh.clicked.connect(lambda: self._refresh_history(force=True))
        toolbar.addWidget(btn_refresh)
        toolbar.addStretch()
        note = QLabel("🗑️ Annuler supprime les transactions / lignes du batch de la base de données.")
        note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        toolbar.addWidget(note)
        v.addLayout(toolbar)

        self._history_status = QLabel("Prêt.")
        self._history_status.setStyleSheet(STYLE_STATUS)
        v.addWidget(self._history_status)

        tbl = QTableWidget(0, len(self._HISTORY_COLS))
        tbl.setHorizontalHeaderLabels(self._HISTORY_COLS)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setMinimumHeight(160)
        tbl.setMaximumHeight(280)
        tbl.setStyleSheet(
            f"QTableWidget {{ background: {BG_PRIMARY}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SUBTLE}; "
            f"gridline-color: {BORDER_SUBTLE}; font-size: 12px; }}"
            f"QHeaderView::section {{ background: {BG_CARD}; color: {TEXT_SECONDARY}; border: none; padding: 4px; }}"
        )
        v.addWidget(tbl)

        self._history_table = tbl
        return grp

    @staticmethod
    def _is_cache_fresh(last_ts: float, ttl_sec: float) -> bool:
        if last_ts <= 0:
            return False
        return (time.monotonic() - last_ts) <= ttl_sec

    def _refresh_history(self, *, force: bool = False) -> None:
        """Recharge le tableau historique depuis la DB."""
        if not force and self._is_cache_fresh(self._last_history_refresh_ts, self._history_cache_ttl_sec):
            return
        self._history_status.setStyleSheet(STYLE_STATUS)
        self._history_status.setText("⏳ Chargement de l'historique...")
        try:
            from services.import_history import list_batches
            batches = list_batches(self._conn, limit=50)
        except Exception as e:
            self._history_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._history_status.setText(f"❌ Erreur de chargement : {e}")
            return

        tbl = self._history_table
        tbl.setRowCount(0)
        if not batches:
            tbl.insertRow(0)
            tbl.setItem(0, 0, QTableWidgetItem("—"))
            tbl.setItem(0, 1, QTableWidgetItem("📥"))
            tbl.setItem(0, 2, QTableWidgetItem("—"))
            tbl.setItem(0, 3, QTableWidgetItem("—"))
            tbl.setItem(0, 4, QTableWidgetItem("—"))
            tbl.setItem(0, 5, QTableWidgetItem("0"))
            tbl.setItem(0, 6, QTableWidgetItem("⚠️ Aucun import"))
            tbl.setItem(0, 7, QTableWidgetItem("—"))
            self._history_status.setStyleSheet(STYLE_STATUS_WARNING)
            self._history_status.setText("⚠️ Aucun import enregistré.")
            self._last_history_refresh_ts = time.monotonic()
            return

        for b in batches:
            ri = tbl.rowCount()
            tbl.insertRow(ri)

            itype = b["import_type"]
            icon = self._TYPE_ICONS.get(itype, "📥")
            status = b["status"]
            rolled_back = (status == "ROLLED_BACK")

            tbl.setItem(ri, 0, QTableWidgetItem(str(b["id"])))
            tbl.setItem(ri, 1, QTableWidgetItem(f"{icon} {itype}"))
            tbl.setItem(ri, 2, QTableWidgetItem(b["person_name"] or "—"))
            detail = b["account_name"] or b["filename"] or "—"
            tbl.setItem(ri, 3, QTableWidgetItem(detail))
            dt = (b["imported_at"] or "")[:16].replace("T", " ")
            tbl.setItem(ri, 4, QTableWidgetItem(dt))
            nb_lbl = f"{b['nb_rows']} ({b['alive_rows']} en base)"
            tbl.setItem(ri, 5, QTableWidgetItem(nb_lbl))
            status_text = "✅ Actif" if not rolled_back else "🗑️ Annulé"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(COLOR_SUCCESS if not rolled_back else TEXT_MUTED))
            tbl.setItem(ri, 6, status_item)

            if not rolled_back and itype == "CREDIT":
                lbl = QTableWidgetItem("⚠️ Manuel")
                lbl.setForeground(QColor(COLOR_WARNING))
                lbl.setToolTip("Les crédits ne peuvent pas être annulés automatiquement.\nSupprimez le crédit manuellement depuis la page Crédits.")
                tbl.setItem(ri, 7, lbl)
            elif not rolled_back and b["alive_rows"] > 0:
                btn = QPushButton("🗑️ Annuler")
                btn.setStyleSheet(
                    "QPushButton { background: #3b0000; color: #f87171; border: 1px solid #7f1d1d; "
                    "border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
                    "QPushButton:hover { background: #5a0000; }"
                )
                batch_id = b["id"]
                nb = b["alive_rows"]
                btn.clicked.connect(lambda checked, bid=batch_id, n=nb: self._rollback_batch(bid, n))
                tbl.setCellWidget(ri, 7, btn)
            else:
                tbl.setItem(ri, 7, QTableWidgetItem("—"))

            if rolled_back:
                for col in range(tbl.columnCount()):
                    item = tbl.item(ri, col)
                    if item:
                        item.setForeground(QColor(TEXT_DISABLED))
        self._history_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._history_status.setText(f"✅ Historique chargé ({len(batches)} batch(s)).")
        self._last_history_refresh_ts = time.monotonic()

    def _rollback_batch(self, batch_id: int, nb_rows: int) -> None:
        """Demande confirmation puis annule le batch."""
        reply = QMessageBox.question(
            self,
            "Confirmer l'annulation",
            f"Voulez-vous vraiment annuler ce batch ?\n\n"
            f"⚠️  {nb_rows} ligne(s) seront supprimées définitivement de la base.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from services.import_history import rollback_batch
            result = rollback_batch(self._conn, batch_id)
            total = result["total_deleted"]
            QMessageBox.information(
                self,
                "Annulation réussie",
                f"✅ Batch #{batch_id} annulé — {total} ligne(s) supprimée(s).",
            )
            self._refresh_history(force=True)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'annuler le batch :\n{e}")

    # ------------------------------------------------------------------
    # Panel Crédit
    # ------------------------------------------------------------------

    def _build_credit_panel(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}")

        inner = QWidget()
        inner.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        w.setWidget(inner)

        cap = QLabel("Tu renseignes la fiche crédit ici. L'amortissement est généré automatiquement (avec gestion du différé).")
        cap.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(cap)

        # Sélection compte crédit
        acc_grp = QGroupBox("Compte crédit")
        acc_grp.setStyleSheet(_GROUP_STYLE)
        acc_v = QVBoxLayout(acc_grp)
        self._credit_account_combo = QComboBox()
        self._credit_account_combo.setStyleSheet(_INPUT_STYLE)
        acc_v.addWidget(QLabel("Sous-compte CREDIT :"))
        acc_v.addWidget(self._credit_account_combo)

        acc_v.addWidget(QLabel("Compte BANQUE payeur :"))
        self._payer_account_combo = QComboBox()
        self._payer_account_combo.setStyleSheet(_INPUT_STYLE)
        acc_v.addWidget(self._payer_account_combo)
        layout.addWidget(acc_grp)

        # Fiche crédit
        fiche_grp = QGroupBox("Fiche crédit")
        fiche_grp.setStyleSheet(_GROUP_STYLE)
        fiche_layout = QHBoxLayout(fiche_grp)

        # Col 1
        col1 = QVBoxLayout()
        col1.addWidget(_make_label("Nom du crédit"))
        self._c_nom = QLineEdit("Crédit")
        self._c_nom.setStyleSheet(_INPUT_STYLE)
        col1.addWidget(self._c_nom)

        col1.addWidget(_make_label("Banque"))
        self._c_banque = QLineEdit()
        self._c_banque.setStyleSheet(_INPUT_STYLE)
        col1.addWidget(self._c_banque)

        col1.addWidget(_make_label("Type"))
        self._c_type = QComboBox()
        self._c_type.addItems(["immo", "conso", "auto", "etudiant", "autre"])
        self._c_type.setCurrentIndex(1)
        self._c_type.setStyleSheet(_INPUT_STYLE)
        col1.addWidget(self._c_type)
        col1.addStretch()
        fiche_layout.addLayout(col1)

        # Col 2
        col2 = QVBoxLayout()
        col2.addWidget(_make_label("Capital emprunté (€)"))
        self._c_capital = QDoubleSpinBox()
        self._c_capital.setRange(0, 10_000_000)
        self._c_capital.setSingleStep(1000)
        self._c_capital.setDecimals(2)
        self._c_capital.setStyleSheet(_INPUT_STYLE)
        col2.addWidget(self._c_capital)

        col2.addWidget(_make_label("Taux nominal (%)"))
        self._c_taux = QDoubleSpinBox()
        self._c_taux.setRange(0, 100)
        self._c_taux.setSingleStep(0.01)
        self._c_taux.setDecimals(3)
        self._c_taux.setStyleSheet(_INPUT_STYLE)
        col2.addWidget(self._c_taux)

        col2.addWidget(_make_label("TAEG (%)"))
        self._c_taeg = QDoubleSpinBox()
        self._c_taeg.setRange(0, 100)
        self._c_taeg.setSingleStep(0.01)
        self._c_taeg.setDecimals(3)
        self._c_taeg.setStyleSheet(_INPUT_STYLE)
        col2.addWidget(self._c_taeg)
        col2.addStretch()
        fiche_layout.addLayout(col2)

        # Col 3
        col3 = QVBoxLayout()
        col3.addWidget(_make_label("Durée (mois)"))
        self._c_duree = QSpinBox()
        self._c_duree.setRange(1, 600)
        self._c_duree.setValue(1)
        self._c_duree.setStyleSheet(_INPUT_STYLE)
        col3.addWidget(self._c_duree)

        col3.addWidget(_make_label("Mensualité théorique (€)"))
        self._c_mensualite = QDoubleSpinBox()
        self._c_mensualite.setRange(0, 100_000)
        self._c_mensualite.setSingleStep(10)
        self._c_mensualite.setDecimals(2)
        self._c_mensualite.setStyleSheet(_INPUT_STYLE)
        col3.addWidget(self._c_mensualite)

        col3.addWidget(_make_label("Assurance mensuelle (€)"))
        self._c_assurance = QDoubleSpinBox()
        self._c_assurance.setRange(0, 10_000)
        self._c_assurance.setSingleStep(1)
        self._c_assurance.setDecimals(2)
        self._c_assurance.setStyleSheet(_INPUT_STYLE)
        col3.addWidget(self._c_assurance)
        col3.addStretch()
        fiche_layout.addLayout(col3)
        layout.addWidget(fiche_grp)

        # Date + actif
        date_row = QHBoxLayout()
        date_row.addWidget(_make_label("Date de début :"))
        self._c_date_debut = QDateEdit()
        self._c_date_debut.setCalendarPopup(True)
        self._c_date_debut.setDate(QDate.currentDate())
        self._c_date_debut.setStyleSheet(_INPUT_STYLE)
        date_row.addWidget(self._c_date_debut)
        self._c_actif = QCheckBox("Crédit actif")
        self._c_actif.setChecked(True)
        self._c_actif.setStyleSheet("color: #94a3b8;")
        date_row.addWidget(self._c_actif)
        date_row.addStretch()
        layout.addLayout(date_row)

        # Différé
        diff_grp = QGroupBox("Différé")
        diff_grp.setStyleSheet(_GROUP_STYLE)
        diff_layout = QHBoxLayout(diff_grp)

        dcol1 = QVBoxLayout()
        dcol1.addWidget(_make_label("Différé (mois)"))
        self._c_diff_mois = QSpinBox()
        self._c_diff_mois.setRange(0, 240)
        self._c_diff_mois.setStyleSheet(_INPUT_STYLE)
        dcol1.addWidget(self._c_diff_mois)
        dcol1.addWidget(_make_label("Type de différé"))
        self._c_diff_type = QComboBox()
        self._c_diff_type.addItems(["aucun", "partiel", "total"])
        self._c_diff_type.setStyleSheet(_INPUT_STYLE)
        dcol1.addWidget(self._c_diff_type)
        diff_layout.addLayout(dcol1)

        dcol2 = QVBoxLayout()
        self._c_diff_assurance = QCheckBox("Assurance pendant différé")
        self._c_diff_assurance.setChecked(True)
        self._c_diff_assurance.setStyleSheet("color: #94a3b8;")
        dcol2.addWidget(self._c_diff_assurance)
        dcol2.addWidget(_make_label("Intérêts pendant différé"))
        self._c_diff_interets = QComboBox()
        self._c_diff_interets.addItems(["payes", "capitalises"])
        self._c_diff_interets.setStyleSheet(_INPUT_STYLE)
        dcol2.addWidget(self._c_diff_interets)
        diff_layout.addLayout(dcol2)

        dcol3 = QVBoxLayout()
        self._c_use_override = QCheckBox("Forcer la mensualité")
        self._c_use_override.setStyleSheet("color: #94a3b8;")
        dcol3.addWidget(self._c_use_override)
        dcol3.addWidget(_make_label("Mensualité forcée (€)"))
        self._c_mensualite_override = QDoubleSpinBox()
        self._c_mensualite_override.setRange(0, 100_000)
        self._c_mensualite_override.setSingleStep(10)
        self._c_mensualite_override.setDecimals(2)
        self._c_mensualite_override.setStyleSheet(_INPUT_STYLE)
        dcol3.addWidget(self._c_mensualite_override)
        diff_layout.addLayout(dcol3)

        layout.addWidget(diff_grp)

        # Bouton + résultat
        btn_save = QPushButton("💾  Enregistrer + Générer amortissement")
        btn_save.setStyleSheet(_BTN_STYLE)
        layout.addWidget(btn_save)

        self._credit_result = QLabel()
        self._credit_result.setWordWrap(True)
        self._credit_result.setStyleSheet(STYLE_STATUS)
        layout.addWidget(self._credit_result)
        layout.addStretch()

        btn_save.clicked.connect(self._on_save_credit)
        self._person_combo_ref = None

        return w

    # ------------------------------------------------------------------
    # Méthodes de page
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rafraîchit les listes de personnes et comptes."""
        self._refresh_people(force=False)

    def _refresh_people(self, *, force: bool = False) -> None:
        if not force and self._is_cache_fresh(self._last_people_refresh_ts, self._people_cache_ttl_sec):
            self._refresh_history(force=False)
            return

        selected_name = self._person_combo.currentText()
        try:
            from services import repositories as repo
            people = repo.list_people(self._conn)
            self._people_cache_df = people
            self._person_id_by_name = {}
            if people is not None and not people.empty:
                self._person_id_by_name = {
                    str(r["name"]): int(r["id"])
                    for _, r in people.iterrows()
                }
            self._last_people_refresh_ts = time.monotonic()
            self._accounts_cache_by_person.clear()

            self._person_combo.blockSignals(True)
            self._person_combo.clear()
            if people is not None and not people.empty:
                self._person_combo.addItems(people["name"].tolist())
                idx = self._person_combo.findText(selected_name)
                if idx >= 0:
                    self._person_combo.setCurrentIndex(idx)
            self._person_combo.blockSignals(False)
        except Exception:
            self._person_combo.clear()
            self._person_combo.addItems(["Papa", "Maman", "Maxime", "Valentin"])

        # BUG-03 FIX: ne connecter le signal qu'une seule fois
        if not getattr(self, "_person_signal_connected", False):
            self._person_combo.currentIndexChanged.connect(self._on_person_changed)
            self._person_signal_connected = True
        self._on_person_changed()
        self._refresh_history(force=False)

    def _on_person_changed(self, *_args) -> None:
        person = self._person_combo.currentText()
        try:
            person_id = self._person_id_by_name.get(person)
            if person_id is None:
                person_id = lookup.get_person_id_by_name(
                    self._conn,
                    person,
                    people_df=self._people_cache_df,
                )
            if person_id is None:
                return
            now = time.monotonic()
            cached = self._accounts_cache_by_person.get(int(person_id))
            if cached and (now - cached[0]) <= self._accounts_cache_ttl_sec:
                accounts_df = cached[1]
            else:
                from services import repositories as repo
                accounts_df = repo.list_accounts(self._conn, person_id=int(person_id))
                self._accounts_cache_by_person[int(person_id)] = (now, accounts_df)

            tr_accounts = lookup.list_accounts_by_types(
                self._conn,
                int(person_id),
                ["PEA", "CTO"],
                accounts_df=accounts_df,
            )

            # Refresh TR accounts
            if hasattr(self._panel_tr, "_refresh_accounts"):
                from services.tr_import import get_tr_phone
                self._panel_tr._refresh_accounts(person_id, accounts=tr_accounts, phone=get_tr_phone(self._conn, int(person_id)))

            # Comptes crédit
            credit_accounts = lookup.list_accounts_by_types(
                self._conn,
                int(person_id),
                ["CREDIT"],
                accounts_df=accounts_df,
            )
            self._credit_account_combo.clear()
            if credit_accounts:
                for acc in credit_accounts:
                    self._credit_account_combo.addItem(f"{acc['name']} (id={acc['id']})", int(acc["id"]))
            else:
                self._credit_account_combo.addItem("Aucun compte CREDIT disponible", None)
                self._credit_result.setStyleSheet(STYLE_STATUS_WARNING)
                self._credit_result.setText("⚠️ Aucun compte crédit pour cette personne.")

            # Comptes banque
            banque_accounts = lookup.list_accounts_by_types(
                self._conn,
                int(person_id),
                ["BANQUE"],
                accounts_df=accounts_df,
            )
            self._payer_account_combo.clear()
            if banque_accounts:
                for acc in banque_accounts:
                    self._payer_account_combo.addItem(f"{acc['name']} (id={acc['id']})", int(acc["id"]))
            else:
                self._payer_account_combo.addItem("Aucun compte BANQUE disponible", None)
                if self._credit_account_combo.currentData() is not None:
                    self._credit_result.setStyleSheet(STYLE_STATUS_WARNING)
                    self._credit_result.setText("⚠️ Aucun compte banque payeur pour cette personne.")
        except Exception:
            pass

    def _on_mode_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _on_save_credit(self) -> None:
        person = self._person_combo.currentText()
        try:
            person_id = lookup.get_person_id_by_name(self._conn, person)
            if person_id is None:
                self._credit_result.setStyleSheet(STYLE_STATUS_ERROR)
                self._credit_result.setText("❌ Personne introuvable.")
                return

            account_id = self._credit_account_combo.currentData()
            if account_id is None:
                self._credit_result.setStyleSheet(STYLE_STATUS_ERROR)
                self._credit_result.setText("❌ Sélectionnez un compte crédit.")
                return
            payer_account_id = self._payer_account_combo.currentData()
            date_debut = self._c_date_debut.date().toString("yyyy-MM-dd")

            account_name = self._credit_account_combo.currentText()
            from services.import_history import create_batch, close_batch
            batch_id = create_batch(
                self._conn,
                import_type="CREDIT",
                person_id=person_id,
                person_name=person,
                account_id=account_id,
                account_name=account_name,
            )

            from services.credits import CreditParams, build_amortissement, replace_amortissement, upsert_credit
            credit_id = upsert_credit(self._conn, {
                "person_id": person_id,
                "account_id": account_id,
                "nom": self._c_nom.text().strip() or "Crédit",
                "banque": self._c_banque.text().strip() or None,
                "type_credit": self._c_type.currentText(),
                "capital_emprunte": self._c_capital.value(),
                "taux_nominal": self._c_taux.value(),
                "taeg": self._c_taeg.value(),
                "duree_mois": self._c_duree.value(),
                "mensualite_theorique": self._c_mensualite.value(),
                "assurance_mensuelle_theorique": self._c_assurance.value(),
                "date_debut": date_debut,
                "actif": 1 if self._c_actif.isChecked() else 0,
                "payer_account_id": payer_account_id,
            })

            use_override = self._c_use_override.isChecked()
            mensualite_ovr = self._c_mensualite_override.value()
            params = CreditParams(
                capital=self._c_capital.value(),
                taux_annuel=self._c_taux.value(),
                duree_mois=self._c_duree.value(),
                date_debut=date_debut,
                assurance_mensuelle=self._c_assurance.value(),
                differe_mois=self._c_diff_mois.value(),
                differe_type=self._c_diff_type.currentText(),
                assurance_pendant_differe=self._c_diff_assurance.isChecked(),
                interets_pendant_differe=self._c_diff_interets.currentText(),
                mensualite=float(mensualite_ovr) if (use_override and mensualite_ovr > 0) else None
            )
            rows = build_amortissement(params)
            n = replace_amortissement(self._conn, credit_id, rows)
            close_batch(self._conn, batch_id, n)

            self._credit_result.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._credit_result.setText(f"✅ Crédit enregistré — amortissement généré ({n} lignes).")

        except Exception as e:
            self._credit_result.setStyleSheet(STYLE_STATUS_ERROR)
            self._credit_result.setText(f"❌ Erreur : {e}")
