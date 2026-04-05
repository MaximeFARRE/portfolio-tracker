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


_PATRIMOINE_KEYS = {"bank", "bourse", "pe", "ent", "immobilier", "credits"}


def _validate_patrimoine_initial(d: dict) -> None:
    """
    Vérifie que le dict patrimoine_initial est complet et cohérent.

    Règles :
    - Toutes les clés de _PATRIMOINE_KEYS doivent être présentes.
    - Chaque valeur d'actif (bank, bourse, pe, ent, immobilier) doit être >= 0.
    - credits doit être >= 0 (c'est un CRD, toujours positif ou nul).

    Utiliser load_initial_patrimoine_from_family() pour construire ce dict
    depuis la base — cela garantit la cohérence assets/dettes.
    """
    missing = _PATRIMOINE_KEYS - d.keys()
    if missing:
        raise ValueError(
            f"patrimoine_initial incomplet — clés manquantes : {sorted(missing)}. "
            "Utilisez load_initial_patrimoine_from_family() pour un dict cohérent."
        )
    asset_keys = _PATRIMOINE_KEYS - {"credits"}
    for k in asset_keys:
        if float(d[k]) < 0:
            raise ValueError(
                f"patrimoine_initial['{k}'] = {d[k]} est négatif — les actifs doivent être >= 0."
            )
    if float(d["credits"]) < 0:
        raise ValueError(
            f"patrimoine_initial['credits'] = {d['credits']} est négatif — "
            "credits représente un CRD (toujours positif ou nul)."
        )


def project_patrimoine(
    patrimoine_initial: dict,
    scenario: ScenarioParams,
    horizon_ans: int = 10,
) -> pd.DataFrame:
    """
    Projection mensuelle du patrimoine.

    patrimoine_initial keys (toutes obligatoires) :
      - bank       : liquidités bancaires
      - bourse     : holdings bourse (capitalisé au taux_bourse_annuel)
      - pe         : private equity (capitalisé au taux_pe_annuel)
      - ent        : entreprises (statique)
      - immobilier : valorisation immobilière (statique)
      - credits    : CRD total, positif — doit correspondre aux dettes réelles

    IMPORTANT : modifier un actif sans ajuster credits produit un patrimoine_net
    incohérent avec la réalité. Préférer load_initial_patrimoine_from_family()
    comme point de départ, puis ajuster assets ET credits ensemble si besoin.

    Retourne un DataFrame avec colonnes :
      mois, annee, bank, bourse, pe, ent, immobilier, credits,
      patrimoine_brut, patrimoine_net, patrimoine_net_reel
    """
    _validate_patrimoine_initial(patrimoine_initial)
    bank = float(patrimoine_initial.get("bank", 0.0))
    bourse = float(patrimoine_initial.get("bourse", 0.0))
    pe = float(patrimoine_initial.get("pe", 0.0))
    ent = float(patrimoine_initial.get("ent", 0.0))
    immobilier = float(patrimoine_initial.get("immobilier", 0.0))
    credits = float(patrimoine_initial.get("credits", 0.0))

    r_bourse_m = (1 + scenario.taux_bourse_annuel / 100) ** (1 / 12) - 1
    r_pe_m = (1 + scenario.taux_pe_annuel / 100) ** (1 / 12) - 1
    defl_m = (1 + scenario.inflation_annuelle / 100) ** (1 / 12)  # facteur inflation mensuel

    n_mois = horizon_ans * 12
    rows = []

    for m in range(n_mois + 1):
        brut = bank + bourse + pe + ent + immobilier
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
            "immobilier": round(immobilier, 2),
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


def load_initial_patrimoine_from_family(conn, family_id: int = 1, person_ids: list[int] | None = None) -> dict:
    """
    Charge le dernier snapshot famille (source canonique),
    avec fallback agrégé personnes si la table famille est vide.
    """
    from services import family_snapshots as fs

    df_family = fs.get_family_weekly_series(conn, family_id=family_id, fallback_person_ids=person_ids or [])
    if df_family is None or df_family.empty:
        return {
            "bank": 0.0,
            "bourse": 0.0,
            "pe": 0.0,
            "ent": 0.0,
            "immobilier": 0.0,
            "credits": 0.0,
        }

    last = df_family.iloc[-1]
    return {
        "bank": float(last.get("liquidites_total", 0.0)),
        "bourse": float(last.get("bourse_holdings", 0.0)),
        "pe": float(last.get("pe_value", 0.0)),
        "ent": float(last.get("ent_value", 0.0)),
        "immobilier": float(last.get("immobilier_value", 0.0)),
        "credits": float(last.get("credits_remaining", 0.0)),
    }


def compute_three_scenarios(
    patrimoine_initial: dict,
    epargne_base: float,
    horizon_ans: int = 10,
    remboursement_mensuel: float = 0.0,
) -> dict[str, pd.DataFrame]:
    """
    Calcule 3 scénarios (pessimiste, base, optimiste).
    Retourne un dict label -> DataFrame.

    patrimoine_initial doit contenir les 6 clés de _PATRIMOINE_KEYS.
    Construire via load_initial_patrimoine_from_family() garantit la cohérence
    entre les actifs et les dettes (credits = CRD réel, pas dérivé des assets).
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
