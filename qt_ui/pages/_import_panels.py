"""
Panels d'import dépenses, revenus et Bankin + styles/helpers partagés.
Extrait de import_page.py pour réduire la taille du fichier principal.
"""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QFileDialog,
)

# ── Styles partagés ──────────────────────────────────────────────────────────

BTN_STYLE = """
    QPushButton { background: #1e3a5f; color: #60a5fa; border: none;
                  border-radius: 6px; padding: 8px 16px; font-size: 13px; }
    QPushButton:hover { background: #1e4a7f; }
    QPushButton:disabled { background: #1a1f2e; color: #475569; }
"""
INPUT_STYLE = "background: #1a1f2e; color: #e2e8f0; border: 1px solid #2a3040; border-radius: 4px; padding: 4px; font-size: 13px;"
LABEL_STYLE = "color: #94a3b8; font-size: 12px; margin-bottom: 2px;"
GROUP_STYLE = (
    "QGroupBox { color: #94a3b8; border: 1px solid #1e2538; border-radius: 6px; "
    "padding: 8px; margin-top: 6px; } "
    "QGroupBox::title { subcontrol-position: top left; padding: 2px 8px; }"
)


def make_label(text: str) -> QLabel:
    """Crée un QLabel avec le style secondaire standard."""
    lbl = QLabel(text)
    lbl.setStyleSheet(LABEL_STYLE)
    return lbl


def build_depenses_panel(conn, get_person_name, refresh_history, table_type: str) -> QWidget:
    """Construit le panel d'import dépenses ou revenus (CSV mensuel).

    Args:
        conn: connexion DB
        get_person_name: callable() → str (nom de la personne sélectionnée)
        refresh_history: callable() pour rafraîchir le tableau historique
        table_type: "depenses" ou "revenus"
    """
    w = QWidget()
    w.setStyleSheet("background: #0e1117;")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    grp = QGroupBox("Fichier CSV")
    grp.setStyleSheet(GROUP_STYLE)
    gv = QVBoxLayout(grp)

    cap = QLabel("Format attendu : Date | Catégories... | Total (Total ignoré)")
    cap.setStyleSheet("color: #64748b; font-size: 11px;")
    gv.addWidget(cap)

    file_row = QHBoxLayout()
    file_lbl = QLabel("Aucun fichier sélectionné")
    file_lbl.setStyleSheet("color: #64748b; font-size: 12px;")
    btn_file = QPushButton("📂  Choisir un CSV")
    btn_file.setStyleSheet(BTN_STYLE)
    file_row.addWidget(btn_file)
    file_row.addWidget(file_lbl, 1)
    gv.addLayout(file_row)

    chk_delete = QCheckBox("Remplacer les données des mois importés (pas l'historique complet)")
    chk_delete.setChecked(True)
    chk_delete.setStyleSheet("color: #94a3b8;")
    gv.addWidget(chk_delete)

    btn_import = QPushButton("✅  Importer")
    btn_import.setStyleSheet(BTN_STYLE)
    gv.addWidget(btn_import)

    result_lbl = QLabel()
    result_lbl.setWordWrap(True)
    result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
    gv.addWidget(result_lbl)

    layout.addWidget(grp)
    layout.addStretch()

    w._file_path = None
    w._file_lbl = file_lbl
    w._chk_delete = chk_delete
    w._result_lbl = result_lbl
    w._table_type = table_type

    def pick_file():
        path, _ = QFileDialog.getOpenFileName(w, "Choisir un CSV", "", "CSV (*.csv)")
        if path:
            w._file_path = path
            file_lbl.setText(path.split("/")[-1].split("\\")[-1])
            result_lbl.setText("")

    def do_import():
        if not w._file_path:
            result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            result_lbl.setText("Veuillez sélectionner un fichier CSV.")
            return
        person = get_person_name()
        try:
            from services.imports import import_wide_csv_to_monthly_table
            from services.import_history import create_batch, close_batch
            from services import import_lookup_service as lookup
            pid = lookup.get_person_id_by_name(conn, person)
            itype = "DEPENSES" if table_type == "depenses" else "REVENUS"
            batch_id = create_batch(
                conn,
                import_type=itype,
                person_id=pid,
                person_name=person,
                filename=os.path.basename(w._file_path),
            )
            with open(w._file_path, "rb") as f:
                res = import_wide_csv_to_monthly_table(
                    conn, table=table_type, person_name=person,
                    file=f, delete_existing=w._chk_delete.isChecked(),
                    import_batch_id=batch_id,
                )
            close_batch(conn, batch_id, res["nb_lignes"])
            result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
            result_lbl.setText(
                f"Import OK ✅ — {res['nb_lignes']} lignes dans {res['table']}\n"
                f"Mois : {res['mois']}\nCatégories : {res['categories']}"
            )
            refresh_history()
        except Exception as e:
            result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            result_lbl.setText(f"Erreur : {e}")

    btn_file.clicked.connect(pick_file)
    btn_import.clicked.connect(do_import)

    return w


def build_bankin_panel(conn, get_person_name, refresh_history) -> QWidget:
    """Construit le panel d'import Bankin (CSV transactions)."""
    w = QWidget()
    w.setStyleSheet("background: #0e1117;")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    grp = QGroupBox("Import Bankin (transactions)")
    grp.setStyleSheet(GROUP_STYLE)
    gv = QVBoxLayout(grp)

    cap = QLabel("Importe le CSV Bankin dans la table transactions (et optionnellement remplit dépenses/revenus).")
    cap.setStyleSheet("color: #64748b; font-size: 11px;")
    gv.addWidget(cap)

    file_row = QHBoxLayout()
    file_lbl = QLabel("Aucun fichier sélectionné")
    file_lbl.setStyleSheet("color: #64748b; font-size: 12px;")
    btn_file = QPushButton("📂  Choisir un CSV Bankin")
    btn_file.setStyleSheet(BTN_STYLE)
    file_row.addWidget(btn_file)
    file_row.addWidget(file_lbl, 1)
    gv.addLayout(file_row)

    chk_fill = QCheckBox("Créer aussi les totaux mensuels (dépenses/revenus)")
    chk_fill.setChecked(True)
    chk_fill.setStyleSheet("color: #94a3b8;")
    gv.addWidget(chk_fill)

    chk_purge = QCheckBox("Supprimer les anciennes transactions de cette personne")
    chk_purge.setChecked(False)
    chk_purge.setStyleSheet("color: #94a3b8;")
    gv.addWidget(chk_purge)

    btn_import = QPushButton("✅  Importer Bankin")
    btn_import.setStyleSheet(BTN_STYLE)
    gv.addWidget(btn_import)

    result_lbl = QLabel()
    result_lbl.setWordWrap(True)
    result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
    gv.addWidget(result_lbl)

    layout.addWidget(grp)
    layout.addStretch()

    w._file_path = None

    def pick_file():
        path, _ = QFileDialog.getOpenFileName(w, "Choisir un CSV Bankin", "", "CSV (*.csv)")
        if path:
            w._file_path = path
            file_lbl.setText(path.split("/")[-1].split("\\")[-1])
            result_lbl.setText("")

    def do_import():
        if not w._file_path:
            result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            result_lbl.setText("Veuillez sélectionner un fichier CSV.")
            return
        person = get_person_name()
        try:
            from services.imports import import_bankin_csv
            from services.import_history import create_batch, close_batch
            from services import import_lookup_service as lookup
            pid = lookup.get_person_id_by_name(conn, person)
            batch_id = create_batch(
                conn,
                import_type="BANKIN",
                person_id=pid,
                person_name=person,
                filename=os.path.basename(w._file_path),
            )
            with open(w._file_path, "rb") as f:
                res = import_bankin_csv(
                    conn, person_name=person, file=f,
                    also_fill_monthly_tables=chk_fill.isChecked(),
                    purge_existing_transactions=chk_purge.isChecked(),
                    import_batch_id=batch_id,
                )
            close_batch(conn, batch_id, res["transactions_inserted"])
            result_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
            result_lbl.setText(
                f"Import Bankin OK ✅ — {res['transactions_inserted']} transactions\n"
                f"Mois dépenses : {res['months_depenses']}\n"
                f"Mois revenus : {res['months_revenus']}"
            )
            refresh_history()
        except Exception as e:
            result_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            result_lbl.setText(f"Erreur : {e}")

    btn_file.clicked.connect(pick_file)
    btn_import.clicked.connect(do_import)

    return w
