"""
Widget QTableView avec modèle Pandas.
Remplace st.dataframe() et st.data_editor() de Streamlit.
"""
import pandas as pd
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt6.QtWidgets import (
    QTableView, QWidget, QVBoxLayout, QHBoxLayout, QAbstractItemView,
    QHeaderView, QLineEdit, QLabel,
)
from PyQt6.QtGui import QColor

from qt_ui.theme import BG_CARD, BG_CARD_ALT, STYLE_TABLE, STYLE_INPUT


class PandasTableModel(QAbstractTableModel):
    """Modèle Qt pour afficher un DataFrame pandas dans un QTableView."""

    def __init__(self, df: pd.DataFrame = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

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
            return QColor("#e0e0e0")

        return None

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

    def get_dataframe(self) -> pd.DataFrame:
        return self._df.copy()


class DataTableWidget(QWidget):
    """Widget complet : tableau + en-têtes stylisés + barre de recherche."""

    def __init__(self, parent=None, editable: bool = False, searchable: bool = True):
        super().__init__(parent)
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

        layout.addWidget(self._view)

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self._full_df = df if df is not None else pd.DataFrame()
        self._search_bar.clear()
        self._model.set_dataframe(self._full_df)
        self._view.resizeColumnsToContents()

    def get_dataframe(self) -> pd.DataFrame:
        return self._model.get_dataframe()

    def _on_filter_changed(self, text: str) -> None:
        if not text.strip() or self._full_df.empty:
            self._model.set_dataframe(self._full_df)
            return
        query = text.strip().lower()
        mask = self._full_df.apply(
            lambda row: any(query in str(v).lower() for v in row), axis=1
        )
        self._model.set_dataframe(self._full_df[mask].reset_index(drop=True))
