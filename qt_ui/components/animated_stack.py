"""
Composant AnimatedStackedWidget pour PyQt6.
Fournit une transition avec glissement (slide) et fondu (fade-in).
"""
import logging
from PyQt6.QtWidgets import QStackedWidget, QWidget, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QPoint

logger = logging.getLogger(__name__)

class AnimatedStackedWidget(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 350
        self._easing = QEasingCurve.Type.OutQuart
        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.finished.connect(self._on_animation_finished)
        
        self._current_index = 0
        self._next_index = 0
        self._is_animating = False

    def set_duration(self, ms: int):
        self._duration = ms

    def set_easing(self, easing: QEasingCurve.Type):
        self._easing = easing

    def setCurrentIndex(self, index: int):
        if self._is_animating or index == self.currentIndex():
            return

        self._current_index = self.currentIndex()
        self._next_index = index
        
        # Déterminer la direction (droite vers gauche si on avance, gauche vers droite si on recule)
        # Mais pour une navigation sidebar, "suivante" est souvent vers la droite.
        # Règle simple : index plus grand = slide vers la gauche (le nouveau vient de la droite)
        direction = 1 if index > self._current_index else -1
        self._animate_transition(direction)

    def setCurrentWidget(self, widget: QWidget):
        index = self.indexOf(widget)
        if index >= 0:
            self.setCurrentIndex(index)

    def _animate_transition(self, direction: int):
        self._is_animating = True
        
        current_widget = self.widget(self._current_index)
        next_widget = self.widget(self._next_index)
        
        if not next_widget or not current_widget:
            super().setCurrentIndex(self._next_index)
            self._is_animating = False
            return
            
        width = self.width()
        
        # Préparer le prochain widget
        next_widget.setGeometry(0, 0, self.width(), self.height())
        next_widget.raise_()
        next_widget.show()
        
        # Position de départ du prochain widget (à l'extérieur)
        start_pos = QPoint(width * direction, 0)
        next_widget.move(start_pos)
        
        # Animation de position pour le prochain widget
        pos_anim_next = QPropertyAnimation(next_widget, b"pos")
        pos_anim_next.setDuration(self._duration)
        pos_anim_next.setStartValue(start_pos)
        pos_anim_next.setEndValue(QPoint(0, 0))
        pos_anim_next.setEasingCurve(self._easing)

        # Animation d'opacité pour le prochain widget
        opacity_effect_next = QGraphicsOpacityEffect(next_widget)
        next_widget.setGraphicsEffect(opacity_effect_next)

        opacity_anim_next = QPropertyAnimation(opacity_effect_next, b"opacity")
        opacity_anim_next.setDuration(self._duration)
        opacity_anim_next.setStartValue(0.0)
        opacity_anim_next.setEndValue(1.0)
        opacity_anim_next.setEasingCurve(self._easing)

        # Animation de position pour le widget actuel (il sort)
        pos_anim_curr = QPropertyAnimation(current_widget, b"pos")
        pos_anim_curr.setDuration(self._duration)
        pos_anim_curr.setStartValue(QPoint(0, 0))
        pos_anim_curr.setEndValue(QPoint(int(-width * direction * 0.3), 0)) # Sortie partielle pour effet de parallaxe
        pos_anim_curr.setEasingCurve(self._easing)

        # Animation d'opacité pour le widget actuel
        opacity_effect_curr = QGraphicsOpacityEffect(current_widget)
        current_widget.setGraphicsEffect(opacity_effect_curr)

        opacity_anim_curr = QPropertyAnimation(opacity_effect_curr, b"opacity")
        opacity_anim_curr.setDuration(int(self._duration * 0.8)) # Disparaît un peu plus vite
        opacity_anim_curr.setStartValue(1.0)
        opacity_anim_curr.setEndValue(0.0)
        opacity_anim_curr.setEasingCurve(self._easing)

        # Groupe d'animations
        self._animation_group.clear()
        self._animation_group.addAnimation(pos_anim_next)
        self._animation_group.addAnimation(opacity_anim_next)
        self._animation_group.addAnimation(pos_anim_curr)
        self._animation_group.addAnimation(opacity_anim_curr)
        
        self._animation_group.start()

    def _on_animation_finished(self):
        # Finaliser le changement d'index (sans animation cette fois via super)
        super().setCurrentIndex(self._next_index)

        # Supprimer les animations d'abord (elles référencent les effets d'opacité)
        # avant de supprimer les effets eux-mêmes pour éviter les dangling pointers
        self._animation_group.clear()

        # Nettoyer les effets et positions
        current_widget = self.widget(self._current_index)
        next_widget = self.widget(self._next_index)

        if current_widget:
            current_widget.setGraphicsEffect(None)
            current_widget.move(0, 0)
        if next_widget:
            next_widget.setGraphicsEffect(None)
            next_widget.move(0, 0)

        self._is_animating = False
        
    def resizeEvent(self, event):
        # S'assurer que les widgets gardent la bonne taille lors du redimensionnement pendant l'anim
        if self._is_animating:
            current_widget = self.widget(self._current_index)
            next_widget = self.widget(self._next_index)
            if current_widget:
                current_widget.resize(self.width(), self.height())
            if next_widget:
                next_widget.resize(self.width(), self.height())
        super().resizeEvent(event)
