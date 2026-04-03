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
_USER_DATA_DIR = Path.home() / ".patrimoine"
_USER_DATA_DIR.mkdir(exist_ok=True)

_LOG_DIR = _USER_DATA_DIR / "logs"
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
    """Copie patrimoine.db (et sa variante Turso) dans ~/.patrimoine/backups/ avec horodatage."""
    backup_dir = _USER_DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    files_to_backup = [
        "patrimoine.db",
        "patrimoine_turso.db",
        "patrimoine_turso.db-info"
    ]
    
    backed_up = False
    for filename in files_to_backup:
        src = _APP_DIR / filename
        if src.exists():
            if ".db-info" in filename:
                dest = backup_dir / f"patrimoine_turso_{timestamp}.db-info"
            else:
                dest = backup_dir / filename.replace(".db", f"_{timestamp}.db")
                
            try:
                if src.is_dir():
                    import shutil
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest)
                logger.info("Sauvegarde DB → %s", dest)
                backed_up = True
            except Exception as e:
                logger.error("Échec sauvegarde %s : %s", filename, e)

    if not backed_up:
        return

    # Rotation : ne garder que les 10 dernières de chaque type principal
    for prefix in ["patrimoine_", "patrimoine_turso_"]:
        # Ne cibler que les fichiers .db pour vérifier le quota des 10 backups
        backups = sorted(backup_dir.glob(f"{prefix}*.db"), key=lambda p: str(p.name))
        
        while len(backups) > 10:
            old = backups.pop(0)
            try:
                old.unlink()
                # Tenter de supprimer le -info associé si présent
                info_file = backup_dir / f"{old.stem}.db-info"
                if info_file.exists():
                    if info_file.is_dir():
                        shutil.rmtree(info_file)
                    else:
                        info_file.unlink()
                        
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
