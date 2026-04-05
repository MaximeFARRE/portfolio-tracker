"""
SkeletonHandler — Gère l'animation de pulsation pour les squelettes de chargement.
Fournit une valeur d'opacité oscillante (0.3 <-> 0.7) utilisable par les widgets.
"""
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class SkeletonHandler(QObject):
    """
    Gère un timer global ou local pour synchroniser les animations de pulsation.
    Émet un signal à chaque mise à jour de l'opacité.
    """
    updated = pyqtSignal(float)

    def __init__(self, parent=None, interval: int = 30):
        super().__init__(parent)
        self._opacity = 0.4
        self._direction = 1
        self._timer = QTimer(self)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def opacity(self) -> float:
        return self._opacity

    def _tick(self) -> None:
        # Oscillation douce entre 0.3 et 0.7
        step = 0.02 * self._direction
        self._opacity += step
        if self._opacity >= 0.7:
            self._opacity = 0.7
            self._direction = -1
        elif self._opacity <= 0.3:
            self._opacity = 0.3
            self._direction = 1
        self.updated.emit(self._opacity)
