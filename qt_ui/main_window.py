"""
Fenêtre principale de l'application Patrimoine.
Contient la barre de navigation latérale + le QStackedWidget central.
"""
import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFrame, QSizePolicy, QStatusBar,
    QComboBox
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon

from qt_ui.pages.famille_page import FamillePage
from qt_ui.pages.personnes_page import PersonnesPage
from qt_ui.pages.import_page import ImportPage
from qt_ui.pages.goals_projection_page import GoalsProjectionPage
from qt_ui.pages.settings_page import SettingsPage
from qt_ui.theme import (
    BG_PRIMARY, BG_SIDEBAR, BG_CARD, BG_HOVER, BG_ACTIVE, BORDER_SUBTLE, BORDER_DEFAULT,
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
        # Déclenché 500ms après le show() pour laisser l'UI se rendre d'abord.
        self._rebuild_thread: AutoRebuildThread | None = None
        QTimer.singleShot(500, self._start_auto_rebuild)

    @staticmethod
    def _row_get(row, key: str, idx: int = 0):
        if row is None:
            return None
        try:
            return row[key]
        except Exception:
            return row[idx]

    @staticmethod
    def _fmt_amount(value) -> str:
        try:
            num = float(value or 0.0)
        except Exception:
            num = 0.0
        return f"{num:,.2f}".replace(",", " ")

    def _build_global_header(self) -> QWidget:
        """Construit le header de recherche globale (AM-01)."""
        header = QFrame()
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

        results = self._query_global_search(query)

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

    def _query_global_search(self, query: str, limit_per_kind: int = 7) -> list[dict]:
        """Recherche rapide multi-objets : personnes, comptes, actifs, transactions."""
        q = query.strip().lower()
        if not q:
            return []

        like = f"%{q}%"
        results: list[dict] = []

        try:
            rows = self._conn.execute(
                """
                SELECT id, name
                FROM people
                WHERE lower(name) LIKE ?
                ORDER BY name
                LIMIT ?;
                """,
                (like, limit_per_kind),
            ).fetchall()
            for row in rows:
                name = str(self._row_get(row, "name", 1))
                results.append(
                    {
                        "kind": "person",
                        "person_id": int(self._row_get(row, "id", 0)),
                        "person_name": name,
                        "label": f"👤 Personne · {name}",
                    }
                )
        except Exception as exc:
            logger.warning("Recherche globale (people) en erreur : %s", exc)

        try:
            rows = self._conn.execute(
                """
                SELECT a.id, a.name, a.account_type,
                       p.id AS person_id, p.name AS person_name
                FROM accounts a
                JOIN people p ON p.id = a.person_id
                WHERE lower(a.name) LIKE ?
                   OR lower(COALESCE(a.institution, '')) LIKE ?
                   OR lower(p.name) LIKE ?
                ORDER BY p.name, a.name
                LIMIT ?;
                """,
                (like, like, like, limit_per_kind),
            ).fetchall()
            for row in rows:
                person_name = str(self._row_get(row, "person_name", 4))
                account_name = str(self._row_get(row, "name", 1))
                results.append(
                    {
                        "kind": "account",
                        "account_id": int(self._row_get(row, "id", 0)),
                        "account_name": account_name,
                        "account_type": str(self._row_get(row, "account_type", 2)),
                        "person_id": int(self._row_get(row, "person_id", 3)),
                        "person_name": person_name,
                        "label": f"🏦 Compte · {account_name} ({person_name})",
                    }
                )
        except Exception as exc:
            logger.warning("Recherche globale (accounts) en erreur : %s", exc)

        try:
            rows = self._conn.execute(
                """
                SELECT a.id, a.symbol, a.name, a.asset_type,
                       (
                         SELECT t.person_id FROM transactions t
                         WHERE t.asset_id = a.id
                         ORDER BY t.date DESC, t.id DESC
                         LIMIT 1
                       ) AS person_id,
                       (
                         SELECT p.name FROM transactions t
                         JOIN people p ON p.id = t.person_id
                         WHERE t.asset_id = a.id
                         ORDER BY t.date DESC, t.id DESC
                         LIMIT 1
                       ) AS person_name,
                       (
                         SELECT t.account_id FROM transactions t
                         WHERE t.asset_id = a.id
                         ORDER BY t.date DESC, t.id DESC
                         LIMIT 1
                       ) AS account_id,
                       (
                         SELECT acc.name FROM transactions t
                         JOIN accounts acc ON acc.id = t.account_id
                         WHERE t.asset_id = a.id
                         ORDER BY t.date DESC, t.id DESC
                         LIMIT 1
                       ) AS account_name
                FROM assets a
                WHERE lower(a.symbol) LIKE ?
                   OR lower(COALESCE(a.name, '')) LIKE ?
                ORDER BY a.symbol
                LIMIT ?;
                """,
                (like, like, limit_per_kind),
            ).fetchall()
            for row in rows:
                symbol = str(self._row_get(row, "symbol", 1))
                asset_name = str(self._row_get(row, "name", 2) or symbol)
                person_name = self._row_get(row, "person_name", 5)
                context = f" ({person_name})" if person_name else ""
                payload = {
                    "kind": "asset",
                    "asset_id": int(self._row_get(row, "id", 0)),
                    "symbol": symbol,
                    "asset_name": asset_name,
                    "asset_type": str(self._row_get(row, "asset_type", 3) or ""),
                    "person_id": self._row_get(row, "person_id", 4),
                    "person_name": person_name,
                    "account_id": self._row_get(row, "account_id", 6),
                    "account_name": self._row_get(row, "account_name", 7),
                    "label": f"📈 Actif · {symbol} — {asset_name}{context}",
                }
                results.append(payload)
        except Exception as exc:
            logger.warning("Recherche globale (assets) en erreur : %s", exc)

        try:
            rows = self._conn.execute(
                """
                SELECT t.id, t.date, t.type, t.amount,
                       p.id AS person_id, p.name AS person_name,
                       acc.id AS account_id, acc.name AS account_name,
                       COALESCE(a.symbol, '') AS asset_symbol
                FROM transactions t
                JOIN people p ON p.id = t.person_id
                JOIN accounts acc ON acc.id = t.account_id
                LEFT JOIN assets a ON a.id = t.asset_id
                WHERE lower(p.name) LIKE ?
                   OR lower(acc.name) LIKE ?
                   OR lower(t.type) LIKE ?
                   OR lower(COALESCE(t.category, '')) LIKE ?
                   OR lower(COALESCE(t.note, '')) LIKE ?
                   OR lower(COALESCE(a.symbol, '')) LIKE ?
                   OR CAST(t.id AS TEXT) LIKE ?
                ORDER BY t.date DESC, t.id DESC
                LIMIT ?;
                """,
                (like, like, like, like, like, like, like, limit_per_kind),
            ).fetchall()
            for row in rows:
                tx_id = int(self._row_get(row, "id", 0))
                date = str(self._row_get(row, "date", 1))
                tx_type = str(self._row_get(row, "type", 2))
                amount = self._fmt_amount(self._row_get(row, "amount", 3))
                person_name = str(self._row_get(row, "person_name", 5))
                account_name = str(self._row_get(row, "account_name", 7))
                asset_symbol = str(self._row_get(row, "asset_symbol", 8) or "")
                suffix = f" · {asset_symbol}" if asset_symbol else ""
                results.append(
                    {
                        "kind": "transaction",
                        "tx_id": tx_id,
                        "date": date,
                        "tx_type": tx_type,
                        "amount": amount,
                        "person_id": int(self._row_get(row, "person_id", 4)),
                        "person_name": person_name,
                        "account_id": int(self._row_get(row, "account_id", 6)),
                        "account_name": account_name,
                        "label": (
                            f"🧾 Transaction #{tx_id} · {date} · {tx_type} · "
                            f"{amount} € ({person_name}/{account_name}){suffix}"
                        ),
                    }
                )
        except Exception as exc:
            logger.warning("Recherche globale (transactions) en erreur : %s", exc)

        return results[:32]

    def _on_global_search_return_pressed(self) -> None:
        query = self._search_box.currentText().strip()
        if len(query) < 2:
            return

        count = self._search_box.count()
        if count == 0:
            results = self._query_global_search(query, limit_per_kind=7)
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
