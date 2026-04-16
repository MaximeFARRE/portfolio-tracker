"""
Panel générique de compte (types non couverts par un panel dédié).
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
)
from PyQt6.QtCore import pyqtSignal

from qt_ui.panels.saisie_panel import SaisiePanel
from qt_ui.theme import BG_PRIMARY, STYLE_BTN_DANGER, TEXT_SECONDARY

logger = logging.getLogger(__name__)


class CompteGenericPanel(QWidget):
    account_deleted = pyqtSignal(int, int)  # person_id, account_id

    def __init__(
        self,
        conn,
        person_id: int,
        account_id: int,
        account_type: str,
        parent=None,
    ):
        super().__init__(parent)
        self._conn = conn
        self._person_id = int(person_id)
        self._account_id = int(account_id)
        self._account_type = str(account_type)

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        top_actions = QHBoxLayout()
        top_actions.addStretch()
        self._btn_delete_account = QPushButton("🗑️  Supprimer le compte")
        self._btn_delete_account.setStyleSheet(STYLE_BTN_DANGER)
        self._btn_delete_account.clicked.connect(self._on_delete_account)
        top_actions.addWidget(self._btn_delete_account)
        root.addLayout(top_actions)

        title = QLabel(f"Compte de type {self._account_type}")
        title.setStyleSheet(f"color: {TEXT_SECONDARY};")
        root.addWidget(title)

        self._saisie = SaisiePanel(
            conn,
            self._person_id,
            self._account_id,
            self._account_type,
        )
        root.addWidget(self._saisie)
        root.addStretch()

    def refresh(self) -> None:
        return

    def _on_delete_account(self) -> None:
        try:
            from services import repositories as repo

            acc = repo.get_account(self._conn, self._account_id) or {}
            account_name = str(acc.get("name") or f"Compte {self._account_id}")

            confirm = QMessageBox(self)
            confirm.setIcon(QMessageBox.Icon.Warning)
            confirm.setWindowTitle("Confirmer la suppression")
            confirm.setText("Voulez-vous vraiment supprimer ce compte ?")
            confirm.setInformativeText(
                "Cette action supprimera aussi toutes les transactions associées et est irréversible."
            )
            confirm.setStandardButtons(
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
            )
            btn_delete = confirm.button(QMessageBox.StandardButton.Yes)
            if btn_delete is not None:
                btn_delete.setText("Supprimer")
            btn_cancel = confirm.button(QMessageBox.StandardButton.Cancel)
            if btn_cancel is not None:
                btn_cancel.setText("Annuler")
            confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if confirm.exec() != QMessageBox.StandardButton.Yes:
                return

            self._btn_delete_account.setEnabled(False)
            delete_res = repo.delete_account(
                self._conn,
                self._account_id,
                person_id=self._person_id,
            )

            from services import snapshots as wk_snap
            wk_snap.rebuild_snapshots_person_from_last(
                self._conn,
                person_id=self._person_id,
                safety_weeks=4,
                fallback_lookback_days=90,
            )

            tx_deleted = int(delete_res.get("transactions_deleted", 0))
            QMessageBox.information(
                self,
                "Compte supprimé",
                (
                    f"Le compte « {account_name} » a été supprimé.\n"
                    f"Transactions supprimées : {tx_deleted}."
                ),
            )
            self.account_deleted.emit(int(self._person_id), int(self._account_id))
        except Exception as e:
            logger.error("CompteGenericPanel._on_delete_account error: %s", e, exc_info=True)
            self._btn_delete_account.setEnabled(True)
            QMessageBox.critical(
                self,
                "Suppression impossible",
                f"Impossible de supprimer ce compte :\n{e}",
            )
