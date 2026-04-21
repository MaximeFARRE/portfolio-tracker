"""
Fenêtre principale de l'application Patrimoine.
Contient la barre de navigation latérale + l'AnimatedStackedWidget central.
"""
import logging
import time
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QFrame, QSizePolicy, QStatusBar,
    QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from services.common_utils import fmt_amount, row_get
from services.global_search_service import query_global_search
from qt_ui.pages.famille_page import FamillePage
from qt_ui.pages.personnes_page import PersonnesPage
from qt_ui.pages.import_page import ImportPage
from qt_ui.pages.goals_projection_page import GoalsProjectionPage
from qt_ui.pages.settings_page import SettingsPage
from qt_ui.theme import (
    BG_PRIMARY, BG_SIDEBAR, BG_CARD, BG_ACTIVE, BORDER_SUBTLE, BORDER_DEFAULT,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DARK, TEXT_DISABLED,
    STYLE_NAV_BTN,
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_cancelled = False
        self._did_work = False

    def cancel(self):
        self._is_cancelled = True

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
                if self._is_cancelled:
                    logger.info("AutoRebuildThread cancelled before person")
                    break
                
                pid = int(person["id"])
                name = str(person.get("name", f"#{pid}"))
                self.progress.emit(
                    f"🔄 Rebuild auto ({i}/{total}) — {name}…"
                )
                try:
                    if not snap.has_new_transactions_since_person_watermark(conn, pid):
                        logger.info("AutoRebuild %s : skipped (no new tx)", name)
                        continue
                    result = snap.rebuild_snapshots_person_from_last(
                        conn,
                        person_id=pid,
                        safety_weeks=4,
                        fallback_lookback_days=90,
                        cancel_check=lambda: self._is_cancelled
                    )
                    logger.info(
                        "AutoRebuild %s : %s",
                        name,
                        result,
                    )
                    if bool(result.get("did_run")) and int(result.get("n_ok", 0)) > 0:
                        self._did_work = True
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
    _SHOW_GLOBAL_SEARCH = False

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

        # Pages (lazy, sauf la page d'accueil)
        self._page_famille = FamillePage(conn)
        self._page_personnes = None
        self._page_import = None
        self._page_goals_projection = None
        self._page_settings = None
        self._current_page_key: str | None = None
        self._page_refresh_ttl_sec = {
            "famille": 8.0,
            "import": 10.0,
            "goals_projection": 10.0,
            "settings": 20.0,
        }
        self._last_page_refresh_at: dict[str, float] = {}

        # Stack
        self._stack = AnimatedStackedWidget()
        self._stack.addWidget(self._page_famille)

        # Recherche globale (AM-01)
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(180)
        self._search_debounce.timeout.connect(self._refresh_global_search_results)
        self._search_query_pending = ""
        self._updating_search_box = False

        # Sidebar
        self._sidebar = NavSidebar(self)
        main_layout.addWidget(self._sidebar)

        # Zone droite (header global + pages)
        right = QWidget()
        right.setStyleSheet(f"background: {BG_PRIMARY};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_global_header())
        right_layout.addWidget(self._stack, 1)
        main_layout.addWidget(right, 1)  # stretch=1 : occupe tout l'espace restant

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
        # Déclenché (par défaut 500ms) après le show() pour laisser l'UI se rendre d'abord.
        self._rebuild_thread: AutoRebuildThread | None = None
        delay_ms = SettingsPage.get_rebuild_delay_ms()
        QTimer.singleShot(delay_ms, self._start_auto_rebuild)

    @staticmethod
    def _row_get(row, key: str, idx: int = 0):
        return row_get(row, key, idx)

    @staticmethod
    def _fmt_amount(value) -> str:
        return fmt_amount(value)

    def _build_global_header(self) -> QWidget:
        """Construit le header de recherche globale (AM-01)."""
        header = QFrame()
        if not self._SHOW_GLOBAL_SEARCH:
            header.setVisible(False)
            header.setFixedHeight(0)
            return header

        header.setStyleSheet(
            f"background: {BG_SIDEBAR}; border-bottom: 1px solid {BORDER_SUBTLE};"
        )
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        title = QLabel("Recherche globale")
        title.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: bold;"
        )
        row.addWidget(title)

        self._search_box = QComboBox()
        self._search_box.setEditable(True)
        self._search_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._search_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._search_box.setMinimumWidth(420)
        self._search_box.setMaxVisibleItems(12)
        self._search_box.setStyleSheet(
            f"""
            QComboBox {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                border-radius: 6px;
                padding: 6px 10px;
                min-height: 32px;
            }}
            QComboBox::drop-down {{ border: none; width: 0px; }}
            QComboBox QAbstractItemView {{
                background: {BG_CARD};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_DEFAULT};
                selection-background-color: {BG_ACTIVE};
                outline: 0;
            }}
            """
        )
        self._search_box.activated[int].connect(self._on_global_search_activated)

        line_edit = self._search_box.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText(
                "Personne, compte, actif, transaction…"
            )
            line_edit.setClearButtonEnabled(True)
            line_edit.textEdited.connect(self._on_global_search_text_edited)
            line_edit.returnPressed.connect(self._on_global_search_return_pressed)

        row.addWidget(self._search_box, 1)

        hint = QLabel("Entrée pour ouvrir")
        hint.setStyleSheet(f"color: {TEXT_DARK}; font-size: 11px;")
        row.addWidget(hint)

        return header

    def _on_global_search_text_edited(self, text: str) -> None:
        if self._updating_search_box:
            return

        self._search_query_pending = text.strip()
        if len(self._search_query_pending) < 2:
            self._updating_search_box = True
            self._search_box.blockSignals(True)
            self._search_box.clear()
            self._search_box.setEditText(text)
            self._search_box.blockSignals(False)
            self._updating_search_box = False
            return

        self._search_debounce.start()

    def _refresh_global_search_results(self) -> None:
        query = self._search_query_pending
        if len(query) < 2:
            return

        results = query_global_search(self._conn, query)

        self._updating_search_box = True
        self._search_box.blockSignals(True)
        self._search_box.clear()
        for item in results:
            self._search_box.addItem(item["label"], item)
        self._search_box.setEditText(query)
        self._search_box.blockSignals(False)
        self._updating_search_box = False

        line_edit = self._search_box.lineEdit()
        if line_edit is not None:
            line_edit.setCursorPosition(len(query))

        if results:
            self._search_box.showPopup()

    def _on_global_search_return_pressed(self) -> None:
        query = self._search_box.currentText().strip()
        if len(query) < 2:
            return

        count = self._search_box.count()
        if count == 0:
            results = query_global_search(self._conn, query)
            if not results:
                self._status.showMessage("Aucun résultat.", 3000)
                return
            self._consume_global_search_result(results[0])
            self._clear_global_search()
            return

        idx = self._search_box.currentIndex()
        if idx < 0:
            typed = query.lower()
            idx = 0
            for i in range(count):
                if self._search_box.itemText(i).strip().lower() == typed:
                    idx = i
                    break

        payload = self._search_box.itemData(idx)
        if isinstance(payload, dict):
            self._consume_global_search_result(payload)
            self._clear_global_search()

    def _on_global_search_activated(self, index: int) -> None:
        if index < 0:
            return
        payload = self._search_box.itemData(index)
        if isinstance(payload, dict):
            self._consume_global_search_result(payload)
            self._clear_global_search()

    def _clear_global_search(self) -> None:
        self._updating_search_box = True
        self._search_box.blockSignals(True)
        self._search_box.clear()
        self._search_box.setEditText("")
        self._search_box.blockSignals(False)
        self._updating_search_box = False

    def _consume_global_search_result(self, item: dict) -> None:
        kind = str(item.get("kind", ""))

        if kind == "person":
            person_name = str(item.get("person_name", ""))
            self.show_person(person_name)
            self._status.showMessage(f"Personne sélectionnée : {person_name}", 5000)
            return

        if kind == "account":
            self.show_page("personnes")
            person_id = item.get("person_id")
            account_id = item.get("account_id")
            account_name = str(item.get("account_name", "Compte"))
            ok = False
            if account_id is not None:
                ok = self._page_personnes.select_account_by_id(
                    int(account_id),
                    person_id=int(person_id) if person_id is not None else None,
                )
            if not ok and person_id is not None:
                self._page_personnes.select_person_by_id(int(person_id))
            self._status.showMessage(f"Compte sélectionné : {account_name}", 5000)
            return

        if kind == "asset":
            self.show_page("personnes")
            person_id = item.get("person_id")
            account_id = item.get("account_id")
            symbol = str(item.get("symbol", "Actif"))
            ok = False
            if account_id is not None:
                ok = self._page_personnes.select_account_by_id(
                    int(account_id),
                    person_id=int(person_id) if person_id is not None else None,
                )
            elif person_id is not None:
                self._page_personnes.select_person_by_id(int(person_id))
            if not ok:
                self._page_personnes.select_bourse_tab()
            self._status.showMessage(f"Actif sélectionné : {symbol}", 5000)
            return

        if kind == "transaction":
            self.show_page("personnes")
            person_id = item.get("person_id")
            account_id = item.get("account_id")
            tx_id = item.get("tx_id")
            if account_id is not None:
                self._page_personnes.select_account_by_id(
                    int(account_id),
                    person_id=int(person_id) if person_id is not None else None,
                )
            elif person_id is not None:
                self._page_personnes.select_person_by_id(int(person_id))
            self._status.showMessage(f"Transaction sélectionnée : #{tx_id}", 5000)

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
        did_work = bool(getattr(self._rebuild_thread, "_did_work", False))
        logger.info("AutoRebuild terminé — did_work=%s", did_work)
        self._status.showMessage(
            "✅ Rebuild auto terminé — données à jour." if did_work
            else "✅ Rebuild auto terminé — aucune donnée nouvelle.",
            5000,
        )
        # Rafraîchir la page active seulement si des snapshots ont changé
        if not did_work:
            return
        current = self._stack.currentWidget()
        key = self._key_for_widget(current)
        if key:
            self._refresh_page_if_stale(key, current, force=True)

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
            self._status.showMessage(f"❌ Erreur chargement personnes : {e}")

    def _ensure_page(self, page: str):
        if page == "famille":
            return self._page_famille
        if page == "personnes":
            if self._page_personnes is None:
                self._page_personnes = PersonnesPage(self._conn)
                self._stack.addWidget(self._page_personnes)
            return self._page_personnes
        if page == "import":
            if self._page_import is None:
                self._page_import = ImportPage(self._conn)
                self._stack.addWidget(self._page_import)
            return self._page_import
        if page == "goals_projection":
            if self._page_goals_projection is None:
                self._page_goals_projection = GoalsProjectionPage(self._conn)
                self._stack.addWidget(self._page_goals_projection)
            return self._page_goals_projection
        if page == "settings":
            if self._page_settings is None:
                self._page_settings = SettingsPage(self._conn)
                self._stack.addWidget(self._page_settings)
            return self._page_settings
        return None

    def _key_for_widget(self, widget) -> str | None:
        if widget is self._page_famille:
            return "famille"
        if widget is self._page_personnes:
            return "personnes"
        if widget is self._page_import:
            return "import"
        if widget is self._page_goals_projection:
            return "goals_projection"
        if widget is self._page_settings:
            return "settings"
        return None

    def _refresh_page_if_stale(self, page_key: str, page_widget, *, force: bool = False) -> None:
        if not hasattr(page_widget, "refresh"):
            return
        now = time.monotonic()
        ttl = float(self._page_refresh_ttl_sec.get(page_key, 0.0))
        last = self._last_page_refresh_at.get(page_key, 0.0)
        if not force and ttl > 0 and (now - last) < ttl:
            return
        try:
            page_widget.refresh()
            self._last_page_refresh_at[page_key] = now
        except Exception as exc:
            logger.warning("Refresh page '%s' échoué : %s", page_key, exc)

    def show_page(self, page: str) -> None:
        """Affiche la page demandée."""
        self._sidebar.set_active(page)
        page_widget = self._ensure_page(page)
        if page_widget is None:
            return
        self._stack.setCurrentWidget(page_widget)
        if page in self._page_refresh_ttl_sec:
            self._refresh_page_if_stale(
                page,
                page_widget,
                force=(self._current_page_key is None),
            )
        self._current_page_key = page

    def show_person(self, name: str) -> None:
        """Navigue vers la page Personnes et sélectionne la personne."""
        self._sidebar.set_active("personnes")
        page_widget = self._ensure_page("personnes")
        if page_widget is None:
            return
        self._stack.setCurrentWidget(page_widget)
        self._page_personnes.select_person_by_name(name)

    def closeEvent(self, event) -> None:
        if self._rebuild_thread is not None and self._rebuild_thread.isRunning():
            self._rebuild_thread.cancel()
            self._rebuild_thread.quit()
            self._rebuild_thread.wait()
        super().closeEvent(event)

    def set_status(self, msg: str) -> None:
        self._status.showMessage(msg)
