"""
Page Personnes — remplace pages/2_Personnes.py
Contient un sélecteur de personne, 8 onglets fixes + onglets dynamiques par compte.
"""
import logging
from typing import Optional
import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QTabWidget, QScrollArea, QSplitter
)
from PyQt6.QtCore import Qt
from qt_ui.components.animated_tab import AnimatedTabWidget

from qt_ui.panels.vue_ensemble_panel import VueEnsemblePanel
from qt_ui.panels.depenses_panel import DepensesPanel
from qt_ui.panels.revenus_panel import RevenusPanel
from qt_ui.panels.credits_overview_panel import CreditsOverviewPanel
from qt_ui.panels.private_equity_panel import PrivateEquityPanel
from qt_ui.panels.entreprises_panel import EntreprisesPanel
from qt_ui.panels.immobilier_panel import ImmobilierPanel
from qt_ui.panels.liquidites_panel import LiquiditesPanel
from qt_ui.panels.bourse_global_panel import BourseGlobalPanel
from qt_ui.panels.ajout_compte_panel import AjoutComptePanel

from utils.libelles import afficher_type_compte
from qt_ui.theme import (
    BG_PRIMARY, BG_SIDEBAR, BG_CARD, BORDER_SUBTLE, BORDER_DEFAULT,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DISABLED,
    ACCENT_BLUE, BG_ACTIVE, STYLE_TAB, STYLE_SCROLLAREA,
    STYLE_TITLE_LARGE,
)

logger = logging.getLogger(__name__)

_COMBO_STYLE = f"""
    QComboBox {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_DEFAULT};
                border-radius: 4px; padding: 6px 10px; font-size: 14px; min-width: 160px; }}
    QComboBox::drop-down {{ border: none; }}
    QComboBox QAbstractItemView {{ background: {BG_CARD}; color: {TEXT_PRIMARY}; selection-background-color: {BG_ACTIVE}; }}
"""


def _make_account_panel(conn, person_id: int, account_id: int, account_type: str, parent=None):
    """Instancie le bon panel selon le type de compte."""
    atype = account_type.upper()
    if atype == "BANQUE":
        from qt_ui.panels.compte_banque_panel import CompteBanquePanel
        return CompteBanquePanel(conn, person_id, account_id, parent=parent)
    elif atype in ("PEA", "PEA_PME", "CTO", "CRYPTO",
                   "ASSURANCE_VIE", "PER", "PEE"):
        from qt_ui.panels.compte_bourse_panel import CompteBoursePanel
        return CompteBoursePanel(conn, person_id, account_id, atype, parent=parent)
    elif atype == "CREDIT":
        from qt_ui.panels.compte_credit_panel import CompteCreditPanel
        return CompteCreditPanel(conn, person_id, account_id, parent=parent)
    else:
        # Fallback générique (PE, IMMOBILIER, etc.)
        from qt_ui.panels.saisie_panel import SaisiePanel
        w = QWidget(parent)
        w.setStyleSheet(f"background: {BG_PRIMARY};")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 12, 12)
        lbl = QLabel(f"Compte de type {account_type}")
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        v.addWidget(lbl)
        saisie = SaisiePanel(conn, person_id, account_id, account_type)
        v.addWidget(saisie)
        v.addStretch()
        return w


class PersonnesPage(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self._conn = conn
        self._current_person_id: Optional[int] = None
        self._people_df: pd.DataFrame = pd.DataFrame()
        self._account_panels: dict = {}

        self.setStyleSheet(f"background: {BG_PRIMARY};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header avec sélecteur de personne
        header = QWidget()
        header.setStyleSheet(f"background: {BG_SIDEBAR}; border-bottom: 1px solid {BORDER_SUBTLE};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)

        title = QLabel("Personnes")
        title.setStyleSheet(STYLE_TITLE_LARGE)
        header_layout.addWidget(title)

        header_layout.addWidget(QLabel("  →  "))
        self._person_combo = QComboBox()
        self._person_combo.setStyleSheet(_COMBO_STYLE)
        self._person_combo.currentIndexChanged.connect(self._on_person_changed)
        header_layout.addWidget(self._person_combo)
        header_layout.addStretch()
        layout.addWidget(header)

        # ── Zone de contenu (onglets fixes + onglets comptes)
        content = QWidget()
        content.setStyleSheet(f"background: {BG_PRIMARY};")
        content_v = QVBoxLayout(content)
        content_v.setContentsMargins(0, 0, 0, 0)
        content_v.setSpacing(0)

        # Onglets FIXES (8 onglets)
        self._fixed_tabs = AnimatedTabWidget()
        self._fixed_tabs.setStyleSheet(STYLE_TAB)
        self._fixed_tabs.currentChanged.connect(self._on_fixed_tab_changed)

        # Les panels fixes sont créés avec person_id=0, mis à jour au changement
        self._panel_vue = VueEnsemblePanel(conn, 0)
        self._panel_dep = DepensesPanel(conn, 0)
        self._panel_rev = RevenusPanel(conn, 0)
        self._panel_credits = CreditsOverviewPanel(conn, 0)
        self._panel_pe = PrivateEquityPanel(conn, 0)
        self._panel_ent = EntreprisesPanel(conn, 0)
        self._panel_immo = ImmobilierPanel(conn, 0)
        self._panel_liq = LiquiditesPanel(conn, 0)
        self._panel_bourse = BourseGlobalPanel(conn, 0)

        self._fixed_tabs.addTab(self._panel_vue, "🔍  Vue d'ensemble")
        self._fixed_tabs.addTab(self._panel_dep, "💸  Dépenses")
        self._fixed_tabs.addTab(self._panel_rev, "💰  Revenus")
        self._fixed_tabs.addTab(self._panel_credits, "🏦  Crédits")
        self._fixed_tabs.addTab(self._panel_pe, "🌱  Private Equity")
        self._fixed_tabs.addTab(self._panel_ent, "🏢  Entreprises")
        self._fixed_tabs.addTab(self._panel_immo, "🏠  Immobilier")
        self._fixed_tabs.addTab(self._panel_liq, "💧  Liquidités")
        self._fixed_tabs.addTab(self._panel_bourse, "📈  Bourse globale")

        content_v.addWidget(self._fixed_tabs)

        # Séparateur + section Comptes
        sep_label = QLabel("  Comptes")
        sep_label.setStyleSheet(f"background: {BG_SIDEBAR}; color: {TEXT_DISABLED}; font-size: 11px; font-weight: bold; letter-spacing: 1px; padding: 6px 20px; border-top: 1px solid {BORDER_SUBTLE};")
        content_v.addWidget(sep_label)

        # Panel d'ajout de compte
        self._ajout_panel = AjoutComptePanel(conn, 0)
        self._ajout_panel.account_created.connect(self._on_account_created)
        add_w = QWidget()
        add_w.setStyleSheet(f"background: {BG_PRIMARY};")
        add_v = QVBoxLayout(add_w)
        add_v.setContentsMargins(12, 8, 12, 8)
        add_v.addWidget(self._ajout_panel)
        content_v.addWidget(add_w)

        # Onglets dynamiques (comptes)
        self._account_tabs = AnimatedTabWidget()
        self._account_tabs.setStyleSheet(STYLE_TAB)
        self._account_tabs.currentChanged.connect(self._on_account_tab_changed)
        content_v.addWidget(self._account_tabs)

        # Un seul QScrollArea pour toute la zone de contenu
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setStyleSheet(STYLE_SCROLLAREA)
        outer_scroll.setWidget(content)
        layout.addWidget(outer_scroll, 1)  # stretch=1 pour occuper tout l'espace restant

        # Charger les personnes
        self._load_people()

    # ── Chargement des personnes ──────────────────────────────────────────────

    def _load_people(self) -> None:
        try:
            from services import repositories as repo
            self._people_df = repo.list_people(self._conn)
            self._person_combo.blockSignals(True)
            self._person_combo.clear()
            if self._people_df is not None and not self._people_df.empty:
                for _, row in self._people_df.iterrows():
                    self._person_combo.addItem(str(row["name"]), int(row["id"]))
            self._person_combo.blockSignals(False)

            if self._person_combo.count() > 0:
                self._on_person_changed(0)
        except Exception as e:
            logger.error("Erreur chargement personnes : %s", e)

    # ── Changement de personne ────────────────────────────────────────────────

    def _on_person_changed(self, index: int) -> None:
        person_id = self._person_combo.itemData(index)
        if person_id is None:
            return
        self._current_person_id = int(person_id)

        # Mettre à jour tous les panels fixes
        self._panel_vue.set_person(self._current_person_id)
        self._panel_dep.set_person(self._current_person_id)
        self._panel_rev.set_person(self._current_person_id)
        self._panel_credits.set_person(self._current_person_id)
        self._panel_pe.set_person(self._current_person_id)
        self._panel_ent.set_person(self._current_person_id)
        self._panel_immo.set_person(self._current_person_id)
        self._panel_liq.set_person(self._current_person_id)
        self._panel_bourse.set_person(self._current_person_id)
        self._ajout_panel.set_person(self._current_person_id)

        # Reconstruire les onglets de comptes
        self._rebuild_account_tabs()

        # Rafraîchir l'onglet fixe actif
        self._on_fixed_tab_changed(self._fixed_tabs.currentIndex())

    def select_person_by_name(self, name: str) -> None:
        """Sélectionne une personne par son nom (appelé depuis la NavSidebar)."""
        for i in range(self._person_combo.count()):
            if self._person_combo.itemText(i) == name:
                self._person_combo.setCurrentIndex(i)
                break

    # ── Onglets fixes ─────────────────────────────────────────────────────────

    def _on_fixed_tab_changed(self, index: int) -> None:
        if self._current_person_id is None:
            return
        panels = [
            self._panel_vue, self._panel_dep, self._panel_rev,
            self._panel_credits, self._panel_pe, self._panel_ent,
            self._panel_immo, self._panel_liq, self._panel_bourse,
        ]
        if 0 <= index < len(panels):
            panels[index].refresh()

    # ── Onglets comptes dynamiques ────────────────────────────────────────────

    def _rebuild_account_tabs(self) -> None:
        """Reconstruit les onglets dynamiques selon les comptes de la personne."""
        # Fermer et vider les anciens
        self._account_tabs.clear()
        self._account_panels.clear()

        if self._current_person_id is None:
            return

        try:
            from services import repositories as repo

            comptes = repo.list_accounts(self._conn, person_id=self._current_person_id)
            if comptes is None or comptes.empty:
                return

            # Masquer les sous-comptes
            try:
                sub_ids = repo.list_all_subaccount_ids(self._conn, self._current_person_id)
                if sub_ids:
                    comptes = comptes[~comptes["id"].isin(sub_ids)].copy()
            except Exception as e:
                logger.warning("Erreur récupération sous-comptes : %s", e)

            comptes = comptes.sort_values(["account_type", "name"]).reset_index(drop=True)

            for _, row in comptes.iterrows():
                account_id = int(row["id"])
                account_type = str(row["account_type"])
                account_name = str(row["name"])
                label = f"{account_name} ({afficher_type_compte(account_type)})"

                panel = _make_account_panel(
                    self._conn, self._current_person_id, account_id, account_type
                )
                self._account_tabs.addTab(panel, label)
                self._account_panels[account_id] = panel

        except Exception as e:
            logger.error("Erreur reconstruction onglets comptes : %s", e)

    def _on_account_tab_changed(self, index: int) -> None:
        # Trouver le panel actif et le rafraîchir
        w = self._account_tabs.widget(index)
        if w is not None and hasattr(w, "refresh"):
            w.refresh()

    def _on_account_created(self) -> None:
        """Appelé quand un compte vient d'être créé."""
        self._rebuild_account_tabs()

    # ── Rafraîchissement global ───────────────────────────────────────────────

    def refresh(self) -> None:
        """Appelé quand on navigue vers cette page."""
        if self._current_person_id is not None:
            self._on_fixed_tab_changed(self._fixed_tabs.currentIndex())
