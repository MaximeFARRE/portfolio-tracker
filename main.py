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
from qt_ui.theme import app_style_sheet, get_current_theme


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
        ("patrimoine.db",           f"patrimoine_{timestamp}.db"),
        ("patrimoine_turso.db",     f"patrimoine_turso_{timestamp}.db"),
        ("patrimoine_turso.db-info", f"patrimoine_turso_{timestamp}.db-info"),
    ]

    backed_up = False
    for filename, destname in files_to_backup:
        src = _APP_DIR / filename
        if not src.exists():
            continue
        dest = backup_dir / destname
        try:
            if src.is_dir():
                shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(dest))
            logger.info("Sauvegarde DB → %s", dest)
            backed_up = True
        except Exception as e:
            logger.error("Échec sauvegarde %s : %s", filename, e)

    if not backed_up:
        return

    # Rotation : ne garder que les 10 dernières de chaque type principal
    for prefix in ["patrimoine_2", "patrimoine_turso_2"]:
        backups = sorted(
            [p for p in backup_dir.glob(f"{prefix}*.db") if p.is_file()],
            key=lambda p: p.name
        )
        while len(backups) > 10:
            old = backups.pop(0)
            try:
                old.unlink()
                # Supprimer le .db-info associé si présent
                for ext in [".db-info"]:
                    companion = backup_dir / (old.stem + ext)
                    if companion.exists():
                        if companion.is_dir():
                            shutil.rmtree(str(companion))
                        else:
                            companion.unlink()
                logger.info("Ancienne sauvegarde supprimée : %s", old.name)
            except Exception:
                pass


def main():
    # Configuration Qt
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

    app = QApplication(sys.argv)
    app.setApplicationName("Patrimoine Desktop")
    app.setOrganizationName("Famille")

    # Style global selon le thème choisi dans les préférences.
    app.setStyleSheet(app_style_sheet())
    logger.info("Thème UI chargé : %s", get_current_theme())

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
