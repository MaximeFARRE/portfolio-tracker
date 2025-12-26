# services/sankey.py
from __future__ import annotations
import sqlite3
from typing import Dict, List, Tuple, Optional

# ---------------------------
# Catégories finales (N3) -> Bloc (N2)
# ---------------------------
N3_TO_N2_DEPENSES: Dict[str, str] = {
    # Logement
    "Loyer": "Logement",
    "Charges logement": "Logement",
    "Assurance & entretien logement": "Logement",

    # Vie quotidienne
    "Courses": "Vie quotidienne",
    "Restaurants": "Vie quotidienne",
    "Achats personnels": "Vie quotidienne",
    "Dépenses courantes": "Vie quotidienne",

    # Abonnements
    "Télécoms & Internet": "Abonnements",
    "Loisirs numériques": "Abonnements",

    # Transport
    "Transport quotidien": "Transport",
    "Véhicule": "Transport",
    "Voyages (transport)": "Transport",

    # Loisirs
    "Loisirs & sorties": "Loisirs",
    "Voyages & vacances": "Loisirs",

    # Santé
    "Soins": "Santé",
    "Complémentaire santé": "Santé",

    # Scolarité / Enfants
    "Scolarité": "Scolarité / Enfants",
    "Enfants": "Scolarité / Enfants",

    # Impôts & charges
    "Impôts & charges": "Impôts & charges",

    # Investissements / Épargne
    "Investissements": "Investissements / Épargne",
    "Épargne": "Investissements / Épargne",
}

# Revenus (N3) -> (N2 = Revenus)
REVENUS_N3 = [
    "Salaire",
    "Revenus récurrents",
    "Revenus financiers",
    "Aides & allocations",
    "Autres revenus",
    "Flux financiers",  # tu as dit “tout apparaître”, donc on l’affiche aussi
]

DEPENSES_N2_ORDER = [
    "Logement",
    "Vie quotidienne",
    "Abonnements",
    "Transport",
    "Loisirs",
    "Santé",
    "Scolarité / Enfants",
    "Impôts & charges",
    "Investissements / Épargne",
]

def _sum_by_categorie(conn: sqlite3.Connection, table: str, person_id: int, mois: str) -> Dict[str, float]:
    rows = conn.execute(
        f"""
        SELECT categorie, SUM(montant) AS total
        FROM {table}
        WHERE person_id = ? AND mois = ?
        GROUP BY categorie
        """,
        (person_id, mois)
    ).fetchall()

    out: Dict[str, float] = {}
    for r in rows:
        cat = r[0] if not hasattr(r, "keys") else r["categorie"]
        tot = r[1] if not hasattr(r, "keys") else r["total"]
        out[str(cat)] = float(tot or 0.0)
    return out


def build_cashflow_sankey(
    conn: sqlite3.Connection,
    *,
    person_id: int,
    mois: str,  # format DB: YYYY-MM-01
) -> dict:
    """
    Sortie compatible Plotly Sankey:
    {
      "labels": [...],
      "sources": [...],
      "targets": [...],
      "values":  [...]
    }
    """

    revenus_raw = _sum_by_categorie(conn, "revenus", person_id, mois)
    depenses_raw = _sum_by_categorie(conn, "depenses", person_id, mois)

    # 1) Normaliser: on ne garde que les catégories "finales" (N3).
    #    Si tu as encore des anciennes catégories, elles iront dans "Dépenses courantes".
    revenus_n3: Dict[str, float] = {k: 0.0 for k in REVENUS_N3}
    for cat, amt in revenus_raw.items():
        if cat in revenus_n3:
            revenus_n3[cat] += amt
        else:
            # fallback -> Autres revenus
            revenus_n3["Autres revenus"] += amt

    depenses_n3: Dict[str, float] = {}
    for cat, amt in depenses_raw.items():
        if cat in N3_TO_N2_DEPENSES:
            depenses_n3[cat] = depenses_n3.get(cat, 0.0) + amt
        else:
            # fallback -> Dépenses courantes
            depenses_n3["Dépenses courantes"] = depenses_n3.get("Dépenses courantes", 0.0) + amt

    total_rev = sum(revenus_n3.values())
    total_dep = sum(depenses_n3.values())

    # 2) Construire les nœuds
    # Colonnes:
    # [Revenus N3] -> [Cash disponible] -> [Dépenses N2] -> [Dépenses N3]
    labels: List[str] = []
    idx: Dict[str, int] = {}

    def add_node(name: str) -> int:
        if name in idx:
            return idx[name]
        idx[name] = len(labels)
        labels.append(name)
        return idx[name]

    # Revenus N3
    for k in REVENUS_N3:
        add_node(k)

    cash_node = add_node("Cash disponible")

    # Dépenses N2
    for n2 in DEPENSES_N2_ORDER:
        add_node(n2)

    # Dépenses N3
    for n3 in depenses_n3.keys():
        add_node(n3)

    # Nœuds d’équilibrage (important)
    # - si dépenses > revenus => on ajoute "Financement (épargne/dette)"
    # - si revenus > dépenses => on ajoute "Excédent"
    financing_node = None
    surplus_node = None
    diff = total_dep - total_rev
    if diff > 1e-9:
        financing_node = add_node("Financement (épargne/dette)")
    elif diff < -1e-9:
        surplus_node = add_node("Excédent (épargne)")

    # 3) Liens
    sources: List[int] = []
    targets: List[int] = []
    values: List[float] = []

    def link(a: str, b: str, v: float):
        if v <= 0:
            return
        sources.append(idx[a])
        targets.append(idx[b])
        values.append(float(v))

    # Revenus -> Cash
    for cat, amt in revenus_n3.items():
        link(cat, "Cash disponible", amt)

    # Financement / Excédent pour équilibrer
    if financing_node is not None:
        link("Financement (épargne/dette)", "Cash disponible", diff)
    if surplus_node is not None:
        link("Cash disponible", "Excédent (épargne)", -diff)

    # Cash -> Dépenses N2 (agrégées)
    by_n2: Dict[str, float] = {n2: 0.0 for n2 in DEPENSES_N2_ORDER}
    for n3, amt in depenses_n3.items():
        n2 = N3_TO_N2_DEPENSES.get(n3, "Vie quotidienne")
        by_n2[n2] = by_n2.get(n2, 0.0) + amt

    for n2, amt in by_n2.items():
        link("Cash disponible", n2, amt)

    # Dépenses N2 -> Dépenses N3
    for n3, amt in depenses_n3.items():
        n2 = N3_TO_N2_DEPENSES.get(n3, "Vie quotidienne")
        link(n2, n3, amt)

    return {
        "labels": labels,
        "sources": sources,
        "targets": targets,
        "values": values,
        "total_rev": total_rev,
        "total_dep": total_dep,
    }
