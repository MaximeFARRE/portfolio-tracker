"""
Optimisation de frontière efficiente avec contraintes de diversification.

Ce module centralise :
- presets de diversification,
- validation des contraintes utilisateur,
- optimisation sous contraintes (long-only),
- métriques de concentration/diversification.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np


OPT_EPS = 1e-8


@dataclass(frozen=True)
class FrontierConstraints:
    """Contraintes utilisateur pour l'optimisation."""

    max_weight_per_asset: float = 1.0
    min_assets: int = 2
    min_active_weight: float = 0.0
    max_assets: int | None = None
    allow_tiny_residuals: bool = True
    allow_short: bool = False
    concentration_penalty: float = 0.0
    n_points: int = 30


@dataclass(frozen=True)
class FrontierPreset:
    key: str
    label: str
    description: str
    constraints: FrontierConstraints


FRONTIER_PRESETS: dict[str, FrontierPreset] = {
    "free": FrontierPreset(
        key="free",
        label="Libre",
        description="Contraintes minimales, proche de la version existante.",
        constraints=FrontierConstraints(
            max_weight_per_asset=1.0,
            min_assets=2,
            min_active_weight=0.0,
            max_assets=None,
            allow_tiny_residuals=True,
            concentration_penalty=0.0,
        ),
    ),
    "balanced": FrontierPreset(
        key="balanced",
        label="Équilibré",
        description="Diversification modérée (max 25% par actif, min 5 actifs).",
        constraints=FrontierConstraints(
            max_weight_per_asset=0.25,
            min_assets=5,
            min_active_weight=0.01,
            max_assets=None,
            allow_tiny_residuals=False,
            concentration_penalty=0.02,
        ),
    ),
    "diversified": FrontierPreset(
        key="diversified",
        label="Diversifié",
        description="Diversification renforcée (max 15% par actif, min 8 actifs).",
        constraints=FrontierConstraints(
            max_weight_per_asset=0.15,
            min_assets=8,
            min_active_weight=0.01,
            max_assets=None,
            allow_tiny_residuals=False,
            concentration_penalty=0.03,
        ),
    ),
    "very_diversified": FrontierPreset(
        key="very_diversified",
        label="Très diversifié",
        description="Diversification stricte (max 10% par actif, min 10 actifs).",
        constraints=FrontierConstraints(
            max_weight_per_asset=0.10,
            min_assets=10,
            min_active_weight=0.01,
            max_assets=None,
            allow_tiny_residuals=False,
            concentration_penalty=0.04,
        ),
    ),
}


def list_frontier_presets() -> list[dict[str, Any]]:
    """Liste les presets (pour UI)."""
    rows: list[dict[str, Any]] = []
    for key in ("free", "balanced", "diversified", "very_diversified"):
        preset = FRONTIER_PRESETS[key]
        c = preset.constraints
        rows.append(
            {
                "key": preset.key,
                "label": preset.label,
                "description": preset.description,
                "constraints": {
                    "max_weight_per_asset": c.max_weight_per_asset,
                    "min_assets": c.min_assets,
                    "min_active_weight": c.min_active_weight,
                    "max_assets": c.max_assets,
                    "allow_tiny_residuals": c.allow_tiny_residuals,
                },
            }
        )
    return rows


def build_constraints_from_settings(
    settings: dict[str, Any] | None,
    *,
    n_assets: int,
) -> tuple[FrontierConstraints, list[str], list[str]]:
    """
    Construit des contraintes applicables depuis preset + overrides.

    Retourne (constraints, warnings, errors).
    """
    settings = settings or {}
    preset_key = str(settings.get("preset") or "free").strip().lower()
    if preset_key not in FRONTIER_PRESETS:
        preset_key = "free"
    base = FRONTIER_PRESETS[preset_key].constraints

    advanced = settings.get("advanced")
    if isinstance(advanced, dict):
        overrides = advanced
    else:
        overrides = settings

    max_weight = _to_float(
        overrides.get("max_weight_per_asset"),
        default=base.max_weight_per_asset,
    )
    min_assets = _to_int(
        overrides.get("min_assets"),
        default=base.min_assets,
    )
    min_active_weight = _to_float(
        overrides.get("min_active_weight"),
        default=base.min_active_weight,
    )
    max_assets = _to_optional_int(
        overrides.get("max_assets"),
        default=base.max_assets,
    )
    allow_tiny_residuals = _to_bool(
        overrides.get("allow_tiny_residuals"),
        default=base.allow_tiny_residuals,
    )
    allow_short = _to_bool(
        overrides.get("allow_short"),
        default=base.allow_short,
    )
    concentration_penalty = _to_float(
        overrides.get("concentration_penalty"),
        default=base.concentration_penalty,
    )
    n_points = _to_int(
        overrides.get("n_points"),
        default=base.n_points,
    )

    constraints = FrontierConstraints(
        max_weight_per_asset=max_weight,
        min_assets=min_assets,
        min_active_weight=min_active_weight,
        max_assets=max_assets,
        allow_tiny_residuals=allow_tiny_residuals,
        allow_short=allow_short,
        concentration_penalty=concentration_penalty,
        n_points=n_points,
    )
    warnings, errors = validate_constraints(constraints, n_assets=n_assets)
    return constraints, warnings, errors


def validate_constraints(
    constraints: FrontierConstraints,
    *,
    n_assets: int,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    if constraints.allow_short:
        errors.append("La vente à découvert n'est pas supportée dans ce mode.")
        return warnings, errors
    if n_assets < 2:
        errors.append("Au moins 2 actifs sont nécessaires pour l'optimisation.")
        return warnings, errors
    if not (0.0 < constraints.max_weight_per_asset <= 1.0):
        errors.append("Le poids maximum par actif doit être dans ]0, 100].")
    if constraints.min_assets < 2:
        errors.append("Le nombre minimum d'actifs doit être >= 2.")
    if constraints.min_assets > n_assets:
        errors.append(
            f"Le minimum d'actifs ({constraints.min_assets}) dépasse le nombre d'actifs disponibles ({n_assets})."
        )
    if constraints.max_assets is not None and constraints.max_assets < constraints.min_assets:
        errors.append("Le nombre maximum d'actifs doit être >= au minimum d'actifs.")
    if constraints.max_assets is not None and constraints.max_assets > n_assets:
        warnings.append(
            f"Le max d'actifs ({constraints.max_assets}) dépasse les actifs disponibles ({n_assets}) "
            "et sera borné automatiquement."
        )
    if constraints.min_active_weight < 0:
        errors.append("Le poids minimum d'une ligne active doit être >= 0.")
    if constraints.min_active_weight >= constraints.max_weight_per_asset:
        errors.append(
            "Le poids minimum d'une ligne active doit être strictement inférieur au poids maximum par actif."
        )
    if constraints.n_points < 8:
        warnings.append("Le nombre de points de frontière est faible (< 8).")

    min_k = max(2, constraints.min_assets)
    max_k = min(n_assets, constraints.max_assets if constraints.max_assets is not None else n_assets)
    feasible_counts = _feasible_core_counts(constraints, min_k=min_k, max_k=max_k)
    if not feasible_counts:
        errors.append(
            "Contraintes incompatibles : aucun nombre d'actifs ne permet de respecter "
            "simultanément la somme des poids, le max par actif et le min par ligne."
        )
    return warnings, errors


def optimize_efficient_frontier(
    *,
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    tickers: list[str],
    risk_free_rate: float,
    constraints: FrontierConstraints,
    current_weights: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    Calcule min variance, max Sharpe et points de frontière avec contraintes.
    """
    if mean_returns.ndim != 1:
        raise ValueError("mean_returns doit être un vecteur 1D")
    n_assets = int(mean_returns.shape[0])
    if n_assets != len(tickers):
        raise ValueError("tickers et mean_returns ont des dimensions incohérentes")
    if cov_matrix.shape != (n_assets, n_assets):
        raise ValueError("cov_matrix a une dimension incohérente")

    cov = _regularize_cov(cov_matrix)
    warnings, errors = validate_constraints(constraints, n_assets=n_assets)
    if errors:
        return {
            "error": " ".join(errors),
            "warnings": warnings,
            "constraints_applied": _constraints_payload(constraints, n_assets=n_assets),
        }

    min_k = max(2, constraints.min_assets)
    max_k = min(n_assets, constraints.max_assets if constraints.max_assets is not None else n_assets)
    feasible_counts = _feasible_core_counts(constraints, min_k=min_k, max_k=max_k)
    if not feasible_counts:
        return {
            "error": "Aucune combinaison d'actifs ne satisfait les contraintes demandées.",
            "warnings": warnings,
            "constraints_applied": _constraints_payload(constraints, n_assets=n_assets),
        }

    count_candidates = _select_count_candidates(feasible_counts, current_weights=current_weights)

    min_var_solution = _optimize_portfolio_mode(
        mode="min_variance",
        mean_returns=mean_returns,
        cov_matrix=cov,
        risk_free_rate=risk_free_rate,
        constraints=constraints,
        count_candidates=count_candidates,
        current_weights=current_weights,
    )
    max_sharpe_solution = _optimize_portfolio_mode(
        mode="max_sharpe",
        mean_returns=mean_returns,
        cov_matrix=cov,
        risk_free_rate=risk_free_rate,
        constraints=constraints,
        count_candidates=count_candidates,
        current_weights=current_weights,
    )

    if min_var_solution is None or max_sharpe_solution is None:
        return {
            "error": (
                "Impossible de trouver une solution robuste avec les contraintes sélectionnées. "
                "Essayez de réduire le minimum d'actifs, d'augmenter le poids max par actif "
                "ou de relâcher le poids minimum par ligne."
            ),
            "warnings": warnings,
            "constraints_applied": _constraints_payload(constraints, n_assets=n_assets),
        }

    min_var_ret = float(min_var_solution @ mean_returns)
    max_sharpe_ret = float(max_sharpe_solution @ mean_returns)
    low_ret = min(min_var_ret, max_sharpe_ret)
    high_ret = max(min_var_ret, max_sharpe_ret)
    if abs(high_ret - low_ret) < 1e-5:
        low_ret = float(np.min(mean_returns))
        high_ret = float(np.max(mean_returns))

    targets = np.linspace(low_ret, high_ret, max(8, constraints.n_points))
    frontier_points: list[dict[str, float]] = []
    for target_ret in targets:
        sol = _optimize_portfolio_mode(
            mode="target_return",
            mean_returns=mean_returns,
            cov_matrix=cov,
            risk_free_rate=risk_free_rate,
            constraints=constraints,
            count_candidates=count_candidates,
            current_weights=current_weights,
            target_return=target_ret,
        )
        if sol is None:
            continue
        ret_ann = float(sol @ mean_returns) * 100.0
        var_ann = float(sol @ cov @ sol)
        vol_ann = math.sqrt(max(var_ann, 0.0)) * 100.0
        frontier_points.append(
            {
                "vol": vol_ann,
                "ret": ret_ann,
            }
        )

    frontier_points = _unique_points(frontier_points)
    if len(frontier_points) < 4:
        warnings.append(
            "Frontière partielle : certaines cibles de rendement ne sont pas atteignables avec les contraintes actuelles."
        )

    min_metrics = compute_portfolio_metrics(
        min_var_solution,
        mean_returns=mean_returns,
        cov_matrix=cov,
        risk_free_rate=risk_free_rate,
    )
    max_metrics = compute_portfolio_metrics(
        max_sharpe_solution,
        mean_returns=mean_returns,
        cov_matrix=cov,
        risk_free_rate=risk_free_rate,
    )
    min_div = compute_diversification_metrics(
        min_var_solution,
        min_active_weight=constraints.min_active_weight,
    )
    max_div = compute_diversification_metrics(
        max_sharpe_solution,
        min_active_weight=constraints.min_active_weight,
    )

    min_data = {
        **min_metrics,
        "weights": _weights_percent_map(tickers, min_var_solution),
        "weights_raw": min_var_solution.tolist(),
        "diversification": min_div,
    }
    max_data = {
        **max_metrics,
        "weights": _weights_percent_map(tickers, max_sharpe_solution),
        "weights_raw": max_sharpe_solution.tolist(),
        "diversification": max_div,
    }

    return {
        "frontier_points": frontier_points,
        "min_variance": min_data,
        "max_sharpe": max_data,
        "constraints_applied": _constraints_payload(constraints, n_assets=n_assets),
        "warnings": warnings,
    }


def compute_portfolio_metrics(
    weights: np.ndarray,
    *,
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float,
) -> dict[str, float]:
    ret_ann = float(weights @ mean_returns)
    var_ann = float(weights @ cov_matrix @ weights)
    var_ann = max(var_ann, 0.0)
    vol_ann = math.sqrt(var_ann)
    sharpe = (ret_ann - risk_free_rate) / vol_ann if vol_ann > OPT_EPS else 0.0
    return {
        "return_ann_pct": round(ret_ann * 100.0, 2),
        "volatility_ann_pct": round(vol_ann * 100.0, 2),
        "sharpe": round(float(sharpe), 3),
    }


def compute_diversification_metrics(
    weights: np.ndarray,
    *,
    min_active_weight: float = 0.0,
) -> dict[str, float | int]:
    w = np.asarray(weights, dtype=float)
    w = np.clip(w, 0.0, 1.0)
    total = float(w.sum())
    if total <= OPT_EPS:
        return {
            "n_assets": 0,
            "largest_position_pct": 0.0,
            "top3_weight_pct": 0.0,
            "hhi": 0.0,
            "effective_n": 0.0,
            "diversification_score": 0.0,
        }
    w = w / total
    active_threshold = max(1e-4, min_active_weight if min_active_weight > 0 else 1e-3)
    active = w[w >= active_threshold]
    hhi = float(np.sum(np.square(w)))
    effective_n = (1.0 / hhi) if hhi > OPT_EPS else 0.0
    n_assets = int(active.shape[0])
    largest = float(np.max(w)) * 100.0
    top3 = float(np.sort(w)[-3:].sum()) * 100.0
    if w.shape[0] <= 1:
        score = 0.0
    else:
        score = (effective_n - 1.0) / (float(w.shape[0]) - 1.0) * 100.0
    score = float(np.clip(score, 0.0, 100.0))
    return {
        "n_assets": n_assets,
        "largest_position_pct": round(largest, 2),
        "top3_weight_pct": round(top3, 2),
        "hhi": round(hhi, 4),
        "effective_n": round(effective_n, 2),
        "diversification_score": round(score, 1),
    }


def _constraints_payload(constraints: FrontierConstraints, *, n_assets: int) -> dict[str, Any]:
    max_assets_effective = constraints.max_assets if constraints.max_assets is not None else n_assets
    return {
        "max_weight_per_asset_pct": round(constraints.max_weight_per_asset * 100.0, 2),
        "min_assets": constraints.min_assets,
        "max_assets": int(min(n_assets, max_assets_effective)),
        "min_active_weight_pct": round(constraints.min_active_weight * 100.0, 2),
        "allow_tiny_residuals": constraints.allow_tiny_residuals,
        "allow_short": constraints.allow_short,
        "n_points": max(8, constraints.n_points),
    }


def _select_count_candidates(
    feasible_counts: list[int],
    *,
    current_weights: np.ndarray | None,
) -> list[int]:
    if len(feasible_counts) <= 4:
        return feasible_counts
    candidates = {feasible_counts[0], feasible_counts[-1]}
    mid = feasible_counts[len(feasible_counts) // 2]
    candidates.add(mid)
    if current_weights is not None and current_weights.size > 0:
        current_n = int(np.sum(current_weights > 1e-3))
        nearest = min(feasible_counts, key=lambda k: abs(k - current_n))
        candidates.add(nearest)
    out = sorted(candidates)
    return out


def _feasible_core_counts(
    constraints: FrontierConstraints,
    *,
    min_k: int,
    max_k: int,
) -> list[int]:
    counts: list[int] = []
    for k in range(min_k, max_k + 1):
        min_sum = k * constraints.min_active_weight
        max_sum = k * constraints.max_weight_per_asset
        if min_sum <= 1.0 + OPT_EPS and max_sum >= 1.0 - OPT_EPS:
            counts.append(k)
    return counts


def _optimize_portfolio_mode(
    *,
    mode: str,
    mean_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float,
    constraints: FrontierConstraints,
    count_candidates: list[int],
    current_weights: np.ndarray | None,
    target_return: float | None = None,
) -> np.ndarray | None:
    from scipy.optimize import minimize

    n_assets = mean_returns.shape[0]
    indiv_vol = np.sqrt(np.maximum(np.diag(cov_matrix), OPT_EPS))
    score_sharpe = (mean_returns - risk_free_rate) / indiv_vol
    score_sharpe = np.nan_to_num(score_sharpe, nan=0.0, posinf=0.0, neginf=0.0)
    score_min_var = -indiv_vol

    best_weights: np.ndarray | None = None
    best_obj = float("inf")

    for k_core in count_candidates:
        candidates = _build_core_candidates(
            k_core,
            n_assets=n_assets,
            mode=mode,
            score_sharpe=score_sharpe,
            score_min_var=score_min_var,
            current_weights=current_weights,
        )
        for core_idx in candidates:
            support_idx, lower_bounds = _build_support_with_residuals(
                core_idx=core_idx,
                n_assets=n_assets,
                constraints=constraints,
                mode=mode,
                score_sharpe=score_sharpe,
                score_min_var=score_min_var,
            )
            upper_bounds = np.full(len(support_idx), constraints.max_weight_per_asset, dtype=float)
            if float(np.sum(lower_bounds)) > 1.0 + OPT_EPS:
                continue
            if float(np.sum(upper_bounds)) < 1.0 - OPT_EPS:
                continue

            x0 = _build_initial_guess(
                support_idx=support_idx,
                lower=lower_bounds,
                upper=upper_bounds,
                current_weights=current_weights,
            )
            if x0 is None:
                continue

            mean_sub = mean_returns[support_idx]
            cov_sub = cov_matrix[np.ix_(support_idx, support_idx)]

            def _base_obj(ws: np.ndarray) -> float:
                ret = float(ws @ mean_sub)
                var = float(ws @ cov_sub @ ws)
                var = max(var, 0.0)
                hhi = float(np.sum(np.square(ws)))
                penalty = constraints.concentration_penalty * hhi
                if mode == "min_variance":
                    return var + penalty
                if mode == "max_sharpe":
                    vol = math.sqrt(var)
                    if vol <= OPT_EPS:
                        return 1e9
                    sharpe = (ret - risk_free_rate) / vol
                    return -sharpe + penalty
                if mode == "target_return":
                    target = float(target_return) if target_return is not None else ret
                    return_gap = (ret - target) ** 2
                    return var + penalty + 80.0 * return_gap
                raise ValueError(f"Mode inconnu: {mode}")

            result = minimize(
                _base_obj,
                x0,
                method="SLSQP",
                bounds=list(zip(lower_bounds, upper_bounds)),
                constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}],
                options={"maxiter": 250, "ftol": 1e-9},
            )
            if not result.success:
                continue
            ws = np.clip(np.asarray(result.x, dtype=float), lower_bounds, upper_bounds)
            if not np.isfinite(ws).all():
                continue
            full = np.zeros(n_assets, dtype=float)
            full[support_idx] = ws
            total = float(full.sum())
            if total <= OPT_EPS:
                continue
            full = full / total

            if not _respects_min_assets(
                full,
                min_assets=constraints.min_assets,
                min_active_weight=constraints.min_active_weight,
            ):
                continue
            if constraints.max_assets is not None:
                active = int(np.sum(full >= max(1e-4, constraints.min_active_weight)))
                if active > constraints.max_assets:
                    continue

            obj_value = _base_obj(ws)
            if obj_value < best_obj:
                best_obj = obj_value
                best_weights = full

    return best_weights


def _build_core_candidates(
    k_core: int,
    *,
    n_assets: int,
    mode: str,
    score_sharpe: np.ndarray,
    score_min_var: np.ndarray,
    current_weights: np.ndarray | None,
) -> list[tuple[int, ...]]:
    import itertools

    if mode == "min_variance":
        primary_score = score_min_var
    else:
        primary_score = score_sharpe

    candidates: list[tuple[int, ...]] = []
    ranked = np.argsort(-primary_score)
    candidates.append(tuple(sorted(ranked[:k_core].tolist())))

    if current_weights is not None and current_weights.size == n_assets:
        ranked_current = np.argsort(-current_weights)
        candidates.append(tuple(sorted(ranked_current[:k_core].tolist())))

    mixed_score = 0.7 * _zscore(primary_score) + 0.3 * _zscore(
        current_weights if current_weights is not None and current_weights.size == n_assets else np.zeros(n_assets)
    )
    ranked_mixed = np.argsort(-mixed_score)
    candidates.append(tuple(sorted(ranked_mixed[:k_core].tolist())))

    if n_assets <= 12 and math.comb(n_assets, k_core) <= 80:
        for combo in itertools.combinations(range(n_assets), k_core):
            candidates.append(tuple(combo))
    else:
        ranked_reverse = np.argsort(primary_score)
        candidates.append(tuple(sorted(ranked_reverse[:k_core].tolist())))

    # Unicité et limite raisonnable.
    uniq = []
    seen: set[tuple[int, ...]] = set()
    for combo in candidates:
        if combo in seen:
            continue
        seen.add(combo)
        uniq.append(combo)
    return uniq[:14]


def _build_support_with_residuals(
    *,
    core_idx: tuple[int, ...],
    n_assets: int,
    constraints: FrontierConstraints,
    mode: str,
    score_sharpe: np.ndarray,
    score_min_var: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    core = list(core_idx)
    max_assets = constraints.max_assets if constraints.max_assets is not None else n_assets
    residual_capacity = max(0, max_assets - len(core))

    support = list(core)
    lower = [constraints.min_active_weight for _ in core]

    if constraints.allow_tiny_residuals and residual_capacity > 0:
        score = score_min_var if mode == "min_variance" else score_sharpe
        ordered = np.argsort(-score)
        extras_target = min(2, residual_capacity, n_assets - len(core))
        for idx in ordered:
            i = int(idx)
            if i in support:
                continue
            support.append(i)
            lower.append(0.0)
            if len(support) >= len(core) + extras_target:
                break

    return np.asarray(support, dtype=int), np.asarray(lower, dtype=float)


def _build_initial_guess(
    *,
    support_idx: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    current_weights: np.ndarray | None,
) -> np.ndarray | None:
    target = np.zeros_like(lower, dtype=float)
    if current_weights is not None and current_weights.size >= int(np.max(support_idx)) + 1:
        target = np.asarray(current_weights[support_idx], dtype=float)
    if float(target.sum()) <= OPT_EPS:
        target = np.ones_like(lower, dtype=float) / float(len(lower))
    else:
        target = target / float(target.sum())
    return _project_to_bounded_simplex(target=target, lower=lower, upper=upper)


def _project_to_bounded_simplex(
    *,
    target: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray | None:
    from scipy.optimize import minimize

    if float(np.sum(lower)) > 1.0 + OPT_EPS:
        return None
    if float(np.sum(upper)) < 1.0 - OPT_EPS:
        return None
    x0 = np.clip(target, lower, upper)
    if float(np.sum(x0)) <= OPT_EPS:
        x0 = lower.copy()
    total = float(np.sum(x0))
    if total > OPT_EPS:
        x0 = x0 / total
    x0 = np.clip(x0, lower, upper)

    result = minimize(
        lambda w: float(np.sum(np.square(w - target))),
        x0,
        method="SLSQP",
        bounds=list(zip(lower, upper)),
        constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}],
        options={"maxiter": 200, "ftol": 1e-10},
    )
    if not result.success:
        return None
    out = np.asarray(result.x, dtype=float)
    out = np.clip(out, lower, upper)
    s = float(np.sum(out))
    if s <= OPT_EPS:
        return None
    out = out / s
    return out


def _respects_min_assets(weights: np.ndarray, *, min_assets: int, min_active_weight: float) -> bool:
    threshold = max(1e-4, min_active_weight)
    active = int(np.sum(weights >= threshold))
    return active >= min_assets


def _weights_percent_map(tickers: list[str], weights: np.ndarray) -> dict[str, float]:
    rows: dict[str, float] = {}
    for i, ticker in enumerate(tickers):
        w = float(weights[i])
        if w <= 1e-4:
            continue
        rows[ticker] = round(w * 100.0, 2)
    return rows


def _unique_points(points: list[dict[str, float]]) -> list[dict[str, float]]:
    if not points:
        return []
    ordered = sorted(points, key=lambda p: (p["vol"], p["ret"]))
    out: list[dict[str, float]] = []
    prev = None
    for p in ordered:
        vol = float(p["vol"])
        ret = float(p["ret"])
        key = (round(vol, 3), round(ret, 3))
        if key == prev:
            continue
        prev = key
        out.append({"vol": key[0], "ret": key[1]})
    return out


def _regularize_cov(cov: np.ndarray) -> np.ndarray:
    c = np.asarray(cov, dtype=float)
    c = np.nan_to_num(c, nan=0.0, posinf=0.0, neginf=0.0)
    c = 0.5 * (c + c.T)
    n = c.shape[0]
    c = c + np.eye(n, dtype=float) * 1e-8
    return c


def _zscore(arr: np.ndarray) -> np.ndarray:
    x = np.asarray(arr, dtype=float)
    if x.size == 0:
        return x
    mu = float(np.mean(x))
    sd = float(np.std(x))
    if sd <= OPT_EPS:
        return np.zeros_like(x, dtype=float)
    return (x - mu) / sd


def _to_float(value: Any, *, default: float) -> float:
    if value is None:
        return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, *, default: int) -> int:
    if value is None:
        return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_optional_int(value: Any, *, default: int | None) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        out = int(value)
        if out <= 0:
            return None
        return out
    except Exception:
        return default


def _to_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "oui", "on"}:
        return True
    if txt in {"0", "false", "no", "non", "off"}:
        return False
    return bool(default)
