"""
Widget KpiCard — remplace la fonction _kpi_card() dupliquée dans 5 fichiers ui/*.py.
"""
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from qt_ui.theme import KPI_TONES


class KpiCard(QFrame):
    """Carte KPI avec titre, valeur principale et sous-titre optionnel."""

    def __init__(self, title: str = "", value: str = "", subtitle: str = "",
                 emoji: str = "", tone: str = "neutral", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(140)
        self.setMinimumHeight(90)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._value_label = QLabel()
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        font_val = QFont()
        font_val.setPointSize(15)
        font_val.setBold(True)
        self._value_label.setFont(font_val)

        self._subtitle_label = QLabel()
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._subtitle_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)
        layout.addWidget(self._subtitle_label)
        layout.addStretch()

        self.set_content(title, value, subtitle, emoji, tone)

    def set_content(self, title: str, value: str, subtitle: str = "",
                    emoji: str = "", tone: str = "neutral") -> None:
        bg, fg = KPI_TONES.get(tone, KPI_TONES["neutral"])

        prefix = f"{emoji} " if emoji else ""
        self._title_label.setText(f"{prefix}{title}")
        self._value_label.setText(str(value))
        self._subtitle_label.setText(str(subtitle) if subtitle else "")
        self._subtitle_label.setVisible(bool(subtitle))

        self.setStyleSheet(f"""
            KpiCard {{
                background-color: {bg};
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.06);
            }}
            QLabel {{
                background: transparent;
                color: {fg};
            }}
        """)
        self._title_label.setStyleSheet(f"color: {fg}; opacity: 0.8; font-size: 11px;")
        self._value_label.setStyleSheet(f"color: {fg}; font-size: 15px; font-weight: bold;")
        self._subtitle_label.setStyleSheet(f"color: {fg}; opacity: 0.65; font-size: 11px;")
