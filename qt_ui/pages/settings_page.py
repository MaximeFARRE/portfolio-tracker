"""
Page Paramètres — AM-11
Accessible via le bouton ⚙️ en bas de la sidebar.
Affiche les infos système, permet la configuration et le backup manuel.
"""
import logging
import shutil
import platform
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QSpinBox, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QScrollArea, QFrame, QSizePolicy
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
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR,
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

        # ── Section 5 : À propos ──────────────────────────────────────────────
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
                QPushButton:hover {{ background: #1e4a7f; }}
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
        self._lbl_save_status.setStyleSheet(STYLE_STATUS_SUCCESS)

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
        self._lbl_backup_status.setStyleSheet(STYLE_STATUS_SUCCESS)
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
        self._settings.setValue("devise_defaut",   self._combo_devise.currentText())
        self._settings.setValue("rebuild_delay_ms", self._spin_delay.value())
        self._settings.setValue("backup_max_count", self._spin_nbackup.value())
        self._settings.sync()
        self._lbl_save_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._lbl_save_status.setText("✅ Enregistré")
        logger.info(
            "Préférences enregistrées: devise=%s, rebuild_delay=%dms, backup_max=%d",
            self._combo_devise.currentText(),
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
            self._refresh_backup_count(backup_dir)
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

    def _refresh_backup_count(self, backup_dir: Path) -> None:
        if not backup_dir.exists():
            self._lbl_backup_count.setText("Aucun backup trouvé.")
            return
        backups = sorted(backup_dir.glob("patrimoine_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            self._lbl_backup_count.setText("Aucun backup disponible.")
        else:
            latest = backups[0]
            mtime = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%d/%m/%Y à %H:%M")
            self._lbl_backup_count.setText(
                f"{len(backups)} backup(s) disponible(s) — "
                f"Dernier : {latest.name} ({mtime})"
            )

    # ── API ────────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Appelé quand la page devient active."""
        from services.db import DB_PATH
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
    def get_backup_max_count() -> int:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return int(s.value("backup_max_count", 10))
