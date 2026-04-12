# BACKLOG_GLOBAL

Mise a jour: 2026-04-12
Objectif: backlog court et actionnable pour l'entree en phase produit.

## Termine
- Stabilisation perf/UX sur les ecrans critiques.
- Convergence projection via `services/projection_service.py` (entree UI unique).
- DQ majeurs traites (DQ-01, DQ-03, DQ-04, DQ-05, DQ-06) avec affichage explicite des etats partiels.
- Durcissement des panels secondaires sur `None/NaN` et nettoyage des charts stale.
- Filet de tests minimal complete:
  - tests contrats FX/DQ;
  - smoke import panels secondaires.
- Pipeline local valide: `python -m pytest -q` -> `168 passed`, `1 warning` non bloquant.

## Reste a faire (P1)
1. Completer 1-2 smoke tests headless sur parcours critiques restants
- Scope: import/recherche globale et un flux refresh bourse bout-en-bout simple.
- Done attendu: couverture minimale des regressions d'integration les plus probables.

2. Clore le point environnement pytest cache
- Scope: permissions `.pytest_cache` ou documentation explicite du warning connu.
- Done attendu: plus de bruit inattendu en CI/local, ou warning accepte et trace.

3. Check pre-release phase produit
- Scope: check-list manuelle courte (import, projection, bourse, navigation personne/famille, settings).
- Done attendu: checklist executee et statut signe avant diffusion plus large.

## A ne pas faire maintenant
- Fusion moteur projection legacy/advanced.
- Refonte architecture DB/repository.
- Refactor massif des gros panels sans changement produit associe.
- Ajout de nouvelles fonctionnalites.

## A preparer plus tard
- Presenter/DTO pour `vue_ensemble_metrics`.
- API publique cash bourse as-of.
- Normalisation transverse des messages d'erreur UI.

## Conclusion
- Stabilisation terminee: **oui**.
- Pret phase produit: **oui, sous controle**.
- Conditions: gate tests vert, smoke pre-release, gel fonctionnel court terme.
