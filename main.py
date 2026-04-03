"""
Point d'entrée de l'application Patrimoine Desktop (PyQt6).
Lance la fenêtre principale et gère le cycle de vie de l'application.
"""
import sys
import os

# Ajouter le répertoire courant au path pour que les imports fonctionnent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
# QWebEngineView requires this attribute to be set before QApplication
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from core.db_connection import get_connection, close_connection
from qt_ui.main_window import MainWindow


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
    close_connection()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
