import pandas as pd
import numpy as np
from ..prevision_models import PrevisionBase, PrevisionConfig, PrevisionResult

def run_monte_carlo_projection(base: PrevisionBase, config: PrevisionConfig) -> PrevisionResult:
    """
    Moteur probabiliste (Monte Carlo) patrimonial par classes d'actifs.
    Génère des rendements aléatoires pour chaque bucket en utilisant une
    distribution normale multivariée (avec corrélation).
    """
    if config.seed is not None:
        np.random.seed(config.seed)
        
    years = config.horizon_years
    months = years * 12
    n_sims = config.num_simulations
    
    # 1. Préparation des buckets
    # Ordre strict: Liquidités, Bourse, Immobilier, PE, Entreprises, Crypto
    bucket_names = ["Liquidités", "Bourse", "Immobilier", "PE", "Entreprises", "Crypto"]
    
    breakdown = base.assets_breakdown
    initial_values = np.array([breakdown.get(b, 0.0) for b in bucket_names])
    
    # Poids initiaux pour distribuer l'épargne (fallback: tout en liquidités si pas d'actifs)
    total_assets = initial_values.sum()
    if total_assets > 0:
        savings_distribution = initial_values / total_assets
    else:
        savings_distribution = np.zeros(len(bucket_names))
        savings_distribution[0] = 1.0 # 100% sur Liquidités
        
    # 2. Paramètres statistiques mensuels
    mu_annual = np.array([config.expected_returns.get(b, 0.0) for b in bucket_names])
    vol_annual = np.array([config.expected_volatilities.get(b, 0.0) for b in bucket_names])
    
    mu_monthly = mu_annual / 12.0
    sigma_monthly = vol_annual / np.sqrt(12.0)
    inflation_monthly = config.inflation_rate / 12.0
    
    # 3. Matrice de corrélation et covariance
    if config.correlation_matrix is not None:
        corr_matrix = np.array(config.correlation_matrix)
    else:
        # Corrélation par défaut : identité (indépendants) avec un léger lien Bourse/PE (ex: 0.5)
        corr_matrix = np.eye(len(bucket_names))
        idx_bourse = bucket_names.index("Bourse")
        idx_pe = bucket_names.index("PE")
        corr_matrix[idx_bourse, idx_pe] = 0.5
        corr_matrix[idx_pe, idx_bourse] = 0.5
        
    # Covariance = diag(sigma) * Corr * diag(sigma)
    diag_sigma = np.diag(sigma_monthly)
    cov_matrix = diag_sigma @ corr_matrix @ diag_sigma
    
    # 4. Simulation Multivariée
    # returns shape : (n_sims, n_months, n_buckets)
    random_returns = np.random.multivariate_normal(mu_monthly, cov_matrix, size=(n_sims, months))
    
    # 5. Trajectoires
    # np array (n_sims, n_months + 1, n_buckets)
    paths_buckets = np.zeros((n_sims, months + 1, len(bucket_names)))
    paths_buckets[:, 0, :] = initial_values
    
    savings_per_bucket_monthly = config.monthly_contribution * savings_distribution
    
    for t in range(1, months + 1):
        # r réel = r brut - inflation
        r_real = random_returns[:, t-1, :] - inflation_monthly
        paths_buckets[:, t, :] = paths_buckets[:, t-1, :] * (1 + r_real) + savings_per_bucket_monthly
        # On empêche un actif d'être négatif à part si c'était géré (non géré en V1)
        paths_buckets[:, t, :] = np.maximum(0, paths_buckets[:, t, :])
        
    # 6. Recomposition du patrimoine total
    # Net worth total par mois et simulation
    sums_assets = paths_buckets.sum(axis=2)
    dates = pd.date_range(start=pd.Timestamp.today().normalize().replace(day=1), periods=months+1, freq='MS')
    
    if base.debts_schedule is not None:
        # Alignement de l'échéancier de dette sur les dates de simulation
        debt_values = base.debts_schedule.reindex(dates).fillna(0.0).values
        # Soustraction par broadcasting : (n_sims, n_steps) - (n_steps,)
        paths_total = sums_assets - debt_values
    else:
        # Fallback sur la dette fixe si l'échéancier est absent
        paths_total = sums_assets - base.current_credits
    
    df_paths = pd.DataFrame(paths_total.T, index=dates)
    
    median_series = df_paths.median(axis=1)
    p10_series = df_paths.quantile(0.10, axis=1)
    p90_series = df_paths.quantile(0.90, axis=1)
    
    result = PrevisionResult(
        config=config,
        base=base,
        median_series=median_series,
        percentile_10_series=p10_series,
        percentile_90_series=p90_series,
        trajectories_df=df_paths,
        final_net_worth_median=float(median_series.iloc[-1])
    )
    
    return result
