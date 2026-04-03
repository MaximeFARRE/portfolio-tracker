"""
Point d'entrée de l'application Patrimoine Desktop (PyQt6).
Lance la fenêtre principale et gère le cycle de vie de l'application.
"""
import sys
import os
import shutil
import logging
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Ajouter le répertoire courant au path pour que les imports fonctionnent
_APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(_APP_DIR))

# ── Logging persistant ────────────────────────────────────────────────────
_LOG_DIR = _APP_DIR / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        RotatingFileHandler(
            _LOG_DIR / "patrimoine.log",
            maxBytes=5 * 1024 * 1024,   # 5 MB par fichier
            backupCount=5,              # 5 fichiers max
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("patrimoine")
logger.info("═" * 60)
logger.info("Démarrage de Patrimoine Desktop")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
# QWebEngineView requires this attribute to be set before QApplication
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from core.db_connection import get_connection, close_connection
from qt_ui.main_window import MainWindow


# ── Exception handler global ──────────────────────────────────────────────
def _global_exception_handler(exc_type, exc_value, exc_tb):
    """Attrape les exceptions non gérées, les logue, et affiche un dialogue."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Exception non gérée:\n%s", tb_text)

    try:
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Erreur inattendue")
        msg.setText("Une erreur inattendue s'est produite.")
        msg.setDetailedText(tb_text)
        msg.setInformativeText(
            f"L'erreur a été enregistrée dans :\n{_LOG_DIR / 'patrimoine.log'}"
        )
        msg.exec()
    except Exception:
        pass

sys.excepthook = _global_exception_handler


# ── Sauvegarde automatique de la DB ───────────────────────────────────────
def _backup_database():
    """Copie patrimoine.db dans backups/ avec horodatage (garde les 10 dernières)."""
    db_path = _APP_DIR / "patrimoine.db"
    if not db_path.exists():
        return

    backup_dir = _APP_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"patrimoine_{timestamp}.db"

    try:
        shutil.copy2(db_path, dest)
        logger.info("Sauvegarde DB → %s", dest)
    except Exception as e:
        logger.error("Échec sauvegarde DB : %s", e)
        return

    # Rotation : ne garder que les 10 dernières sauvegardes
    backups = sorted(backup_dir.glob("patrimoine_*.db"), key=lambda p: p.name)
    while len(backups) > 10:
        old = backups.pop(0)
        try:
            old.unlink()
            logger.info("Ancienne sauvegarde supprimée : %s", old.name)
        except Exception:
            pass


def main():
    # Configuration Qt
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

    app = QApplication(sys.argv)
    app.setApplicationName("Patrimoine Desktop")
    app.setOrganizationName("Famille")

    # Style global (dark theme)
    app.setStyleSheet("""
        QWidget {
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 13px;
            color: #e2e8f0;
        }
        QLabel { color: #e2e8f0; }
        QScrollBar:vertical {
            background: #0f1623;
            width: 8px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical {
            background: #334155;
            border-radius: 4px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover { background: #475569; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal {
            background: #0f1623;
            height: 8px;
            border-radius: 4px;
        }
        QScrollBar::handle:horizontal {
            background: #334155;
            border-radius: 4px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover { background: #475569; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QToolTip {
            background: #1e2538;
            color: #e2e8f0;
            border: 1px solid #2a3040;
            padding: 4px;
        }
    """)

    # Connexion DB
    try:
        conn = get_connection()
    except Exception as e:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Erreur DB", f"Impossible d'initialiser la base de données :\n{e}")
        sys.exit(1)

    # Fenêtre principale
    window = MainWindow(conn)
    window.show()

    # Lancement
    exit_code = app.exec()

    # Sauvegarde automatique avant fermeture
    logger.info("Fermeture de l'application...")
    _backup_database()
    close_connection()
    logger.info("Application fermée proprement.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
