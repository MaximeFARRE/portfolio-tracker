"""
Panel d'ajout de compte — remplace ui/compte_ajout.py
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QGroupBox
)
from PyQt6.QtCore import pyqtSignal
from qt_ui.theme import (
    STYLE_INPUT, STYLE_BTN_CREATE, STYLE_GROUP,
    STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR, ACCENT_BLUE,
)
from utils.libelles import SOUS_TYPES_LIVRET

logger = logging.getLogger(__name__)

TYPES_COMPTE = [
    "BANQUE",
    "LIVRET",
    "PEA",
    "PEA_PME",
    "CTO",
    "CRYPTO",
    "ASSURANCE_VIE",
    "PER",
    "PEE",
]
DEVISES = ["EUR", "USD", "CHF", "GBP", "JPY"]

# Sous-types de livrets affichés dans l'ordre de fréquence
_SOUS_TYPES_LIVRET_LABELS = list(SOUS_TYPES_LIVRET.values())
_SOUS_TYPES_LIVRET_CODES = list(SOUS_TYPES_LIVRET.keys())


class AjoutComptePanel(QGroupBox):
    """Panel pliable pour ajouter un compte. Émet account_created() lors du succès."""
    account_created = pyqtSignal()

    def __init__(self, conn, person_id: int, parent=None):
        super().__init__("➕  Ajouter un compte", parent)
        self._conn = conn
        self._person_id = person_id

        self.setStyleSheet(STYLE_GROUP + f" QGroupBox::title {{ color: {ACCENT_BLUE}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        row1 = QHBoxLayout()
        c1 = QVBoxLayout()
        c1.addWidget(QLabel("Nom du compte :"))
        self._nom_edit = QLineEdit()
        self._nom_edit.setPlaceholderText("BNP, Caisse d'Épargne, PEA Bourso...")
        self._nom_edit.setStyleSheet(STYLE_INPUT)
        c1.addWidget(self._nom_edit)
        row1.addLayout(c1)

        c2 = QVBoxLayout()
        c2.addWidget(QLabel("Devise :"))
        self._devise_combo = QComboBox()
        self._devise_combo.addItems(DEVISES)
        self._devise_combo.setStyleSheet(STYLE_INPUT)
        c2.addWidget(self._devise_combo)
        row1.addLayout(c2)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        c3 = QVBoxLayout()
        c3.addWidget(QLabel("Type de compte :"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(TYPES_COMPTE)
        self._type_combo.setStyleSheet(STYLE_INPUT)
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        c3.addWidget(self._type_combo)
        row2.addLayout(c3)

        c4 = QVBoxLayout()
        c4.addWidget(QLabel("Institution (optionnel) :"))
        self._institution_edit = QLineEdit()
        self._institution_edit.setStyleSheet(STYLE_INPUT)
        c4.addWidget(self._institution_edit)
        row2.addLayout(c4)
        layout.addLayout(row2)

        # Sélecteur de sous-type livret — visible uniquement si type = LIVRET
        self._subtype_row = QHBoxLayout()
        self._subtype_lbl = QLabel("Sous-type de livret :")
        self._subtype_combo = QComboBox()
        self._subtype_combo.addItems(_SOUS_TYPES_LIVRET_LABELS)
        self._subtype_combo.setStyleSheet(STYLE_INPUT)
        self._subtype_row.addWidget(self._subtype_lbl)
        self._subtype_row.addWidget(self._subtype_combo)
        self._subtype_row.addStretch()
        layout.addLayout(self._subtype_row)
        self._set_subtype_visible(False)

        btn_row = QHBoxLayout()
        btn_create = QPushButton("Créer le compte ✅")
        btn_create.setStyleSheet(STYLE_BTN_CREATE)
        btn_create.clicked.connect(self._on_create)
        btn_row.addWidget(btn_create)

        self._result_lbl = QLabel()
        self._result_lbl.setStyleSheet(STYLE_STATUS_SUCCESS)
        btn_row.addWidget(self._result_lbl)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def set_person(self, person_id: int) -> None:
        self._person_id = person_id

    def _set_subtype_visible(self, visible: bool) -> None:
        self._subtype_lbl.setVisible(visible)
        self._subtype_combo.setVisible(visible)

    def _on_type_changed(self, account_type: str) -> None:
        self._set_subtype_visible(account_type == "LIVRET")

    def _on_create(self) -> None:
        nom = self._nom_edit.text().strip()
        if not nom:
            self._result_lbl.setStyleSheet(STYLE_STATUS_ERROR)
            self._result_lbl.setText("Le nom du compte est obligatoire.")
            return

        account_type = self._type_combo.currentText()
        subtype = None
        if account_type == "LIVRET":
            idx = self._subtype_combo.currentIndex()
            subtype = _SOUS_TYPES_LIVRET_CODES[idx]

        try:
            from services import repositories as repo
            repo.create_account(
                self._conn,
                self._person_id,
                nom,
                account_type,
                self._institution_edit.text().strip() or None,
                self._devise_combo.currentText(),
                subtype=subtype,
            )
            self._result_lbl.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._result_lbl.setText(f"Compte '{nom}' créé ✅")
            self._nom_edit.clear()
            self._institution_edit.clear()
            self.account_created.emit()
        except Exception as e:
            logger.error("Erreur création compte: %s", e, exc_info=True)
            self._result_lbl.setStyleSheet(STYLE_STATUS_ERROR)
            self._result_lbl.setText(f"Erreur : {e}")
