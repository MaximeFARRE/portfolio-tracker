"""
Panel d'un compte Banque — remplace ui/compte_banque.py
"""
import logging
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QMenu
)
from PyQt6.QtCore import pyqtSignal
from qt_ui.components.animated_tab import AnimatedTabWidget
from qt_ui.widgets import DataTableWidget, MetricLabel
from qt_ui.panels.saisie_panel import SaisiePanel
from qt_ui.theme import (
    BG_PRIMARY, STYLE_SECTION, STYLE_TAB_INNER, STYLE_BTN_DANGER,
    STYLE_STATUS, STYLE_STATUS_SUCCESS, STYLE_STATUS_WARNING, STYLE_STATUS_ERROR,
)

logger = logging.getLogger(__name__)


class CompteBanquePanel(QWidget):
    account_deleted = pyqtSignal(int, int)  # person_id, account_id

    def __init__(self, conn, person_id: int, account_id: int, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._account_id = account_id

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        main_v = QVBoxLayout(self)
        main_v.setContentsMargins(12, 12, 12, 12)
        main_v.setSpacing(12)

        top_actions = QHBoxLayout()
        top_actions.addStretch()
        self._btn_delete_account = QPushButton("🗑️  Supprimer le compte")
        self._btn_delete_account.setStyleSheet(STYLE_BTN_DANGER)
        self._btn_delete_account.clicked.connect(self._on_delete_account)
        top_actions.addWidget(self._btn_delete_account)
        main_v.addLayout(top_actions)

        tabs = AnimatedTabWidget()
        tabs.setStyleSheet(STYLE_TAB_INNER)

        # Dashboard
        dash = QWidget()
        dash.setStyleSheet(f"background: {BG_PRIMARY};")
        dash_v = QVBoxLayout(dash)
        dash_v.setContentsMargins(8, 8, 8, 8)
        dash_v.setSpacing(10)

        kpi_row = QHBoxLayout()
        self._kpi_solde = MetricLabel("Solde actuel", "—")
        self._kpi_interets = MetricLabel("Intérêts 12 mois", "—")
        kpi_row.addWidget(self._kpi_solde)
        kpi_row.addWidget(self._kpi_interets)
        kpi_row.addStretch()
        dash_v.addLayout(kpi_row)

        lbl_hist = QLabel("Dernières opérations")
        lbl_hist.setStyleSheet(STYLE_SECTION)
        dash_v.addWidget(lbl_hist)
        self._table_recent = DataTableWidget()
        self._table_recent.setMinimumHeight(300)
        self._table_recent.set_filter_config([
            {"col": "type",     "kind": "combo",      "label": "Type"},
            {"col": "category", "kind": "combo",      "label": "Catégorie"},
        ])
        self._table_recent.set_combo_delegate("category", [])
        self._table_recent.cell_changed.connect(self._on_recent_table_cell_changed)
        self._install_tx_context_menu(self._table_recent)
        dash_v.addWidget(self._table_recent)
        dash_v.addStretch()
        tabs.addTab(dash, "🏦  Tableau de bord")

        # Saisie
        self._saisie = SaisiePanel(conn, person_id, account_id, "BANQUE")
        tabs.addTab(self._saisie, "✏️  Saisie")

        # Historique complet
        hist = QWidget()
        hist.setStyleSheet(f"background: {BG_PRIMARY};")
        hist_v = QVBoxLayout(hist)
        hist_v.setContentsMargins(8, 8, 8, 8)
        self._hist_table = DataTableWidget()
        self._hist_table.setMinimumHeight(400)
        self._hist_table.set_filter_config([
            {"col": "type",     "kind": "combo",        "label": "Type"},
            {"col": "date",     "kind": "date_range",   "label": "Date"},
            {"col": "amount",   "kind": "number_range", "label": "Montant"},
            {"col": "category", "kind": "combo",        "label": "Catégorie"},
        ])
        self._hist_table.set_combo_delegate("category", [])
        self._hist_table.cell_changed.connect(self._on_hist_table_cell_changed)
        self._install_tx_context_menu(self._hist_table)
        hist_v.addWidget(self._hist_table)
        self._tx_action_status = QLabel("")
        self._tx_action_status.setStyleSheet(STYLE_STATUS)
        hist_v.addWidget(self._tx_action_status)
        tabs.addTab(hist, "📋  Historique")

        main_v.addWidget(tabs)
        self._tabs = tabs
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._load_dashboard()

    def refresh(self) -> None:
        self._load_dashboard()

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 0:
            self._load_dashboard()
        elif idx == 2:
            self._load_history()

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
            logger.error("CompteBanquePanel._on_delete_account error: %s", e, exc_info=True)
            self._btn_delete_account.setEnabled(True)
            QMessageBox.critical(
                self,
                "Suppression impossible",
                f"Impossible de supprimer ce compte :\n{e}",
            )

    def _load_dashboard(self) -> None:
        try:
            from services import repositories as repo
            from services.calculations import solde_compte, interets_12_mois

            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=100000)
            if tx is None or tx.empty:
                self._kpi_solde.set_content("Solde actuel", "0,00 €")
                self._table_recent.set_dataframe(pd.DataFrame())
                return

            solde = solde_compte(tx)
            interets_12m = interets_12_mois(tx)

            self._kpi_solde.set_content("Solde actuel", f"{solde:,.2f} €".replace(",", " "))
            self._kpi_interets.set_content("Intérêts 12 mois", f"{interets_12m:,.2f} €".replace(",", " "))

            tx = tx.copy()
            tx["etat"] = tx["analysis_state"].apply(self._format_analysis_state) if "analysis_state" in tx.columns else "Normale"
            cols = ["date", "type", "amount", "fees", "category", "etat", "note", "id", "is_hidden_from_cashflow", "is_internal_transfer"]
            cols = [c for c in cols if c in tx.columns]
            recent_df = tx[cols].head(50).copy()
            self._table_recent.set_dataframe(recent_df)
            for hidden_col in ("id", "is_hidden_from_cashflow", "is_internal_transfer"):
                self._table_recent.hide_column(hidden_col)
            self._configure_category_delegate(self._table_recent, recent_df)
        except Exception as exc:
            logger.exception("CompteBanquePanel._load_dashboard error", exc_info=exc)

    def _load_history(self) -> None:
        try:
            from services import repositories as repo
            from utils.libelles import afficher_type_operation

            tx = repo.list_transactions(self._conn, account_id=self._account_id, limit=5000)
            if tx is None or tx.empty:
                self._hist_table.set_dataframe(pd.DataFrame())
                return
            tx = tx.copy()
            tx["etat"] = tx["analysis_state"].apply(self._format_analysis_state) if "analysis_state" in tx.columns else "Normale"
            if "type" in tx.columns:
                tx["type"] = tx["type"].apply(lambda t: afficher_type_operation(str(t)))
            cols = [
                "date", "type", "amount", "fees", "category", "etat", "note", "id",
                "is_hidden_from_cashflow", "is_internal_transfer", "analysis_state",
            ]
            cols = [c for c in cols if c in tx.columns]
            hist_df = tx[cols].copy()
            self._hist_table.set_dataframe(hist_df)
            for hidden_col in ("id", "is_hidden_from_cashflow", "is_internal_transfer", "analysis_state"):
                self._hist_table.hide_column(hidden_col)
            self._configure_category_delegate(self._hist_table, hist_df)
        except Exception as exc:
            logger.error("CompteBanquePanel._load_history error: %s", exc, exc_info=True)

    @staticmethod
    def _format_analysis_state(state: str) -> str:
        code = str(state or "").upper()
        if code == "HIDDEN":
            return "Masquée"
        if code == "INTERNAL_TRANSFER":
            return "Virement interne"
        if code == "DELETED":
            return "Supprimée"
        return "Normale"

    def _configure_category_delegate(self, table_widget: DataTableWidget, df: pd.DataFrame) -> None:
        if df is None or df.empty or "category" not in df.columns:
            return
        categories = sorted({str(v).strip() for v in df["category"].tolist() if pd.notna(v) and str(v).strip()})
        if not categories:
            categories = ["Autres revenus", "Dépenses courantes", "Flux financiers"]
        table_widget.set_combo_delegate("category", categories)

    def _selected_transaction_row(self, table_widget: DataTableWidget) -> dict | None:
        view = getattr(table_widget, "_view", None)
        if view is None or view.selectionModel() is None:
            return None
        selected_rows = view.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row_index = selected_rows[0].row()
        df = table_widget.get_dataframe()
        if df.empty or row_index >= len(df):
            return None
        try:
            return df.iloc[row_index].to_dict()
        except Exception:
            return None

    def _selected_transaction_id(self, table_widget: DataTableWidget) -> int | None:
        row = self._selected_transaction_row(table_widget)
        if not row:
            return None
        tx_id = row.get("id")
        if tx_id is None:
            return None
        try:
            return int(tx_id)
        except Exception:
            return None

    def _set_tx_status(self, message: str, level: str = "info") -> None:
        if level == "success":
            self._tx_action_status.setStyleSheet(STYLE_STATUS_SUCCESS)
        elif level == "warning":
            self._tx_action_status.setStyleSheet(STYLE_STATUS_WARNING)
        elif level == "error":
            self._tx_action_status.setStyleSheet(STYLE_STATUS_ERROR)
        else:
            self._tx_action_status.setStyleSheet(STYLE_STATUS)
        self._tx_action_status.setText(message)

    def _refresh_tables_after_tx_action(self) -> None:
        self._load_dashboard()
        self._load_history()

    def _on_hist_table_cell_changed(self, row: int, col_name: str, new_value) -> None:
        if col_name != "category":
            return
        self._update_category_from_row(self._hist_table, row, new_value)

    def _on_recent_table_cell_changed(self, row: int, col_name: str, new_value) -> None:
        if col_name != "category":
            return
        self._update_category_from_row(self._table_recent, row, new_value)

    def _update_category_from_row(self, table_widget: DataTableWidget, row: int, new_value) -> None:
        from services import repositories as repo

        df = table_widget.get_dataframe()
        if df.empty or row >= len(df) or "id" not in df.columns:
            return
        try:
            tx_id = int(df.iloc[row]["id"])
        except Exception:
            return

        ok = repo.update_transaction_category(self._conn, tx_id, str(new_value) if new_value is not None else None)
        if not ok:
            self._set_tx_status("⚠️ Impossible de modifier la catégorie (transaction introuvable).", "warning")
            return
        self._set_tx_status("✅ Catégorie mise à jour.", "success")
        self._refresh_tables_after_tx_action()

    def _install_tx_context_menu(self, table_widget: DataTableWidget) -> None:
        view = getattr(table_widget, "_view", None)
        if view is None:
            return
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(lambda pos, tw=table_widget: self._open_tx_context_menu(tw, pos))

    def _open_tx_context_menu(self, table_widget: DataTableWidget, pos) -> None:
        from services import repositories as repo

        view = getattr(table_widget, "_view", None)
        if view is not None:
            idx = view.indexAt(pos)
            if idx.isValid():
                view.selectRow(idx.row())

        row = self._selected_transaction_row(table_widget)
        tx_id = self._selected_transaction_id(table_widget)
        if row is None or tx_id is None:
            return

        is_hidden = bool(int(row.get("is_hidden_from_cashflow") or 0))
        is_internal = bool(int(row.get("is_internal_transfer") or 0))

        menu = QMenu(self)
        act_hide = menu.addAction("Réafficher dans l'analyse" if is_hidden else "Masquer de l'analyse")
        act_internal = menu.addAction("Retirer virement interne" if is_internal else "Marquer comme virement interne")
        menu.addSeparator()
        act_delete = menu.addAction("Supprimer la transaction")

        chosen = menu.exec(view.viewport().mapToGlobal(pos) if view is not None else self.mapToGlobal(pos))
        if chosen is None:
            return

        try:
            if chosen == act_hide:
                ok = repo.hide_transaction(self._conn, tx_id, hidden=not is_hidden)
                if ok:
                    self._set_tx_status(
                        "✅ Transaction masquée de l'analyse." if not is_hidden else "✅ Transaction réintégrée dans l'analyse.",
                        "success",
                    )
                else:
                    self._set_tx_status("⚠️ Transaction introuvable.", "warning")
            elif chosen == act_internal:
                ok = repo.mark_transaction_as_internal_transfer(self._conn, tx_id, value=not is_internal)
                if ok:
                    self._set_tx_status(
                        "✅ Transaction marquée comme virement interne." if not is_internal else "✅ Marquage virement interne retiré.",
                        "success",
                    )
                else:
                    self._set_tx_status("⚠️ Transaction introuvable.", "warning")
            elif chosen == act_delete:
                answer = QMessageBox.question(
                    self,
                    "Confirmer la suppression",
                    "Supprimer cette transaction importée ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                repo.delete_transaction(self._conn, tx_id)
                self._set_tx_status("✅ Transaction supprimée.", "success")
            self._refresh_tables_after_tx_action()
        except Exception as exc:
            self._set_tx_status(f"❌ Action impossible : {exc}", "error")
