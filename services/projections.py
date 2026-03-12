"""
services/projections.py
Projections patrimoniales multi-scénarios.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScenarioParams:
    """Paramètres d'un scénario de projection."""
    label: str = "Base"
    taux_bourse_annuel: float = 7.0        # %
    taux_pe_annuel: float = 10.0           # %
    epargne_mensuelle: float = 1_000.0     # €/mois
    inflation_annuelle: float = 2.0        # % (déflateur)
    # Crédit : diminution mensuelle du CRD (remboursement moyen)
    remboursement_mensuel_credit: float = 0.0  # € (amortissement mensuel moyen)


def project_patrimoine(
    patrimoine_initial: dict,
    scenario: ScenarioParams,
    horizon_ans: int = 10,
) -> pd.DataFrame:
    """
    Projection mensuelle du patrimoine.

    patrimoine_initial keys:
      - bank (liquidités bancaires)
      - bourse (holdings bourse)
      - pe (private equity)
      - ent (entreprises)
      - credits (CRD total, positif)

    Retourne un DataFrame avec colonnes :
      mois, bank, bourse, pe, ent, credits,
      patrimoine_brut, patrimoine_net, patrimoine_net_reel
    """
    bank = float(patrimoine_initial.get("bank", 0.0))
    bourse = float(patrimoine_initial.get("bourse", 0.0))
    pe = float(patrimoine_initial.get("pe", 0.0))
    ent = float(patrimoine_initial.get("ent", 0.0))
    credits = float(patrimoine_initial.get("credits", 0.0))

    r_bourse_m = (1 + scenario.taux_bourse_annuel / 100) ** (1 / 12) - 1
    r_pe_m = (1 + scenario.taux_pe_annuel / 100) ** (1 / 12) - 1
    defl_m = (1 + scenario.inflation_annuelle / 100) ** (1 / 12)  # facteur inflation mensuel

    n_mois = horizon_ans * 12
    rows = []

    for m in range(n_mois + 1):
        brut = bank + bourse + pe + ent
        net = brut - credits
        # Patrimoine net en euros constants (début de simulation)
        net_reel = net / (defl_m ** m)

        rows.append({
            "mois": m,
            "annee": m / 12,
            "bank": round(bank, 2),
            "bourse": round(bourse, 2),
            "pe": round(pe, 2),
            "ent": round(ent, 2),
            "credits": round(credits, 2),
            "patrimoine_brut": round(brut, 2),
            "patrimoine_net": round(net, 2),
            "patrimoine_net_reel": round(net_reel, 2),
        })

        if m < n_mois:
            # Capitalisation
            bourse *= (1 + r_bourse_m)
            pe *= (1 + r_pe_m)
            # Épargne mensuelle -> ajoutée en banque (modèle simple)
            bank += scenario.epargne_mensuelle
            # Remboursement crédit
            credits = max(0.0, credits - scenario.remboursement_mensuel_credit)

    return pd.DataFrame(rows)


def compute_three_scenarios(
    patrimoine_initial: dict,
    epargne_base: float,
    horizon_ans: int = 10,
    remboursement_mensuel: float = 0.0,
) -> dict[str, pd.DataFrame]:
    """
    Calcule 3 scénarios (pessimiste, base, optimiste).
    Retourne un dict label -> DataFrame.
    """
    scenarios = [
        ScenarioParams(
            label="Pessimiste",
            taux_bourse_annuel=4.0,
            taux_pe_annuel=5.0,
            epargne_mensuelle=epargne_base * 0.8,
            inflation_annuelle=3.0,
            remboursement_mensuel_credit=remboursement_mensuel,
        ),
        ScenarioParams(
            label="Base",
            taux_bourse_annuel=7.0,
            taux_pe_annuel=10.0,
            epargne_mensuelle=epargne_base,
            inflation_annuelle=2.0,
            remboursement_mensuel_credit=remboursement_mensuel,
        ),
        ScenarioParams(
            label="Optimiste",
            taux_bourse_annuel=10.0,
            taux_pe_annuel=15.0,
            epargne_mensuelle=epargne_base * 1.2,
            inflation_annuelle=1.0,
            remboursement_mensuel_credit=remboursement_mensuel,
        ),
    ]

    return {s.label: project_patrimoine(patrimoine_initial, s, horizon_ans) for s in scenarios}


def summary_table(results: dict[str, pd.DataFrame], horizons: list[int] = None) -> pd.DataFrame:
    """
    Tableau résumé patrimoine net à différents horizons pour les 3 scénarios.
    horizons: liste d'années (ex: [1, 3, 5, 10])
    """
    if horizons is None:
        horizons = [1, 3, 5, 10]

    rows = []
    for label, df in results.items():
        row = {"Scénario": label}
        for h in horizons:
            m = h * 12
            sub = df[df["mois"] == m]
            if not sub.empty:
                row[f"{h} an(s)"] = round(float(sub.iloc[0]["patrimoine_net"]), 0)
            else:
                row[f"{h} an(s)"] = None
        rows.append(row)

    return pd.DataFrame(rows)
