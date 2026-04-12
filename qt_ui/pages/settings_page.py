"""
Page Paramètres — AM-11
Accessible via le bouton ⚙️ en bas de la sidebar.
Affiche les infos système, permet la configuration et le backup manuel.
"""
import logging
import shutil
import platform
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import monotonic

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QScrollArea, QFrame, QSizePolicy, QTabWidget
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QClipboard
from PyQt6.QtWidgets import QApplication

from qt_ui.theme import (
    BG_PRIMARY, BG_CARD, BG_SIDEBAR, BG_ACTIVE,
    BORDER_SUBTLE, BORDER_DEFAULT,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DISABLED,
    ACCENT_BLUE, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    STYLE_BTN_PRIMARY, STYLE_BTN_PRIMARY_BORDERED, STYLE_BTN_SUCCESS,
    STYLE_GROUP, STYLE_INPUT_FOCUS, STYLE_TITLE_LARGE, STYLE_SECTION,
    STYLE_STATUS, STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, STYLE_STATUS_WARNING,
    BG_ACTIVE_HOVER,
    get_current_theme,
)

logger = logging.getLogger(__name__)

APP_VERSION = "2.0.0"
_SETTINGS_ORG  = "Famille"
_SETTINGS_APP  = "PatrimoineDesktop"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {BORDER_SUBTLE}; margin: 4px 0;")
    return f


def _card_style() -> str:
    return f"""
        QGroupBox {{
            color: {TEXT_SECONDARY};
            border: 1px solid {BORDER_SUBTLE};
            border-radius: 8px;
            padding: 12px 10px 10px 10px;
            margin-top: 6px;
            background: {BG_CARD};
        }}
        QGroupBox::title {{
            subcontrol-position: top left;
            padding: 2px 10px;
            font-weight: bold;
            font-size: 13px;
            color: {TEXT_SECONDARY};
        }}
    """


# ─── SettingsPage ──────────────────────────────────────────────────────────────

class SettingsPage(QWidget):
    """
    Page Paramètres (AM-11).
    Intégrée dans le QStackedWidget de MainWindow.
    """

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self._backup_count_cache_ttl_s = 8.0
        self._backup_count_cache_ts = 0.0
        self._backup_count_cache_dir_mtime_ns = None
        self._backup_count_cache_text = None
        self._preset_scope_cache: dict[tuple[str, int | None], dict] = {}
        self._preset_scope_cache_order: list[tuple[str, int | None]] = []
        self._preset_scope_cache_limit = 8

        self.setStyleSheet(f"background: {BG_PRIMARY};")

        # ── Scroll area enveloppante ──────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {BG_PRIMARY}; }}")
        outer.addWidget(scroll)

        inner = QWidget()
        inner.setStyleSheet(f"background: {BG_PRIMARY};")
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 24, 32, 32)
        layout.setSpacing(20)

        # ── Titre ─────────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title = QLabel("⚙️  Paramètres")
        title.setStyleSheet(STYLE_TITLE_LARGE)
        header_row.addWidget(title)
        header_row.addStretch()
        layout.addLayout(header_row)

        layout.addWidget(_sep())

        # ── Section 1 : Informations système ──────────────────────────────────
        layout.addWidget(self._build_system_info())

        # ── Section 2 : Préférences ────────────────────────────────────────────
        layout.addWidget(self._build_preferences())

        # ── Section 3 : Sauvegarde ────────────────────────────────────────────
        layout.addWidget(self._build_backup())

        # ── Section 4 : Logs ──────────────────────────────────────────────────
        layout.addWidget(self._build_logs())

        # ── Section 5 : Presets de simulation ────────────────────────────────
        self._sim_presets_box = self._build_simulation_presets()
        layout.addWidget(self._sim_presets_box)

        # ── Section 6 : À propos ──────────────────────────────────────────────
        layout.addWidget(self._build_about())

        layout.addStretch()

    # ── Sections ──────────────────────────────────────────────────────────────

    def _build_system_info(self) -> QGroupBox:
        box = QGroupBox("ℹ️  Informations système")
        box.setStyleSheet(_card_style())
        form = QFormLayout(box)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        from services.db import DB_PATH
        _USER_DATA_DIR = Path.home() / ".patrimoine"

        fields = [
            ("Chemin de la base de données",  str(DB_PATH)),
            ("Dossier de données utilisateur", str(_USER_DATA_DIR)),
            ("Dossier des logs",               str(_USER_DATA_DIR / "logs")),
            ("Dossier des backups",            str(_USER_DATA_DIR / "backups")),
            ("Version de l'application",       APP_VERSION),
            ("Système d'exploitation",         f"{platform.system()} {platform.release()}"),
            ("Python",                          platform.python_version()),
        ]

        for label_text, value_text in fields:
            lbl = QLabel(label_text + " :")
            lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")

            val_row = QHBoxLayout()
            val_lbl = QLabel(value_text)
            val_lbl.setStyleSheet(f"""
                color: {TEXT_PRIMARY};
                font-size: 12px;
                background: {BG_SIDEBAR};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px;
                padding: 3px 8px;
            """)
            val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val_lbl.setCursor(Qt.CursorShape.IBeamCursor)
            val_row.addWidget(val_lbl, 1)

            btn_copy = QPushButton("📋")
            btn_copy.setFixedSize(28, 28)
            btn_copy.setToolTip("Copier dans le presse-papier")
            btn_copy.setStyleSheet(f"""
                QPushButton {{ background: {BG_ACTIVE}; color: {ACCENT_BLUE};
                               border: none; border-radius: 4px; font-size: 13px; }}
                QPushButton:hover {{ background: {BG_ACTIVE_HOVER}; }}
            """)
            btn_copy.clicked.connect(lambda _, v=value_text: self._copy_to_clipboard(v))
            val_row.addWidget(btn_copy)

            container = QWidget()
            container.setStyleSheet("background: transparent;")
            container.setLayout(val_row)
            form.addRow(lbl, container)

        return box

    def _build_preferences(self) -> QGroupBox:
        box = QGroupBox("🎛️  Préférences")
        box.setStyleSheet(_card_style())
        form = QFormLayout(box)
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Devise par défaut
        lbl_dev = QLabel("Devise par défaut :")
        lbl_dev.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._combo_devise = QComboBox()
        self._combo_devise.addItems(["EUR", "USD", "GBP", "CHF", "JPY", "CAD"])
        self._combo_devise.setStyleSheet(STYLE_INPUT_FOCUS)
        self._combo_devise.setCurrentText(self._settings.value("devise_defaut", "EUR"))
        self._combo_devise.setMaximumWidth(120)
        form.addRow(lbl_dev, self._combo_devise)

        # Thème UI (appliqué au prochain démarrage)
        lbl_theme = QLabel("Thème de l'interface :")
        lbl_theme.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._combo_theme = QComboBox()
        self._combo_theme.setStyleSheet(STYLE_INPUT_FOCUS)
        self._combo_theme.addItem("Sombre", "dark")
        self._combo_theme.addItem("Clair", "light")
        current_theme = str(self._settings.value("ui_theme", get_current_theme())).strip().lower()
        idx_theme = self._combo_theme.findData("light" if current_theme == "light" else "dark")
        self._combo_theme.setCurrentIndex(idx_theme if idx_theme >= 0 else 0)
        self._combo_theme.setMaximumWidth(160)
        form.addRow(lbl_theme, self._combo_theme)

        # Délai rebuild auto (ms)
        lbl_delay = QLabel("Délai rebuild auto (ms) :")
        lbl_delay.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        lbl_delay.setToolTip(
            "Délai entre le démarrage de l'interface et le lancement\n"
            "du rebuild automatique des snapshots (en millisecondes).\n"
            "500 ms par défaut. Augmentez si l'app est lente au démarrage."
        )
        self._spin_delay = QSpinBox()
        self._spin_delay.setRange(0, 10000)
        self._spin_delay.setSingleStep(250)
        self._spin_delay.setSuffix(" ms")
        self._spin_delay.setStyleSheet(STYLE_INPUT_FOCUS)
        self._spin_delay.setValue(int(self._settings.value("rebuild_delay_ms", 500)))
        self._spin_delay.setMaximumWidth(120)
        form.addRow(lbl_delay, self._spin_delay)

        # Nombre de backups à conserver
        lbl_nback = QLabel("Backups à conserver :")
        lbl_nback.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self._spin_nbackup = QSpinBox()
        self._spin_nbackup.setRange(1, 50)
        self._spin_nbackup.setValue(int(self._settings.value("backup_max_count", 10)))
        self._spin_nbackup.setSuffix(" fichiers")
        self._spin_nbackup.setStyleSheet(STYLE_INPUT_FOCUS)
        self._spin_nbackup.setMaximumWidth(140)
        form.addRow(lbl_nback, self._spin_nbackup)

        # Bouton Enregistrer
        self._btn_save = QPushButton("💾  Enregistrer les préférences")
        self._btn_save.setStyleSheet(STYLE_BTN_SUCCESS)
        self._btn_save.setFixedWidth(240)
        self._btn_save.clicked.connect(self._save_preferences)
        self._lbl_save_status = QLabel()
        self._lbl_save_status.setStyleSheet(STYLE_STATUS)

        save_row = QHBoxLayout()
        save_row.addWidget(self._btn_save)
        save_row.addWidget(self._lbl_save_status)
        save_row.addStretch()
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        w.setLayout(save_row)
        form.addRow("", w)

        return box

    def _build_backup(self) -> QGroupBox:
        box = QGroupBox("🗄️  Sauvegardes")
        box.setStyleSheet(_card_style())
        v = QVBoxLayout(box)
        v.setSpacing(12)

        from services.db import DB_PATH
        _USER_DATA_DIR = Path.home() / ".patrimoine"
        backup_dir = _USER_DATA_DIR / "backups"

        # Statut des backups existants
        self._lbl_backup_count = QLabel()
        self._lbl_backup_count.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._refresh_backup_count(backup_dir)
        v.addWidget(self._lbl_backup_count)

        # Boutons
        btn_row = QHBoxLayout()

        btn_now = QPushButton("📦  Créer un backup maintenant")
        btn_now.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
        btn_now.clicked.connect(lambda: self._do_backup(DB_PATH, backup_dir))
        btn_row.addWidget(btn_now)

        btn_open = QPushButton("📂  Ouvrir le dossier backups")
        btn_open.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_open.clicked.connect(lambda: self._open_folder(backup_dir))
        btn_row.addWidget(btn_open)

        btn_custom = QPushButton("💾  Exporter vers…")
        btn_custom.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_custom.clicked.connect(lambda: self._export_custom(DB_PATH))
        btn_row.addWidget(btn_custom)

        btn_row.addStretch()
        v.addLayout(btn_row)

        self._lbl_backup_status = QLabel()
        self._lbl_backup_status.setStyleSheet(STYLE_STATUS)
        v.addWidget(self._lbl_backup_status)

        return box

    def _build_logs(self) -> QGroupBox:
        box = QGroupBox("📋  Logs")
        box.setStyleSheet(_card_style())
        v = QVBoxLayout(box)
        v.setSpacing(10)

        _USER_DATA_DIR = Path.home() / ".patrimoine"
        log_dir = _USER_DATA_DIR / "logs"
        log_file = log_dir / "patrimoine.log"

        lbl_path = QLabel(f"Fichier de log : <code>{log_file}</code>")
        lbl_path.setTextFormat(Qt.TextFormat.RichText)
        lbl_path.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        v.addWidget(lbl_path)

        btn_row = QHBoxLayout()
        btn_open_log = QPushButton("📂  Ouvrir le dossier logs")
        btn_open_log.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_open_log.clicked.connect(lambda: self._open_folder(log_dir))
        btn_row.addWidget(btn_open_log)
        btn_row.addStretch()
        v.addLayout(btn_row)

        return box

    def _build_simulation_presets(self) -> QGroupBox:
        """Section de configuration des presets de simulation par scope."""
        from services.simulation_presets_repository import (
            PRESET_DEFAULTS, PRESET_KEYS, get_all_presets,
            initialize_default_presets, update_preset,
        )
        from services.goals_projection_repository import list_people_for_scope

        box = QGroupBox("📊  Presets de simulation")
        box.setStyleSheet(_card_style())
        v = QVBoxLayout(box)
        v.setSpacing(12)

        # ── Sélecteur de scope ────────────────────────────────────────────────
        scope_row = QHBoxLayout()
        lbl_scope = QLabel("Scope :")
        lbl_scope.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        scope_combo = QComboBox()
        scope_combo.setStyleSheet(STYLE_INPUT_FOCUS)
        scope_combo.setMaximumWidth(200)
        scope_combo.addItem("Famille", ("family", None))
        try:
            people_df = list_people_for_scope(self._conn)
            if people_df is not None and not people_df.empty:
                for _, pr in people_df.iterrows():
                    scope_combo.addItem(str(pr["name"]), ("person", int(pr["id"])))
        except Exception:
            pass
        scope_row.addWidget(lbl_scope)
        scope_row.addWidget(scope_combo)
        scope_row.addStretch()
        v.addLayout(scope_row)

        # ── Onglets par preset ────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 6px; }}
            QTabBar::tab {{
                background: {BG_CARD}; color: {TEXT_SECONDARY};
                padding: 6px 16px; border: 1px solid {BORDER_SUBTLE};
                border-bottom: none; border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{ background: {BG_ACTIVE}; color: {TEXT_PRIMARY}; font-weight: bold; }}
        """)

        _PRESET_LABELS = {"pessimiste": "Pessimiste", "realiste": "Réaliste", "optimiste": "Optimiste"}

        _FIELDS = [
            # ── Rendements attendus ──────────────────────────────────────────────
            ("return_liquidites_pct",  "Rendement Liquidités (%)",         -20.0, 50.0, " %"),
            ("return_bourse_pct",      "Rendement Bourse (%)",             -20.0, 50.0, " %"),
            ("return_immobilier_pct",  "Rendement Immobilier (%)",         -20.0, 50.0, " %"),
            ("return_pe_pct",          "Rendement Private Equity (%)",     -20.0, 50.0, " %"),
            ("return_entreprises_pct", "Rendement Entreprises (%)",        -20.0, 50.0, " %"),
            # ── Volatilités (pour Monte Carlo) ───────────────────────────────────
            ("vol_liquidites_pct",     "Volatilité Liquidités (%)",          0.0, 50.0, " %"),
            ("vol_bourse_pct",         "Volatilité Bourse (%)",              0.0, 80.0, " %"),
            ("vol_immobilier_pct",     "Volatilité Immobilier (%)",          0.0, 50.0, " %"),
            ("vol_pe_pct",             "Volatilité Private Equity (%)",      0.0, 80.0, " %"),
            ("vol_entreprises_pct",    "Volatilité Entreprises (%)",         0.0, 80.0, " %"),
            ("vol_crypto_pct",         "Volatilité Crypto (%)",              0.0, 200.0, " %"),
            # ── Macro ────────────────────────────────────────────────────────────
            ("inflation_pct",          "Inflation (%)",                      -5.0, 20.0, " %"),
            ("income_growth_pct",      "Croissance revenus (%)",            -20.0, 20.0, " %"),
            ("expense_growth_pct",     "Croissance dépenses (%)",           -20.0, 20.0, " %"),
            ("fire_multiple",          "Multiple FIRE",                        1.0, 200.0, ""),
            ("savings_factor",         "Facteur épargne (×)",                  0.0,   5.0, " ×"),
        ]

        # {preset_key: {field: QDoubleSpinBox}}
        preset_spinboxes: dict[str, dict] = {}
        preset_status_labels: dict[str, QLabel] = {}

        for preset_key in PRESET_KEYS:
            tab_widget = QWidget()
            tab_widget.setStyleSheet(f"background: {BG_CARD};")
            tab_layout = QVBoxLayout(tab_widget)
            tab_layout.setContentsMargins(12, 12, 12, 12)
            tab_layout.setSpacing(8)

            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            form.setSpacing(8)

            spins: dict[str, QDoubleSpinBox] = {}
            for field, label, lo, hi, suffix in _FIELDS:
                sp = QDoubleSpinBox()
                sp.setRange(lo, hi)
                sp.setDecimals(2)
                if suffix:
                    sp.setSuffix(suffix)
                sp.setStyleSheet(STYLE_INPUT_FOCUS)
                sp.setValue(float(PRESET_DEFAULTS[preset_key].get(field, 0.0)))
                form.addRow(label + " :", sp)
                spins[field] = sp

            preset_spinboxes[preset_key] = spins
            tab_layout.addLayout(form)

            status_lbl = QLabel("")
            status_lbl.setStyleSheet(STYLE_STATUS)
            preset_status_labels[preset_key] = status_lbl

            def _make_save_fn(pk):
                def _save():
                    scope_data = scope_combo.currentData()
                    if not scope_data:
                        return
                    s_type, s_id = scope_data
                    params = {f: preset_spinboxes[pk][f].value() for f, *_ in _FIELDS}
                    try:
                        update_preset(self._conn, pk, s_type, s_id, params)
                        self._invalidate_scope_presets_cache(s_type, s_id)
                        preset_status_labels[pk].setStyleSheet(STYLE_STATUS_SUCCESS)
                        preset_status_labels[pk].setText("✅ Preset sauvegardé.")
                    except Exception as exc:
                        preset_status_labels[pk].setStyleSheet(STYLE_STATUS_ERROR)
                        preset_status_labels[pk].setText(f"❌ Erreur : {exc}")
                return _save

            btn_save = QPushButton(f"Sauvegarder « {_PRESET_LABELS[preset_key]} »")
            btn_save.setStyleSheet(STYLE_BTN_PRIMARY_BORDERED)
            btn_save.clicked.connect(_make_save_fn(preset_key))

            bottom_row = QHBoxLayout()
            bottom_row.addWidget(btn_save)
            bottom_row.addWidget(status_lbl)
            bottom_row.addStretch()
            tab_layout.addLayout(bottom_row)

            tabs.addTab(tab_widget, _PRESET_LABELS[preset_key])

        v.addWidget(tabs)

        def _load_presets_for_scope():
            scope_data = scope_combo.currentData()
            if not scope_data:
                return
            s_type, s_id = scope_data
            cached = self._get_cached_scope_presets(s_type, s_id)
            if cached is not None:
                all_p = cached
            else:
                try:
                    initialize_default_presets(self._conn, s_type, s_id)
                    all_p = get_all_presets(self._conn, s_type, s_id)
                    self._set_cached_scope_presets(s_type, s_id, all_p)
                except Exception:
                    all_p = {}
            for pk in PRESET_KEYS:
                p = all_p.get(pk, PRESET_DEFAULTS[pk])
                for field, *_ in _FIELDS:
                    if field in preset_spinboxes[pk]:
                        preset_spinboxes[pk][field].setValue(
                            float(p.get(field, PRESET_DEFAULTS[pk].get(field, 0.0)))
                        )
                if pk in preset_status_labels:
                    preset_status_labels[pk].setText("")

        scope_combo.currentIndexChanged.connect(lambda _: _load_presets_for_scope())
        _load_presets_for_scope()

        return box

    def _build_about(self) -> QGroupBox:
        box = QGroupBox("🧾  À propos")
        box.setStyleSheet(_card_style())
        v = QVBoxLayout(box)
        v.setSpacing(8)

        data = [
            ("Application",  "Patrimoine Desktop"),
            ("Version",       APP_VERSION),
            ("Framework",     "PyQt6"),
            ("Base de données", "SQLite (WAL mode)"),
            ("Auteur",        "Maxime FARRE"),
            ("Licence",       "Privée — usage personnel"),
        ]

        for label, value in data:
            row = QHBoxLayout()
            lbl = QLabel(label + " :")
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; min-width: 160px;")
            lbl.setFixedWidth(160)
            val = QLabel(value)
            val.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            v.addLayout(row)

        return box

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _save_preferences(self) -> None:
        previous_theme = str(self._settings.value("ui_theme", get_current_theme())).strip().lower()
        new_theme = str(self._combo_theme.currentData() or "dark").strip().lower()

        self._settings.setValue("devise_defaut",   self._combo_devise.currentText())
        self._settings.setValue("ui_theme", new_theme)
        self._settings.setValue("rebuild_delay_ms", self._spin_delay.value())
        self._settings.setValue("backup_max_count", self._spin_nbackup.value())
        self._settings.sync()
        if previous_theme != new_theme:
            self._lbl_save_status.setStyleSheet(STYLE_STATUS_WARNING)
            self._lbl_save_status.setText("⚠️ Préférences enregistrées — redémarrez l'app pour appliquer le thème.")
        else:
            self._lbl_save_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._lbl_save_status.setText("✅ Préférences enregistrées.")
        logger.info(
            "Préférences enregistrées: devise=%s, theme=%s, rebuild_delay=%dms, backup_max=%d",
            self._combo_devise.currentText(),
            new_theme,
            self._spin_delay.value(),
            self._spin_nbackup.value(),
        )

    def _do_backup(self, db_path: Path, backup_dir: Path) -> None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"patrimoine_{timestamp}.db"
        try:
            shutil.copy2(str(db_path), str(dest))
            self._lbl_backup_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._lbl_backup_status.setText(f"✅ Backup créé : {dest.name}")
            self._refresh_backup_count(backup_dir, force=True)
            logger.info("Backup manuel créé : %s", dest)
        except Exception as e:
            self._lbl_backup_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._lbl_backup_status.setText(f"❌ Erreur : {e}")
            logger.error("Backup manuel échoué : %s", e)

    def _export_custom(self, db_path: Path) -> None:
        dest_str, _ = QFileDialog.getSaveFileName(
            self, "Exporter la base de données",
            str(Path.home() / f"patrimoine_{datetime.now().strftime('%Y%m%d')}.db"),
            "SQLite Database (*.db);;All files (*)",
        )
        if not dest_str:
            return
        try:
            shutil.copy2(str(db_path), dest_str)
            self._lbl_backup_status.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._lbl_backup_status.setText(f"✅ Exporté vers : {Path(dest_str).name}")
        except Exception as e:
            self._lbl_backup_status.setStyleSheet(STYLE_STATUS_ERROR)
            self._lbl_backup_status.setText(f"❌ Erreur : {e}")

    def _open_folder(self, path: Path) -> None:
        import subprocess, sys
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            logger.warning("Impossible d'ouvrir le dossier : %s", e)

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _refresh_backup_count(self, backup_dir: Path, *, force: bool = False) -> None:
        dir_mtime_ns = None
        if backup_dir.exists():
            try:
                dir_mtime_ns = backup_dir.stat().st_mtime_ns
            except Exception:
                dir_mtime_ns = None

        now = monotonic()
        cache_is_fresh = (
            not force
            and self._backup_count_cache_text is not None
            and (now - self._backup_count_cache_ts) <= self._backup_count_cache_ttl_s
            and self._backup_count_cache_dir_mtime_ns == dir_mtime_ns
        )
        if cache_is_fresh:
            self._lbl_backup_count.setText(self._backup_count_cache_text)
            return

        if not backup_dir.exists():
            msg = "Aucune sauvegarde disponible."
            self._lbl_backup_count.setText(msg)
            self._backup_count_cache_text = msg
            self._backup_count_cache_ts = now
            self._backup_count_cache_dir_mtime_ns = dir_mtime_ns
            return

        backups = sorted(backup_dir.glob("patrimoine_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            msg = "Aucune sauvegarde disponible."
        else:
            latest = backups[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%d/%m/%Y à %H:%M")
            msg = (
                f"{len(backups)} sauvegarde(s) disponible(s) — "
                f"Dernier : {latest.name} ({mtime})"
            )
        self._lbl_backup_count.setText(msg)
        self._backup_count_cache_text = msg
        self._backup_count_cache_ts = now
        self._backup_count_cache_dir_mtime_ns = dir_mtime_ns

    def _get_cached_scope_presets(self, scope_type: str, scope_id: int | None) -> dict | None:
        key = (scope_type, scope_id)
        cached = self._preset_scope_cache.get(key)
        if cached is None:
            return None
        return deepcopy(cached)

    def _set_cached_scope_presets(self, scope_type: str, scope_id: int | None, values: dict) -> None:
        key = (scope_type, scope_id)
        self._preset_scope_cache[key] = deepcopy(values or {})
        if key in self._preset_scope_cache_order:
            self._preset_scope_cache_order.remove(key)
        self._preset_scope_cache_order.append(key)
        while len(self._preset_scope_cache_order) > self._preset_scope_cache_limit:
            oldest = self._preset_scope_cache_order.pop(0)
            self._preset_scope_cache.pop(oldest, None)

    def _invalidate_scope_presets_cache(self, scope_type: str, scope_id: int | None) -> None:
        key = (scope_type, scope_id)
        self._preset_scope_cache.pop(key, None)
        if key in self._preset_scope_cache_order:
            self._preset_scope_cache_order.remove(key)

    # ── API ────────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Appelé quand la page devient active."""
        _USER_DATA_DIR = Path.home() / ".patrimoine"
        self._refresh_backup_count(_USER_DATA_DIR / "backups")

    # ── Accesseurs pour QSettings ──────────────────────────────────────────────

    @staticmethod
    def get_devise_defaut() -> str:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return str(s.value("devise_defaut", "EUR"))

    @staticmethod
    def get_rebuild_delay_ms() -> int:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return int(s.value("rebuild_delay_ms", 500))

    @staticmethod
    def get_ui_theme() -> str:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        val = str(s.value("ui_theme", get_current_theme())).strip().lower()
        return "light" if val == "light" else "dark"

    @staticmethod
    def get_backup_max_count() -> int:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return int(s.value("backup_max_count", 10))
