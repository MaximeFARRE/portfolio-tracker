"""
Page Import — remplace pages/3_Import.py
Permet d'importer des CSV de dépenses/revenus, des transactions Bankin,
des transactions Trade Republic (via pytr), et de configurer des crédits.
"""
import os
import tempfile
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QGroupBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QScrollArea, QDateEdit, QStackedWidget, QMessageBox,
    QFileDialog, QTextEdit, QSizePolicy, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QDate, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor


_BTN_STYLE = """
    QPushButton { background: #1e3a5f; color: #60a5fa; border: none;
                  border-radius: 6px; padding: 8px 16px; font-size: 13px; }
    QPushButton:hover { background: #1e4a7f; }
    QPushButton:disabled { background: #1a1f2e; color: #475569; }
"""
_INPUT_STYLE = "background: #1a1f2e; color: #e2e8f0; border: 1px solid #2a3040; border-radius: 4px; padding: 4px; font-size: 13px;"
_LABEL_STYLE = "color: #94a3b8; font-size: 12px; margin-bottom: 2px;"
_GROUP_STYLE = "QGroupBox { color: #94a3b8; border: 1px solid #1e2538; border-radius: 6px; padding: 8px; margin-top: 6px; } QGroupBox::title { subcontrol-position: top left; padding: 2px 8px; }"


def _make_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(_LABEL_STYLE)
    return lbl


class ImportPage(QScrollArea):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._csv_path: str | None = None

        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: #0e1117; }")

        container = QWidget()
        container.setStyleSheet("background: #0e1117;")
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)
        self.setWidget(container)

        # Header
        header = QLabel("📥  Importer / Configurer")
        header.setStyleSheet("color: #e2e8f0; font-size: 22px; font-weight: bold;")
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
        self._panel_depenses = self._build_depenses_panel("depenses")
        self._panel_revenus = self._build_depenses_panel("revenus")
        self._panel_bankin = self._build_bankin_panel()
        self._panel_tr = self._build_tr_panel()
        self._panel_credit = self._build_credit_panel()

        self._stack.addWidget(self._panel_depenses)
        self._stack.addWidget(self._panel_revenus)
        self._stack.addWidget(self._panel_bankin)
        self._stack.addWidget(self._panel_tr)
        self._stack.addWidget(self._panel_credit)

        main_layout.addWidget(self._stack)

        # ── Historique des imports (AM-19) ──────────────────────────────────
        self._history_panel = self._build_history_panel()
        main_layout.addWidget(self._history_panel)

        main_layout.addStretch()

        self._refresh_people()

    def _build_depenses_panel(self, table_type: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: #0e1117;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        grp = QGroupBox("Fichier CSV")
        grp.setStyleSheet(_GROUP_STYLE)
        gv = QVBoxLayout(grp)

        cap = QLabel("Format attendu : Date | Catégories... | Total (Total ignoré)")
        cap.setStyleSheet("color: #64748b; font-size: 11px;")
        gv.addWidget(cap)

        file_row = QHBoxLayout()
        # Store file path per panel
        file_lbl = QLabel("Aucun fichier sélectionné")
        file_lbl.setStyleSheet("color: #64748b; font-size: 12px;")
        btn_file = QPushButton("📂  Choisir un CSV")
        btn_file.setStyleSheet(_BTN_STYLE)
        file_row.addWidget(btn_file)
        file_row.addWidget(file_lbl, 1)
        gv.addLayout(file_row)

        chk_delete = QCheckBox("Remplacer les données existantes (cette personne)")
        chk_delete.setChecked(True)
        chk_delete.setStyleSheet("color: #94a3b8;")
        gv.addWidget(chk_delete)

        btn_import = QPushButton("✅  Importer")
        btn_import.setStyleSheet(_BTN_STYLE)
        gv.addWidget(btn_import)

        result_lbl = QLabel()
        result_lbl.setWordWrap(True)
        result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
        gv.addWidget(result_lbl)

        layout.addWidget(grp)
        layout.addStretch()

        # Store references on the widget
        w._file_path = None
        w._file_lbl = file_lbl
        w._chk_delete = chk_delete
        w._result_lbl = result_lbl
        w._table_type = table_type

        def pick_file():
            path, _ = QFileDialog.getOpenFileName(w, "Choisir un CSV", "", "CSV (*.csv)")
            if path:
                w._file_path = path
                file_lbl.setText(path.split("/")[-1].split("\\")[-1])
                result_lbl.setText("")

        def do_import():
            if not w._file_path:
                result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                result_lbl.setText("Veuillez sélectionner un fichier CSV.")
                return
            person = self._person_combo.currentText()
            try:
                from services.imports import import_wide_csv_to_monthly_table
                from services.import_history import create_batch, close_batch
                import os
                pid = self._conn.execute(
                    "SELECT id FROM people WHERE name = ?", (person,)
                ).fetchone()
                pid = int(pid[0]) if pid else None
                itype = "DEPENSES" if table_type == "depenses" else "REVENUS"
                batch_id = create_batch(
                    self._conn,
                    import_type=itype,
                    person_id=pid,
                    person_name=person,
                    filename=os.path.basename(w._file_path),
                )
                with open(w._file_path, "rb") as f:
                    res = import_wide_csv_to_monthly_table(
                        self._conn, table=table_type, person_name=person,
                        file=f, delete_existing=w._chk_delete.isChecked(),
                        import_batch_id=batch_id,
                    )
                close_batch(self._conn, batch_id, res["nb_lignes"])
                result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
                result_lbl.setText(
                    f"Import OK ✅ — {res['nb_lignes']} lignes dans {res['table']}\n"
                    f"Mois : {res['mois']}\nCatégories : {res['categories']}"
                )
                self._refresh_history()
            except Exception as e:
                result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                result_lbl.setText(f"Erreur : {e}")

        btn_file.clicked.connect(pick_file)
        btn_import.clicked.connect(do_import)

        return w

    def _build_bankin_panel(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: #0e1117;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        grp = QGroupBox("Import Bankin (transactions)")
        grp.setStyleSheet(_GROUP_STYLE)
        gv = QVBoxLayout(grp)

        cap = QLabel("Importe le CSV Bankin dans la table transactions (et optionnellement remplit dépenses/revenus).")
        cap.setStyleSheet("color: #64748b; font-size: 11px;")
        gv.addWidget(cap)

        file_row = QHBoxLayout()
        file_lbl = QLabel("Aucun fichier sélectionné")
        file_lbl.setStyleSheet("color: #64748b; font-size: 12px;")
        btn_file = QPushButton("📂  Choisir un CSV Bankin")
        btn_file.setStyleSheet(_BTN_STYLE)
        file_row.addWidget(btn_file)
        file_row.addWidget(file_lbl, 1)
        gv.addLayout(file_row)

        chk_fill = QCheckBox("Créer aussi les totaux mensuels (dépenses/revenus)")
        chk_fill.setChecked(True)
        chk_fill.setStyleSheet("color: #94a3b8;")
        gv.addWidget(chk_fill)

        chk_purge = QCheckBox("Supprimer les anciennes transactions de cette personne")
        chk_purge.setChecked(False)
        chk_purge.setStyleSheet("color: #94a3b8;")
        gv.addWidget(chk_purge)

        btn_import = QPushButton("✅  Importer Bankin")
        btn_import.setStyleSheet(_BTN_STYLE)
        gv.addWidget(btn_import)

        result_lbl = QLabel()
        result_lbl.setWordWrap(True)
        result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
        gv.addWidget(result_lbl)

        layout.addWidget(grp)
        layout.addStretch()

        w._file_path = None

        def pick_file():
            path, _ = QFileDialog.getOpenFileName(w, "Choisir un CSV Bankin", "", "CSV (*.csv)")
            if path:
                w._file_path = path
                file_lbl.setText(path.split("/")[-1].split("\\")[-1])
                result_lbl.setText("")

        def do_import():
            if not w._file_path:
                result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                result_lbl.setText("Veuillez sélectionner un fichier CSV.")
                return
            person = self._person_combo.currentText()
            try:
                from services.imports import import_bankin_csv
                from services.import_history import create_batch, close_batch
                import os
                pid = self._conn.execute(
                    "SELECT id FROM people WHERE name = ?", (person,)
                ).fetchone()
                pid = int(pid[0]) if pid else None
                batch_id = create_batch(
                    self._conn,
                    import_type="BANKIN",
                    person_id=pid,
                    person_name=person,
                    filename=os.path.basename(w._file_path),
                )
                with open(w._file_path, "rb") as f:
                    res = import_bankin_csv(
                        self._conn, person_name=person, file=f,
                        also_fill_monthly_tables=chk_fill.isChecked(),
                        purge_existing_transactions=chk_purge.isChecked(),
                        import_batch_id=batch_id,
                    )
                close_batch(self._conn, batch_id, res["transactions_inserted"])
                result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
                result_lbl.setText(
                    f"Import Bankin OK ✅ — {res['transactions_inserted']} transactions\n"
                    f"Mois dépenses : {res['months_depenses']}\n"
                    f"Mois revenus : {res['months_revenus']}"
                )
                self._refresh_history()
            except Exception as e:
                result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                result_lbl.setText(f"Erreur : {e}")

        btn_file.clicked.connect(pick_file)
        btn_import.clicked.connect(do_import)

        return w

    # ------------------------------------------------------------------
    # Panel Trade Republic
    # ------------------------------------------------------------------

    def _build_tr_panel(self) -> QWidget:
        """
        Panel Trade Republic — flux 2 étapes :
          Étape 1 : Se connecter  (pytr login -n PHONE -p PIN --store_credentials)
                    → pytr affiche un code ; l'utilisateur le saisit ici si demandé.
          Étape 2 : Exporter     (pytr export_transactions --outputdir DIR)
                    → utilise les credentials sauvegardés, sans PIN.
        """
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet("QScrollArea { border: none; background: #0e1117; }")

        inner = QWidget()
        inner.setStyleSheet("background: #0e1117;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        w.setWidget(inner)

        # ── Étape 1 : Connexion ──────────────────────────────────────────────
        step1_grp = QGroupBox("Étape 1 — Connexion Trade Republic")
        step1_grp.setStyleSheet(_GROUP_STYLE)
        s1v = QVBoxLayout(step1_grp)

        row_phone = QHBoxLayout()
        row_phone.addWidget(_make_label("Téléphone (format +33…)  "))
        tr_phone_edit = QLineEdit()
        tr_phone_edit.setPlaceholderText("+33612345678")
        tr_phone_edit.setStyleSheet(_INPUT_STYLE)
        tr_phone_edit.setMinimumWidth(180)
        row_phone.addWidget(tr_phone_edit)
        btn_save_phone = QPushButton("💾 Sauvegarder")
        btn_save_phone.setStyleSheet(_BTN_STYLE)
        btn_save_phone.setFixedWidth(130)
        row_phone.addWidget(btn_save_phone)
        row_phone.addStretch()
        s1v.addLayout(row_phone)

        row_pin = QHBoxLayout()
        row_pin.addWidget(_make_label("Code PIN TR (4 chiffres)  "))
        tr_pin_edit = QLineEdit()
        tr_pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        tr_pin_edit.setMaxLength(4)
        tr_pin_edit.setFixedWidth(70)
        tr_pin_edit.setStyleSheet(_INPUT_STYLE)
        row_pin.addWidget(tr_pin_edit)
        row_pin.addStretch()
        s1v.addLayout(row_pin)

        note1 = QLabel(
            "ℹ️  Login web : Trade Republic envoie une notification push "
            "sur votre téléphone pour confirmer la connexion.\n"
            "L'ancien mode 'App Login' n'est plus supporté par TR. "
            "Si la connexion échoue ('Expecting value'), cliquez sur :\n👉 'Mettre à jour pytr' pour contourner automatiquement la protection anti-bots."
        )
        note1.setWordWrap(True)
        note1.setStyleSheet("color: #60a5fa; font-size: 11px; margin-top: 4px; margin-bottom: 8px;")
        s1v.addWidget(note1)

        btn_row_login = QHBoxLayout()
        btn_login = QPushButton("🔐  Étape 1 — Se connecter à Trade Republic")
        btn_login.setStyleSheet(_BTN_STYLE)
        btn_row_login.addWidget(btn_login)

        btn_update_pytr = QPushButton("🔄  Mettre à jour pytr")
        btn_update_pytr.setStyleSheet(
            "QPushButton { background: #1a2a1a; color: #4ade80; border: 1px solid #166534; "
            "border-radius: 6px; padding: 8px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #1e3a1e; }"
        )
        btn_update_pytr.setToolTip("pip install --upgrade pytr")
        btn_row_login.addWidget(btn_update_pytr)
        btn_row_login.addStretch()
        s1v.addLayout(btn_row_login)

        # Zone log (temps réel pytr)
        log_edit = QTextEdit()
        log_edit.setReadOnly(True)
        log_edit.setFixedHeight(150)
        log_edit.setStyleSheet(
            "background: #0a0e16; color: #94a3b8; border: 1px solid #1e2538; "
            "border-radius: 4px; font-family: monospace; font-size: 11px;"
        )
        s1v.addWidget(log_edit)

        # Saisie du code interactif (caché par défaut)
        code_frame = QWidget()
        code_frame.setStyleSheet(
            "background: #1a2535; border: 1px solid #2a4a6a; border-radius: 6px; padding: 4px;"
        )
        code_row = QHBoxLayout(code_frame)
        code_row.setContentsMargins(8, 6, 8, 6)
        code_lbl = QLabel("Code reçu :")
        code_lbl.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        code_edit = QLineEdit()
        code_edit.setMaxLength(10)
        code_edit.setFixedWidth(120)
        code_edit.setStyleSheet(_INPUT_STYLE)
        code_edit.setPlaceholderText("ex: AB12 ou 123456")
        btn_send_code = QPushButton("✅ Valider")
        btn_send_code.setStyleSheet(_BTN_STYLE)
        code_row.addWidget(code_lbl)
        code_row.addWidget(code_edit)
        code_row.addWidget(btn_send_code)
        code_row.addStretch()
        s1v.addWidget(code_frame)

        # Caché initialement
        code_frame.hide()

        layout.addWidget(step1_grp)

        # ── Étape 2 : Export ─────────────────────────────────────────────────
        step2_grp = QGroupBox("Étape 2 — Exporter les transactions")
        step2_grp.setStyleSheet(_GROUP_STYLE)
        s2v = QVBoxLayout(step2_grp)

        acc_lbl = _make_label("Compte par défaut (si inconnu ou espèce) :")
        s2v.addWidget(acc_lbl)

        acc_row = QHBoxLayout()
        tr_account_combo = QComboBox()
        tr_account_combo.setStyleSheet(_INPUT_STYLE)
        acc_row.addWidget(tr_account_combo)

        chk_multi_account = QCheckBox("J'ai plusieurs comptes (répartition auto)")
        chk_multi_account.setChecked(True)
        chk_multi_account.setStyleSheet("color: #94a3b8;")
        acc_row.addWidget(chk_multi_account)
        acc_row.addStretch()
        s2v.addLayout(acc_row)

        btn_row2 = QHBoxLayout()
        btn_export = QPushButton("🔄  Étape 2 — Exporter depuis Trade Republic")
        btn_export.setStyleSheet(_BTN_STYLE)
        btn_export.setEnabled(False)   # activé après login réussi
        btn_row2.addWidget(btn_export)

        btn_import_csv = QPushButton("📂  Importer un CSV existant")
        btn_import_csv.setStyleSheet(_BTN_STYLE)
        btn_row2.addWidget(btn_import_csv)
        btn_row2.addStretch()
        s2v.addLayout(btn_row2)

        layout.addWidget(step2_grp)

        # ── Configuration Multi-Comptes (masqué par défaut) ──────────────────
        multi_acc_grp = QGroupBox("Configuration des actifs détectés (Multi-Comptes)")
        multi_acc_grp.setStyleSheet(_GROUP_STYLE)
        multi_v = QVBoxLayout(multi_acc_grp)
        
        multi_acc_scroll = QScrollArea()
        multi_acc_scroll.setWidgetResizable(True)
        multi_acc_scroll.setMaximumHeight(200)
        multi_acc_scroll.setStyleSheet("QScrollArea { border: none; background: #0a0e16; }")
        multi_item_widget = QWidget()
        multi_item_widget.setStyleSheet("background: #0a0e16;")
        multi_item_layout = QVBoxLayout(multi_item_widget)
        multi_item_layout.setSpacing(4)
        multi_item_layout.setContentsMargins(4, 4, 4, 4)
        multi_acc_scroll.setWidget(multi_item_widget)
        multi_v.addWidget(multi_acc_scroll)
        
        btn_apply_mapping = QPushButton("🔄 Générer l'aperçu avec cette configuration")
        btn_apply_mapping.setStyleSheet(_BTN_STYLE)
        multi_v.addWidget(btn_apply_mapping)
        multi_acc_grp.hide()
        layout.addWidget(multi_acc_grp)

        # ── Aperçu + import ──────────────────────────────────────────────────
        prev_grp = QGroupBox("Aperçu des transactions à importer")
        prev_grp.setStyleSheet(_GROUP_STYLE)
        prev_v = QVBoxLayout(prev_grp)

        preview_table = QTableWidget(0, 8)
        preview_table.setHorizontalHeaderLabels(
            ["Date", "Compte", "Type", "Titre", "Ticker", "Qté", "Prix", "Montant (€)"]
        )
        preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        preview_table.setStyleSheet(
            "QTableWidget { background: #0a0e16; color: #e2e8f0; border: 1px solid #1e2538; "
            "gridline-color: #1e2538; font-size: 12px; }"
            "QHeaderView::section { background: #1a1f2e; color: #94a3b8; border: none; padding: 4px; }"
        )
        preview_table.setMinimumHeight(180)
        prev_v.addWidget(preview_table)

        summary_lbl = QLabel()
        summary_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        prev_v.addWidget(summary_lbl)

        btn_confirm = QPushButton("✅  Confirmer et importer en base")
        btn_confirm.setStyleSheet(_BTN_STYLE)
        btn_confirm.setEnabled(False)
        prev_v.addWidget(btn_confirm)

        result_lbl = QLabel()
        result_lbl.setWordWrap(True)
        result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
        prev_v.addWidget(result_lbl)

        layout.addWidget(prev_grp)
        layout.addStretch()

        # ── Références sur le widget ──────────────────────────────────────────
        w._tr_phone_edit = tr_phone_edit
        w._tr_account_combo = tr_account_combo
        w._pending_filepath = None
        w._pytr_proc = None      # PytrProcess en cours (login)
        w._poll_timer = None     # QTimer de polling
        w._ticker_map = {}
        w._combo_by_ticker = {}

        # ── Helpers ──────────────────────────────────────────────────────────

        def _log(msg: str, color: str = "#94a3b8") -> None:
            from services.tr_import import strip_ansi
            clean = strip_ansi(msg).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            log_edit.append(f'<span style="color:{color}">{clean}</span>')

        def _get_person_id() -> int | None:
            person = self._person_combo.currentText()
            row = self._conn.execute(
                "SELECT id FROM people WHERE name = ?", (person,)
            ).fetchone()
            if not row:
                return None
            return int(row[0] if not hasattr(row, "keys") else row["id"])

        def _save_phone() -> None:
            pid = _get_person_id()
            if not pid:
                _log("Personne introuvable.", "#ef4444")
                return
            phone = tr_phone_edit.text().strip()
            if not phone:
                _log("Numéro vide.", "#ef4444")
                return
            try:
                from services.tr_import import save_tr_phone
                save_tr_phone(self._conn, pid, phone)
                _log(f"✔ Téléphone sauvegardé : {phone}", "#22c55e")
            except Exception as e:
                _log(f"Erreur sauvegarde : {e}", "#ef4444")

        # ── Étape 1 : login interactif ────────────────────────────────────────

        def _do_login() -> None:
            phone = tr_phone_edit.text().strip()
            pin = tr_pin_edit.text().strip()
            if not phone:
                _log("Saisissez le numéro de téléphone.", "#ef4444")
                return
            if not pin:
                _log("Saisissez le code PIN.", "#ef4444")
                return

            btn_login.setEnabled(False)
            btn_export.setEnabled(False)
            code_frame.hide()
            log_edit.clear()

            _log(f"Connexion à Trade Republic… (Web Login)", "#60a5fa")

            pytr_args = ["login", "-n", phone, "-p", pin, "--store_credentials"]

            from services.tr_import import PytrProcess
            proc = PytrProcess(pytr_args)
            proc.start()
            w._pytr_proc = proc

            timer = QTimer()
            w._poll_timer = timer

            def _poll() -> None:
                if w._pytr_proc is None:
                    timer.stop()
                    return

                # Lecture de toutes les lignes disponibles
                while True:
                    line = proc.next_line(timeout=0.0)
                    if line is None:
                        # Fin du processus
                        timer.stop()
                        code_frame.hide()
                        rc = proc.returncode if proc.returncode is not None else -1
                        if rc == 0:
                            _log("✅ Connexion réussie ! Vous pouvez maintenant exporter.", "#22c55e")
                            btn_export.setEnabled(True)
                        else:
                            _log(f"⛔  Connexion échouée (code {rc}).", "#ef4444")
                            # Aide contextuelle selon l'erreur
                            recent = log_edit.toPlainText().lower()
                            if "expecting value" in recent:
                                _log("", "#ef4444")
                                _log("💡 Cause probable : l'API Trade Republic n'a renvoyé aucune réponse JSON.", "#f59e0b")
                                _log("👉 Solution : Cliquez sur '🔄 Mettre à jour pytr' pour installer la résolution WAF automatique.", "#f59e0b")
                                _log("👉 Vérifiez également depuis votre navigateur si TR demande un Captcha manuel.", "#f59e0b")
                            elif "invalid" in recent or "wrong" in recent or "incorrect" in recent:
                                _log("💡 PIN ou numéro de téléphone incorrect.", "#f59e0b")
                            elif "too many" in recent or "rate" in recent or "429" in recent:
                                _log("💡 Trop de tentatives. Attendez quelques minutes.", "#f59e0b")
                        btn_login.setEnabled(True)
                        w._pytr_proc = None
                        return
                    if line == "":
                        # Pas de nouvelle ligne pour l'instant
                        break

                    # Affichage dans le log (ANSI déjà strippé dans _log)
                    _log(line)

                    lower = line.lower()

                    # Plus de reset device car l'App Login n'est plus utilisé
                    # ── Détection de demande de code ─────────────────────────
                    # Web login : "Enter the code you received to your mobile app"
                    # App login : "You should have received a SMS with a token. Please type it in:"
                    # App login : "SMS requested. Enter the confirmation code:"
                    if (
                        ("enter" in lower and ("code" in lower or "token" in lower))
                        or "code:" in lower
                        or "4-character" in lower
                        or "sms" in lower and "code" in lower
                        or "confirmation code" in lower
                        or "token" in lower and ("type" in lower or "enter" in lower)
                        or "notification" in lower and "enter" in lower
                    ):
                        code_frame.show()
                        code_edit.setFocus()
                        _log("⬆️  Saisissez le code reçu (app TR ou SMS) puis cliquez ✅ Valider.", "#f59e0b")

            timer.timeout.connect(_poll)
            timer.start(150)   # polling toutes les 150 ms

        def _send_code() -> None:
            code = code_edit.text().strip()
            if not code or w._pytr_proc is None:
                return
            w._pytr_proc.send_input(code)
            _log(f"✔ Code envoyé : {code}", "#f59e0b")
            code_edit.clear()
            code_frame.hide()

        # ── Étape 2 : export ─────────────────────────────────────────────────

        def _do_export() -> None:
            account_id = tr_account_combo.currentData()
            if not account_id:
                _log("Aucun compte sélectionné.", "#ef4444")
                return

            btn_export.setEnabled(False)
            _log("Export des transactions en cours…", "#60a5fa")

            output_dir = os.path.join(tempfile.gettempdir(), "tr_export")

            class _ExportThread(QThread):
                done = pyqtSignal(int, str)

                def __init__(self, out_dir):
                    super().__init__()
                    self._out = out_dir

                def run(self):
                    from services.tr_import import run_pytr_export
                    rc, msg = run_pytr_export(self._out)
                    self.done.emit(rc, msg)

            thread = _ExportThread(output_dir)
            w._export_thread = thread

            def _on_export_done(rc: int, msg: str) -> None:
                btn_export.setEnabled(True)
                if msg:
                    for line in msg.splitlines():
                        _log(line)
                if rc == 0:
                    _log("✅ Export terminé.", "#22c55e")
                    from services.tr_import import find_tr_csv
                    csv_path = find_tr_csv(output_dir)
                    if csv_path:
                        _log(f"CSV : {csv_path}", "#94a3b8")
                        _run_preview(csv_path)
                    else:
                        _log("CSV introuvable.", "#ef4444")
                else:
                    _log(f"Erreur export (code {rc}).", "#ef4444")

            thread.done.connect(_on_export_done)
            thread.start()

        # ── Preview (thread pour ne pas bloquer l'UI pendant la résolution ISIN) ──

        class _PredictionThread(QThread):
            done = pyqtSignal(list)
            error = pyqtSignal(str)

            def __init__(self, filepath, pid):
                super().__init__()
                self._filepath = filepath
                self._pid = pid

            def run(self):
                try:
                    from services.db import get_conn
                    from services.tr_import import extract_tr_tickers_with_predictions
                    with get_conn() as local_conn:
                        results = extract_tr_tickers_with_predictions(local_conn, self._filepath, self._pid)
                    self.done.emit(results)
                except Exception as e:
                    self.error.emit(str(e))

        class _PreviewThread(QThread):
            """Lance import_tr_transactions(dry_run=True) dans un thread séparé.
            La résolution ISIN→ticker fait des appels API qui peuvent prendre
            quelques secondes — on ne bloque pas l'UI pendant ce temps."""
            done = pyqtSignal(object)   # résultat dict ou Exception
            error = pyqtSignal(str)

            def __init__(self, filepath, pid, acc_id, ticker_map):
                super().__init__()
                self._filepath = filepath
                self._pid = pid
                self._acc_id = acc_id
                self._ticker_map = ticker_map

            def run(self):
                try:
                    from services.db import get_conn
                    from services.tr_import import import_tr_transactions
                    with get_conn() as local_conn:
                        result = import_tr_transactions(
                            local_conn, self._filepath, self._pid, self._acc_id, 
                            dry_run=True, ticker_account_map=self._ticker_map
                        )
                    self.done.emit(result)
                except Exception as e:
                    self.error.emit(str(e))

        def _execute_preview(filepath: str) -> None:
            account_id = tr_account_combo.currentData()
            pid = _get_person_id()
            thread = _PreviewThread(filepath, pid, account_id, w._ticker_map)
            w._preview_thread = thread  # garder une référence

            def _on_preview_done(result) -> None:
                btn_export.setEnabled(True)
                btn_import_csv.setEnabled(True)
                btn_apply_mapping.setEnabled(True)
                w._pending_filepath = filepath
                preview_table.setRowCount(0)

                acc_labels = {tr_account_combo.itemData(i): tr_account_combo.itemText(i) 
                              for i in range(tr_account_combo.count())}

                for r in result.get("preview", []):
                    ri = preview_table.rowCount()
                    preview_table.insertRow(ri)
                    eff_acc = r.get("effective_account_id", account_id)
                    acc_text = acc_labels.get(eff_acc, str(eff_acc))
                    
                    vals = [
                        r.get("date", ""),
                        acc_text,
                        r.get("type", ""),
                        r.get("title", ""),
                        r.get("symbol", r.get("isin", "")),
                        str(r.get("shares") or ""),
                        str(r.get("price") or ""),
                        f"{r.get('amount', 0):.2f}",
                    ]
                    for ci, v in enumerate(vals):
                        item = QTableWidgetItem(v)
                        if r.get("duplicate"):
                            item.setForeground(QColor("#64748b"))
                        if ci == 4 and r.get("isin"):
                            item.setToolTip(f"ISIN : {r.get('isin', '')}")
                        preview_table.setItem(ri, ci, item)

                n_ins = result.get("to_insert", 0)
                n_dup = result.get("duplicates", 0)
                n_skip = result.get("skipped", 0)
                n_resolved = result.get("resolved_tickers", 0)
                unresolved = result.get("unresolved_isins", [])

                summary_parts = [
                    f"{n_ins} à importer",
                    f"{n_dup} doublons ignorés",
                    f"{n_skip} lignes invalides",
                    f"{n_resolved} tickers résolus",
                ]
                if unresolved:
                    summary_parts.append(f"{len(unresolved)} ISIN(s) non résolus")
                summary_lbl.setText("  •  ".join(summary_parts))

                if unresolved:
                    _log(
                        f"⚠️  {len(unresolved)} ISIN(s) sans ticker : "
                        + ", ".join(unresolved[:5])
                        + (" …" if len(unresolved) > 5 else ""),
                        "#f59e0b",
                    )

                btn_confirm.setEnabled(n_ins > 0)
                result_lbl.setText("")

            def _on_preview_error(msg: str) -> None:
                btn_export.setEnabled(True)
                btn_import_csv.setEnabled(True)
                btn_apply_mapping.setEnabled(True)
                summary_lbl.setText("")
                _log(f"Erreur lecture CSV : {msg}", "#ef4444")

            thread.done.connect(_on_preview_done)
            thread.error.connect(_on_preview_error)
            thread.start()

        def _apply_mapping_and_preview():
            btn_apply_mapping.setEnabled(False)
            w._ticker_map = {}
            for sym, combo in w._combo_by_ticker.items():
                w._ticker_map[sym] = combo.currentData()
            _execute_preview(w._pending_filepath)
            
        btn_apply_mapping.clicked.connect(_apply_mapping_and_preview)

        def _run_preview(filepath: str) -> None:
            account_id = tr_account_combo.currentData()
            if not account_id:
                _log("Aucun compte sélectionné.", "#ef4444")
                return

            pid = _get_person_id()
            if not pid:
                _log("Personne introuvable.", "#ef4444")
                return

            btn_confirm.setEnabled(False)
            btn_export.setEnabled(False)
            btn_import_csv.setEnabled(False)
            btn_apply_mapping.setEnabled(False)
            summary_lbl.setText("⏳  Analyse en cours…")
            preview_table.setRowCount(0)
            result_lbl.setText("")
            w._pending_filepath = filepath

            if chk_multi_account.isChecked():
                multi_acc_grp.show()
                pred_thread = _PredictionThread(filepath, pid)
                w._prediction_thread = pred_thread
                def _on_pred_done(results):
                    while multi_item_layout.count():
                        c = multi_item_layout.takeAt(0)
                        if c.widget(): c.widget().deleteLater()
                    w._combo_by_ticker.clear()
                    
                    if not results:
                        lbl = QLabel("Aucun ticker trouvé dans l'export.")
                        lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
                        multi_item_layout.addWidget(lbl)
                    else:
                        for rx in results:
                            sym = rx["symbol"]
                            pred_acc = rx["predicted_account_id"]
                            row_w = QWidget()
                            row_w.setStyleSheet("background: transparent;")
                            rl = QHBoxLayout(row_w)
                            rl.setContentsMargins(0, 0, 0, 0)
                            name_lbl = QLabel(f"[{sym}] {rx['title'][:30]}")
                            name_lbl.setStyleSheet("color: #e2e8f0; font-size: 12px;")
                            name_lbl.setMinimumWidth(180)
                            rl.addWidget(name_lbl)
                            
                            cbo = QComboBox()
                            cbo.setStyleSheet(_INPUT_STYLE)
                            for i in range(tr_account_combo.count()):
                                cbo.addItem(tr_account_combo.itemText(i), tr_account_combo.itemData(i))
                            if pred_acc:
                                idx = cbo.findData(pred_acc)
                                if idx >= 0:
                                    cbo.setCurrentIndex(idx)
                            w._combo_by_ticker[sym] = cbo
                            rl.addWidget(cbo)
                            rl.addStretch()
                            multi_item_layout.addWidget(row_w)
                            
                    _apply_mapping_and_preview()
                
                def _on_pred_error(err):
                    _log(f"Erreur prédiction multi-compte : {err}", "#ef4444")
                    _execute_preview(filepath)
                    
                pred_thread.done.connect(_on_pred_done)
                pred_thread.error.connect(_on_pred_error)
                pred_thread.start()
            else:
                multi_acc_grp.hide()
                w._ticker_map = {}
                _execute_preview(filepath)

        def _pick_csv() -> None:
            path, _ = QFileDialog.getOpenFileName(
                inner, "Choisir un CSV Trade Republic", "", "CSV (*.csv)"
            )
            if path:
                _log(f"CSV sélectionné : {path}", "#94a3b8")
                _run_preview(path)

        def _confirm_import() -> None:
            filepath = w._pending_filepath
            account_id = tr_account_combo.currentData()
            account_label = tr_account_combo.currentText()
            pid = _get_person_id()
            person = self._person_combo.currentText()
            if not filepath or not account_id or not pid:
                return
            try:
                from services.tr_import import import_tr_transactions
                from services.import_history import create_batch, close_batch
                import os
                batch_id = create_batch(
                    self._conn,
                    import_type="TR",
                    person_id=pid,
                    person_name=person,
                    account_id=account_id,
                    account_name=account_label,
                    filename=os.path.basename(filepath),
                )
                result = import_tr_transactions(
                    self._conn, filepath, pid, account_id,
                    dry_run=False, ticker_account_map=w._ticker_map,
                    import_batch_id=batch_id,
                )
                n = result["to_insert"]
                close_batch(self._conn, batch_id, n)
                result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
                result_lbl.setText(f"Import OK ✅ — {n} transactions enregistrées.")
                btn_confirm.setEnabled(False)
                _log(f"✅ {n} transactions importées (batch #{batch_id}).", "#22c55e")
                self._refresh_history()
            except Exception as e:
                result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                result_lbl.setText(f"Erreur : {e}")

        # ── Mise à jour pytr ─────────────────────────────────────────────────
        def _do_update_pytr() -> None:
            btn_update_pytr.setEnabled(False)
            _log("📦  pip install --upgrade pytr en cours…", "#60a5fa")

            class _UpgradeThread(QThread):
                done = pyqtSignal(int, str)
                def run(self):
                    import subprocess, sys, shutil
                    # Chercher pip dans le même Python que pytr
                    from services.tr_import import _find_pytr_cmd
                    pytr_cmd = _find_pytr_cmd()
                    py = pytr_cmd[0] if pytr_cmd[0] != "-m" else sys.executable
                    pip = shutil.which("pip") or shutil.which("pip3")
                    cmds = [[py, "-m", "pip", "install", "--upgrade", "pytr"]]
                    if pip:
                        cmds.append([pip, "install", "--upgrade", "pytr"])
                    for cmd in cmds:
                        try:
                            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                            if r.returncode == 0:
                                self.done.emit(0, (r.stdout or r.stderr or "").strip())
                                return
                        except Exception as e:
                            pass
                    self.done.emit(1, "Échec mise à jour. Lancez manuellement : pip install --upgrade pytr")

            t = _UpgradeThread()
            w._upgrade_thread = t

            def _on_upgrade(rc, msg):
                btn_update_pytr.setEnabled(True)
                from services.tr_import import strip_ansi
                for line in strip_ansi(msg).splitlines()[-5:]:  # Dernières 5 lignes
                    if line.strip():
                        _log(line, "#22c55e" if rc == 0 else "#ef4444")
                if rc == 0:
                    _log("✅  pytr mis à jour. Relancez la connexion.", "#22c55e")
                else:
                    _log("❌  Mise à jour échouée. Voir les logs ci-dessus.", "#ef4444")

            t.done.connect(_on_upgrade)
            t.start()

        # ── Connexions signaux ────────────────────────────────────────────────
        btn_save_phone.clicked.connect(_save_phone)
        btn_login.clicked.connect(_do_login)
        btn_send_code.clicked.connect(_send_code)
        code_edit.returnPressed.connect(_send_code)
        btn_export.clicked.connect(_do_export)
        btn_import_csv.clicked.connect(_pick_csv)
        btn_confirm.clicked.connect(_confirm_import)
        btn_update_pytr.clicked.connect(_do_update_pytr)

        # Refresh comptes quand personne change
        w._refresh_accounts = lambda person_id: self._refresh_tr_accounts(
            tr_account_combo, tr_phone_edit, person_id
        )

        return w

    def _refresh_tr_accounts(
        self, combo: QComboBox, phone_edit: QLineEdit, person_id: int
    ) -> None:
        """Recharge les comptes PEA/CTO pour la personne sélectionnée."""
        combo.clear()
        try:
            df = pd.read_sql_query(
                """SELECT id, name, account_type FROM accounts
                   WHERE person_id = ? AND account_type IN ('PEA', 'CTO')
                   ORDER BY account_type, name""",
                self._conn,
                params=[person_id],
            )
            for _, r in df.iterrows():
                combo.addItem(f"{r['name']} ({r['account_type']})", int(r["id"]))

            # Charger le téléphone sauvegardé
            from services.tr_import import get_tr_phone
            phone = get_tr_phone(self._conn, person_id)
            if phone:
                phone_edit.setText(phone)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Panel Historique des imports (AM-19)
    # ------------------------------------------------------------------

    _HISTORY_COLS = ["#", "Type", "Personne", "Compte / Fichier", "Date", "Lignes", "Statut", "Action"]
    _TYPE_ICONS = {"TR": "📈", "BANKIN": "🏦", "DEPENSES": "💸", "REVENUS": "💰"}

    def _build_history_panel(self) -> QGroupBox:
        grp = QGroupBox("📋  Historique des imports")
        grp.setStyleSheet(_GROUP_STYLE)
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        # Barre d'outils
        toolbar = QHBoxLayout()
        btn_refresh = QPushButton("🔄  Rafraîchir")
        btn_refresh.setStyleSheet(_BTN_STYLE)
        btn_refresh.setFixedWidth(130)
        btn_refresh.clicked.connect(self._refresh_history)
        toolbar.addWidget(btn_refresh)
        toolbar.addStretch()
        note = QLabel("🗑️ Annuler supprime les transactions / lignes du batch de la base de données.")
        note.setStyleSheet("color: #64748b; font-size: 11px;")
        toolbar.addWidget(note)
        v.addLayout(toolbar)

        # Tableau
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
            "QTableWidget { background: #0a0e16; color: #e2e8f0; border: 1px solid #1e2538; "
            "gridline-color: #1e2538; font-size: 12px; }"
            "QHeaderView::section { background: #1a1f2e; color: #94a3b8; border: none; padding: 4px; }"
        )
        v.addWidget(tbl)

        self._history_table = tbl
        return grp

    def _refresh_history(self) -> None:
        """Recharge le tableau historique depuis la DB."""
        try:
            from services.import_history import list_batches
            batches = list_batches(self._conn, limit=50)
        except Exception:
            return

        tbl = self._history_table
        tbl.setRowCount(0)

        for b in batches:
            ri = tbl.rowCount()
            tbl.insertRow(ri)

            itype = b["import_type"]
            icon = self._TYPE_ICONS.get(itype, "📥")
            status = b["status"]
            rolled_back = (status == "ROLLED_BACK")

            # Colonne 0 — id
            tbl.setItem(ri, 0, QTableWidgetItem(str(b["id"])))
            # Colonne 1 — type
            tbl.setItem(ri, 1, QTableWidgetItem(f"{icon} {itype}"))
            # Colonne 2 — personne
            tbl.setItem(ri, 2, QTableWidgetItem(b["person_name"] or "—"))
            # Colonne 3 — compte / fichier
            detail = b["account_name"] or b["filename"] or "—"
            tbl.setItem(ri, 3, QTableWidgetItem(detail))
            # Colonne 4 — date
            dt = (b["imported_at"] or "")[:16].replace("T", " ")
            tbl.setItem(ri, 4, QTableWidgetItem(dt))
            # Colonne 5 — nb lignes
            nb_lbl = f"{b['nb_rows']} ({b['alive_rows']} en base)"
            tbl.setItem(ri, 5, QTableWidgetItem(nb_lbl))
            # Colonne 6 — statut
            status_text = "✅ Actif" if not rolled_back else "🗑️ Annulé"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor("#22c55e" if not rolled_back else "#64748b"))
            tbl.setItem(ri, 6, status_item)

            # Colonne 7 — bouton Annuler (seulement si actif et lignes présentes)
            if not rolled_back and b["alive_rows"] > 0:
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

            # Griser la ligne si annulée
            if rolled_back:
                for col in range(tbl.columnCount()):
                    item = tbl.item(ri, col)
                    if item:
                        item.setForeground(QColor("#475569"))

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
            self._refresh_history()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'annuler le batch :\n{e}")

    def _build_credit_panel(self) -> QWidget:
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet("QScrollArea { border: none; background: #0e1117; }")

        inner = QWidget()
        inner.setStyleSheet("background: #0e1117;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        w.setWidget(inner)

        cap = QLabel("Tu renseignes la fiche crédit ici. L'amortissement est généré automatiquement (avec gestion du différé).")
        cap.setStyleSheet("color: #64748b; font-size: 11px;")
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
        self._credit_result.setStyleSheet("color: #22c55e; font-size: 12px;")
        layout.addWidget(self._credit_result)
        layout.addStretch()

        btn_save.clicked.connect(self._on_save_credit)
        self._person_combo_ref = None  # will be set in refresh

        return w

    def refresh(self) -> None:
        """Rafraîchit les listes de personnes et comptes."""
        self._refresh_people()

    def _refresh_people(self) -> None:
        try:
            from services import repositories as repo
            people = repo.list_people(self._conn)
            self._person_combo.blockSignals(True)
            self._person_combo.clear()
            if people is not None and not people.empty:
                self._person_combo.addItems(people["name"].tolist())
            self._person_combo.blockSignals(False)
        except Exception:
            self._person_combo.addItems(["Papa", "Maman", "Maxime", "Valentin"])

        # BUG-03 FIX: ne connecter le signal qu'une seule fois
        if not getattr(self, "_person_signal_connected", False):
            self._person_combo.currentIndexChanged.connect(self._on_person_changed)
            self._person_signal_connected = True
        self._on_person_changed()
        self._refresh_history()

    def _on_person_changed(self) -> None:
        person = self._person_combo.currentText()
        try:
            row = self._conn.execute("SELECT id FROM people WHERE name = ?", (person,)).fetchone()
            if not row:
                return
            person_id = int(row[0] if not hasattr(row, '__getitem__') else row["id"])

            # Refresh TR accounts
            if hasattr(self._panel_tr, "_refresh_accounts"):
                self._panel_tr._refresh_accounts(person_id)

            # Comptes crédit
            df_credit = pd.read_sql_query(
                "SELECT id, name FROM accounts WHERE person_id = ? AND account_type = 'CREDIT' ORDER BY name",
                self._conn, params=[person_id]
            )
            self._credit_account_combo.clear()
            if not df_credit.empty:
                for _, r in df_credit.iterrows():
                    self._credit_account_combo.addItem(f"{r['name']} (id={r['id']})", int(r["id"]))

            # Comptes banque
            df_banque = pd.read_sql_query(
                "SELECT id, name FROM accounts WHERE person_id = ? AND account_type = 'BANQUE' ORDER BY name",
                self._conn, params=[person_id]
            )
            self._payer_account_combo.clear()
            if not df_banque.empty:
                for _, r in df_banque.iterrows():
                    self._payer_account_combo.addItem(f"{r['name']} (id={r['id']})", int(r["id"]))
        except Exception:
            pass

    def _on_mode_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _on_save_credit(self) -> None:
        person = self._person_combo.currentText()
        try:
            row = self._conn.execute("SELECT id FROM people WHERE name = ?", (person,)).fetchone()
            if not row:
                self._credit_result.setStyleSheet("color: #ef4444; font-size: 12px;")
                self._credit_result.setText("Personne introuvable.")
                return
            person_id = int(row[0] if not hasattr(row, '__getitem__') else row["id"])

            account_id = self._credit_account_combo.currentData()
            payer_account_id = self._payer_account_combo.currentData()
            date_debut = self._c_date_debut.date().toString("yyyy-MM-dd")

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

            self._credit_result.setStyleSheet("color: #22c55e; font-size: 12px;")
            self._credit_result.setText(f"Crédit enregistré ✅ | Amortissement généré ✅ ({n} lignes)")

        except Exception as e:
            self._credit_result.setStyleSheet("color: #ef4444; font-size: 12px;")
            self._credit_result.setText(f"Erreur : {e}")
