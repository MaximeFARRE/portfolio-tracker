# Architecture - Patrimoine Desktop

Dernière mise à jour: 2026-04-12
Périmètre: architecture réellement observée dans le code actuel.

## 1. Vue d'ensemble de l'application
L'application est une desktop app PyQt6 de suivi patrimonial familial.

Chemin principal d'exécution:

```text
main.py
  -> core/db_connection.py (init DB + connexion singleton)
  -> qt_ui/main_window.py (navigation + pages)
  -> qt_ui/pages/* + qt_ui/panels/*
  -> services/* (métier, calculs, imports, projections)
  -> services/repositories.py + services d'accès lecture + SQL service + db/schema.sql
```

Architecture dominante observée:
- structure majoritaire orientée `UI -> services -> DB`.
- l'écart principal ancien (SQL métier dans l'UI) est traité: les accès lecture UI passent par des services dédiés; les risques restants portent surtout sur les gros modules UI, la coexistence des moteurs de projection et les tests UI.

## 2. Arborescence logique du projet
Arborescence logique (couches actives):

```text
main.py                          # bootstrap app, logging, backup DB
core/
  db_connection.py               # singleton connexion, init et seed

qt_ui/
  main_window.py                 # shell app + navigation + recherche globale
  pages/                         # pages racines (famille, personnes, import, objectifs, settings)
  panels/                        # vues métier détaillées
  widgets/                       # composants UI réutilisables
  components/                    # animation, skeleton, stack

services/
  db.py                          # connexion sqlite/libsql, migrations, helpers DB
  repositories.py                # accès CRUD génériques
  snapshots.py (façade) / snapshots_*.py / family_snapshots.py
  cashflow.py / credits.py / liquidites.py
  bourse_analytics.py / bourse_advanced_analytics.py
  projections.py / prevision*.py / projection_service.py
  global_search_service.py / import_lookup_service.py / panel_data_access.py
  imports.py / tr_import.py / import_history.py
  market_history.py / fx.py / pricing.py / isin_resolver.py
  pdf_export.py

db/
  schema.sql
  migrations/*.sql

tests/
  test_*.py                      # tests surtout orientés services

docs/
  ARCHITECTURE.md                # ce document
  SOURCE_DE_VERITE.md            # fonctions canoniques par domaine
  CONTEXT.md                     # contexte technique détaillé

scripts/
  patrimoine.spec                # spec PyInstaller
```

## 3. Description des couches

### 3.1 UI / pages / panels / widgets
Couche concernée:
- `qt_ui/main_window.py`
- `qt_ui/pages/*`
- `qt_ui/panels/*`
- `qt_ui/widgets/*`

Responsabilités réellement présentes:
- navigation et orchestration d'écrans,
- rendu des tableaux/graphes,
- interactions utilisateur,
- déclenchement de rebuild snapshots en thread,
- recherche globale multi-objets.

État actuel:
- les accès recherche/import/panels sont sortis vers `services/global_search_service.py`, `services/import_lookup_service.py` et `services/panel_data_access.py`;
- aucun `execute()` SQL métier direct restant observé dans `qt_ui/*`;
- les PRAGMA de connexion dans `qt_ui/main_window.py` restent du wiring technique, pas de la logique métier.

Conclusion: couche UI = orchestration + rendu; les risques restants sont surtout la taille des composants et les flux asynchrones.

### 3.2 Services métier
Couche concernée: `services/*`.

Responsabilités réellement présentes:
- calculs patrimoniaux hebdo (`snapshots.py`, `family_snapshots.py`),
- KPI cashflow/épargne (`cashflow.py`),
- crédits (fiche, amortissement, coût réel) (`credits.py`),
- bourse live/perf/diagnostics (`bourse_analytics.py`),
- analytics avancées risques (`bourse_advanced_analytics.py`),
- projections et scénarios (`projections.py`, `prevision*.py`),
- imports CSV et historique/rollback (`imports.py`, `tr_import.py`, `import_history.py`).

Observation:
- c'est la couche la plus riche et la plus proche d'une vraie source de vérité métier.
- certaines responsabilités sont dupliquées entre services (ex: variantes rebuild snapshots/famille).

### 3.3 Accès base de données
Couches impliquées:
- `services/db.py`
- `core/db_connection.py`
- `services/repositories.py`
- SQL dans les services métier/repositories; plus de SQL métier direct observé dans l'UI.

Responsabilités réellement présentes:
- init DB + migrations SQL + migrations code versionnées,
- connexion locale SQLite (WAL) ou libsql/Turso avec wrapper de compat Row,
- CRUD générique via `repositories.py`.

Particularités:
- coexistence de 2 styles d'accès:
  - style repository,
  - style SQL inline dans différents modules.

### 3.4 Analytics / calculs
Modules principaux:
- `services/calculations.py`
- `services/bourse_analytics.py`
- `services/bourse_advanced_analytics.py`
- `services/vue_ensemble_metrics.py`
- `services/projections.py`
- `services/prevision*`

Responsabilités réelles:
- calculs de soldes, cashflow, perf, CAGR,
- métriques de risque (Sharpe, VaR/ES, corrélations, contributions),
- projections déterministes + stress + Monte Carlo (prévision).

État constaté:
- couche analytique puissante mais dispersée sur plusieurs modules longs.

### 3.5 Import / export / sync / API externes
Modules:
- import: `services/imports.py`, `services/tr_import.py`, `services/import_history.py`
- export: `services/pdf_export.py`
- sync marché/FX: `services/market_history.py`
- pricing live/FX: `services/pricing.py`, `services/fx.py`
- résolution ISIN: `services/isin_resolver.py`

APIs externes réellement utilisées:
- `yfinance`
- OpenFIGI
- Frankfurter API
- Trade Republic via CLI `pytr`

Zone floue / sensible:
- les comportements de fallback réseau sont répartis dans plusieurs services, pas centralisés.

## 4. Flux de données principaux

### Flux A - Démarrage
1. `main.py` configure logs/thème/exception handler.
2. `core/db_connection.get_connection()` lance `init_db()`, `seed_minimal()`, migrations.
3. `MainWindow` charge les pages.
4. un thread lance `rebuild_snapshots_person_from_last` au démarrage.

### Flux B - Navigation et affichage personne
1. UI sélectionne personne/compte.
2. Panels appellent services (ex: `vue_ensemble_metrics`, `bourse_analytics`, `credits`).
3. Services lisent DB via repository/SQL.
4. UI render tables/charts.

### Flux C - Import données
1. UI import choisit type (dépenses/revenus/Bankin/TR/crédit).
2. service d'import parse/normalise.
3. écriture DB + enregistrement batch import.
4. rollback possible via `import_history`.

### Flux D - Données marché et FX
1. services snapshots/bourse déclenchent sync weekly/live.
2. récupération prix/fx via yfinance (+ fallback/pivot FX).
3. stockage tables `asset_prices_weekly` / `fx_rates_weekly`.
4. valorisation patrimoine/positions.

### Flux E - Projections
1. UI objectifs/scénarios lit base patrimoniale.
2. `projection_service.py` route les requêtes vers le bon moteur selon le mode demandé.
3. UI affiche courbes/scénarios/milestones.

**Note sur les deux moteurs coexistants :**
- `services/projections.py` — moteur déterministe original (FIRE, milestones simples). Conservé car encore utilisé par `goals_projection_page`.
- `services/prevision*.py` + `services/prevision_engines/` — moteur avancé (Monte Carlo, stress, scénarios multicouches). Utilisé par `prevision_avancee_panel`.
- `services/projection_service.py` — façade qui isole l'UI des deux moteurs.
- **Pour tout nouveau code** : utiliser `projection_service.py` comme point d'entrée. Ne pas appeler `projections.py` ou `prevision*.py` directement depuis l'UI.

## 5. Règles de dépendances entre couches (état actuel)
Règle souhaitée dans le code:
- UI dépend des services.
- services dépendent de DB/repositories.
- DB ne dépend pas de UI.

Réalité observée:
- règle respectée côté UI pour le SQL métier;
- dette restante côté services: coexistence SQL inline/repositories et moteurs projection legacy/advanced.

Règles pratiques actuellement suivies:
- pas d'import UI depuis services internes privés (globalement vrai);
- services centraux utilisés pour KPI principaux;
- lookups UI centralisés dans services dédiés.

## 6. Anti-patterns déjà présents dans le projet

1. SQL dans l'UI
- État actuel: traité. Plus de SQL métier direct observé dans `qt_ui/*` (migré vers services dédiés).

2. Fichiers monolithiques
- `qt_ui/pages/goals_projection_page.py` (~1435 lignes, extraction partielle vers `_goals_projection_*`)
- `qt_ui/pages/import_page.py` (~585 lignes, extraction partielle vers `_import_panels.py` et `_tr_panel.py`)
- `qt_ui/panels/bourse_global_panel.py` (~1152 lignes)
- `services/snapshots.py` est désormais une façade; la complexité est déplacée vers `snapshots_compute.py`, `snapshots_rebuild.py`, `snapshots_read.py`, `snapshots_helpers.py`

3. Duplication de logique
- Helpers techniques largement standardisés via `services/common_utils.py`.
- Zone restante: cash bourse as-of partagé via helper privé de `bourse_analytics`, à extraire seulement si ce calcul rebouge.

4. Paramètres UI runtime
- Les préférences runtime principales ont été branchées; garder des tests si ce domaine rebouge.

5. Legacy ambigu conservé dans le repo actif
- Résolu : `legacy/3_Import_streamlit.py` et `pages/3_Import.py` supprimés (code Streamlit orphelin, jamais importé).

## 7. Règles de refactor à respecter pour l'avenir

1. Interdire toute nouvelle requête SQL métier dans l'UI; les accès existants ont été déplacés vers des services dédiés.
2. Maintenir un point d'entrée service unique par KPI métier.
3. Découper les gros modules sans changer le comportement (refactor incrémental).
4. Centraliser les helpers transverses (conversion float/date/row).
5. Ajouter un test de non-régression à chaque correction de bug métier.
6. Mettre à jour la documentation d'architecture dans la même PR que le code.

## 8. Fichiers ou modules sensibles
Sensibles = impact fort + risque de régression:
- `main.py` (bootstrap, backup, fermeture)
- `core/db_connection.py` (lifecycle connexion)
- `services/db.py` (migrations, compat sqlite/libsql)
- `services/snapshots.py` (valeur patrimoniale hebdo)
- `services/family_snapshots.py` (agrégats famille)
- `services/bourse_analytics.py` (positions/perf)
- `services/cashflow.py` (épargne/KPI)
- `services/credits.py` (CRD/amortissements)
- `qt_ui/main_window.py` (navigation globale + recherche + rebuild thread)
- `qt_ui/pages/import_page.py` (pipeline import critique)

## 9. Endroits où la dette technique est la plus forte

1. Gros composants UI / orchestration
- dette élevée dans `goals_projection_page.py`, `bourse_global_panel.py` et `prevision_avancee_panel.py` à cause de leur taille et de leurs flux asynchrones.

2. Projection et modèles coexistants
- `projection_service.py` isole l'UI des deux moteurs. `projections.py` (moteur simple, goals) et `prevision*.py` (moteur avancé, Monte Carlo/stress) coexistent intentionnellement — voir Flux E pour le détail et les règles d'usage.

3. Tests UI / smoke tests
- bonne couverture services, mais couverture UI-end-to-end limitée.

4. Services data-access
- SQL inline encore présent côté services; acceptable court terme, à faire évoluer opportunément.

## Règles d'évolution de l'architecture
Principes simples pour éviter la dégradation:

1. Une fonctionnalité métier = un service référent explicite.
2. UI sans SQL métier (tolérer seulement wiring temporaire, documenté et daté).
3. Toute nouvelle logique de fallback vit côté service, pas côté panel.
4. Toute règle métier modifiée doit être couverte par un test dédié.
5. Les gros fichiers doivent être découpés avant ajout massif de nouvelles features.
6. Toute exception d'architecture doit être listée ici avec plan de sortie.
7. Documentation et code évoluent ensemble (pas de doc différée).
