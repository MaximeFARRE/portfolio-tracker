"""
Dialog de modification d'un actif (nom, symbole, devise).
Calqué sur TransactionEditDialog de compte_bourse_panel.py.
"""
import logging
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout,
    QLabel, QLineEdit, QComboBox,
)
from PyQt6.QtCore import Qt
from qt_ui.theme import (
    BG_PRIMARY, STYLE_INPUT, STYLE_BTN_SUCCESS,
    STYLE_STATUS_ERROR,
)

logger = logging.getLogger(__name__)

_DEVISES = ["EUR", "USD", "GBP", "CHF", "CAD", "JPY", "AUD", "SEK", "NOK", "DKK"]


class EditAssetDialog(QDialog):
    """Dialogue de modification d'un actif : nom, symbole, devise."""

    def __init__(self, conn, asset_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._asset_id = int(asset_id)

        self.setWindowTitle("Modifier l'actif")
        self.setModal(True)
        self.resize(440, 260)
        self.setStyleSheet(f"background: {BG_PRIMARY};")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit()
        self._name_edit.setStyleSheet(STYLE_INPUT)
        form.addRow("Nom", self._name_edit)

        self._symbol_edit = QLineEdit()
        self._symbol_edit.setStyleSheet(STYLE_INPUT)
        self._symbol_edit.setPlaceholderText("ex : AIR.PA, AAPL, BTC-USD")
        form.addRow("Symbole / Ticker", self._symbol_edit)

        self._currency_combo = QComboBox()
        self._currency_combo.setStyleSheet(STYLE_INPUT)
        self._currency_combo.setEditable(True)
        self._currency_combo.addItems(_DEVISES)
        form.addRow("Devise", self._currency_combo)

        root.addLayout(form)

        self._warning_label = QLabel(
            "⚠️  Si vous modifiez le symbole, l'historique local des prix sera mis à jour."
        )
        self._warning_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
        self._warning_label.setWordWrap(True)
        self._warning_label.setVisible(False)
        root.addWidget(self._warning_label)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(STYLE_STATUS_ERROR)
        self._error_label.setWordWrap(True)
        root.addWidget(self._error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._btn_save = buttons.addButton("Enregistrer", QDialogButtonBox.ButtonRole.AcceptRole)
        self._btn_save.setStyleSheet(STYLE_BTN_SUCCESS)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._on_accept)
        root.addWidget(buttons)

        self._original_symbol: str = ""
        self._prefill()
        self._symbol_edit.textChanged.connect(self._on_symbol_changed)

    def _prefill(self) -> None:
        from services import repositories as repo
        asset = repo.get_asset_by_id(self._conn, self._asset_id)
        if asset is None:
            self._error_label.setText(f"Actif introuvable (id={self._asset_id}).")
            return
        name = str(asset.get("name", ""))
        symbol = str(asset.get("symbol", ""))
        currency = str(asset.get("currency", "EUR"))

        self._name_edit.setText(name)
        self._symbol_edit.setText(symbol)
        self._original_symbol = symbol.strip().upper()

        idx = self._currency_combo.findText(currency.upper())
        if idx >= 0:
            self._currency_combo.setCurrentIndex(idx)
        else:
            self._currency_combo.setCurrentText(currency.upper())

    def _on_symbol_changed(self, text: str) -> None:
        changed = text.strip().upper() != self._original_symbol
        self._warning_label.setVisible(changed)

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        symbol = self._symbol_edit.text().strip().upper()
        currency = self._currency_combo.currentText().strip().upper()

        if not name:
            self._error_label.setText("Le nom ne peut pas être vide.")
            return
        if not symbol:
            self._error_label.setText("Le symbole ne peut pas être vide.")
            return

        try:
            from services import repositories as repo
            repo.update_asset(self._conn, self._asset_id, name, symbol, currency)
        except ValueError as e:
            self._error_label.setText(str(e))
            return
        except Exception as e:
            logger.error("update_asset: erreur inattendue: %s", e, exc_info=True)
            self._error_label.setText(f"Erreur : {e}")
            return

        self.accept()
