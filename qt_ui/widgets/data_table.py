"""
Widget QTableView avec modèle Pandas.
Remplace st.dataframe() et st.data_editor() de Streamlit.

AM-12 : FilterBar avec filtres combo / date_range / number_range
AM-13 : Tri amélioré via PandasTableModel.sort() + indicateur visuel
"""
import pandas as pd
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, pyqtSignal, QDate, QTimer
from PyQt6.QtWidgets import (
    QTableView, QWidget, QVBoxLayout, QHBoxLayout, QAbstractItemView,
    QHeaderView, QLineEdit, QLabel, QStyledItemDelegate, QComboBox,
    QDoubleSpinBox, QDateEdit, QPushButton, QSizePolicy, QFrame,
)
from PyQt6.QtGui import QColor, QPainter, QBrush
from qt_ui.components.skeleton_handler import SkeletonHandler

from qt_ui.theme import (
    BG_CARD, BG_CARD_ALT, STYLE_TABLE, STYLE_INPUT,
    STYLE_INPUT_FOCUS, TEXT_MUTED, BORDER_DEFAULT, BG_HOVER,
    ACCENT_BLUE, TEXT_SECONDARY,
)


# ─── Modèle Pandas ─────────────────────────────────────────────────────────────

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
        try:
            self._df.sort_values(by=col_name, ascending=ascending, inplace=True, kind='mergesort')
            self._df.reset_index(drop=True, inplace=True)
        except Exception:
            pass  # Parfois le tri échoue sur des types mixtes/objets
        self.layoutChanged.emit()


# ─── Delegate ComboBox ─────────────────────────────────────────────────────────

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


# ─── FilterBar ─────────────────────────────────────────────────────────────────

_STYLE_FILTER_COMBO = f"""
    QComboBox {{
        background: {BG_CARD}; color: {TEXT_SECONDARY};
        border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
        padding: 4px 8px; font-size: 13px; min-width: 130px;
    }}
    QComboBox:focus {{ border: 1px solid {ACCENT_BLUE}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: #1e2538;
        color: #e2e8f0;
        border: 1px solid {BORDER_DEFAULT};
        border-radius: 4px;
        padding: 4px;
        min-width: 200px;
        font-size: 13px;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 12px;
        min-height: 28px;
        border-radius: 3px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {ACCENT_BLUE};
        color: white;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: {ACCENT_BLUE};
        color: white;
    }}
"""

_STYLE_FILTER_SPIN = f"""
    QDoubleSpinBox {{
        background: {BG_CARD}; color: {TEXT_SECONDARY};
        border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
        padding: 2px 4px; font-size: 12px; min-width: 80px;
    }}
    QDoubleSpinBox:focus {{ border: 1px solid {ACCENT_BLUE}; }}
"""

_STYLE_FILTER_DATE = f"""
    QDateEdit {{
        background: {BG_CARD}; color: {TEXT_SECONDARY};
        border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
        padding: 2px 4px; font-size: 12px; min-width: 95px;
    }}
    QDateEdit:focus {{ border: 1px solid {ACCENT_BLUE}; }}
    QDateEdit::drop-down {{ border: none; }}
"""

_STYLE_FILTER_LABEL = f"color: {TEXT_MUTED}; font-size: 11px;"

_STYLE_RESET_BTN = f"""
    QPushButton {{
        background: transparent; color: {TEXT_MUTED};
        border: 1px solid {BORDER_DEFAULT}; border-radius: 4px;
        padding: 2px 8px; font-size: 11px;
    }}
    QPushButton:hover {{ background: {BG_HOVER}; color: white; }}
"""

_STYLE_FILTERBAR = f"""
    QWidget#filterBar {{
        background: rgba(26, 31, 46, 0.7);
        border: 1px solid {BORDER_DEFAULT};
        border-radius: 6px;
    }}
"""


class FilterBar(QWidget):
    """
    Barre de filtres avancés, configurable via set_config().

    Chaque filtre est un dict :
        {"col": "date",   "kind": "date_range",   "label": "Du/Au"}
        {"col": "type",   "kind": "combo",         "label": "Type"}
        {"col": "amount", "kind": "number_range",  "label": "Min/Max"}
    """

    filters_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filterBar")
        self.setStyleSheet(_STYLE_FILTERBAR)

        self._config: list[dict] = []
        # Widgets de filtres enregistrés : col -> widget(s)
        self._filter_widgets: dict = {}

        # Layout principal vertical (2 lignes)
        self._main_v = QVBoxLayout(self)
        self._main_v.setContentsMargins(8, 6, 8, 6)
        self._main_v.setSpacing(4)

        # Ligne 1 : recherche texte + combos + bouton reset
        self._row1 = QHBoxLayout()
        self._row1.setSpacing(8)

        # Recherche texte (toujours présente)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Recherche...")
        self._search.setStyleSheet(STYLE_INPUT + " max-height: 24px; font-size: 12px;")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.filters_changed)
        self._row1.addWidget(self._search, stretch=2)

        self._main_v.addLayout(self._row1)

        # Ligne 2 : date_range + number_range
        self._row2 = QHBoxLayout()
        self._row2.setSpacing(8)
        self._row2_used = False
        self._main_v.addLayout(self._row2)

        # Bouton reset (sera ajouté à row1 à la fin)
        self._btn_reset = QPushButton("✕  Reset")
        self._btn_reset.setStyleSheet(_STYLE_RESET_BTN)
        self._btn_reset.setFixedHeight(24)
        self._btn_reset.clicked.connect(self._reset_all)

    def set_config(self, config: list[dict]) -> None:
        """Configure les filtres. Appelé une seule fois après construction."""
        self._config = config

        # Vider row1 (sauf la search bar) et row2
        while self._row1.count() > 1:
            item = self._row1.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        while self._row2.count():
            item = self._row2.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._filter_widgets.clear()
        self._row2_used = False

        for cfg in config:
            kind = cfg.get("kind", "combo")
            col = cfg.get("col", "")
            label = cfg.get("label", col.capitalize())

            if kind == "combo":
                lbl = QLabel(f"{label} :")
                lbl.setStyleSheet(_STYLE_FILTER_LABEL)
                combo = QComboBox()
                combo.setStyleSheet(_STYLE_FILTER_COMBO)
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
                combo.view().setMinimumWidth(200)
                combo.addItem("Tous")
                combo.currentTextChanged.connect(self.filters_changed)
                self._row1.addWidget(lbl)
                self._row1.addWidget(combo)
                self._filter_widgets[col] = combo

            elif kind == "date_range":
                self._row2_used = True
                lbl_du = QLabel(f"{label} — Du :")
                lbl_du.setStyleSheet(_STYLE_FILTER_LABEL)
                date_from = QDateEdit()
                date_from.setCalendarPopup(True)
                date_from.setDisplayFormat("dd/MM/yyyy")
                date_from.setStyleSheet(_STYLE_FILTER_DATE)
                date_from.setSpecialValueText("—")  # Valeur nulle = pas de filtre
                date_from.setDate(QDate(2000, 1, 1))
                date_from.dateChanged.connect(self.filters_changed)

                lbl_au = QLabel("Au :")
                lbl_au.setStyleSheet(_STYLE_FILTER_LABEL)
                date_to = QDateEdit()
                date_to.setCalendarPopup(True)
                date_to.setDisplayFormat("dd/MM/yyyy")
                date_to.setStyleSheet(_STYLE_FILTER_DATE)
                date_to.setDate(QDate.currentDate())
                date_to.dateChanged.connect(self.filters_changed)

                self._row2.addWidget(lbl_du)
                self._row2.addWidget(date_from)
                self._row2.addWidget(lbl_au)
                self._row2.addWidget(date_to)
                self._filter_widgets[col] = (date_from, date_to)

            elif kind == "number_range":
                self._row2_used = True
                lbl_min = QLabel(f"{label} — Min :")
                lbl_min.setStyleSheet(_STYLE_FILTER_LABEL)
                spin_min = QDoubleSpinBox()
                spin_min.setRange(0, 999_999_999)
                spin_min.setDecimals(2)
                spin_min.setValue(0.0)
                spin_min.setStyleSheet(_STYLE_FILTER_SPIN)
                spin_min.valueChanged.connect(self.filters_changed)

                lbl_max = QLabel("Max :")
                lbl_max.setStyleSheet(_STYLE_FILTER_LABEL)
                spin_max = QDoubleSpinBox()
                spin_max.setRange(0, 999_999_999)
                spin_max.setDecimals(2)
                spin_max.setSpecialValueText("∞")
                spin_max.setValue(0.0)  # 0 = pas de filtre max
                spin_max.setStyleSheet(_STYLE_FILTER_SPIN)
                spin_max.valueChanged.connect(self.filters_changed)

                self._row2.addWidget(lbl_min)
                self._row2.addWidget(spin_min)
                self._row2.addWidget(lbl_max)
                self._row2.addWidget(spin_max)
                self._filter_widgets[col] = (spin_min, spin_max)

        # Stretcher + bouton reset en fin de row1
        self._row1.addStretch()
        self._row1.addWidget(self._btn_reset)

        # Stretcher fin de row2
        if self._row2_used:
            self._row2.addStretch()
        else:
            # Masquer row2 si vide
            pass

    def populate_combo(self, col: str, values: list) -> None:
        """Remplit un QComboBox de filtre avec les valeurs uniques du DataFrame."""
        widget = self._filter_widgets.get(col)
        if widget is None or not isinstance(widget, QComboBox):
            return
        current = widget.currentText()
        widget.blockSignals(True)
        widget.clear()
        widget.addItem("Tous")
        for v in sorted(set(str(x) for x in values if pd.notna(x) and str(x).strip())):
            widget.addItem(v)
        # Restaurer la sélection si possible
        idx = widget.findText(current)
        if idx >= 0:
            widget.setCurrentIndex(idx)
        widget.blockSignals(False)

    def get_search_text(self) -> str:
        return self._search.text().strip().lower()

    def get_filter_values(self) -> dict:
        """Retourne un dict col -> valeur(s) de filtre active."""
        result = {}
        for col, widget in self._filter_widgets.items():
            cfg = next((c for c in self._config if c["col"] == col), {})
            kind = cfg.get("kind", "combo")

            if kind == "combo":
                val = widget.currentText()
                result[col] = None if val == "Tous" else val

            elif kind == "date_range":
                date_from, date_to = widget
                result[col] = (
                    date_from.date().toPyDate(),
                    date_to.date().toPyDate(),
                )

            elif kind == "number_range":
                spin_min, spin_max = widget
                result[col] = (
                    spin_min.value(),
                    spin_max.value() if spin_max.value() > 0 else None,
                )
        return result

    def _reset_all(self) -> None:
        """Remet tous les filtres à zéro."""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)

        for col, widget in self._filter_widgets.items():
            cfg = next((c for c in self._config if c["col"] == col), {})
            kind = cfg.get("kind", "combo")

            if kind == "combo":
                widget.blockSignals(True)
                widget.setCurrentIndex(0)
                widget.blockSignals(False)

            elif kind == "date_range":
                date_from, date_to = widget
                date_from.blockSignals(True)
                date_to.blockSignals(True)
                date_from.setDate(QDate(2000, 1, 1))
                date_to.setDate(QDate.currentDate())
                date_from.blockSignals(False)
                date_to.blockSignals(False)

            elif kind == "number_range":
                spin_min, spin_max = widget
                spin_min.blockSignals(True)
                spin_max.blockSignals(True)
                spin_min.setValue(0.0)
                spin_max.setValue(0.0)
                spin_min.blockSignals(False)
                spin_max.blockSignals(False)

        self.filters_changed.emit()


# ─── DataTableWidget ───────────────────────────────────────────────────────────

class DataTableWidget(QWidget):
    """
    Widget complet : tableau + en-têtes stylisés + barre de recherche + FilterBar optionnelle.

    AM-12 : Filtres par type/catégorie (combo), date_range, number_range.
             Activer via set_filter_config([...]).
    AM-13 : Tri par clic sur header (flèches ↑↓) — déjà supporté via setSortingEnabled.
    """

    # Émis quand une cellule éditable est modifiée : (row_in_model, col_name, new_value)
    cell_changed = pyqtSignal(int, str, object)

    def __init__(self, parent=None, editable: bool = False, searchable: bool = True):
        super().__init__(parent)
        self._loading = False
        self._full_df: pd.DataFrame = pd.DataFrame()
        self._search_blob: pd.Series | None = None
        self._model = PandasTableModel()
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setStyleSheet(STYLE_TABLE)

        self._skeleton_handler = SkeletonHandler(self)
        self._skeleton_handler.updated.connect(self._view.viewport().update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Barre de recherche simple (legacy, masquée si FilterBar active) ──
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("🔍  Filtrer...")
        self._search_bar.setStyleSheet(STYLE_INPUT + " max-height: 28px;")
        self._search_bar.textChanged.connect(self._queue_simple_filter)
        self._search_bar.setClearButtonEnabled(True)
        if searchable:
            layout.addWidget(self._search_bar)
        else:
            self._search_bar.hide()

        # ── FilterBar (AM-12) — créée mais masquée jusqu'à set_filter_config() ──
        self._filter_bar: FilterBar | None = None
        self._filter_config: list[dict] = []
        self._pending_simple_filter_text: str = ""
        self._simple_filter_debounce = QTimer(self)
        self._simple_filter_debounce.setSingleShot(True)
        self._simple_filter_debounce.setInterval(120)
        self._simple_filter_debounce.timeout.connect(self._apply_pending_simple_filter)

        self._advanced_filter_debounce = QTimer(self)
        self._advanced_filter_debounce.setSingleShot(True)
        self._advanced_filter_debounce.setInterval(120)
        self._advanced_filter_debounce.timeout.connect(self._on_advanced_filter_changed)

        # Configuration de la vue
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

    # ── AM-12 : Configuration des filtres avancés ──────────────────────────────

    def set_filter_config(self, config: list[dict]) -> None:
        """
        Active la FilterBar avec la configuration donnée.
        Masque la barre de recherche simple et la remplace.

        config = [
            {"col": "type",     "kind": "combo",        "label": "Type"},
            {"col": "date",     "kind": "date_range",   "label": "Date"},
            {"col": "amount",   "kind": "number_range", "label": "Montant"},
            {"col": "category", "kind": "combo",        "label": "Catégorie"},
        ]
        """
        self._filter_config = config

        # Créer la FilterBar si elle n'existe pas encore
        if self._filter_bar is None:
            self._filter_bar = FilterBar()
            # L'insérer avant la table (position 0 du layout)
            layout = self.layout()
            layout.insertWidget(0, self._filter_bar)
            self._filter_bar.filters_changed.connect(self._queue_advanced_filter_changed)

        self._filter_bar.set_config(config)

        # Masquer la barre de recherche simple pour éviter la duplication
        self._search_bar.hide()

    def _populate_filter_combos(self) -> None:
        """Remplit les combos de la FilterBar avec les valeurs uniques du df."""
        if self._filter_bar is None or self._full_df.empty:
            return
        for cfg in self._filter_config:
            if cfg.get("kind") == "combo":
                col = cfg["col"]
                if col in self._full_df.columns:
                    self._filter_bar.populate_combo(col, self._full_df[col].tolist())

    def _on_advanced_filter_changed(self) -> None:
        """Applique tous les filtres actifs (texte + combo + date + nombre)."""
        if self._full_df.empty:
            return

        df = self._full_df

        # Filtre texte global
        text = self._filter_bar.get_search_text()
        if text:
            df = self._apply_text_filter(df, text)

        # Filtres avancés
        filter_vals = self._filter_bar.get_filter_values()
        for cfg in self._filter_config:
            col = cfg["col"]
            kind = cfg.get("kind", "combo")
            val = filter_vals.get(col)

            if col not in df.columns or val is None:
                continue

            if kind == "combo" and val is not None:
                df = df[df[col].astype(str) == val]

            elif kind == "date_range":
                date_from, date_to = val
                try:
                    col_dt = pd.to_datetime(df[col], errors="coerce")
                    from_ts = pd.Timestamp(date_from)
                    to_ts = pd.Timestamp(date_to).replace(hour=23, minute=59, second=59)
                    df = df[(col_dt >= from_ts) & (col_dt <= to_ts)]
                except Exception:
                    pass

            elif kind == "number_range":
                min_val, max_val = val
                try:
                    col_num = pd.to_numeric(df[col], errors="coerce").abs()
                    if min_val > 0:
                        df = df[col_num >= min_val]
                    if max_val is not None and max_val > 0:
                        df = df[col_num <= max_val]
                except Exception:
                    pass

        self._model.set_dataframe(df.reset_index(drop=True))
        self._apply_delegates()
        self._apply_hidden_cols()

    # ── Chargement / skelton ───────────────────────────────────────────────────

    def set_loading(self, loading: bool) -> None:
        """Active ou désactive le mode skeleton."""
        self._loading = loading
        if loading:
            self._skeleton_handler.start()
            self._model.set_dataframe(pd.DataFrame({"Loading...": [""] * 5}))
        else:
            self._skeleton_handler.stop()
        self._view.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

    # ── DataFrame ─────────────────────────────────────────────────────────────

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self._full_df = df if df is not None else pd.DataFrame()
        self._invalidate_search_cache()

        # Si FilterBar active, repopuler les combos AVANT de réinitialiser les filtres
        if self._filter_bar is not None:
            self._filter_bar.blockSignals(True)
            self._populate_filter_combos()
            self._filter_bar.blockSignals(False)
            # Appliquer les filtres actuels (sans reset)
            self._on_advanced_filter_changed()
        else:
            self._search_bar.clear()
            self._model.set_dataframe(self._full_df)

        self._view.resizeColumnsToContents()
        self._apply_delegates()
        self._apply_hidden_cols()

    def get_dataframe(self) -> pd.DataFrame:
        return self._model.get_dataframe()

    def set_column_colors(self, column_colors: dict) -> None:
        """Définit des fonctions de couleur par colonne."""
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

    # ── Internes ──────────────────────────────────────────────────────────────

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
        """Filtre textuel simple (barre de recherche legacy)."""
        if not text.strip() or self._full_df.empty:
            self._model.set_dataframe(self._full_df)
            self._apply_delegates()
            self._apply_hidden_cols()
            return
        query = text.strip().lower()
        filtered = self._apply_text_filter(self._full_df, query)
        self._model.set_dataframe(filtered.reset_index(drop=True))
        self._apply_delegates()
        self._apply_hidden_cols()

    def _queue_simple_filter(self, text: str) -> None:
        self._pending_simple_filter_text = text
        self._simple_filter_debounce.start()

    def _apply_pending_simple_filter(self) -> None:
        self._on_filter_changed(self._pending_simple_filter_text)

    def _queue_advanced_filter_changed(self) -> None:
        self._advanced_filter_debounce.start()

    def _invalidate_search_cache(self) -> None:
        self._search_blob = None

    def _ensure_search_blob(self) -> pd.Series:
        if self._search_blob is not None and len(self._search_blob) == len(self._full_df):
            return self._search_blob
        if self._full_df.empty:
            self._search_blob = pd.Series(dtype="object")
            return self._search_blob
        # Concatène chaque ligne en un texte unique réutilisable pour les recherches.
        self._search_blob = (
            self._full_df.fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.lower()
        )
        return self._search_blob

    def _apply_text_filter(self, df: pd.DataFrame, query: str) -> pd.DataFrame:
        if df.empty or not query:
            return df
        query_norm = str(query).strip().lower()
        if not query_norm:
            return df
        if df is self._full_df:
            blob = self._ensure_search_blob()
        else:
            blob = (
                df.fillna("")
                .astype(str)
                .agg(" ".join, axis=1)
                .str.lower()
            )
        mask = blob.str.contains(query_norm, regex=False, na=False)
        return df[mask]
