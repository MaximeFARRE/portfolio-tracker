"""
Widget CollapsibleSection — section accordéon repliable/dépliable.

Usage :
    section = CollapsibleSection("Mon titre", parent=self)
    content = QVBoxLayout()
    content.addWidget(QLabel("Contenu"))
    section.set_content_layout(content)
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame, QPushButton
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, pyqtSignal

from qt_ui.theme import (
    BG_CARD, BORDER_SUBTLE, TEXT_PRIMARY, TEXT_SECONDARY,
    BG_HOVER, ACCENT_BLUE,
)


class CollapsibleSection(QFrame):
    """
    Section accordéon avec titre cliquable et contenu repliable.

    Signaux :
        toggled(bool) — émis quand la section est ouverte (True) ou fermée (False).
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._is_expanded = False
        self._animation: QPropertyAnimation | None = None

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            CollapsibleSection {{
                background: {BG_CARD};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 8px;
            }}
        """)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Bouton titre ──────────────────────────────────────────────────
        self._toggle_btn = QPushButton(f"  ▶  {title}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_PRIMARY};
                border: none;
                text-align: left;
                padding: 12px 16px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {BG_HOVER};
                color: {ACCENT_BLUE};
                border-radius: 8px;
            }}
            QPushButton:checked {{
                color: {ACCENT_BLUE};
            }}
        """)
        self._toggle_btn.clicked.connect(self._on_toggle)
        self._title_text = title
        root_layout.addWidget(self._toggle_btn)

        # ── Container de contenu (caché par défaut) ───────────────────────
        self._content_widget = QWidget()
        self._content_widget.setMaximumHeight(0)
        self._content_widget.setStyleSheet("background: transparent;")
        root_layout.addWidget(self._content_widget)

    def set_content_layout(self, layout: QVBoxLayout) -> None:
        """Définit le layout de contenu de la section."""
        # Supprimer l'ancien layout si existant
        old_layout = self._content_widget.layout()
        if old_layout is not None:
            # Nettoyer l'ancien layout
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.setParent(None)

        layout.setContentsMargins(16, 4, 16, 12)
        self._content_widget.setLayout(layout)

    def is_expanded(self) -> bool:
        """Retourne True si la section est dépliée."""
        return self._is_expanded

    def _on_toggle(self) -> None:
        """Bascule ouvert/fermé avec animation."""
        self._is_expanded = not self._is_expanded
        arrow = "▼" if self._is_expanded else "▶"
        self._toggle_btn.setText(f"  {arrow}  {self._title_text}")

        # Émettre d'abord le signal pour que le contenu soit chargé
        # (chargement lazy) avant de calculer la hauteur cible.
        self.toggled.emit(self._is_expanded)

        if self._is_expanded:
            # On anime vers une valeur très grande : le widget prendra
            # la place dont il a besoin sans être bridé par le maximumHeight.
            start_height = 0
            end_height = 16_000  # QWIDGETSIZE_MAX pratique — jamais atteint réellement
        else:
            start_height = self._content_widget.height()
            end_height = 0

        self._animation = QPropertyAnimation(self._content_widget, b"maximumHeight")
        self._animation.setDuration(280)
        self._animation.setStartValue(start_height)
        self._animation.setEndValue(end_height)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.start()
