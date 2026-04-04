"""
LoadingOverlay — spinner semi-transparent superposé au panel pendant le chargement.

Usage :
    class MyPanel(QWidget):
        def __init__(self, ...):
            ...
            self._overlay = LoadingOverlay(self)   # passe le panel comme parent

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._overlay.resize(self.size())       # suit le redimensionnement

        def _load_data(self):
            self._overlay.start("Chargement des données…")
            try:
                ...
            except ...:
                ...
            finally:
                self._overlay.stop()
"""
import math
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsBlurEffect
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont


class _SpinnerWidget(QWidget):
    """Petit widget qui dessine un arc rotatif (spinner)."""

    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self._size = size
        self._angle = 0
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.setInterval(30)          # ~33 fps
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = self._size
        pen_width = 3  # Plus fin pour un look moderne

        # Arc de fond (gris discret)
        p.setPen(QPen(QColor(80, 90, 110, 40), pen_width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        margin = pen_width // 2 + 4
        rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
        p.drawArc(rect, 0, 360 * 16)

        # Arc animé (bleu accent)
        gradient_color = QColor(96, 165, 250)   # ACCENT_BLUE #60a5fa
        p.setPen(QPen(gradient_color, pen_width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        # Animation plus fluide
        start_angle = int(-self._angle * 16)
        span_angle  = int(90 * 16)  # Arc plus court (90° au lieu de 270°)
        p.drawArc(rect, start_angle, span_angle)
        p.end()


class LoadingOverlay(QWidget):
    """
    Overlay semi-transparent avec spinner animé et texte optionnel.
    Doit être enfant du widget qu'il recouvre.

    Appeler resize(parent.size()) dans resizeEvent() du parent
    pour que l'overlay suive le redimensionnement.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("LoadingOverlay")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        self._spinner = _SpinnerWidget(size=52, parent=self)
        layout.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(11)
        self._label.setFont(font)
        self._label.setStyleSheet("color: #94a3b8; background: transparent;")
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Fond semi-transparent
        self.setStyleSheet("""
            #LoadingOverlay {
                background-color: rgba(14, 17, 23, 140);
                border-radius: 8px;
            }
        """)

        self._blur_effect = QGraphicsBlurEffect()
        self._blur_effect.setBlurRadius(10)
        self._blur_enabled = True

        self.hide()

    # ── API publique ──────────────────────────────────────────────────────

    def start(self, text: str = "Chargement…", blur: bool = True) -> None:
        """Affiche l'overlay et démarre l'animation."""
        self._label.setText(text)
        self._label.setVisible(bool(text))
        
        parent = self.parentWidget()
        if parent:
            self.resize(parent.size())
            if blur:
                parent.setGraphicsEffect(self._blur_effect)
        
        self.raise_()
        self.show()
        self._spinner.start()

    def stop(self) -> None:
        """Masque l'overlay et arrête l'animation."""
        self._spinner.stop()
        parent = self.parentWidget()
        if parent:
            parent.setGraphicsEffect(None)
        self.hide()
