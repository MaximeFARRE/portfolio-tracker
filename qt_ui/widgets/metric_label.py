"""
Widget MetricLabel — remplace st.metric() de Streamlit.
Affiche un label de titre + une valeur mise en avant + delta optionnel.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from qt_ui.theme import TEXT_SECONDARY, TEXT_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, BG_CARD
from qt_ui.components.skeleton_handler import SkeletonHandler


class MetricLabel(QWidget):
    """Remplace st.metric(label, value, delta)."""

    def __init__(self, label: str = "", value: str = "", delta: str = "",
                 delta_positive: bool = True, parent=None):
        super().__init__(parent)
        self._loading = False
        self._skeleton_handler = SkeletonHandler(self)
        self._skeleton_handler.updated.connect(self.update)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self._label_lbl = QLabel()
        self._label_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")

        self._value_lbl = QLabel()
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self._value_lbl.setFont(font)
        self._value_lbl.setStyleSheet(f"color: {TEXT_PRIMARY};")

        self._delta_lbl = QLabel()
        self._delta_lbl.setStyleSheet("font-size: 11px;")

        layout.addWidget(self._label_lbl)
        layout.addWidget(self._value_lbl)
        layout.addWidget(self._delta_lbl)

        self.set_content(label, value, delta, delta_positive)

    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        if loading:
            self._skeleton_handler.start()
        else:
            self._skeleton_handler.stop()
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._loading:
            return

        from PyQt6.QtGui import QPainter, QColor, QBrush
        from PyQt6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        alpha = int(self._skeleton_handler.opacity() * 255)
        brush = QBrush(QColor(100, 110, 130, alpha))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)

        # Title rect
        p.drawRoundedRect(QRectF(8, 6, 60, 10), 3, 3)
        # Value rect
        p.drawRoundedRect(QRectF(8, 22, 80, 18), 4, 4)
        # Delta rect
        if self._delta_lbl.isVisible():
            p.drawRoundedRect(QRectF(8, 46, 40, 10), 3, 3)
        p.end()

    def set_content(self, label: str, value: str, delta: str = "",
                    delta_positive: bool = True) -> None:
        self._label_lbl.setText(str(label))
        self._value_lbl.setText(str(value))

        if delta:
            color = COLOR_SUCCESS if delta_positive else COLOR_ERROR
            arrow = "▲" if delta_positive else "▼"
            self._delta_lbl.setText(f"{arrow} {delta}")
            self._delta_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")
            self._delta_lbl.setVisible(True)
        else:
            self._delta_lbl.setVisible(False)
