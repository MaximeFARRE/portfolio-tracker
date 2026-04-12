# Rapport Codex - Correctif Epargne / Vue Ensemble

## Cause racine

Les fonctions d'épargne ne matérialisaient plus les mois calendaires sans écriture (revenus/dépenses).

Conséquences observées :
- `get_person_monthly_savings_series` renvoyait uniquement les mois présents en base.
- Les KPI 12 mois de `vue_ensemble_metrics.py` (`capacite_epargne_avg`, `depenses_moy_12m`) étaient calculés sur trop peu de lignes (ex. 4 au lieu de 12), donc biaisés.

## Correctifs appliqués

### 1) `services/cashflow.py`
- `get_person_monthly_savings_series` :
  - reindex explicite sur une fenêtre mensuelle complète (`n_mois`) ancrée sur `end_month` (ou dernier mois observé),
  - remplissage des mois manquants à `0.0` pour `revenus`, `depenses`, `epargne`,
  - conservation du calcul `taux_epargne` (`NA` si revenus nuls).
- `compute_savings_metrics` :
  - conservation du contrat legacy des moyennes agrégées (`avg_monthly_income`, `avg_monthly_expenses`, `avg_monthly_savings`) en les calculant sur les mois avec données non nulles dans la fenêtre (sinon fallback).

### 2) `services/vue_ensemble_metrics.py`
- KPI 12 mois renforcés : reindex mensuel explicite sur les 12 derniers mois calendaires avant calcul des agrégats (`sum/mean`), avec mois manquants à `0.0`.

### 3) `tests/test_vue_ensemble_metrics.py`
- Ajout d'un test de non-régression :
  - `test_vue_ensemble_metrics_kpis_include_missing_months_as_zero`
  - vérifie que les KPI 12 mois incluent bien les mois absents comme zéros.

## Fichiers modifiés

- `services/cashflow.py`
- `services/vue_ensemble_metrics.py`
- `tests/test_vue_ensemble_metrics.py`
- `REPORT_CODEX_EPARGNE.md`

## Résultats des tests

### Ciblé
- Commande: `python -m pytest -q tests/test_vue_ensemble_metrics.py`
- Résultat: `5 passed`

### Suite projet
- Commande: `python -m pytest -q tests`
- Résultat: `98 passed`

Notes:
- `python -m pytest -q` à la racine échoue en collecte sur des dossiers temporaires `pytest-cache-files-*` (PermissionError Windows). La suite officielle sous `tests/` est entièrement verte.
