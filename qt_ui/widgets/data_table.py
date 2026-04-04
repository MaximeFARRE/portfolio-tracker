"""
Widget QTableView avec modèle Pandas.
Remplace st.dataframe() et st.data_editor() de Streamlit.
"""
import pandas as pd
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, pyqtSignal
from PyQt6.QtWidgets import (
    QTableView, QWidget, QVBoxLayout, QHBoxLayout, QAbstractItemView,
    QHeaderView, QLineEdit, QLabel, QStyledItemDelegate, QComboBox,
)
from PyQt6.QtGui import QColor, QPainter, QBrush
from qt_ui.components.skeleton_handler import SkeletonHandler

from qt_ui.theme import BG_CARD, BG_CARD_ALT, STYLE_TABLE, STYLE_INPUT


class PandasTableModel(QAbstractTableModel):
    """Modèle Qt pour afficher un DataFrame pandas dans un QTableView."""

    def __init__(self, df: pd.DataFrame = None, column_colors: dict = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        # column_colors: dict[str, callable(value) -> hex_str | None]
        self._column_colors: dict = column_colors or {}
        self._editable_cols: set = set()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._df.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self._df.iloc[index.row(), index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            if pd.isna(value):
                return ""
            if isinstance(value, float):
                return f"{value:,.2f}"
            return str(value)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if isinstance(value, (int, float)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() % 2 == 0:
                return QColor(BG_CARD)
            return QColor(BG_CARD_ALT)

        if role == Qt.ItemDataRole.ForegroundRole:
            col_name = self._df.columns[index.column()]
            if col_name in self._column_colors:
                try:
                    color = self._column_colors[col_name](self._df.iloc[index.row(), index.column()])
                    if color:
                        return QColor(color)
                except Exception:
                    pass
            return QColor("#e0e0e0")

        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.EditRole and index.isValid():
            self._df.iloc[index.row(), index.column()] = value
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsEnabled
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._df.columns[index.column()] in self._editable_cols:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df if df is not None else pd.DataFrame()
        self.endResetModel()

    def set_column_colors(self, column_colors: dict) -> None:
        self._column_colors = column_colors or {}
        if not self._df.empty:
            self.layoutChanged.emit()

    def set_editable_cols(self, cols: set) -> None:
        self._editable_cols = cols or set()

    def get_dataframe(self) -> pd.DataFrame:
        return self._df.copy()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        """Trie le DataFrame selon la colonne cliquée."""
        if self._df.empty:
            return
        self.layoutAboutToBeChanged.emit()
        col_name = self._df.columns[column]
        ascending = (order == Qt.SortOrder.AscendingOrder)
        
        # On utilise inplace=True pour trier les données réelles
        # kind='mergesort' est stable et performant sur petits jeux
        try:
            self._df.sort_values(by=col_name, ascending=ascending, inplace=True, kind='mergesort')
            self._df.reset_index(drop=True, inplace=True)
        except Exception:
            pass # Parfois le tri échoue sur des types mixtes/objets
            
        self.layoutChanged.emit()


class ComboBoxDelegate(QStyledItemDelegate):
    """Délégué affichant un QComboBox pour les cellules éditables."""

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self._items = list(items)

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(self._items)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if value in self._items:
            editor.setCurrentText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class DataTableWidget(QWidget):
    """Widget complet : tableau + en-têtes stylisés + barre de recherche."""

    # Émis quand une cellule éditable est modifiée : (row_in_model, col_name, new_value)
    cell_changed = pyqtSignal(int, str, object)

    def __init__(self, parent=None, editable: bool = False, searchable: bool = True):
        super().__init__(parent)
        self._loading = False
        self._skeleton_handler = SkeletonHandler(self)
        self._skeleton_handler.updated.connect(self._view.viewport().update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Barre de recherche
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("🔍  Filtrer...")
        self._search_bar.setStyleSheet(STYLE_INPUT + " max-height: 28px;")
        self._search_bar.textChanged.connect(self._on_filter_changed)
        self._search_bar.setClearButtonEnabled(True)
        if searchable:
            layout.addWidget(self._search_bar)
        else:
            self._search_bar.hide()

        self._full_df: pd.DataFrame = pd.DataFrame()
        self._model = PandasTableModel()
        self._view = QTableView()
        self._view.setModel(self._model)

        # Style
        self._view.setStyleSheet(STYLE_TABLE)

        self._view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._view.horizontalHeader().setStretchLastSection(True)
        self._view.verticalHeader().setVisible(False)
        self._view.setAlternatingRowColors(False)
        self._view.setSortingEnabled(True)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        if editable:
            self._view.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        else:
            self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Mapping colonne → items pour les delegates ComboBox (persistant entre set_dataframe)
        self._combo_delegates: dict = {}  # col_name -> [items]
        # Colonnes à masquer visuellement
        self._hidden_cols: set = set()

        # Propager les modifications de cellule éditable
        self._model.dataChanged.connect(self._on_model_data_changed)

        layout.addWidget(self._view)

    def set_loading(self, loading: bool) -> None:
        """Active ou désactive le mode skeleton."""
        self._loading = loading
        if loading:
            self._skeleton_handler.start()
            # On vide temporairement le modèle ou on affiche des lignes fantômes
            self._model.set_dataframe(pd.DataFrame({"Loading...": [""] * 5}))
        else:
            self._skeleton_handler.stop()
        self._view.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._loading:
            return

        # On dessine les skeletons par-dessus le viewport de la table
        # Note: PaintEvent d'un QWidget parent ne dessine pas sur les enfants complexes.
        # Il est préférable d'utiliser un overlay ou de modifier le modèle.
        # Ici je vais utiliser le PaintEvent du viewport via un délégué ou simplement
        # dessiner des barres grises si le modèle est en mode "Loading".
        pass

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self._full_df = df if df is not None else pd.DataFrame()
        self._search_bar.clear()
        self._model.set_dataframe(self._full_df)
        self._view.resizeColumnsToContents()
        self._apply_delegates()
        self._apply_hidden_cols()

    def get_dataframe(self) -> pd.DataFrame:
        return self._model.get_dataframe()

    def set_column_colors(self, column_colors: dict) -> None:
        """Définit des fonctions de couleur par colonne. Ex: {"PnL (€)": lambda v: "#4ade80" if v >= 0 else "#f87171"}"""
        self._model.set_column_colors(column_colors)

    def set_combo_delegate(self, col_name: str, items: list) -> None:
        """Rend une colonne éditable via une liste déroulante. Persistant entre les set_dataframe()."""
        self._combo_delegates[col_name] = list(items)
        self._model.set_editable_cols(self._model._editable_cols | {col_name})
        self._view.setEditTriggers(
            self._view.editTriggers() | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self._apply_delegates()

    def hide_column(self, col_name: str) -> None:
        """Masque une colonne par son nom (elle reste dans le DataFrame sous-jacent)."""
        self._hidden_cols.add(col_name)
        self._apply_hidden_cols()

    def _apply_delegates(self) -> None:
        df = self._model.get_dataframe()
        if df.empty:
            return
        cols = list(df.columns)
        for col_name, items in self._combo_delegates.items():
            if col_name in cols:
                col_idx = cols.index(col_name)
                delegate = ComboBoxDelegate(items, self._view)
                self._view.setItemDelegateForColumn(col_idx, delegate)

    def _apply_hidden_cols(self) -> None:
        df = self._model.get_dataframe()
        if df.empty:
            return
        cols = list(df.columns)
        for col_name in self._hidden_cols:
            if col_name in cols:
                col_idx = cols.index(col_name)
                self._view.setColumnHidden(col_idx, True)

    def _on_model_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles) -> None:
        if Qt.ItemDataRole.EditRole in (roles or []):
            row = top_left.row()
            col = top_left.column()
            df = self._model.get_dataframe()
            if row < len(df) and col < len(df.columns):
                col_name = df.columns[col]
                new_value = df.iloc[row, col]
                self.cell_changed.emit(row, col_name, new_value)

    def _on_filter_changed(self, text: str) -> None:
        if not text.strip() or self._full_df.empty:
            self._model.set_dataframe(self._full_df)
            self._apply_delegates()
            self._apply_hidden_cols()
            return
        query = text.strip().lower()
        mask = self._full_df.apply(
            lambda row: any(query in str(v).lower() for v in row), axis=1
        )
        self._model.set_dataframe(self._full_df[mask].reset_index(drop=True))
        self._apply_delegates()
        self._apply_hidden_cols()
