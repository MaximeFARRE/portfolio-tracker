"""
Panel Trade Republic — connexion pytr, export, aperçu, import.
Extrait de import_page.py pour réduire la taille du fichier principal.
"""
import os
import tempfile
from services import import_lookup_service as lookup
from qt_ui.pages._import_panels import BTN_STYLE, INPUT_STYLE, GROUP_STYLE, make_label
from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QGroupBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QTextEdit, QHeaderView, QAbstractItemView, QFileDialog, QSizePolicy,
)
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor


# ── QThread helpers (définis au niveau module) ───────────────────────────────

class _ExportThread(QThread):
    done = pyqtSignal(int, str)

    def __init__(self, out_dir, waf_token: str = ""):
        super().__init__()
        self._out = out_dir
        self._waf_token = waf_token

    def run(self):
        from services.tr_import import run_pytr_export
        rc, msg = run_pytr_export(self._out, waf_token=self._waf_token)
        self.done.emit(rc, msg)


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
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, filepath, pid, acc_id, ticker_map, canonical_symbol_map):
        super().__init__()
        self._filepath = filepath
        self._pid = pid
        self._acc_id = acc_id
        self._ticker_map = ticker_map
        self._canonical_symbol_map = canonical_symbol_map

    def run(self):
        try:
            from services.db import get_conn
            from services.tr_import import import_tr_transactions
            with get_conn() as local_conn:
                result = import_tr_transactions(
                    local_conn, self._filepath, self._pid, self._acc_id,
                    dry_run=True,
                    ticker_account_map=self._ticker_map,
                    canonical_symbol_map=self._canonical_symbol_map,
                )
            self.done.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _TickerPreviewThread(QThread):
    done = pyqtSignal(str, object)

    def __init__(self, symbol: str):
        super().__init__()
        self._symbol = (symbol or "").strip().upper()

    def run(self):
        try:
            from services.ticker_preview_service import preview_ticker_live
            self.done.emit(self._symbol, preview_ticker_live(self._symbol))
        except Exception as e:
            self.done.emit(
                self._symbol,
                {
                    "found": False,
                    "name": self._symbol or None,
                    "price": None,
                    "currency": None,
                    "status": "error",
                    "warning": str(e),
                },
            )


class _UpgradeThread(QThread):
    done = pyqtSignal(int, str)

    def run(self):
        import subprocess, sys, shutil
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
            except Exception:
                pass
        self.done.emit(1, "Échec mise à jour. Lancez manuellement : pip install --upgrade pytr")


# ── Panel principal ──────────────────────────────────────────────────────────

class TrImportPanel(QScrollArea):
    """
    Panel Trade Republic complet : connexion pytr (Étape 1) + export + aperçu + import.

    Args:
        conn: connexion DB partagée
        get_person_name: callable() → str — nom de la personne sélectionnée dans la page parente
        refresh_history: callable() — rafraîchit le tableau historique dans la page parente
    """

    def __init__(self, conn, get_person_name, refresh_history, parent=None):
        super().__init__(parent)
        self._conn = conn
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: #0e1117; }")

        inner = QWidget()
        inner.setStyleSheet("background: #0e1117;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.setWidget(inner)

        # ── Étape 1 : Connexion ──────────────────────────────────────────────
        step1_grp = QGroupBox("Étape 1 — Connexion Trade Republic")
        step1_grp.setStyleSheet(GROUP_STYLE)
        s1v = QVBoxLayout(step1_grp)

        row_phone = QHBoxLayout()
        row_phone.addWidget(make_label("Téléphone (format +33…)  "))
        tr_phone_edit = QLineEdit()
        tr_phone_edit.setPlaceholderText("+33612345678")
        tr_phone_edit.setStyleSheet(INPUT_STYLE)
        tr_phone_edit.setMinimumWidth(180)
        row_phone.addWidget(tr_phone_edit)
        btn_save_phone = QPushButton("💾 Sauvegarder")
        btn_save_phone.setStyleSheet(BTN_STYLE)
        btn_save_phone.setFixedWidth(130)
        row_phone.addWidget(btn_save_phone)
        row_phone.addStretch()
        s1v.addLayout(row_phone)

        row_pin = QHBoxLayout()
        row_pin.addWidget(make_label("Code PIN TR (4 chiffres)  "))
        tr_pin_edit = QLineEdit()
        tr_pin_edit.setEchoMode(QLineEdit.EchoMode.Password)
        tr_pin_edit.setMaxLength(4)
        tr_pin_edit.setFixedWidth(70)
        tr_pin_edit.setStyleSheet(INPUT_STYLE)
        row_pin.addWidget(tr_pin_edit)
        row_pin.addStretch()
        s1v.addLayout(row_pin)

        # WAF token manuel (optionnel, nécessaire depuis avril 2026)
        row_waf = QHBoxLayout()
        row_waf.addWidget(make_label("WAF Token (optionnel)  "))
        tr_waf_edit = QLineEdit()
        tr_waf_edit.setPlaceholderText("Coller le cookie aws-waf-token depuis le navigateur")
        tr_waf_edit.setStyleSheet(INPUT_STYLE)
        tr_waf_edit.setMinimumWidth(300)
        row_waf.addWidget(tr_waf_edit, 1)
        row_waf.addStretch()
        s1v.addLayout(row_waf)

        note1 = QLabel(
            "ℹ️  Si 'Expecting value' apparaît : ouvrez app.traderepublic.com → F12 → Application → Cookies\n"
            "→ copiez la valeur de 'aws-waf-token' et collez-la ci-dessus, puis relancez."
        )
        note1.setWordWrap(True)
        note1.setStyleSheet("color: #60a5fa; font-size: 11px; margin-top: 4px; margin-bottom: 8px;")
        s1v.addWidget(note1)

        btn_row_login = QHBoxLayout()
        btn_login = QPushButton("🔐  Étape 1 — Se connecter à Trade Republic")
        btn_login.setStyleSheet(BTN_STYLE)
        btn_row_login.addWidget(btn_login)

        btn_stop_login = QPushButton("⏹  Arrêter")
        btn_stop_login.setStyleSheet(
            "QPushButton { background: #2a1a1a; color: #f87171; border: 1px solid #7f1d1d; "
            "border-radius: 6px; padding: 8px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #3a1a1a; }"
            "QPushButton:disabled { color: #4a3030; border-color: #3a2020; }"
        )
        btn_stop_login.setEnabled(False)
        btn_row_login.addWidget(btn_stop_login)

        btn_update_pytr = QPushButton("🔄  Mettre à jour pytr")
        btn_update_pytr.setStyleSheet(
            "QPushButton { background: #1a2a1a; color: #4ade80; border: 1px solid #166534; "
            "border-radius: 6px; padding: 8px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #1e3a1e; }"
        )
        btn_update_pytr.setToolTip("pip install --upgrade pytr")
        btn_row_login.addWidget(btn_update_pytr)

        btn_reset_creds = QPushButton("🗑️  Reset credentials")
        btn_reset_creds.setStyleSheet(
            "QPushButton { background: #2a1a1a; color: #f87171; border: 1px solid #7f1d1d; "
            "border-radius: 6px; padding: 8px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #3a1a1a; }"
        )
        btn_reset_creds.setToolTip(
            "Supprime ~/.pytr/credentials pour forcer un nouveau login complet.\n"
            "Utile si la connexion échoue avec 'Expecting value' (credentials périmés)."
        )
        btn_row_login.addWidget(btn_reset_creds)
        btn_row_login.addStretch()
        s1v.addLayout(btn_row_login)

        log_edit = QTextEdit()
        log_edit.setReadOnly(True)
        log_edit.setFixedHeight(150)
        log_edit.setStyleSheet(
            "background: #0a0e16; color: #94a3b8; border: 1px solid #1e2538; "
            "border-radius: 4px; font-family: monospace; font-size: 11px;"
        )
        s1v.addWidget(log_edit)

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
        code_edit.setStyleSheet(INPUT_STYLE)
        code_edit.setPlaceholderText("ex: AB12 ou 123456")
        btn_send_code = QPushButton("✅ Valider")
        btn_send_code.setStyleSheet(BTN_STYLE)
        code_row.addWidget(code_lbl)
        code_row.addWidget(code_edit)
        code_row.addWidget(btn_send_code)
        code_row.addStretch()
        s1v.addWidget(code_frame)
        code_frame.hide()

        layout.addWidget(step1_grp)

        # ── Étape 2 : Export ─────────────────────────────────────────────────
        step2_grp = QGroupBox("Étape 2 — Exporter les transactions")
        step2_grp.setStyleSheet(GROUP_STYLE)
        step2_grp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        s2v = QVBoxLayout(step2_grp)

        acc_lbl = make_label("Compte par défaut (si inconnu ou espèce) :")
        s2v.addWidget(acc_lbl)

        acc_row = QHBoxLayout()
        tr_account_combo = QComboBox()
        tr_account_combo.setStyleSheet(INPUT_STYLE)
        acc_row.addWidget(tr_account_combo)

        chk_multi_account = QCheckBox("J'ai plusieurs comptes (répartition auto)")
        chk_multi_account.setChecked(True)
        chk_multi_account.setStyleSheet("color: #94a3b8;")
        acc_row.addWidget(chk_multi_account)
        acc_row.addStretch()
        s2v.addLayout(acc_row)

        btn_row2 = QHBoxLayout()
        btn_export = QPushButton("🔄  Étape 2 — Exporter depuis Trade Republic")
        btn_export.setStyleSheet(BTN_STYLE)
        btn_export.setEnabled(False)
        btn_row2.addWidget(btn_export)

        btn_import_csv = QPushButton("📂  Importer un CSV existant")
        btn_import_csv.setStyleSheet(BTN_STYLE)
        btn_row2.addWidget(btn_import_csv)
        btn_row2.addStretch()
        s2v.addLayout(btn_row2)

        layout.addWidget(step2_grp)

        # ── Configuration Multi-Comptes ──────────────────────────────────────
        multi_acc_grp = QGroupBox("Configuration des actifs détectés (Multi-Comptes)")
        multi_acc_grp.setStyleSheet(GROUP_STYLE)
        multi_acc_grp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        multi_v = QVBoxLayout(multi_acc_grp)

        multi_acc_scroll = QScrollArea()
        multi_acc_scroll.setWidgetResizable(True)
        multi_acc_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        multi_acc_scroll.setMinimumHeight(420)
        multi_acc_scroll.setStyleSheet("QScrollArea { border: none; background: #0a0e16; }")
        multi_item_widget = QWidget()
        multi_item_widget.setStyleSheet("background: #0a0e16;")
        multi_item_layout = QVBoxLayout(multi_item_widget)
        multi_item_layout.setSpacing(4)
        multi_item_layout.setContentsMargins(4, 4, 4, 4)
        multi_acc_scroll.setWidget(multi_item_widget)
        multi_v.addWidget(multi_acc_scroll)

        btn_apply_mapping = QPushButton("🔄 Générer l'aperçu avec cette configuration")
        btn_apply_mapping.setStyleSheet(BTN_STYLE)
        multi_v.addWidget(btn_apply_mapping)
        multi_acc_grp.hide()
        layout.addWidget(multi_acc_grp, 1)

        # ── Aperçu + import ──────────────────────────────────────────────────
        prev_grp = QGroupBox("Aperçu des transactions à importer")
        prev_grp.setStyleSheet(GROUP_STYLE)
        prev_v = QVBoxLayout(prev_grp)

        preview_table = QTableWidget(0, 13)
        preview_table.setHorizontalHeaderLabels(
            [
                "Date",
                "Compte",
                "Type",
                "Titre",
                "Ticker brut",
                "Ticker canonique",
                "Qté",
                "Prix tx",
                "Montant (€)",
                "Nom",
                "Prix live",
                "Devise",
                "Statut",
            ]
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
        btn_confirm.setStyleSheet(BTN_STYLE)
        btn_confirm.setEnabled(False)
        prev_v.addWidget(btn_confirm)

        result_lbl = QLabel()
        result_lbl.setWordWrap(True)
        result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
        prev_v.addWidget(result_lbl)

        layout.addWidget(prev_grp)
        layout.addStretch()

        # ── Références sur le widget ─────────────────────────────────────────
        self._tr_phone_edit = tr_phone_edit
        self._tr_account_combo = tr_account_combo
        self._pending_filepath = None
        self._pytr_proc = None
        self._poll_timer = None
        self._ticker_map = {}
        self._canonical_symbol_map = {}
        self._combo_by_ticker = {}
        self._symbol_edit_by_ticker = {}
        self._preview_label_by_ticker = {}
        self._preview_seq = 0
        self._ticker_preview_cache = {}
        self._active_preview_threads: list = []

        # ── Helpers ──────────────────────────────────────────────────────────

        def _log(msg: str, color: str = "#94a3b8") -> None:
            from services.tr_import import strip_ansi
            clean = strip_ansi(msg).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            pin = tr_pin_edit.text().strip()
            if pin and len(pin) >= 4:
                clean = clean.replace(pin, "****")
            log_edit.append(f'<span style="color:{color}">{clean}</span>')

        def _get_person_id() -> int | None:
            person = get_person_name()
            return lookup.get_person_id_by_name(self._conn, person)

        def _format_ticker_preview(preview: dict) -> str:
            if not preview:
                return "Nom: — | Prix: — | Devise: — | Statut: —"
            name = preview.get("name") or "—"
            price = preview.get("price")
            price_txt = f"{float(price):.4f}" if price is not None else "—"
            ccy = preview.get("currency") or "—"
            status = str(preview.get("status") or "unknown").upper()
            return f"Nom: {name} | Prix: {price_txt} | Devise: {ccy} | Statut: {status}"

        def _preview_label_color(preview: dict) -> str:
            status = str((preview or {}).get("status") or "").lower()
            if status == "ok":
                return "#22c55e"
            if status in ("partial",):
                return "#f59e0b"
            if status in ("empty",):
                return "#94a3b8"
            return "#ef4444"

        def _cleanup_finished_threads() -> None:
            """Supprime les threads terminés de la liste de références."""
            self._active_preview_threads = [
                t for t in self._active_preview_threads if t.isRunning()
            ]

        def _request_ticker_preview(symbol: str, label: QLabel, seq: int) -> None:
            symbol_u = (symbol or "").strip().upper()
            if not symbol_u:
                label.setStyleSheet("color: #94a3b8; font-size: 11px;")
                label.setText("Nom: — | Prix: — | Devise: — | Statut: EMPTY")
                return

            _cleanup_finished_threads()
            thread = _TickerPreviewThread(symbol_u)
            self._active_preview_threads.append(thread)

            def _done(returned_symbol: str, payload: dict):
                if getattr(label, "_preview_req_seq", None) != seq:
                    return
                if returned_symbol != (symbol or "").strip().upper():
                    return
                self._ticker_preview_cache[returned_symbol] = payload
                label.setStyleSheet(f"color: {_preview_label_color(payload)}; font-size: 11px;")
                label.setText(_format_ticker_preview(payload))

            thread.done.connect(_done)
            thread.start()

        def _bind_live_preview(symbol_edit: QLineEdit, preview_label: QLabel) -> None:
            timer = QTimer(self)
            timer.setSingleShot(True)

            def _trigger_preview() -> None:
                self._preview_seq += 1
                seq = self._preview_seq
                setattr(preview_label, "_preview_req_seq", seq)
                preview_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
                preview_label.setText("Chargement preview…")
                _request_ticker_preview(symbol_edit.text(), preview_label, seq)

            timer.timeout.connect(_trigger_preview)

            def _on_text_changed(_text: str) -> None:
                timer.start(350)

            symbol_edit.textChanged.connect(_on_text_changed)
            timer.start(10)

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

        def _finish_login(success: bool) -> None:
            """Remet l'UI dans l'état repos après une connexion (réussie ou non)."""
            btn_login.setEnabled(True)
            btn_stop_login.setEnabled(False)
            code_frame.hide()
            self._pytr_proc = None
            if self._poll_timer:
                self._poll_timer.stop()
                self._poll_timer = None

        def _stop_login() -> None:
            if self._pytr_proc and self._pytr_proc.is_running():
                self._pytr_proc.terminate()
                _log("⏹ Connexion interrompue par l'utilisateur.", "#f59e0b")
            _finish_login(False)

        def _do_login(*, is_retry: bool = False) -> None:
            phone = tr_phone_edit.text().strip()
            pin = tr_pin_edit.text().strip()
            if not phone:
                _log("Saisissez le numéro de téléphone.", "#ef4444")
                return
            if not pin:
                _log("Saisissez le code PIN.", "#ef4444")
                return

            btn_login.setEnabled(False)
            btn_stop_login.setEnabled(True)
            btn_export.setEnabled(False)
            code_frame.hide()

            if is_retry:
                _log("─" * 40, "#334155")
                _log("🔄 Nouvelle tentative…", "#60a5fa")
            else:
                log_edit.clear()
                _log("Connexion à Trade Republic… (Web Login)", "#60a5fa")

            pytr_args = ["login", "-n", phone, "-p", pin, "--store_credentials"]
            waf_token = tr_waf_edit.text().strip()

            from services.tr_import import PytrProcess
            proc = PytrProcess(pytr_args, waf_token=waf_token)
            if waf_token:
                _log(f"WAF token manuel fourni ({len(waf_token)} car.)", "#22c55e")
            proc.start()
            self._pytr_proc = proc

            timer = QTimer()
            self._poll_timer = timer

            def _poll() -> None:
                if self._pytr_proc is None:
                    timer.stop()
                    return

                while True:
                    line = proc.next_line(timeout=0.0)
                    if line is None:
                        timer.stop()
                        rc = proc.returncode if proc.returncode is not None else -1
                        if rc == 0:
                            _log("✅ Connexion réussie ! Vous pouvez maintenant exporter.", "#22c55e")
                            btn_export.setEnabled(True)
                        else:
                            _log(f"⛔  Connexion échouée (code {rc}).", "#ef4444")
                            recent = log_edit.toPlainText().lower()
                            if "expecting value" in recent:
                                from services.tr_import import clear_pytr_credentials, pytr_has_credentials
                                if not is_retry and pytr_has_credentials():
                                    _log("🔄 Credentials périmés — suppression et nouvelle tentative…", "#f59e0b")
                                    clear_pytr_credentials()
                                    _finish_login(False)
                                    _do_login(is_retry=True)
                                    return
                                # Deuxième échec : WAF automatique refusé (bug pytr #330)
                                from services.tr_import import clear_pytr_credentials
                                clear_pytr_credentials()
                                _log("", "#ef4444")
                                _log("💡 Bug connu pytr 0.4.7 : le token WAF automatique n'est plus accepté par TR.", "#f59e0b")
                                _log("👉 Solution : ouvrez app.traderepublic.com dans votre navigateur", "#f59e0b")
                                _log("   → F12 → Application → Cookies → copiez 'aws-waf-token'", "#f59e0b")
                                _log("   → collez-le dans le champ 'WAF Token' ci-dessus → relancez.", "#f59e0b")
                            elif "invalid" in recent or "wrong" in recent or "incorrect" in recent:
                                _log("💡 PIN ou numéro de téléphone incorrect.", "#f59e0b")
                            elif "too many" in recent or "rate" in recent or "429" in recent:
                                _log("💡 Trop de tentatives. Attendez quelques minutes.", "#f59e0b")
                        _finish_login(rc == 0)
                        return
                    if line == "":
                        break

                    # Colorier les lignes d'erreur pour faciliter le diagnostic
                    lower = line.lower()
                    if any(k in lower for k in ("error", "traceback", "exception", "keyerror", "attributeerror")):
                        _log(line, "#ef4444")
                    elif any(k in lower for k in ("warning", "warn")):
                        _log(line, "#f59e0b")
                    else:
                        _log(line)

                    # Réinitialisation du device : réponse automatique "y"
                    if "reset device" in lower:
                        proc.send_input("y")
                        _log("✔ Device reset confirmé automatiquement.", "#f59e0b")

                    # Demande de code (push notification ou SMS)
                    elif (
                        ("enter" in lower and ("code" in lower or "token" in lower))
                        or "code:" in lower
                        or "4-character" in lower
                        or ("sms" in lower and "code" in lower)
                        or "confirmation code" in lower
                        or ("token" in lower and ("type" in lower or "enter" in lower))
                        or ("notification" in lower and "enter" in lower)
                    ):
                        code_frame.show()
                        code_edit.setFocus()
                        _log("⬆️  Saisissez le code reçu (app TR ou SMS) puis cliquez ✅ Valider.", "#f59e0b")

            timer.timeout.connect(_poll)
            timer.start(150)

        def _send_code() -> None:
            code = code_edit.text().strip()
            if not code or self._pytr_proc is None:
                return
            self._pytr_proc.send_input(code)
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
            waf_token = tr_waf_edit.text().strip()
            thread = _ExportThread(output_dir, waf_token=waf_token)
            self._export_thread = thread

            def _on_export_done(rc: int, msg: str) -> None:
                self._export_thread = None
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

        # ── Preview ──────────────────────────────────────────────────────────

        def _execute_preview(filepath: str) -> None:
            account_id = tr_account_combo.currentData()
            pid = _get_person_id()
            thread = _PreviewThread(
                filepath,
                pid,
                account_id,
                self._ticker_map,
                self._canonical_symbol_map,
            )
            self._preview_thread = thread

            def _on_preview_done(result) -> None:
                try:
                    self._preview_thread = None
                    btn_export.setEnabled(True)
                    btn_import_csv.setEnabled(True)
                    btn_apply_mapping.setEnabled(True)
                    self._pending_filepath = filepath
                    preview_table.setRowCount(0)

                    acc_labels = {tr_account_combo.itemData(i): tr_account_combo.itemText(i)
                                  for i in range(tr_account_combo.count())}

                    for r in result.get("preview", []):
                        ri = preview_table.rowCount()
                        preview_table.insertRow(ri)
                        eff_acc = r.get("effective_account_id", account_id)
                        acc_text = acc_labels.get(eff_acc, str(eff_acc))
                        canonical_symbol = str(r.get("symbol") or "")
                        live = self._ticker_preview_cache.get(canonical_symbol.upper(), {})
                        live_price = live.get("price")
                        vals = [
                            str(r.get("date", "")),
                            str(acc_text),
                            str(r.get("type", "")),
                            str(r.get("title", "")),
                            str(r.get("raw_symbol", "")),
                            str(canonical_symbol),
                            str(r.get("shares") or ""),
                            str(r.get("price") or ""),
                            f"{float(r.get('amount') or 0):.2f}",
                            str(live.get("name") or "—"),
                            f"{float(live_price):.4f}" if live_price is not None else "—",
                            str(live.get("currency") or "—"),
                            str(live.get("status") or "—").upper(),
                        ]
                        for ci, v in enumerate(vals):
                            item = QTableWidgetItem(v)
                            if r.get("duplicate"):
                                item.setForeground(QColor("#64748b"))
                            if ci == 5 and r.get("isin"):
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
                except Exception as e:
                    import traceback
                    _log(f"❌ Erreur affichage aperçu : {e}", "#ef4444")
                    for tb_line in traceback.format_exc().splitlines():
                        _log(tb_line, "#ef4444")

            def _on_preview_error(msg: str) -> None:
                self._preview_thread = None
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
            self._ticker_map = {}
            self._canonical_symbol_map = {}
            for sym, combo in self._combo_by_ticker.items():
                self._ticker_map[sym] = combo.currentData()
                symbol_edit = self._symbol_edit_by_ticker.get(sym)
                if symbol_edit:
                    canonical = symbol_edit.text().strip().upper()
                    if canonical:
                        self._canonical_symbol_map[sym] = canonical
            if not self._pending_filepath:
                return
            _execute_preview(self._pending_filepath)

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
            self._pending_filepath = filepath

            multi_acc_grp.show()
            pred_thread = _PredictionThread(filepath, pid)
            self._prediction_thread = pred_thread

            def _on_pred_done(results):
                try:
                    self._prediction_thread = None
                    while multi_item_layout.count():
                        c = multi_item_layout.takeAt(0)
                        if c.widget():
                            c.widget().deleteLater()
                    self._combo_by_ticker.clear()
                    self._symbol_edit_by_ticker.clear()
                    self._preview_label_by_ticker.clear()

                    allow_multi = chk_multi_account.isChecked()

                    if not results:
                        lbl = QLabel("Aucun ticker trouvé dans l'export.")
                        lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
                        multi_item_layout.addWidget(lbl)
                    else:
                        for rx in results:
                            raw_sym = str(rx.get("raw_symbol") or rx.get("symbol") or "").strip().upper()
                            canonical_sym = str(rx.get("canonical_symbol") or rx.get("symbol") or raw_sym).strip().upper()
                            if not raw_sym:
                                continue
                            pred_acc = rx.get("predicted_account_id")
                            row_w = QWidget()
                            row_w.setStyleSheet("background: transparent;")
                            row_v = QVBoxLayout(row_w)
                            row_v.setContentsMargins(0, 0, 0, 0)
                            row_v.setSpacing(2)

                            rl = QHBoxLayout()
                            rl.setContentsMargins(0, 0, 0, 0)
                            name_lbl = QLabel(f"[{raw_sym}] {rx.get('title', '')[:30]}")
                            name_lbl.setStyleSheet("color: #e2e8f0; font-size: 12px;")
                            name_lbl.setMinimumWidth(180)
                            name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                            rl.addWidget(name_lbl, 2)

                            sym_edit = QLineEdit()
                            sym_edit.setStyleSheet(INPUT_STYLE)
                            sym_edit.setText(canonical_sym)
                            sym_edit.setPlaceholderText("Ticker canonique")
                            sym_edit.setMinimumWidth(180)
                            rl.addWidget(sym_edit, 1)

                            cbo = QComboBox()
                            cbo.setStyleSheet(INPUT_STYLE)
                            cbo.setMinimumWidth(220)
                            for i in range(tr_account_combo.count()):
                                cbo.addItem(tr_account_combo.itemText(i), tr_account_combo.itemData(i))
                            if allow_multi and pred_acc:
                                idx = cbo.findData(pred_acc)
                                if idx >= 0:
                                    cbo.setCurrentIndex(idx)
                            else:
                                idx_default = cbo.findData(account_id)
                                if idx_default >= 0:
                                    cbo.setCurrentIndex(idx_default)
                                cbo.setEnabled(allow_multi)
                            self._combo_by_ticker[raw_sym] = cbo
                            self._symbol_edit_by_ticker[raw_sym] = sym_edit
                            rl.addWidget(cbo, 1)
                            row_v.addLayout(rl)

                            preview_lbl = QLabel("Nom: — | Prix: — | Devise: — | Statut: —")
                            preview_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
                            row_v.addWidget(preview_lbl)
                            self._preview_label_by_ticker[raw_sym] = preview_lbl
                            _bind_live_preview(sym_edit, preview_lbl)
                            multi_item_layout.addWidget(row_w)

                    _apply_mapping_and_preview()
                except Exception as e:
                    import traceback
                    _log(f"❌ Erreur prédiction multi-compte : {e}", "#ef4444")
                    for tb_line in traceback.format_exc().splitlines():
                        _log(tb_line, "#ef4444")

            def _on_pred_error(err):
                self._prediction_thread = None
                _log(f"Erreur prédiction multi-compte : {err}", "#ef4444")
                _execute_preview(filepath)

            pred_thread.done.connect(_on_pred_done)
            pred_thread.error.connect(_on_pred_error)
            pred_thread.start()

        def _pick_csv() -> None:
            path, _ = QFileDialog.getOpenFileName(
                inner, "Choisir un CSV Trade Republic", "", "CSV (*.csv)"
            )
            if path:
                _log(f"CSV sélectionné : {path}", "#94a3b8")
                _run_preview(path)

        def _confirm_import() -> None:
            filepath = self._pending_filepath
            account_id = tr_account_combo.currentData()
            account_label = tr_account_combo.currentText()
            pid = _get_person_id()
            person = get_person_name()
            if not filepath or not account_id or not pid:
                return
            try:
                from services.tr_import import import_tr_transactions
                from services.import_history import create_batch, close_batch
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
                    dry_run=False,
                    ticker_account_map=self._ticker_map,
                    canonical_symbol_map=self._canonical_symbol_map,
                    import_batch_id=batch_id,
                )
                n = result["to_insert"]
                close_batch(self._conn, batch_id, n)
                result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
                result_lbl.setText(f"Import OK ✅ — {n} transactions enregistrées.")
                btn_confirm.setEnabled(False)
                _log(f"✅ {n} transactions importées (batch #{batch_id}).", "#22c55e")
                refresh_history()
            except Exception as e:
                import traceback
                result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
                result_lbl.setText(f"Erreur : {e}")
                _log(f"❌ Erreur import : {e}", "#ef4444")
                for tb_line in traceback.format_exc().splitlines():
                    _log(tb_line, "#ef4444")

        # ── Mise à jour pytr ─────────────────────────────────────────────────
        def _do_update_pytr() -> None:
            btn_update_pytr.setEnabled(False)
            _log("📦  pip install --upgrade pytr en cours…", "#60a5fa")

            t = _UpgradeThread()
            self._upgrade_thread = t

            def _on_upgrade(rc, msg):
                self._upgrade_thread = None
                btn_update_pytr.setEnabled(True)
                from services.tr_import import strip_ansi
                for line in strip_ansi(msg).splitlines()[-5:]:
                    if line.strip():
                        _log(line, "#22c55e" if rc == 0 else "#ef4444")
                if rc == 0:
                    _log("✅  pytr mis à jour. Relancez la connexion.", "#22c55e")
                else:
                    _log("❌  Mise à jour échouée. Voir les logs ci-dessus.", "#ef4444")

            t.done.connect(_on_upgrade)
            t.start()

        # ── Reset credentials ─────────────────────────────────────────────────
        def _do_reset_creds() -> None:
            from services.tr_import import clear_pytr_credentials, get_pytr_credentials_path
            cred_path = get_pytr_credentials_path()
            if clear_pytr_credentials():
                _log(f"✔ Credentials supprimés ({cred_path}).", "#22c55e")
                _log("Relancez maintenant la connexion (Étape 1).", "#94a3b8")
            else:
                _log("ℹ️ Aucun credentials stocké localement.", "#94a3b8")

        # ── Connexions signaux ────────────────────────────────────────────────
        btn_save_phone.clicked.connect(_save_phone)
        btn_login.clicked.connect(_do_login)
        btn_stop_login.clicked.connect(_stop_login)
        btn_send_code.clicked.connect(_send_code)
        code_edit.returnPressed.connect(_send_code)
        btn_export.clicked.connect(_do_export)
        btn_import_csv.clicked.connect(_pick_csv)
        btn_confirm.clicked.connect(_confirm_import)
        btn_update_pytr.clicked.connect(_do_update_pytr)
        btn_reset_creds.clicked.connect(_do_reset_creds)

    def _refresh_accounts(
        self,
        person_id: int,
        *,
        accounts: list[dict] | None = None,
        phone: str | None = None,
    ) -> None:
        """Recharge les comptes PEA/CTO pour la personne sélectionnée."""
        self._tr_account_combo.clear()
        try:
            tr_accounts = accounts if accounts is not None else lookup.list_accounts_by_types(
                self._conn, person_id, ["PEA", "CTO"]
            )
            for acc in tr_accounts:
                self._tr_account_combo.addItem(
                    f"{acc['name']} ({acc['account_type']})", int(acc["id"])
                )
            if phone is None:
                from services.tr_import import get_tr_phone
                phone = get_tr_phone(self._conn, person_id)
            if phone:
                self._tr_phone_edit.setText(phone)
        except Exception:
            pass
