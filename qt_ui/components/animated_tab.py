from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabBar, QSizePolicy
from PyQt6.QtGui import QIcon
from qt_ui.components.animated_stack import AnimatedStackedWidget

class AnimatedTabWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        
        self._tab_bar = QTabBar()
        self._tab_bar.setDrawBase(False)
        self._tab_bar.setExpanding(False)
        
        self._stack = AnimatedStackedWidget()
        
        self._layout.addWidget(self._tab_bar)
        self._layout.addWidget(self._stack, 1)
        
        # Signaux
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self.currentChanged = self._tab_bar.currentChanged # Signal proxy

    def _on_tab_changed(self, index: int):
        self._stack.setCurrentIndex(index)

    def addTab(self, widget: QWidget, label: str, icon: QIcon = None) -> int:
        if icon:
            idx = self._tab_bar.addTab(icon, label)
        else:
            idx = self._tab_bar.addTab(label)
        self._stack.addWidget(widget)
        return idx

    def insertTab(self, index: int, widget: QWidget, label: str, icon: QIcon = None) -> int:
        if icon:
            idx = self._tab_bar.insertTab(index, icon, label)
        else:
            idx = self._tab_bar.insertTab(index, label)
        self._stack.insertWidget(index, widget)
        return idx
    
    def setTabIcon(self, index: int, icon: QIcon):
        self._tab_bar.setTabIcon(index, icon)

    def removeTab(self, index: int):
        self._tab_bar.removeTab(index)
        widget = self._stack.widget(index)
        if widget:
            self._stack.removeWidget(widget)

    def clear(self):
        self._tab_bar.clear()
        while self._stack.count() > 0:
            w = self._stack.widget(0)
            self._stack.removeWidget(w)

    def count(self) -> int:
        return self._tab_bar.count()

    def currentIndex(self) -> int:
        return self._tab_bar.currentIndex()

    def setCurrentIndex(self, index: int):
        self._tab_bar.setCurrentIndex(index)
        self._stack.setCurrentIndex(index)

    def widget(self, index: int) -> QWidget:
        return self._stack.widget(index)

    def setTabEnabled(self, index: int, enabled: bool):
        self._tab_bar.setTabEnabled(index, enabled)

    def setTabText(self, index: int, text: str):
        self._tab_bar.setTabText(index, text)
        
    def tabText(self, index: int) -> str:
        return self._tab_bar.tabText(index)

    def setStyleSheet(self, style: str):
        # On applique le style à la TabBar et au Stack.
        # Pour simuler QTabWidget::pane, on cible le stack directement.
        super().setStyleSheet(style)
        self._tab_bar.setStyleSheet(style)
        
        # Adaptation du style pour le stack (le pane de QTabWidget)
        # Si STYLE_TAB contient QTabWidget::pane, on le transforme en AnimatedStackedWidget
        pane_style = style.replace("QTabWidget::pane", "AnimatedStackedWidget")
        self._stack.setStyleSheet(pane_style)
