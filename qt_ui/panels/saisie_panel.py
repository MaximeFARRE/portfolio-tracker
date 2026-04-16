"""
Panel de saisie d'opération — remplace ui/compte_saisie.py
Gère la synchronisation qty × prix = total via signaux Qt.
"""
import logging
import re
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QLineEdit, QDateEdit, QGroupBox,
    QRadioButton, QButtonGroup, QMessageBox, QStackedWidget
)
from PyQt6.QtCore import Qt, QDate, QTimer, QThread, pyqtSignal

from utils.libelles import LIBELLES_TYPE_OPERATION, code_operation_depuis_libelle
from utils.validators import operation_requiert_actif, operation_requiert_quantite_prix
from qt_ui.theme import (
    BG_PRIMARY, STYLE_INPUT, STYLE_LABEL, STYLE_BTN_PRIMARY,
    STYLE_BTN_DANGER, STYLE_GROUP, STYLE_STATUS_SUCCESS, STYLE_STATUS_ERROR,
    TEXT_SECONDARY, TEXT_MUTED,
)

logger = logging.getLogger(__name__)


class _TickerPreviewThread(QThread):
    done = pyqtSignal(int, str, object)

    def __init__(self, request_id: int, symbol: str):
        super().__init__()
        self._request_id = int(request_id)
        self._symbol = (symbol or "").strip().upper()

    def run(self):
        try:
            from services.ticker_preview_service import preview_ticker_live
            payload = preview_ticker_live(self._symbol)
        except Exception as e:
            payload = {
                "found": False,
                "name": self._symbol or None,
                "price": None,
                "currency": None,
                "status": "error",
                "warning": str(e),
            }
        self.done.emit(self._request_id, self._symbol, payload)

ASSET_TYPES = [
    "action",
    "etf",
    "fonds",
    "scpi",
    "obligation",
    "fonds_euros",
    "crypto",
    "private_equity",
    "non_cote",
    "autre",
]

# Types d'actifs sans ticker de marché — pas de cotation automatique,
# prix mis à jour manuellement.
_ASSET_TYPES_NON_COTES = {
    "scpi", "private_equity", "non_cote",
    "fonds", "fonds_euros", "autre",
}


def _auto_symbol(name: str, conn) -> str:
    """
    Génère un symbole unique à partir du nom pour les actifs non cotés.
    Ex : "SCPI Primovie" → "SCPI_PRIMOVIE", ou "SCPI_PRIMOVIE_1" si déjà pris.
    """
    from services import panel_data_access as pda

    base = re.sub(r"[^A-Z0-9]", "_", name.upper())
    base = re.sub(r"_+", "_", base).strip("_")[:20] or "ACTIF"
    sym, counter = base, 1
    while pda.asset_symbol_exists(conn, sym):
        sym = f"{base[:17]}_{counter}"
        counter += 1
    return sym

# Opérations communes à tous les comptes multi-supports (bourse + enveloppes fiscales)
_OPS_MULTI_SUPPORT = [
    "DEPOT", "RETRAIT", "ACHAT", "VENTE", "DIVIDENDE", "FRAIS", "INTERETS",
]

TYPES_PAR_COMPTE = {
    # ── Comptes bancaires ──────────────────────────────────────────────────
    "BANQUE":        ["DEPOT", "RETRAIT", "DEPENSE", "FRAIS", "IMPOT", "INTERETS"],
    # ── Livrets réglementés (pas de dépense ni de frais — uniquement flux livret)
    "LIVRET":        ["DEPOT", "RETRAIT", "INTERETS"],
    # ── Comptes bourse et enveloppes fiscales ──────────────────────────────
    "PEA":           _OPS_MULTI_SUPPORT,
    "PEA_PME":       _OPS_MULTI_SUPPORT,          # Proche PEA, coté + non coté
    "CTO":           _OPS_MULTI_SUPPORT,
    "CRYPTO":        _OPS_MULTI_SUPPORT,
    "ASSURANCE_VIE": _OPS_MULTI_SUPPORT,          # Multi-supports, fonds euros inclus
    "PER":           _OPS_MULTI_SUPPORT,          # Multi-supports
    "PEE":           _OPS_MULTI_SUPPORT + ["ABONDEMENT"],  # + abondement employeur
    # ── Comptes spéciaux (gérés via d'autres panels dédiés) ───────────────
    "IMMOBILIER":    ["LOYER", "DEPENSE", "FRAIS", "IMPOT"],
    "CREDIT":        ["REMBOURSEMENT_CREDIT", "INTERETS", "FRAIS"],
}


def _lbl(text):
    l = QLabel(text)
    l.setStyleSheet(STYLE_LABEL)
    return l


class SaisiePanel(QWidget):
    """Panel de saisie d'une opération financière."""

    def __init__(self, conn, person_id: int, account_id: int, account_type: str, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._person_id = person_id
        self._account_id = account_id
        self._account_type = account_type
        self._syncing = False
        self._asset_id = None
        self._ticker_preview_timer = QTimer(self)
        self._ticker_preview_timer.setSingleShot(True)
        self._ticker_preview_timer.timeout.connect(self._run_pending_ticker_preview)
        self._pending_preview_symbol = ""
        self._pending_preview_target = "new"
        self._preview_request_id = 0
        self._ticker_preview_threads: list = []

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ─── Type + Date + Frais
        top_grp = QGroupBox("Saisie d'opération")
        top_grp.setStyleSheet(STYLE_GROUP)
        top_v = QVBoxLayout(top_grp)

        row1 = QHBoxLayout()
        c1 = QVBoxLayout()
        c1.addWidget(_lbl("Type d'opération"))
        self._type_combo = QComboBox()
        self._type_combo.setStyleSheet(STYLE_INPUT)
        types = TYPES_PAR_COMPTE.get(account_type.upper(), ["DEPENSE", "FRAIS"])
        for t in types:
            self._type_combo.addItem(LIBELLES_TYPE_OPERATION.get(t, t), t)
        c1.addWidget(self._type_combo)

        c1.addWidget(_lbl("Date"))
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setStyleSheet(STYLE_INPUT)
        c1.addWidget(self._date_edit)
        row1.addLayout(c1)

        c2 = QVBoxLayout()
        c2.addWidget(_lbl("Frais (optionnel)"))
        self._fees_spin = QDoubleSpinBox()
        self._fees_spin.setRange(0, 100_000)
        self._fees_spin.setSingleStep(0.5)
        self._fees_spin.setDecimals(2)
        self._fees_spin.setStyleSheet(STYLE_INPUT)
        c2.addWidget(self._fees_spin)

        c2.addWidget(_lbl("Note (optionnel)"))
        self._note_edit = QLineEdit()
        self._note_edit.setStyleSheet(STYLE_INPUT)
        c2.addWidget(self._note_edit)
        row1.addLayout(c2)
        top_v.addLayout(row1)
        layout.addWidget(top_grp)

        # ─── Actif (si requis)
        self._asset_grp = QGroupBox("Actif")
        self._asset_grp.setStyleSheet(STYLE_GROUP)
        asset_v = QVBoxLayout(self._asset_grp)

        # Radio mode
        mode_row = QHBoxLayout()
        self._radio_existing = QRadioButton("Choisir un actif existant")
        self._radio_new = QRadioButton("Créer un nouvel actif")
        self._radio_existing.setChecked(True)
        self._radio_existing.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._radio_new.setStyleSheet(f"color: {TEXT_SECONDARY};")
        mode_row.addWidget(self._radio_existing)
        mode_row.addWidget(self._radio_new)
        mode_row.addStretch()
        asset_v.addLayout(mode_row)

        self._asset_stack = QStackedWidget()

        # Actif existant
        existing_w = QWidget()
        ev = QVBoxLayout(existing_w)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.addWidget(_lbl("Ticker"))
        self._asset_combo = QComboBox()
        self._asset_combo.setStyleSheet(STYLE_INPUT)
        ev.addWidget(self._asset_combo)
        self._asset_info = QLabel()
        self._asset_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        ev.addWidget(self._asset_info)
        self._asset_live_preview = QLabel("Nom: — | Prix: — | Devise: — | Statut: —")
        self._asset_live_preview.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        ev.addWidget(self._asset_live_preview)
        self._asset_stack.addWidget(existing_w)

        # Nouvel actif
        new_w = QWidget()
        nv = QHBoxLayout(new_w)
        nv.setContentsMargins(0, 0, 0, 0)
        nc1 = QVBoxLayout()
        self._new_symbol_lbl = _lbl("Ticker / Symbole")
        nc1.addWidget(self._new_symbol_lbl)
        self._new_symbol = QLineEdit()
        self._new_symbol.setPlaceholderText("AAPL, CW8, BTC-USD...")
        self._new_symbol.setStyleSheet(STYLE_INPUT)
        nc1.addWidget(self._new_symbol)
        # Hint affiché seulement pour les actifs non cotés
        self._new_symbol_hint = QLabel("⚠️ Optionnel — généré depuis le nom si vide")
        self._new_symbol_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        self._new_symbol_hint.setVisible(False)
        nc1.addWidget(self._new_symbol_hint)
        self._new_symbol_live_preview = QLabel("Nom: — | Prix: — | Devise: — | Statut: —")
        self._new_symbol_live_preview.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        nc1.addWidget(self._new_symbol_live_preview)
        nv.addLayout(nc1)
        nc2 = QVBoxLayout()
        nc2.addWidget(_lbl("Nom"))
        self._new_name = QLineEdit()
        self._new_name.setStyleSheet(STYLE_INPUT)
        nc2.addWidget(self._new_name)
        nv.addLayout(nc2)
        nc3 = QVBoxLayout()
        nc3.addWidget(_lbl("Type d'actif"))
        self._new_type = QComboBox()
        self._new_type.addItems(ASSET_TYPES)
        self._new_type.setStyleSheet(STYLE_INPUT)
        nc3.addWidget(self._new_type)
        nv.addLayout(nc3)
        self._asset_stack.addWidget(new_w)

        asset_v.addWidget(self._asset_stack)
        layout.addWidget(self._asset_grp)

        # ─── Montants
        amounts_grp = QGroupBox("Montants")
        amounts_grp.setStyleSheet(STYLE_GROUP)
        amounts_v = QHBoxLayout(amounts_grp)

        self._qty_grp = QVBoxLayout()
        self._qty_grp.addWidget(_lbl("Quantité"))
        self._qty_spin = QDoubleSpinBox()
        self._qty_spin.setRange(0, 1_000_000_000)
        self._qty_spin.setDecimals(6)
        self._qty_spin.setSingleStep(1)
        self._qty_spin.setStyleSheet(STYLE_INPUT)
        self._qty_grp.addWidget(self._qty_spin)
        amounts_v.addLayout(self._qty_grp)

        self._price_grp = QVBoxLayout()
        self._price_grp.addWidget(_lbl("Prix unitaire"))
        self._price_spin = QDoubleSpinBox()
        self._price_spin.setRange(0, 1_000_000_000)
        self._price_spin.setDecimals(4)
        self._price_spin.setSingleStep(1)
        self._price_spin.setStyleSheet(STYLE_INPUT)
        self._price_grp.addWidget(self._price_spin)
        amounts_v.addLayout(self._price_grp)

        total_col = QVBoxLayout()
        total_col.addWidget(_lbl("Montant total"))
        self._total_spin = QDoubleSpinBox()
        self._total_spin.setRange(0, 1_000_000_000_000)
        self._total_spin.setDecimals(2)
        self._total_spin.setSingleStep(10)
        self._total_spin.setStyleSheet(STYLE_INPUT)
        total_col.addWidget(self._total_spin)
        amounts_v.addLayout(total_col)

        layout.addWidget(amounts_grp)

        # ─── Bouton soumettre
        btn_row = QHBoxLayout()
        self._btn_submit = QPushButton("✅  Enregistrer l'opération")
        self._btn_submit.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_row.addWidget(self._btn_submit)

        self._result_lbl = QLabel()
        self._result_lbl.setStyleSheet(STYLE_STATUS_SUCCESS)
        self._result_lbl.setWordWrap(True)
        btn_row.addWidget(self._result_lbl, 1)
        layout.addLayout(btn_row)

        layout.addStretch()

        # ─── Connexions
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._radio_existing.toggled.connect(self._on_asset_mode_changed)
        self._asset_combo.currentIndexChanged.connect(self._on_asset_selected)
        self._new_type.currentIndexChanged.connect(self._on_new_asset_type_changed)
        self._new_symbol.textChanged.connect(self._on_new_symbol_changed)
        self._qty_spin.valueChanged.connect(self._sync_from_qty_price)
        self._price_spin.valueChanged.connect(self._sync_from_qty_price)
        self._total_spin.valueChanged.connect(self._sync_from_total)
        self._btn_submit.clicked.connect(self._on_submit)

        # Init
        self._load_assets()
        self._on_type_changed()
        self._on_new_asset_type_changed()

    def _load_assets(self) -> None:
        from services import repositories as repo
        actifs = repo.list_assets(self._conn)
        self._asset_combo.clear()
        if actifs is not None and not actifs.empty:
            for _, r in actifs.iterrows():
                self._asset_combo.addItem(f"{r['symbol']} — {r.get('name', '')}", int(r["id"]))
        self._on_asset_selected()

    def _on_type_changed(self) -> None:
        type_code = self._type_combo.currentData() or ""
        needs_asset = operation_requiert_actif(type_code)
        needs_qty_price = operation_requiert_quantite_prix(type_code)

        self._asset_grp.setVisible(needs_asset)
        self._qty_spin.setEnabled(needs_qty_price)
        self._price_spin.setEnabled(needs_qty_price)
        if not needs_qty_price:
            self._qty_spin.setValue(0)
            self._price_spin.setValue(0)

    def _on_asset_mode_changed(self) -> None:
        self._asset_stack.setCurrentIndex(0 if self._radio_existing.isChecked() else 1)
        if self._radio_existing.isChecked():
            self._on_asset_selected()
        else:
            self._on_new_symbol_changed(self._new_symbol.text())

    def _on_new_asset_type_changed(self) -> None:
        """Adapte le champ ticker selon que l'actif est coté ou non coté."""
        atype = self._new_type.currentText()
        if atype in _ASSET_TYPES_NON_COTES:
            self._new_symbol.setPlaceholderText("Optionnel — généré depuis le nom si vide")
            self._new_symbol_hint.setVisible(True)
        else:
            self._new_symbol.setPlaceholderText("AAPL, CW8, BTC-USD...")
            self._new_symbol_hint.setVisible(False)

    def _on_asset_selected(self) -> None:
        from services import panel_data_access as pda

        aid = self._asset_combo.currentData()
        self._asset_id = aid
        if aid:
            row = pda.get_asset_symbol_name(self._conn, aid)
            if row:
                sym = row[0] if not hasattr(row, '__getitem__') else row["symbol"]
                name = row[1] if not hasattr(row, '__getitem__') else row["name"]
                self._asset_info.setText(f"{sym} — {name}")
                self._schedule_ticker_preview(str(sym), target="existing")
                return
        self._asset_info.setText("")
        self._asset_live_preview.setText("Nom: — | Prix: — | Devise: — | Statut: —")
        self._asset_live_preview.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

    def _on_new_symbol_changed(self, _text: str) -> None:
        if self._radio_new.isChecked():
            self._schedule_ticker_preview(self._new_symbol.text(), target="new")

    @staticmethod
    def _format_ticker_preview(preview: dict) -> str:
        name = preview.get("name") or "—"
        price = preview.get("price")
        price_txt = f"{float(price):.4f}" if price is not None else "—"
        ccy = preview.get("currency") or "—"
        status = str(preview.get("status") or "—").upper()
        return f"Nom: {name} | Prix: {price_txt} | Devise: {ccy} | Statut: {status}"

    @staticmethod
    def _ticker_preview_color(preview: dict) -> str:
        status = str(preview.get("status") or "").lower()
        if status == "ok":
            return "#22c55e"
        if status == "partial":
            return "#f59e0b"
        if status == "empty":
            return TEXT_MUTED
        return "#ef4444"

    def _schedule_ticker_preview(self, symbol: str, *, target: str) -> None:
        self._pending_preview_symbol = (symbol or "").strip().upper()
        self._pending_preview_target = target
        self._preview_request_id += 1
        self._ticker_preview_timer.start(350)

    def _run_pending_ticker_preview(self) -> None:
        request_id = self._preview_request_id
        symbol = self._pending_preview_symbol
        target = self._pending_preview_target
        label = self._asset_live_preview if target == "existing" else self._new_symbol_live_preview
        if not symbol:
            label.setText("Nom: — | Prix: — | Devise: — | Statut: EMPTY")
            label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            return

        label.setText("Chargement preview…")
        label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        # Nettoyer les threads terminés avant d'en lancer un nouveau
        self._ticker_preview_threads = [
            t for t in self._ticker_preview_threads if t.isRunning()
        ]
        thread = _TickerPreviewThread(request_id, symbol)
        self._ticker_preview_threads.append(thread)
        thread.done.connect(self._on_ticker_preview_done)
        thread.start()

    def _on_ticker_preview_done(self, request_id: int, _symbol: str, payload: dict) -> None:
        if request_id != self._preview_request_id:
            return
        target = self._pending_preview_target
        label = self._asset_live_preview if target == "existing" else self._new_symbol_live_preview
        label.setText(self._format_ticker_preview(payload))
        label.setStyleSheet(f"color: {self._ticker_preview_color(payload)}; font-size: 11px;")

    def _sync_from_qty_price(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            total = self._qty_spin.value() * self._price_spin.value()
            self._total_spin.setValue(round(total, 2))
        finally:
            self._syncing = False

    def _sync_from_total(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            price = self._price_spin.value()
            if price > 1e-9:
                qty = self._total_spin.value() / price
                self._qty_spin.setValue(round(qty, 6))
        finally:
            self._syncing = False

    def _on_submit(self) -> None:
        from services import repositories as repo
        type_code = self._type_combo.currentData()
        date_str  = self._date_edit.date().toString("yyyy-MM-dd")
        fees      = self._fees_spin.value()
        note      = self._note_edit.text().strip() or None
        amount    = self._total_spin.value()
        qty       = self._qty_spin.value()
        price     = self._price_spin.value()

        # ── Résoudre / créer l'actif ──────────────────────────────────────
        asset_id  = None
        new_atype = None  # type de l'actif nouvellement créé (si applicable)

        if operation_requiert_actif(type_code):
            if self._radio_existing.isChecked():
                asset_id = self._asset_combo.currentData()
                if not asset_id:
                    self._show_error("Veuillez sélectionner un actif.")
                    return
            else:
                atype = self._new_type.currentText()
                nom   = self._new_name.text().strip()
                sym   = self._new_symbol.text().strip().upper()

                # Pour les actifs non cotés, le ticker est optionnel
                if not sym:
                    if atype in _ASSET_TYPES_NON_COTES:
                        if not nom:
                            self._show_error("Le nom est obligatoire pour les actifs non cotés.")
                            return
                        sym = _auto_symbol(nom, self._conn)
                    else:
                        self._show_error("Le ticker est obligatoire pour les actifs cotés.")
                        return

                nom = nom or sym  # fallback si nom vide
                try:
                    asset_id  = repo.create_asset(self._conn, sym, nom, atype)
                    new_atype = atype
                    self._load_assets()  # rafraîchir la liste pour les prochaines saisies
                except Exception as e:
                    logger.error("Erreur création actif: %s", e, exc_info=True)
                    self._show_error(f"Erreur création actif : {e}")
                    return

        # ── Enregistrer la transaction ────────────────────────────────────
        try:
            repo.create_transaction(self._conn, {
                "date":       date_str,
                "person_id":  self._person_id,
                "account_id": self._account_id,
                "type":       type_code,
                "amount":     amount,
                "fees":       fees,
                "asset_id":   asset_id,
                "quantity":   qty   if qty   > 0 else None,
                "price":      price if price > 0 else None,
                "note":       note,
            })

            # ── Pour les actifs non cotés : sauvegarder le prix de l'opération
            # comme dernier prix connu, afin d'afficher une valeur dans les positions.
            if asset_id and price > 0 and type_code in ("ACHAT", "VENTE"):
                # Déterminer si l'actif est non coté (nouveau ou existant)
                atype_effectif = new_atype
                if atype_effectif is None:
                    # Actif existant — on vérifie son type en base
                    from services import panel_data_access as pda
                    row = pda.get_asset_type(self._conn, asset_id)
                    atype_effectif = row["asset_type"] if row else ""
                if atype_effectif in _ASSET_TYPES_NON_COTES:
                    try:
                        repo.upsert_price(self._conn, asset_id, date_str, price)
                    except Exception as e:
                        logger.warning("Impossible d'upsert le prix pour actif non coté: %s", e)

            self._result_lbl.setStyleSheet(STYLE_STATUS_SUCCESS)
            self._result_lbl.setText(
                f"Opération enregistrée ✅ — {type_code} {amount:.2f} le {date_str}"
            )
            # Reset des champs montants
            self._qty_spin.setValue(0)
            self._price_spin.setValue(0)
            self._total_spin.setValue(0)
            self._fees_spin.setValue(0)
            self._note_edit.clear()

        except Exception as e:
            logger.error("Erreur enregistrement opération: %s", e, exc_info=True)
            self._show_error(str(e))

    def _show_error(self, msg: str) -> None:
        self._result_lbl.setStyleSheet(STYLE_STATUS_ERROR)
        self._result_lbl.setText(f"Erreur : {msg}")
