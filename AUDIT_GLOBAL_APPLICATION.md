# Audit Global de l'Application

## 1. Synthèse générale

### 1.1 Verdict global

L'application repose sur une base conceptuelle sérieuse: séparation partielle UI / services / repositories, schéma SQLite assez riche, snapshots hebdomadaires, gestion famille / personne explicite, objectifs et projections déjà structurés, historique d'imports, migrations versionnées.

En revanche, l'état global du projet reste **fragile** sur quatre axes:

1. **Fiabilité fonctionnelle**: plusieurs défauts bloquants ou quasi bloquants existent encore sur les imports, les snapshots famille et les crédits.
2. **Cohérence métier**: certains calculs changent selon le scope ou le chemin de calcul utilisé, ce qui fragilise fortement la confiance dans les chiffres.
3. **Maintenabilité**: plusieurs pages et services sont devenus trop gros, trop couplés, et concentrent à la fois UI, orchestration, logique métier et gestion d'erreurs.
4. **Exploitabilité**: la stratégie de test est insuffisante et, dans l'état observé, le dépôt n'est pas prêt pour une validation automatique fiable.

### 1.2 Constats majeurs

| Gravité | Constat | Impact |
|---|---|---|
| Critique | `services/imports.py` contient un vrai `SyntaxError` (guillemets typographiques) | Les imports mensuels / Bankin associés à ce module ne sont pas fiables et les tests qui l'importent cassent immédiatement |
| Critique | `services/tr_import.py` requête `assets.isin` alors que la colonne n'existe pas dans `db/schema.sql` | Import Trade Republic potentiellement cassé en production |
| Critique | `services/family_snapshots.py` n'agrège pas `immobilier_value` | Les chiffres famille et les projections famille peuvent être faux |
| Haute | `services/credits.py` n'enregistre pas `payer_account_id` dans `upsert_credit()` | Une partie du modèle crédit est incohérente entre UI, DB et calculs |
| Haute | `services/import_history.py` ne sait pas annuler les imports de type crédit | Historique d'import partiellement mensonger et rollback incomplet |
| Haute | Les pages lourdes (`Import`, `Objectifs & Projection`, `Personnes`) font beaucoup de travail sur le thread UI | Risque de lenteur, gels et UX irrégulière |
| Haute | La couverture de tests est faible et l'environnement de test n'est pas prêt (`pytest` absent, README non aligné) | Régressions difficiles à détecter |

### 1.3 Ce qui est bien fait

- Le **schéma SQL** est globalement propre, riche, avec des index et des clés étrangères utiles.
- La distinction **scope personne / scope famille** est présente dans le modèle, ce qui est une bonne base produit.
- La logique de **snapshots hebdomadaires** est une bonne direction pour éviter de recalculer tout le patrimoine à chaque affichage.
- L'application dispose déjà d'une vraie couche **services métier** et de plusieurs **repositories**, ce qui reste mieux qu'une logique totalement noyée dans l'UI.
- La présence d'**import batches**, de **migrations**, de **scénarios**, de **jalons natifs** et d'**objectifs** montre une ambition produit cohérente.
- Le **handler global d'exception** et les **sauvegardes automatiques** vont dans le bon sens, même si certains détails sont fragiles.

### 1.4 Méthode et limites de l'audit

Audit réalisé par lecture critique du code, vérifications statiques ciblées, compilation Python ponctuelle, inspection du schéma SQL et des tests.

Limites constatées:

- `pytest` n'est pas disponible dans l'environnement observé.
- Le dépôt ne déclare pas d'autre outil de packaging que `requirements.txt`, et le `README.md` indique `pytest -q` sans que l'environnement soit prêt à l'exécuter.
- Certaines validations n'ont donc pas pu être confirmées par exécution complète de la suite.

## 2. Bugs / erreurs / incohérences

### 2.1 Bugs bloquants ou très sévères

- **`services/imports.py` ne compile pas**.
  - Constat: `SyntaxError: invalid character '“'` sur les lignes autour de `services/imports.py:337` et `services/imports.py:343`.
  - Impact: les imports qui passent par ce module sont cassés à l'exécution. `tests/test_imports.py` importe aussi ce module, donc la suite de tests casse dès l'import.
  - Fichiers concernés: `services/imports.py`, `tests/test_imports.py`, `qt_ui/pages/import_page.py`.

- **Import Trade Republic incohérent avec le schéma**.
  - Constat: `services/tr_import.py` fait un `JOIN` / filtrage sur `a.isin` vers `services/tr_import.py:672`, alors que `db/schema.sql` ne définit pas cette colonne dans `assets`. L'ISIN vit dans `asset_meta`.
  - Impact: crash SQL probable sur import TR, ou à minima logique de déduplication invalide.
  - Fichiers concernés: `services/tr_import.py`, `db/schema.sql`.

- **Les snapshots famille oublient l'immobilier**.
  - Constat: `services/family_snapshots.py` n'insère ni n'agrège `immobilier_value` dans `upsert_family_snapshot()` ni dans les requêtes `SUM(...)`, alors que `db/schema.sql` prévoit bien `immobilier_value` dans `patrimoine_snapshots_family_weekly` et que `services/projections.py` le lit.
  - Impact: les projections famille, le patrimoine famille et certains écrans peuvent afficher des chiffres faux ou incohérents avec les écrans personne.
  - Fichiers concernés: `services/family_snapshots.py`, `services/projections.py`, `services/family_dashboard.py`, `qt_ui/pages/famille_page.py`, `db/schema.sql`.

### 2.2 Bugs fonctionnels importants

- **`upsert_credit()` ignore `payer_account_id`**.
  - Constat: `services/credits.py` manipule ensuite `payer_account_id` dans d'autres calculs, mais `upsert_credit()` ne l'inclut pas dans la liste `fields`.
  - Impact: la page Import peut collecter cette information, mais elle ne semble pas persistée par ce point d'entrée. Le coût réel mensuel du crédit peut devenir faux ou nul.
  - Fichiers concernés: `services/credits.py`, `qt_ui/pages/import_page.py`, `db/schema.sql`.

- **Rollback d'import incomplet**.
  - Constat: `services/import_history.py` ne traite que `TR`, `BANKIN`, `DEPENSES`, `REVENUS`. La page Import expose pourtant un flux `Crédit (config + génération)`.
  - Impact: l'utilisateur peut croire qu'un batch est annulable alors qu'une partie des effets métier ne l'est pas.
  - Fichiers concernés: `services/import_history.py`, `qt_ui/pages/import_page.py`, éventuellement `services/credits.py`.

- **Suppression trop large lors d'un réimport mensuel**.
  - Constat: dans `services/imports.py`, le mode `delete_existing=True` supprime tout le contenu de la table cible pour `person_id`, pas seulement les mois importés.
  - Impact: un réimport partiel peut effacer l'historique complet d'une personne sur `depenses` ou `revenus`.
  - Fichiers concernés: `services/imports.py`, `qt_ui/pages/import_page.py`.

- **Incohérence de comportement famille selon le chemin de calcul**.
  - Constat: `services/family_dashboard.py` reconstruit la série famille directement depuis les snapshots personnes et inclut l'immobilier, tandis que `services/projections.py` lit la table famille, qui l'oublie.
  - Impact: deux écrans “famille” peuvent afficher des patrimoines différents sans raison métier visible.
  - Fichiers concernés: `services/family_dashboard.py`, `services/family_snapshots.py`, `services/projections.py`, `qt_ui/pages/famille_page.py`, `qt_ui/pages/goals_projection_page.py`.

### 2.3 Incohérences métier ou zones fragiles

- **Le mode de calcul “live” et le mode “historique” de la bourse ne semblent pas reposer sur le même pipeline**.
  - Impact: risque de divergence de valorisation, PnL ou allocation selon le mode affiché.
  - Fichiers concernés: `qt_ui/panels/bourse_global_panel.py`, `services/portfolio.py`, `services/bourse_analytics.py`, `services/market_history.py`.

- **Le surchargement de patrimoine initial en projection est conceptuellement discutable**.
  - Constat: l'override de patrimoine initial semble repondérer les classes d'actifs, mais pas nécessairement les dettes de manière cohérente.
  - Impact: la projection peut raconter une histoire mathématique qui ne correspond plus à la structure réelle du patrimoine.
  - Fichiers concernés: `services/projections.py`, `qt_ui/pages/goals_projection_page.py`.

- **La notion de scénario par défaut n'est pas protégée au niveau base**.
  - Constat: la page semble remettre tous les scénarios d'un scope à `0`, puis en remettre un à `1`, sans contrainte d'unicité explicite.
  - Impact: en cas d'erreur intermédiaire, de concurrence future ou d'évolution UI, plusieurs scénarios “par défaut” peuvent coexister.
  - Fichiers concernés: `qt_ui/pages/goals_projection_page.py`, `services/goals_projection_repository.py`, migrations SQL.

- **Des commentaires et tests ne reflètent plus le comportement réel**.
  - Constat: `tests/test_snapshots.py` attend encore `sens_flux("INCONNU") == -1`, alors que `utils/validators.py` documente maintenant une `ValueError` pour type inconnu.
  - Impact: documentation vivante non fiable, confiance réduite dans les tests.
  - Fichiers concernés: `utils/validators.py`, `tests/test_snapshots.py`.

### 2.4 Cas limites insuffisamment sécurisés

- Base vide ou partiellement initialisée: beaucoup de pages semblent survivre grâce à des `except Exception`, pas grâce à de vrais états vides explicitement gérés.
- Imports partiels: présence d'effets de bord métier non toujours rattachés proprement à un batch.
- Données FX incomplètes: certaines valorisations tombent à `0` ou dérivent vers `None` / `NaN` selon le pipeline utilisé.
- Données famille incomplètes: l'absence de certains champs agrégés peut produire des écarts silencieux plutôt qu'une alerte claire.

## 3. Problèmes techniques / architecture

### 3.1 Fichiers et classes beaucoup trop gros

Les gros fichiers sont un vrai sujet structurel. Les plus préoccupants:

- `qt_ui/pages/goals_projection_page.py`
- `qt_ui/pages/import_page.py`
- `qt_ui/pages/famille_page.py`
- `qt_ui/main_window.py`
- `services/snapshots.py`
- `services/tr_import.py`
- `qt_ui/panels/credits_overview_panel.py`
- `qt_ui/panels/bourse_global_panel.py`
- `qt_ui/panels/famille_dashboard_panel.py`

Effets concrets:

- lecture difficile
- régressions faciles
- responsabilités entremêlées
- tests unitaires difficiles à écrire
- refactor futur coûteux

### 3.2 Découpage insuffisant entre UI, orchestration et métier

Le problème n'est pas l'absence totale de couches, mais leur porosité.

Exemples typiques:

- Les pages UI pilotent directement beaucoup trop de logique métier et de persistance.
- Les panels calculent, chargent, rechargent, formatent et affichent au même endroit.
- Les services manipulent parfois à la fois SQL, règles métier, conversions et représentation d'affichage.

Conséquence: l'application devient difficile à faire évoluer sans toucher plusieurs couches à la fois.

### 3.3 Duplication et centralisation incomplète

- DDL réparti entre `db/schema.sql`, `services/db.py` et plusieurs fonctions `ensure_*`.
- Logique de snapshots / patrimoine déclinée dans plusieurs services avec variantes.
- Logique de calcul de liquidité et d'agrégats dispersée entre snapshots, panels et services spécialisés.
- Gestion du temps / dates / semaines / timezone répétée à plusieurs endroits.

Cette duplication n'est pas seulement esthétique: elle crée déjà des incohérences visibles, notamment sur la famille.

### 3.4 Gestion d'erreurs trop large

Le volume de `except Exception` est trop important, notamment dans:

- `qt_ui/pages/import_page.py`
- `qt_ui/pages/goals_projection_page.py`
- `services/import_history.py`
- plusieurs services de données / diagnostics

Problème de fond:

- l'application masque des erreurs au lieu de les traiter
- les états dégradés deviennent silencieux
- le débogage réel devient plus coûteux

### 3.5 Conventions hétérogènes

- Mélange de services très structurés et d'autres beaucoup plus opportunistes.
- Cohérence variable entre repositories dédiés et accès SQL directs dispersés.
- Nommage parfois stable, parfois historiquement dérivé.
- Quelques signes de dette de fusion / évolution rapide: imports dupliqués, commentaires obsolètes, logique laissée en place après évolution du schéma.

## 4. Performance / robustesse

### 4.1 Travail lourd encore exécuté sur le thread UI

Plusieurs pages chargent ou recalculent beaucoup trop en synchrone:

- changement de page dans `qt_ui/main_window.py`
- changement de personne dans `qt_ui/pages/personnes_page.py`
- chargement bourse globale
- chargement famille / dashboard / projections
- flux d'import et de preview

Impact:

- gels temporaires
- sensation de lenteur dès que le volume augmente
- risque de “l'application a planté” alors qu'elle bloque simplement l'interface

### 4.2 Recalculs et requêtes coûteuses

Points à surveiller:

- relectures répétées de transactions avec des limites très élevées
- agrégations Python / pandas là où une agrégation SQL suffirait
- snapshots / valorisations / FX recalculés trop souvent
- nombreux `commit()` à grain très fin, nuisibles à la performance et à la cohérence transactionnelle

### 4.3 Usage de pandas pas toujours proportionné

Pandas est utile pour certains pipelines analytiques, mais plusieurs parties de l'application l'utilisent pour des opérations qui relèvent davantage de SQL ou d'objets métier simples.

Conséquences:

- surcoût mémoire
- complexité de debug
- difficulté à traiter proprement `None`, `NaN`, conversions de type et arrondis

### 4.4 Robustesse des valorisations et FX

- Les conversions FX manquantes peuvent sous-valoriser silencieusement le patrimoine.
- Certains chemins de calcul semblent plus stricts que d'autres face aux valeurs manquantes.
- L'historique investi peut utiliser des conversions qui ne sont pas historiquement alignées, ce qui déforme les séries passées.

### 4.5 Scalabilité future

Le projet fonctionnera probablement correctement sur des volumes petits à moyens, mais plusieurs choix actuels sont fragiles si l'utilisateur accumule:

- plusieurs années d'historique bancaire
- beaucoup de transactions titres
- plusieurs personnes / familles / comptes
- synchronisations de marché régulières

## 5. UX / logique produit

### 5.1 La page Import est trop chargée

La page Import concentre trop de responsabilités produit:

- imports mensuels
- import Bankin
- import Trade Republic
- historique / rollback
- configuration crédit
- génération d'amortissement

Conséquence: forte densité cognitive, difficulté à comprendre l'ordre des actions et les conséquences métier.

### 5.2 La confiance dans les chiffres peut être entamée

Le plus gros risque produit n'est pas seulement un crash, mais une **perte de confiance**.

Quand un même patrimoine peut diverger selon:

- page famille
- projection famille
- mode live / historique
- disponibilité FX
- état des snapshots

alors l'utilisateur ne sait plus quel chiffre croire.

### 5.3 Objectifs & Projection: puissant mais trop dense

La page apporte de la valeur, mais elle paraît trop complexe pour son niveau actuel de robustesse.

Points faibles probables:

- trop d'options dans une seule surface
- logique de scénarios, presets, jalons et projections pas assez hiérarchisée
- effort mental élevé pour comprendre quel paramètre pilote réellement le résultat

### 5.4 Cohérence inter-pages perfectible

- La logique famille n'est pas totalement homogène entre dashboard et projections.
- Les pages personne et famille n'expliquent pas toujours la provenance du chiffre affiché.
- Les chemins de calcul “historique”, “live”, “snapshot” et “projection” devraient être plus lisibles pour l'utilisateur.

### 5.5 Ce qui manque côté produit

- Des messages d'état plus pédagogiques quand une valeur est estimée, manquante ou partielle.
- Une distinction explicite entre donnée saisie, donnée importée, donnée calculée et donnée projetée.
- Des indicateurs de fraîcheur des données plus systématiques.
- Une simplification du parcours crédit et import.

## 6. Sécurité / fiabilité / qualité

### 6.1 Validation de données insuffisante par endroits

- Certaines validations existent, mais elles ne sont pas centralisées.
- Plusieurs entrées UI semblent reposer sur des conversions tardives ou sur des `try/except` larges.
- Les imports restent une zone particulièrement sensible aux formats incomplets ou inattendus.

### 6.2 Qualité transactionnelle moyenne

- Beaucoup d'opérations sont engagées par petits morceaux.
- Certaines suites d'actions métier devraient être atomiques et ne le sont pas assez.
- Les rollbacks métier sont incomplets.

### 6.3 Risque de crash ou d'état partiellement faux

- `SyntaxError` dans un module métier critique.
- Requêtes SQL non alignées avec le schéma réel.
- Champs lus sans être systématiquement produits sur tous les pipelines.
- Exceptions parfois avalées au lieu de faire échouer proprement l'opération.

### 6.4 Couverture de tests insuffisante

Constat pragmatique:

- seulement **9 fichiers de tests** pour environ **652 lignes** sur un projet devenu large
- pas de vraie couverture UI
- faible couverture des imports complexes, des scopes famille, des pages PyQt et des chemins critiques de cohérence
- `README.md` indique `pytest -q`, mais l'environnement observé ne dispose pas de `pytest`
- certains tests ne sont plus alignés avec le comportement courant

### 6.5 Points positifs malgré tout

- Le projet a déjà une culture de tests minimale.
- La présence de migrations et d'un schéma explicite réduit le risque de dérive totale.
- Des garde-fous existent déjà sur certaines absences de colonnes / données.

## 7. Idées d'amélioration

### 7.1 Améliorations rapides

- Corriger les erreurs bloquantes d'import (`services/imports.py`, `services/tr_import.py`).
- Réaligner immédiatement les snapshots famille avec `immobilier_value`.
- Intégrer `payer_account_id` au flux complet crédit.
- Compléter le rollback des imports pour tous les types exposés par l'UI.
- Réactiver une base de test exécutable (`pytest`, documentation, commandes de validation).
- Remplacer les `except Exception` les plus critiques par des erreurs métiers explicites.

### 7.2 Améliorations moyennes

- Extraire la logique métier lourde des pages `Import` et `GoalsProjection` vers des services d'orchestration dédiés.
- Unifier la source de vérité des agrégats famille.
- Isoler un pipeline unique de valorisation bourse, avec variantes live / historique clairement cadrées.
- Mieux centraliser les validations de formulaires et d'imports.
- Introduire des transactions explicites sur les opérations multi-étapes.
- Réduire les recalculs via cache applicatif ciblé sur snapshots, prix et FX.

### 7.3 Grosses améliorations / V2 long terme

- Repenser le découpage de l'application par domaines métier: imports, patrimoine courant, marché, crédits, projections, famille.
- Introduire une couche “application services / use cases” claire entre UI et repositories.
- Déplacer les traitements lourds hors du thread UI avec une stratégie de tâches asynchrones cohérente.
- Construire une vraie stratégie de tests: unitaires, intégration SQLite, tests de cohérence métier, tests UI minimaux.
- Définir une politique formelle de “source de vérité” pour chaque KPI affiché.

## 8. Liste de tâches concrètes priorisées

### 8.1 Priorité haute

| Titre | Explication courte | Fichiers probablement concernés | Difficulté |
|---|---|---|---|
| Corriger le module `services/imports.py` | Le module ne compile pas et casse un pan critique des imports | `services/imports.py`, `tests/test_imports.py`, `qt_ui/pages/import_page.py` | Facile |
| Réparer l'import Trade Republic vis-à-vis de l'ISIN | La requête utilise une colonne absente du schéma et la déduplication est mal branchée | `services/tr_import.py`, `db/schema.sql`, éventuellement `services/repositories.py` | Moyen |
| Réintégrer `immobilier_value` dans les snapshots famille | Aujourd'hui la famille peut être projetée avec un patrimoine faux | `services/family_snapshots.py`, `services/projections.py`, `services/family_dashboard.py`, `qt_ui/pages/famille_page.py` | Moyen |
| Persister correctement `payer_account_id` dans les crédits | L'UI collecte l'information mais le service de persistance n'est pas cohérent | `services/credits.py`, `qt_ui/pages/import_page.py`, `db/schema.sql` | Facile |
| Compléter le rollback des imports crédit | L'historique d'import n'est pas fiable si certains batchs ne sont pas réellement annulables | `services/import_history.py`, `services/credits.py`, `qt_ui/pages/import_page.py` | Moyen |
| Sécuriser le réimport mensuel partiel | Éviter qu'un import partiel efface toute l'historique d'une personne | `services/imports.py`, `qt_ui/pages/import_page.py` | Moyen |
| Remettre la chaîne de tests en état | Installer / déclarer `pytest`, réaligner README et rendre la suite exécutable | `requirements.txt`, `README.md`, `tests/*` | Facile |
| Corriger les tests obsolètes sur `sens_flux` | Les tests doivent refléter le contrat actuel, pas l'ancien comportement | `utils/validators.py`, `tests/test_snapshots.py` | Facile |

### 8.2 Priorité moyenne

| Titre | Explication courte | Fichiers probablement concernés | Difficulté |
|---|---|---|---|
| Extraire la logique de la page Import | Réduire la taille et le couplage de la page la plus risquée | `qt_ui/pages/import_page.py`, nouveaux services d'orchestration, `services/imports.py`, `services/tr_import.py`, `services/import_history.py` | Difficile |
| Extraire la logique de la page Objectifs & Projection | Diminuer le risque de régression sur un écran devenu trop dense | `qt_ui/pages/goals_projection_page.py`, `services/projections.py`, `services/goals_projection_repository.py`, `services/native_milestones.py` | Difficile |
| Unifier le pipeline de calcul famille | Éviter les chiffres différents selon l'écran | `services/family_snapshots.py`, `services/family_dashboard.py`, `services/projections.py` | Moyen |
| Réduire les `except Exception` | Transformer des erreurs silencieuses en erreurs métier ou messages UX propres | `qt_ui/pages/import_page.py`, `qt_ui/pages/goals_projection_page.py`, `services/*` | Moyen |
| Regrouper la logique de schéma / migrations | Éviter la duplication entre `schema.sql`, migrations et `ensure_*` dispersés | `db/schema.sql`, `migrations/*`, `services/db.py`, `core/db_connection.py` | Difficile |
| Rendre atomiques les opérations métier multi-étapes | Import, rollback, scénarios par défaut, snapshots | `services/import_history.py`, `services/imports.py`, `services/family_snapshots.py`, `services/goals_projection_repository.py` | Moyen |
| Optimiser les chargements lourds côté UI | Réduire les gels de l'interface sur navigation et changements de scope | `qt_ui/main_window.py`, `qt_ui/pages/personnes_page.py`, `qt_ui/panels/*`, `services/*` | Difficile |

### 8.3 Priorité basse

| Titre | Explication courte | Fichiers probablement concernés | Difficulté |
|---|---|---|---|
| Corriger la rotation de sauvegardes | La logique par préfixe est fragile et peu lisible | `main.py` | Facile |
| Nettoyer les imports et conventions de code | Réduire la dette triviale mais cumulative | `services/credits.py`, divers services / pages | Facile |
| Documenter la source de vérité des KPIs | Mieux expliquer ce qui est calculé, agrégé ou projeté | `README.md`, documentation d'architecture, pages UI concernées | Moyen |
| Introduire des indicateurs de fraîcheur des données | Améliorer la confiance utilisateur | `qt_ui/pages/*`, `qt_ui/panels/*`, `services/market_history.py`, `services/fx.py` | Moyen |
| Réduire l'usage de pandas là où SQL suffit | Gagner en lisibilité et en coût CPU / mémoire | `services/liquidites.py`, `services/bourse_analytics.py`, `services/snapshots.py` | Moyen |

## Conclusion

Le projet est **prometteur mais pas encore suffisamment sécurisé pour inspirer une confiance totale sur les chiffres et les imports**. Le sujet principal n'est pas un manque de fonctionnalités; c'est un besoin de consolidation.

L'ordre de priorité recommandé est clair:

1. réparer les bugs bloquants et les incohérences de données
2. rétablir une base de tests exécutable et crédible
3. unifier les pipelines de calcul critiques
4. seulement ensuite engager les gros refactors UI / architecture
