"""
Fenêtre principale de l'application Patrimoine.
Contient la barre de navigation latérale + le QStackedWidget central.
"""
import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QSizePolicy, QStatusBar
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon

from qt_ui.pages.famille_page import FamillePage
from qt_ui.pages.personnes_page import PersonnesPage
from qt_ui.pages.import_page import ImportPage
from qt_ui.theme import (
    BG_PRIMARY, BG_SIDEBAR, BG_HOVER, BG_ACTIVE, BORDER_SUBTLE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DARK, TEXT_DISABLED,
    ACCENT_BLUE, STYLE_NAV_BTN,
)

logger = logging.getLogger(__name__)


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

        self._btn_famille.clicked.connect(lambda: main_window.show_page("famille"))
        self._btn_personnes.clicked.connect(lambda: main_window.show_page("personnes"))
        self._btn_import.clicked.connect(lambda: main_window.show_page("import"))

        layout.addWidget(self._btn_famille)
        layout.addWidget(self._btn_personnes)
        layout.addWidget(self._btn_import)

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

        # Stack
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_famille)
        self._stack.addWidget(self._page_personnes)
        self._stack.addWidget(self._page_import)

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

    def show_person(self, name: str) -> None:
        """Navigue vers la page Personnes et sélectionne la personne."""
        self._sidebar.set_active("personnes")
        self._stack.setCurrentWidget(self._page_personnes)
        self._page_personnes.select_person_by_name(name)

    def set_status(self, msg: str) -> None:
        self._status.showMessage(msg)
