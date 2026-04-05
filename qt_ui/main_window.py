"""
Fenêtre principale de l'application Patrimoine.
Contient la barre de navigation latérale + le QStackedWidget central.
"""
import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QSizePolicy, QStatusBar
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon

from qt_ui.pages.famille_page import FamillePage
from qt_ui.pages.personnes_page import PersonnesPage
from qt_ui.pages.import_page import ImportPage
from qt_ui.pages.goals_projection_page import GoalsProjectionPage
from qt_ui.pages.settings_page import SettingsPage
from qt_ui.theme import (
    BG_PRIMARY, BG_SIDEBAR, BG_HOVER, BG_ACTIVE, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DARK, TEXT_DISABLED,
    ACCENT_BLUE, STYLE_NAV_BTN,
)
from qt_ui.components.animated_stack import AnimatedStackedWidget

logger = logging.getLogger(__name__)


# ── Background rebuild thread (AM-30) ────────────────────────────────────────

class AutoRebuildThread(QThread):
    """
    Thread de rebuild automatique au lancement.

    Crée sa propre connexion SQLite dédiée (isolation thread, BUG-01) et
    lance rebuild_snapshots_person_from_last() pour chaque personne en
    arrière-plan, sans bloquer l'UI.

    Signaux :
      progress(str)  — message de statut court affiché dans la status bar
      finished_ok()  — rebuild terminé avec succès
      finished_err(str) — rebuild terminé avec une erreur
    """

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

    def run(self) -> None:
        try:
            import sqlite3
            from services.db import DB_PATH
            from services import repositories as repo
            from services import snapshots as snap

            # ── Connexion dédiée à ce thread ────────────────────────────
            conn = sqlite3.connect(str(DB_PATH), check_same_thread=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA cache_size = -32000;")   # 32 MB
            conn.execute("PRAGMA synchronous = NORMAL;")

            # ── Liste des personnes ─────────────────────────────────────
            people = repo.list_people(conn)
            if people is None or people.empty:
                conn.close()
                self.finished_ok.emit()
                return

            total = len(people)
            for i, (_, person) in enumerate(people.iterrows(), start=1):
                pid = int(person["id"])
                name = str(person.get("name", f"#{pid}"))
                self.progress.emit(
                    f"🔄 Rebuild auto ({i}/{total}) — {name}…"
                )
                try:
                    result = snap.rebuild_snapshots_person_from_last(
                        conn,
                        person_id=pid,
                        safety_weeks=4,
                        fallback_lookback_days=90,
                    )
                    logger.info(
                        "AutoRebuild %s : %s",
                        name,
                        result,
                    )
                except Exception as exc:
                    logger.warning(
                        "AutoRebuild %s — erreur ignorée : %s", name, exc
                    )

            conn.close()
            self.finished_ok.emit()

        except Exception as exc:
            logger.error("AutoRebuildThread — erreur critique : %s", exc)
            self.finished_err.emit(str(exc))


class NavButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setStyleSheet(STYLE_NAV_BTN.format(color=TEXT_SECONDARY))
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class NavSidebar(QFrame):
    """Panneau de navigation latéral gauche."""

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = main_window
        self.setFixedWidth(220)
        self.setStyleSheet(f"""
            NavSidebar {{
                background-color: {BG_SIDEBAR};
                border-right: 1px solid {BORDER_SUBTLE};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(2)

        # Titre app
        title = QLabel("Patrimoine")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; margin-bottom: 16px;")
        layout.addWidget(title)

        # Séparateur
        layout.addWidget(self._make_separator())

        # Navigation principale
        nav_label = QLabel("NAVIGATION")
        nav_label.setStyleSheet(f"color: {TEXT_DISABLED}; font-size: 10px; padding: 8px 16px 4px 16px; letter-spacing: 1px;")
        layout.addWidget(nav_label)

        self._btn_famille = NavButton("🏠  Famille")
        self._btn_personnes = NavButton("👤  Personnes")
        self._btn_import = NavButton("📥  Import")
        self._btn_goals_projection = NavButton("🎯  Objectifs & Projection")

        self._btn_famille.clicked.connect(lambda: main_window.show_page("famille"))
        self._btn_personnes.clicked.connect(lambda: main_window.show_page("personnes"))
        self._btn_import.clicked.connect(lambda: main_window.show_page("import"))
        self._btn_goals_projection.clicked.connect(lambda: main_window.show_page("goals_projection"))

        layout.addWidget(self._btn_famille)
        layout.addWidget(self._btn_personnes)
        layout.addWidget(self._btn_import)
        layout.addWidget(self._btn_goals_projection)

        # Séparateur
        layout.addWidget(self._make_separator())

        # Personnes
        self._person_label = QLabel("PERSONNES")
        self._person_label.setStyleSheet(f"color: {TEXT_DISABLED}; font-size: 10px; padding: 8px 16px 4px 16px; letter-spacing: 1px;")
        layout.addWidget(self._person_label)

        self._person_buttons: list[QPushButton] = []
        self._person_container = QWidget()
        self._person_layout = QVBoxLayout(self._person_container)
        self._person_layout.setContentsMargins(0, 0, 0, 0)
        self._person_layout.setSpacing(2)
        layout.addWidget(self._person_container)

        layout.addStretch()

        # ── Bouton Paramètres (bas de sidebar) ─────────────────────────────
        layout.addWidget(self._make_separator())
        self._btn_settings = QPushButton("⚙️  Paramètres")
        self._btn_settings.setCheckable(True)
        self._btn_settings.setStyleSheet(STYLE_NAV_BTN.format(color=TEXT_MUTED))
        self._btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_settings.clicked.connect(lambda: main_window.show_page("settings"))
        layout.addWidget(self._btn_settings)

        # Version
        ver = QLabel("v2.0 — Qt Desktop")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(f"color: {TEXT_DARK}; font-size: 10px;")
        layout.addWidget(ver)

        # Sélection initiale
        self._btn_famille.setChecked(True)

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER_SUBTLE}; margin: 4px 8px;")
        return sep

    def populate_people(self, people_df) -> None:
        """Popule les boutons de navigation par personne."""
        # Vider les anciens boutons
        for btn in self._person_buttons:
            btn.setParent(None)
        self._person_buttons.clear()

        if people_df is None or people_df.empty:
            return

        for _, row in people_df.iterrows():
            name = str(row["name"])
            btn = NavButton(f"  {name}")
            btn.clicked.connect(lambda checked, n=name: self._mw.show_person(n))
            self._person_layout.addWidget(btn)
            self._person_buttons.append(btn)

    def set_active(self, page: str) -> None:
        """Met en surbrillance le bouton actif."""
        self._btn_famille.setChecked(page == "famille")
        self._btn_personnes.setChecked(page == "personnes")
        self._btn_import.setChecked(page == "import")
        self._btn_goals_projection.setChecked(page == "goals_projection")
        self._btn_settings.setChecked(page == "settings")
        for btn in self._person_buttons:
            btn.setChecked(False)


class MainWindow(QMainWindow):
    """Fenêtre principale de l'application."""

    def __init__(self, conn):
        super().__init__()
        self._conn = conn
        self.setWindowTitle("Suivie Patrimoine — Desktop")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(f"QMainWindow {{ background-color: {BG_PRIMARY}; }}")

        # Widget central
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Pages
        self._page_famille = FamillePage(conn)
        self._page_personnes = PersonnesPage(conn)
        self._page_import = ImportPage(conn)
        self._page_goals_projection = GoalsProjectionPage(conn)
        self._page_settings = SettingsPage(conn)

        # Stack
        self._stack = AnimatedStackedWidget()
        self._stack.addWidget(self._page_famille)
        self._stack.addWidget(self._page_personnes)
        self._stack.addWidget(self._page_import)
        self._stack.addWidget(self._page_goals_projection)
        self._stack.addWidget(self._page_settings)

        # Sidebar
        self._sidebar = NavSidebar(self)
        main_layout.addWidget(self._sidebar)
        main_layout.addWidget(self._stack, 1)  # stretch=1 : occupe tout l'espace restant

        # Status bar
        self._status = QStatusBar()
        self._status.setStyleSheet(f"background: {BG_SIDEBAR}; color: {TEXT_MUTED}; font-size: 11px;")
        self.setStatusBar(self._status)
        self._status.showMessage("Prêt")

        # Charger les personnes dans la sidebar
        self._load_people()

        # Page initiale
        self.show_page("famille")

        # ── Rebuild automatique au lancement (AM-30) ──────────────────────
        # Déclenché 500ms après le show() pour laisser l'UI se rendre d'abord.
        self._rebuild_thread: AutoRebuildThread | None = None
        QTimer.singleShot(500, self._start_auto_rebuild)

    def _start_auto_rebuild(self) -> None:
        """Lance le rebuild automatique en background thread."""
        self._rebuild_thread = AutoRebuildThread(self)
        self._rebuild_thread.progress.connect(self._on_rebuild_progress)
        self._rebuild_thread.finished_ok.connect(self._on_rebuild_done)
        self._rebuild_thread.finished_err.connect(self._on_rebuild_error)
        self._rebuild_thread.start()
        logger.info("AutoRebuild démarré en background.")

    def _on_rebuild_progress(self, msg: str) -> None:
        self._status.showMessage(msg)

    def _on_rebuild_done(self) -> None:
        """Appelé dans le thread Qt principal après le rebuild réussi."""
        logger.info("AutoRebuild terminé — rafraîchissement de la page active.")
        self._status.showMessage("✅ Rebuild auto terminé — données à jour.", 5000)
        # Rafraîchir la page courante si elle a une méthode refresh()
        current = self._stack.currentWidget()
        if hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception as exc:
                logger.warning("Refresh post-rebuild échoué : %s", exc)

    def _on_rebuild_error(self, err: str) -> None:
        logger.error("AutoRebuild échoué : %s", err)
        self._status.showMessage(f"⚠️ Rebuild auto échoué : {err}", 8000)

    def _load_people(self) -> None:
        try:
            from services import repositories as repo
            people = repo.list_people(self._conn)
            self._sidebar.populate_people(people)
        except Exception as e:
            logger.error("Erreur chargement des personnes : %s", e)
            self._status.showMessage(f"Erreur chargement personnes : {e}")

    def show_page(self, page: str) -> None:
        """Affiche la page demandée."""
        self._sidebar.set_active(page)
        if page == "famille":
            self._stack.setCurrentWidget(self._page_famille)
            self._page_famille.refresh()
        elif page == "personnes":
            self._stack.setCurrentWidget(self._page_personnes)
        elif page == "import":
            self._stack.setCurrentWidget(self._page_import)
            self._page_import.refresh()
        elif page == "goals_projection":
            self._stack.setCurrentWidget(self._page_goals_projection)
            self._page_goals_projection.refresh()
        elif page == "settings":
            self._stack.setCurrentWidget(self._page_settings)
            self._page_settings.refresh()

    def show_person(self, name: str) -> None:
        """Navigue vers la page Personnes et sélectionne la personne."""
        self._sidebar.set_active("personnes")
        self._stack.setCurrentWidget(self._page_personnes)
        self._page_personnes.select_person_by_name(name)

    def closeEvent(self, event) -> None:
        if self._rebuild_thread is not None and self._rebuild_thread.isRunning():
            self._rebuild_thread.quit()
            self._rebuild_thread.wait()
        super().closeEvent(event)

    def set_status(self, msg: str) -> None:
        self._status.showMessage(msg)
