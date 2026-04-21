# SOURCE_DE_VERITE

Mise a jour: 2026-04-12

## Objectif
Documenter les contrats metier effectivement en vigueur apres stabilisation.

## 1) Regle de couche

```text
UI -> services -> DB/repositories
```

- `services/*`: source canonique des regles metier.
- `qt_ui/*`: orchestration + rendu, sans calcul metier durable.
- SQL metier: autorise dans `services/*`, interdit dans `qt_ui/*`.

## 2) Contrats canoniques DQ / non calculable

### FX
- `services/fx.py::convert`:
  - retourne un montant converti si taux disponible;
  - retourne `None` si taux introuvable.
- `services/market_history.py::convert_weekly`:
  - meme contrat (`None` si taux introuvable).

### Liquidites
- `services/liquidites.py::get_liquidites_summary` retourne:
  - `bank_cash_eur`, `bourse_cash_eur`, `pe_cash_eur`, `total_eur`;
  - `quality_status` (`ok` / `partial`);
  - `missing_fx` (liste detaillee des comptes exclus).
- Regle: un FX manquant n'est pas un vrai zero metier; l'UI doit afficher un etat partiel.

### Bourse live/historique
- `services/portfolio.py` expose `valuation_status`:
  - `ok`, `missing_price`, `missing_fx`.
- Prix absent/non valable:
  - `last_price`, `value`, `pnl_latent` restent non calculables (`NaN`/`None`), jamais forces a `0` metier.
- `services/bourse_analytics.py::get_bourse_state_asof` retourne:
  - `total_val`, `total_pnl` a `None` si non calculables;
  - `quality_status`, `missing_prices`, `missing_fx`.
- `services/bourse_analytics.py::get_bourse_performance_metrics` retourne:
  - `global_perf_pct` / `ytd_perf_pct` a `None` si non calculables;
  - `perf_warnings`, `missing_income_fx`, `quality_status`.

## 3) Contrat d'affichage UI
- Valeur non calculable -> afficher `—` (pas `0`).
- Donnee partielle -> afficher un message local explicite.
- Graphique sans donnees exploitables -> vider/placeholder (pas de chart stale).

## 4) Projections
- Toute UI projection passe par `services/projection_service.py`.
- Les deux moteurs restent actifs:
  - `services/projections.py` (legacy simple),
  - `services/prevision*.py` (avancee/stress/MC).
- Coexistence assumee en phase produit; ne pas fusionner maintenant.

## 5) Tests minimaux de garde
- Commande canonique: `python -m pytest -q`.
- Etat courant: `168 passed`, `1 warning` environnemental non bloquant (`.pytest_cache`).
- Gardes DQ/FX: `tests/test_fx_contract.py`.
- Smoke import panels secondaires: `tests/test_import_smoke_panels.py`.

## 6) Statut pilotage

### Termine
- Contrats DQ principaux implementes et affiches.
- Convergence projection via facade.
- Durcissement panels secondaires sur `None/NaN`.

### Reste a faire
- Ajouter 1-2 smoke tests headless supplementaires sur parcours critiques.
- Clore ou documenter le warning `.pytest_cache`.

### A ne pas faire maintenant
- Fusion des moteurs projection.
- Refonte architecture lourde DB/UI.

### A preparer plus tard
- Presenter/DTO pour `vue_ensemble_metrics`.
- API publique cash bourse as-of.
