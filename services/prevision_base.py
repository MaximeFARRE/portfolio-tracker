import logging
import pandas as pd
from typing import Dict, Any, List
from .prevision_models import PrevisionBase

logger = logging.getLogger(__name__)


def _get_fire_annual_expenses(conn, scope_type: str, scope_id) -> float:
    """
    Retourne les dépenses annuelles moyennes (base de calcul FIRE)
    à partir du cashflow des 12 derniers mois disponibles.
    """
    try:
        from services.cashflow import get_cashflow_for_scope
        df_cf = get_cashflow_for_scope(conn, scope_type, scope_id)
        if df_cf is None or df_cf.empty:
            return 0.0
        last_12 = df_cf.tail(12)
        if "expenses" not in last_12.columns:
            return 0.0
        avg_monthly = float(last_12["expenses"].mean())
        return avg_monthly * 12.0
    except Exception as exc:
        logger.warning("Impossible de calculer fire_annual_expenses pour %s=%s : %s",
                       scope_type, scope_id, exc)
        return 0.0

def _get_aggregated_debts_schedule(conn, person_ids: List[int], horizon_years: int = 30) -> pd.Series:
    """
    Agrège les restes à vivre (CRD) de tous les crédits actifs pour une liste de personnes.
    Retourne une série temporelle mensuelle.
    """
    from services.credits import list_credits_by_person, get_amortissements
    
    # On commence au 1er du mois courant
    start_date = pd.Timestamp.today().normalize().replace(day=1)
    # On voit large (30 ans par défaut)
    end_date = start_date + pd.DateOffset(years=horizon_years)
    months = pd.date_range(start=start_date, end=end_date, freq='MS')
    
    total_crd = pd.Series(0.0, index=months)
    
    for pid in person_ids:
        try:
            credits_df = list_credits_by_person(conn, pid, only_active=True)
            for _, row in credits_df.iterrows():
                cid = int(row["id"])
                amort_df = get_amortissements(conn, cid)
                if amort_df.empty:
                    continue
                
                amort_df["date_echeance"] = pd.to_datetime(amort_df["date_echeance"])
                # Sécurisation des dates au 1er du mois pour alignement
                amort_df["date_echeance"] = amort_df["date_echeance"].dt.to_period("M").dt.to_timestamp()
                
                # On prend le dernier CRD connu pour chaque mois (au cas où il y aurait plusieurs lignes)
                amort_series = amort_df.groupby("date_echeance")["crd"].last()
                
                # Alignement sur nos mois de projection
                reindexed = amort_series.reindex(months)
                
                # Fallback : si la projection va plus loin que l'échéancier, la dette est de 0
                # Si l'échéancier commence après le début de la projection, on pourrait boucher, 
                # mais list_credits_by_person(only_active=True) suggère qu'ils sont en cours.
                reindexed = reindexed.fillna(0.0)
                
                total_crd += reindexed
        except Exception as exc:
            logger.warning(f"Erreur lors de l'agrégation des crédits pour person_id={pid}: {exc}")
            
    return total_crd

def build_prevision_base_for_scope(conn, scope_type: str, scope_id) -> PrevisionBase:
    """
    Construit la base patrimoniale de départ pour une projection,
    en respectant strictement les sources de vérité existantes (SSOT).
    """
    logger.info(f"Construction de la base de prévision pour {scope_type}={scope_id}")
    
    scope_type_lower = scope_type.strip().lower()
    warnings = []
    metadata = {"scope_type": scope_type, "scope_id": str(scope_id)}
    
    base_kwargs: Dict[str, Any] = {
        "current_net_worth": 0.0,
        "current_cash": 0.0,
        "current_equity": 0.0,
        "current_real_estate": 0.0,
        "current_pe": 0.0,
        "current_business": 0.0,
        "current_crypto": 0.0,
        "current_credits": 0.0,
        "current_savings_per_year": 0.0,
        "current_passive_income_per_year": 0.0,
    }

    if scope_type_lower == "person":
        from services.vue_ensemble_metrics import get_vue_ensemble_metrics
        metrics = get_vue_ensemble_metrics(conn, scope_id)
        
        base_kwargs["current_net_worth"] = metrics.get("net") or 0.0
        base_kwargs["current_cash"] = metrics.get("liq") or 0.0
        base_kwargs["current_equity"] = metrics.get("bourse") or 0.0
        base_kwargs["current_real_estate"] = metrics.get("immo_value") or 0.0
        base_kwargs["current_pe"] = metrics.get("pe_value") or 0.0
        base_kwargs["current_business"] = metrics.get("ent_value") or 0.0
        base_kwargs["current_credits"] = metrics.get("credits") or 0.0
        
        # Dette dynamique
        base_kwargs["debts_schedule"] = _get_aggregated_debts_schedule(conn, [scope_id])
        
        # Flux
        # Epargne: on extrapole la moyenne mensuelle 12m sur 1 an
        capa_avg = metrics.get("capacite_epargne_avg") or 0.0
        base_kwargs["current_savings_per_year"] = float(capa_avg * 12)
        
        metadata["asof_date"] = metrics.get("asof_date", "")

    elif scope_type_lower == "family":
        from services.family_dashboard import get_family_series, compute_allocations_family, compute_family_kpis
        from services.cashflow import compute_savings_metrics

        family_id = int(scope_id) if scope_id is not None else 1
        df_family = get_family_series(conn, family_id=family_id)
        if df_family is not None and not df_family.empty:
            kpis = compute_family_kpis(df_family)
            allocs = compute_allocations_family(df_family)
            
            base_kwargs["current_net_worth"] = kpis.get("patrimoine_net", 0.0)
            base_kwargs["current_credits"] = kpis.get("credits_remaining", 0.0)
            
            base_kwargs["current_cash"] = allocs.get("Liquidités", 0.0)
            base_kwargs["current_equity"] = allocs.get("Bourse", 0.0)
            base_kwargs["current_pe"] = allocs.get("Private Equity", 0.0)
            base_kwargs["current_business"] = allocs.get("Entreprises", 0.0)
            base_kwargs["current_real_estate"] = allocs.get("Immobilier", 0.0)
            
            # Pour l'épargne: on manque de get_family_flux_summary en SSOT directe agglomérée,
            # et le computed savings metric ne marche bien que pour 'person'.
            # On utilise le cashflow_for_scope générique.
            from services.cashflow import get_cashflow_for_scope
            df_cf = get_cashflow_for_scope(conn, "family", family_id)
            if df_cf is not None and not df_cf.empty:
                last_12 = df_cf.tail(12)
                base_kwargs["current_savings_per_year"] = float(last_12["savings"].mean() * 12) if not last_12.empty else 0.0
            
            metadata["asof_date"] = str(kpis.get("asof", ""))

        # Dette dynamique famille
        from services.repositories import list_people
        people_df = list_people(conn)
        if people_df is not None and not people_df.empty:
            p_ids = people_df["id"].tolist()
            base_kwargs["debts_schedule"] = _get_aggregated_debts_schedule(conn, p_ids)
    else:
        warnings.append(f"Type de scope '{scope_type}' non reconnu.")

    # Champs non supportés en V1
    warnings.append("Crypto n'est pas encore directement géré par une agrégation SSOT, forcé à 0.0")
    warnings.append("Revenus passifs totaux non réconciliés SSOT pour base prevision, forcé à 0.0")

    # Dépenses annuelles pour le calcul FIRE
    base_kwargs["fire_annual_expenses"] = _get_fire_annual_expenses(
        conn, scope_type_lower, scope_id
    )

    # Si l'échéancier de dette est vide / tout à 0 alors que le snapshot indique
    # un crédit > 0, on repasse en fallback "dette fixe" côté engine (debts_schedule=None)
    # pour préserver la cohérence au mois 0 (net simulé = net snapshot).
    schedule = base_kwargs.get("debts_schedule")
    current_credits = float(base_kwargs.get("current_credits") or 0.0)
    if isinstance(schedule, pd.Series):
        schedule_num = pd.to_numeric(schedule, errors="coerce").fillna(0.0)
        if current_credits > 0.0 and (schedule_num.empty or float(schedule_num.abs().max()) == 0.0):
            base_kwargs["debts_schedule"] = None
            warnings.append(
                "Échéancier de dette indisponible : fallback sur current_credits fixe pour cohérence du net."
            )
        else:
            base_kwargs["debts_schedule"] = schedule_num

    # Écriture
    base = PrevisionBase(
        **base_kwargs,
        warnings=warnings,
        metadata=metadata
    )
    
    return base
