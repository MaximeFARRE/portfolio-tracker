# Checklist Qualite

Version: 2026-04-11
Usage: checklist opérationnelle continue pour garder l'application propre et cohérente.

## A. Avant chaque PR
- [ ] Le scope fonctionnel est clair et limité.
- [ ] Les changements respectent `UI -> services -> repository/DB`.
- [ ] Aucun nouveau SQL métier n'est ajouté en UI.
- [ ] Les tests liés au scope sont ajoutés/mis à jour.
- [ ] `python -m pytest -q` est exécuté.
- [ ] Les docs racine impactées sont mises à jour (`README`, `ARCHITECTURE`, `SOURCE_DE_VERITE`, backlog/audit si pertinent).

## B. Garde-fous de code
- [ ] Noms explicites (pas d'abréviations ambigües).
- [ ] Pas de duplication de logique métier (chercher d'abord API existante dans `services/`).
- [ ] Fallbacks explicites et logués dans les services.
- [ ] Valeurs monétaires et dates normalisées dans une seule couche.
- [ ] Pas d'effet de bord caché (commit DB, IO, thread) sans point d'entrée clair.

## C. Garde-fous tests
- [ ] Les cas nominaux sont testés.
- [ ] Les cas limites sont testés (données manquantes, zéro, dates invalides).
- [ ] Au moins un test de non-régression sur bug corrigé.
- [ ] Les contrats métier SSOT sont couverts (KPI principaux).

## D. Revue hebdomadaire (amélioration continue)
- [ ] Repasser `AUDIT_GLOBAL.md` et fermer/ouvrir les points pertinents.
- [ ] Reprioriser `BACKLOG_GLOBAL.md` (P0/P1/P2).
- [ ] Identifier 1 dette technique à traiter dans la semaine (max 1-2 jours).
- [ ] Vérifier qu'aucun document racine n'est devenu obsolète.

## E. Release / tag
- [ ] Tous les tests passent.
- [ ] Aucun lien doc cassé.
- [ ] Aucune ambiguïté sur la source de vérité métier.
- [ ] Les options exposées dans Paramètres sont effectivement branchées au runtime.
- [ ] Sauvegarde DB testée (création + rotation).

## F. Règle de décision rapide
En cas de doute:
1. Vérifier `SOURCE_DE_VERITE.md`.
2. Si absent, ajouter l'API canonique dans un service puis documenter.
3. Ne pas implémenter de logique métier durable en UI.
