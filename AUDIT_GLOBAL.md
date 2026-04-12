# AUDIT_GLOBAL

Date d'audit: 2026-04-12
Portee: phase de stabilisation terminee (perf, UX, convergence projection, DQ, smoke tests minimaux).

## Methode
- Relecture ciblee des modules critiques `qt_ui/*`, `services/*`, `tests/*`.
- Verification technique:
  - `python -m pytest -q` -> `168 passed`, `1 warning` (permissions `.pytest_cache`, non bloquant).
- Verification fonctionnelle ciblee:
  - Contrats DQ bourse/liquidites en place et affiches en UI (plus de faux zero metier sur les cas traites).
  - Panels secondaires durcis sur `None/NaN` et charts stale.

## Synthese d'etat

### Termine
- Stabilisation performance:
  - refresh/rebuild bourse et snapshots sans regression detectee;
  - optimisation locale sans refonte lourde.
- Harmonisation UX:
  - affichage explicite des etats partiels (`quality_status`, warnings locaux, `—` quand non calculable);
  - nettoyage des charts stale sur les ecrans touches.
- Convergence projection:
  - `services/projection_service.py` reste l'entree UI canonique;
  - coexistence legacy/advanced explicite et cadree.
- Data quality gaps principaux traites:
  - DQ-01 / DQ-03 / DQ-04 / DQ-05 / DQ-06 implementes cote services + affichage UI adapte.
- Filet de test minimal ajoute:
  - smoke imports panels secondaires;
  - tests ciblant le contrat de normalisation numerique.

### Reste a faire (reel)
- Etendre legerement les smoke tests UI headless sur 1-2 parcours utilisateur critiques supplementaires (sans grosse suite).
- Traiter le warning environnement `.pytest_cache` (permissions locales), ou le documenter comme connu.
- Formaliser un check pre-release court (smoke manuel des flux critiques) avant ouverture produit plus large.

### A ne pas faire maintenant
- Fusionner les moteurs projection en un seul moteur.
- Refonte globale DB/repository.
- Refactor massif des gros panels sans besoin produit immediat.
- Ajout de nouvelles fonctionnalites pendant la stabilisation.

### A preparer plus tard
- Presenter/DTO pour `services/vue_ensemble_metrics.py`.
- API publique neutre pour le cash bourse as-of (si le domaine rebouge).
- Harmonisation transverse des messages d'erreur UI (au fil des flux, pas big bang).

## Conclusion
- Stabilisation terminee ? **Oui**, sur le perimetre technique vise.
- Pret pour phase produit ? **Oui, en phase produit encadree**.
- Sous quelles conditions ?
  - conserver le gel fonctionnel court terme (pas de nouvelles features);
  - garder `python -m pytest -q` vert comme gate;
  - executer le smoke manuel pre-release (import, bourse refresh, projection, navigation personne/famille);
  - accepter les refactors uniquement opportunistes et localises.
