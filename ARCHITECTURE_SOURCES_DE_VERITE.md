# Sources de Vérité de l'Application

Ce document définit les *Seules Sources de Vérité* (SSOT - Single Source of Truth) à utiliser pour les calculs fonctionnels. 
L'objectif est d'éliminer les chemins de calcul incohérents et de s'assurer que, quel que soit l'écran, les KPIs (patrimoine, performance bourse, cashflow, etc.) affichent **le même chiffre**.

---

## 1. Patrimoine Global et Historique

### Le problème constaté
L'historique du patrimoine (personne et famille) est parfois recalculé à la volée en sommant les comptes ou en agrégeant des snapshots, avec parfois des décalages sur le "live" par rapport au dernier snapshot.

### La Source de Vérité : Les Snapshots Hebdomadaires (`patrimoine_snapshots` et `patrimoine_snapshots_family_weekly`)
- **Historique** : Il ne doit **jamais** être recalculé à la volée à l'affichage. L'interface (Dashboard, Famille, Bourse globale) doit consommer **les tables de snapshots** via `services.snapshots` et `services.family_snapshots`.
- **Valeur Live (Aujourd'hui)** : La valeur "Live" peut être calculée par-dessus (ex: valeur as-of d'aujourd'hui injectée comme dernier point sur la courbe), mais les données passées doivent être strictes.
- **Famille** : N'utiliser que `family_snapshots.get_family_weekly_series` (qui lit `patrimoine_snapshots_family_weekly`).

*Refactor ciblé : S'assurer que tous les graphiques d'évolution du patrimoine pointent exclusivement sur ces tables et n'essaient pas d'agréger dynamiquement les comptes à chaque rendu.*

---

## 2. Bourse & Portefeuilles

### Le problème constaté
Il existe au moins deux moteurs de calcul de positions :
- `services.positions` (`compute_positions_asof`)
- `services.portfolio` (`compute_positions_v2_fx`)
La vue "Bourse Globale" fait ses propres appels et agrège elle-même les positions "live" alors que `bourse_analytics.py` possède aussi de la logique d'historique. De plus, le montant investi (`invested_eur`) est calculé indépendamment.

### La Source de Vérité : Les Transactions Bourse (Type: ACHAT / VENTE)
- **Positions courantes (Live)** : Le calcul doit toujours se faire via la re-sommation chronologique des quantités issues de la table `transactions` (où `account_type` est PEA, CTO ou CRYPTO) au taux FX live et au Prix live.
- **Outil unifié** : Il faut converger vers **une seule fonction core** de calcul des positions (fusion de `positions.py` et `portfolio.py`). `portfolio.compute_positions_v2_fx` semble être la plus avancée en termes de Forex de bout en bout.
- **Rendements / PnL** : 
  - *Capital Investi* : Somme nette en euros des transferts (ACHAT + Frais - VENTE + Frais associés). Devrait être unifié sous `bourse_analytics.compute_invested_amount_eur_asof`.
  - *Performance (%)* : Doit être basée sur `(Valeur Live / Capital Investi) - 1`.
  - *Revenus Passifs* : Requête stricte sur `transactions` de type `DIVIDENDE` ou `INTERETS` convertis au taux FX du versement. Actuellement bien centralisés dans `bourse_analytics.compute_passive_income_history`.

---

## 3. Cashflow, Épargne et Revenus / Dépenses

### Le problème constaté
Différents endroits calculent la notion de Cashflow (Analytics, Native Milestones, Projections) en lisant directement les tables. 

### La Source de Vérité : Tables `revenus` et `depenses`
- **Revenus et Dépenses mensuels** : La source absolue n'est pas la table `transactions` brutes, mais les tables agréguées `revenus` et `depenses` (souvent générées via les imports CSV ou Bankin).
- **Calcul du Taux d'Épargne** : `(Revenus - Dépenses) / Revenus`. Ce calcul doit être abstrait dans une seule fonction (ex: `services.analytics` ou `services.cashflow`) que `native_milestones.py`, `analytics_views.py` et `projections.py` appelleront pour trouver le `savings_rate_12m` ou `monthly_savings_capacity`.

*Refactor ciblé : Sortir le calcul de cashflow de la vue (analytics_views.py) et de milestones (native_milestones.py) pour le mettre dans un service partagé `services.cashflow` et garantir le même périmètre.*

---

## 4. Crédits Immobiliers & Consommation

### Le problème constaté
L'UI et le Dashboard utilisent les amortissements théoriques ou les coûts Bankin pour évaluer l'impact mensuel.

### La Source de Vérité : La table `credit_amortissements`
- **Tableau de bord** : Le Capital Restant Dû (CRD) à un mois T est *uniquement* la valeur `crd` à la date correspondante dans `credit_amortissements`.
- **Coût Réel versus Théorique** : Si on veut l'impact budget réel, on peut lire les transactions Bankin du mois (`services.credits.cout_reel_mois_credit_via_bankin`), mais pour l'évaluation patrimoniale (Net Worth), c'est l'amortissement théorique généré sur la base du contrat qui sert de passif financier.

---

## Plan d'Action (Phase 3 et suivantes)

1. **Unification Bourse** : Remplacer les usages de `portfolio.py` et intégrer ses forces dans `bourse_analytics.py` (ou `market.py`) afin de n'avoir qu'un seul `get_live_bourse_positions(person_id)`.
2. **Unification Cashflow** : Extraire `_load_monthly_income_expenses_for_scope` de `native_milestones.py` et la fonction équivalente de `analytics_views.py` vers un `services/cashflow.py`.
3. **Ménage des Imports** : Les UIs ne doivent appeler que les services métier (qui encapsulent ces Sources de vérité). 

Ces règles seront la base des prochains refactorings pour garantir une stabilité totale des KPI de l'application.

---

## 5. Cartographie KPI → Service Officiel

Ce tableau liste **la fonction exacte** à appeler pour chaque KPI. Quand l'état est « à unifier », la colonne *Source cible* indique la fonction finale après refactor.

| KPI | Source officielle actuelle | Source cible après refactor | État |
|-----|---------------------------|----------------------------|------|
| **Historique patrimoine personne** | `services.snapshots.rebuild_snapshots_person_from_last` (écriture) / `services.repositories.list_patrimoine_snapshots` (lecture) | `services.snapshots.get_person_weekly_series` (à créer, lecture seule) | Lecture pas encore encapsulée dans un getter dédié |
| **Historique patrimoine famille** | `services.family_snapshots.get_family_weekly_series` | Idem (déjà SSOT) | **OK** |
| **Valeur live patrimoine personne** | `services.vue_ensemble_metrics.get_vue_ensemble_metrics` | Idem (point d'entrée unique pour la vue d'ensemble) | **OK** |
| **Positions live bourse** | `services.portfolio.compute_positions_v2_fx` + agrégation locale dans `bourse_global_panel.py` | `services.bourse_analytics.get_live_bourse_positions` (à créer) | À créer / à unifier |
| **Capital investi bourse** | `services.bourse_analytics.compute_invested_amount_eur_asof` | Idem (déjà SSOT) | **OK** |
| **Série historique bourse** | `services.bourse_analytics.get_bourse_weekly_series` | Idem (déjà SSOT) | **OK** |
| **Performance bourse (perf, CAGR, 12m)** | `services.bourse_analytics.get_bourse_performance_metrics` | Idem (déjà SSOT) | **OK** |
| **Revenus passifs (dividendes, intérêts)** | `services.bourse_analytics.compute_passive_income_history` | Idem (déjà SSOT) | **OK** |
| **Cashflow mensuel (revenus - dépenses)** | Calculé dans `native_milestones.py` ET `analytics_views.py` ET `projections.py` indépendamment | `services.cashflow.get_cashflow_for_scope` | **Partiellement migré** — `cashflow.py` existe mais n'est pas encore appelé partout |
| **Taux d'épargne 12 mois** | `services.revenus_repository.compute_taux_epargne_mensuel` ET `services.cashflow.compute_savings_metrics` | `services.cashflow.compute_savings_metrics` (via `savings_rate_12m`) | À unifier — deux implémentations coexistent |
| **Capacité d'épargne mensuelle** | `services.cashflow.compute_savings_metrics` (via `avg_monthly_savings`) | Idem (déjà SSOT) | **OK** |
| **Capital restant dû (CRD) crédit** | `services.credits.get_crd_a_date` | Idem (déjà SSOT) | **OK** |
| **Coût réel mensuel d'un crédit** | `services.credits.cout_reel_mois_credit_via_bankin` | Idem (déjà SSOT) | **OK** |
| **Positions immobilier** | `services.immobilier_repository.aggregate_positions` | Idem (déjà SSOT) | **OK** |
| **Positions entreprises** | `services.entreprises_repository.list_positions_for_person` | Idem (déjà SSOT) | **OK** |
| **Positions Private Equity** | `services.private_equity.build_pe_positions` | Idem (déjà SSOT) | **OK** |
| **Projection patrimoine** | `services.projections.run_projection` | Idem (déjà SSOT) | **OK** |
| **Base de projection (patrimoine initial)** | `services.projections.get_projection_base_for_scope` | Idem (déjà SSOT) | **OK** |
| **Cible FIRE** | `services.projections.compute_fire_target` | Idem (déjà SSOT) | **OK** |
| **Jalons / Milestones** | `services.native_milestones.build_native_milestones_for_scope` | Idem (déjà SSOT) | **OK** |
| **Diagnostic tickers bourse** | `services.bourse_analytics.get_tickers_diagnostic_df` | Idem (déjà SSOT) | **OK** |
| **Taux FX live** | `services.fx.ensure_fx_rate` | Idem (déjà SSOT) | **OK** |
| **Taux FX historique (hebdo)** | `services.market_history.get_fx_asof` | Idem (déjà SSOT) | **OK** |
| **Prix actif historique (hebdo)** | `services.market_history.get_price_asof` | Idem (déjà SSOT) | **OK** |

---

## 6. Cartographie Écrans → Services Consommés

### 6.1 Pages principales

| Écran | Services appelés aujourd'hui | Logique inline constatée | Service cible après refactor |
|-------|------------------------------|--------------------------|------------------------------|
| **famille_page.py** | `family_snapshots`, `snapshots`, `family_dashboard`, `repositories`, `calculations`, `diagnostics_global` | Agrégation DataFrame (groupby/sum), génération Plotly, statistiques (variance, perf) | Lecture exclusive via `family_snapshots.get_family_weekly_series` + `family_dashboard.*` — zéro agrégation locale |
| **goals_projection_page.py** | `goals_projection_repository`, `projections`, `simulation_presets_repository`, `native_milestones` | Filtrage DataFrame, calculs FIRE, ajustement savings factor | Consommer uniquement `projections.run_projection` et `native_milestones.build_native_milestones_for_scope` — pas de recalcul local |
| **import_page.py** | `imports`, `tr_import`, `import_history`, `credits`, `repositories` | Parsing CSV avec pandas, itération batch | OK — logique d'import légitime dans la page |
| **personnes_page.py** | `repositories` | Itération `.iterrows()` pour peupler les sélecteurs | OK — logique UI légitime |
| **settings_page.py** | `simulation_presets_repository`, `goals_projection_repository` | File I/O (backups), QSettings | OK — logique de config légitime |

### 6.2 Panels détail

| Panel | Services appelés aujourd'hui | Problème identifié | Cible |
|-------|------------------------------|--------------------|-------|
| **vue_ensemble_panel.py** | `vue_ensemble_metrics`, `snapshots`, `market_history` | Agrégation DataFrame famille/personne | Appeler uniquement `vue_ensemble_metrics.get_vue_ensemble_metrics` |
| **bourse_global_panel.py** | `bourse_analytics`, `repositories`, `pricing`, `fx`, `portfolio`, `snapshots`, `tr_import` | **Agrège lui-même les positions live** via `portfolio.compute_positions_v2_fx` + boucle sur comptes | Consommer un seul `bourse_analytics.get_live_bourse_positions` (à créer) |
| **compte_bourse_panel.py** | `repositories`, `pricing`, `fx`, `portfolio` | Calcul de positions par compte via `portfolio` directement | Consommer `bourse_analytics` pour le calcul, UI ne fait que l'affichage |
| **depenses_panel.py** | `depenses_repository` | Aucun | **OK** — lecture directe du repository |
| **revenus_panel.py** | `revenus_repository` | Aucun | **OK** |
| **taux_epargne_panel.py** | `revenus_repository.compute_taux_epargne_mensuel` | Doublon potentiel avec `cashflow.compute_savings_metrics` | Migrer vers `cashflow.compute_savings_metrics` |
| **credits_overview_panel.py** | `credits`, `repositories` | Aucun majeur | **OK** |
| **compte_credit_panel.py** | `credits`, `repositories` | Aucun majeur | **OK** |
| **liquidites_panel.py** | `liquidites._compute_liquidites_like_overview` | Appelle une fonction privée (préfixe `_`) | Exposer via une fonction publique |
| **immobilier_panel.py** | `immobilier_repository` | Aucun | **OK** |
| **entreprises_panel.py** | `entreprises_repository` | Aucun | **OK** |
| **private_equity_panel.py** | `private_equity_repository` | Aucun | **OK** |
| **sankey_panel.py** | `sankey` | Aucun | **OK** |
| **saisie_panel.py** | `repositories` | Aucun | **OK** |

---

## 7. Politique de Fallback

Quand une donnée est absente, voici le comportement **autorisé** par domaine :

### 7.1 Snapshots

| Situation | Comportement actuel | Comportement cible |
|-----------|--------------------|--------------------|
| Snapshot famille manquant sur la semaine courante | Fallback : somme des snapshots individuels (`fallback_person_ids`) | **Conserver ce fallback** — il est explicite et tracé dans le code |
| Snapshot personne manquant | Retourne `{}` (dict vide), les champs valent 0.0 | **Conserver** — l'UI doit afficher « données indisponibles » plutôt que 0 € |
| Dates invalides dans les snapshots | Coercition `errors="coerce"` → lignes supprimées silencieusement | **Conserver** — mais logger un warning |

### 7.2 Prix & FX

| Situation | Comportement actuel | Comportement cible |
|-----------|--------------------|--------------------|
| Prix live absent pour un actif | `fetch_last_price_auto` retourne `(None, source)` → l'appelant met 0.0 | **Prendre le dernier prix hebdo connu** via `market_history.get_price_asof` et **marquer l'actif comme "prix stale"** dans l'UI |
| Taux FX hebdo manquant | Stratégie multi-tier : direct → inverse → cross-rate via USD → `None` | **Conserver la stratégie multi-tier**. Si `None` : `convert_weekly` retourne 0.0 |
| FX live manquant | `fx.ensure_fx_rate` tente un fetch, retourne `None` si échec | **Utiliser le dernier taux connu** (fallback explicite). Ne jamais mettre 0.0 pour un FX car ça annule la valorisation |

### 7.3 Cashflow & Épargne

| Situation | Comportement actuel | Comportement cible |
|-----------|--------------------|--------------------|
| Aucun revenu/dépense enregistré | Retourne DataFrame vide, métriques à 0.0 | **Conserver** — 0.0 est correct (pas de données ≠ donnée à zéro, mais acceptable pour les calculs) |
| Mois manquant dans la série cashflow | Outer merge + `fillna(0.0)` | **Conserver** — un mois sans donnée = 0 revenu et 0 dépense |

### 7.4 Crédits

| Situation | Comportement actuel | Comportement cible |
|-----------|--------------------|--------------------|
| Amortissement absent pour un crédit (crédit très récent) | `get_crd_a_date` : si aucune échéance passée, prend le premier CRD du tableau | **Conserver** — cohérent (le crédit vient de démarrer) |
| Aucun tableau d'amortissement généré | `get_amortissements` retourne DataFrame vide | **L'écran doit afficher « amortissement non généré »** et proposer de le générer via `build_amortissement` |

### 7.5 Immobilier & Entreprises

| Situation | Comportement actuel | Comportement cible |
|-----------|--------------------|--------------------|
| Historique valorisation absent à une date | Fallback : utilise la valorisation courante de la table `immobiliers` / `enterprises` | **Conserver** — c'est la meilleure estimation disponible |

### 7.6 Projections

| Situation | Comportement actuel | Comportement cible |
|-----------|--------------------|--------------------|
| Aucun snapshot disponible pour la base | `_empty_projection_base()` retourne tout à 0.0 | **Conserver** — la projection part de zéro, ce qui est techniquement correct |
| `patrimoine_brut` absent dans le snapshot | Reconstruit : `brut = net + credits` | **Conserver** — reconstruction cohérente |

---

## 8. Séparation Source Actuelle vs Source Cible (par domaine)

### 8.1 Bourse — Positions Live

| | Détail |
|---|--------|
| **Source actuelle provisoire** | `services.portfolio.compute_positions_v2_fx` appelé directement par `bourse_global_panel.py` et `compte_bourse_panel.py`, avec agrégation locale (boucle sur comptes, merge des prix live) |
| **Source cible** | `services.bourse_analytics.get_live_bourse_positions(conn, person_id)` — une seule fonction qui encapsule `compute_positions_v2_fx` + agrégation multi-comptes + prix live + FX |
| **Transition** | 1. Créer `get_live_bourse_positions` dans `bourse_analytics.py` en déplaçant la logique de `bourse_global_panel.py`. 2. Faire pointer les deux panels bourse dessus. 3. Supprimer les imports directs de `portfolio` dans les panels. |

### 8.2 Bourse — Moteur de calcul positions

| | Détail |
|---|--------|
| **Source actuelle provisoire** | Deux moteurs coexistent : `services.positions.compute_positions_asof` (v1, sans FX de bout en bout) et `services.portfolio.compute_positions_v2_fx` (v2, FX complet) |
| **Source cible** | `services.portfolio.compute_positions_v2_fx` est le moteur retenu (FX de bout en bout). `positions.compute_positions_asof` deviendra un wrapper ou sera supprimé. |
| **Transition** | 1. Auditer les appelants de `positions.compute_positions_asof` (utilisé dans `bourse_analytics` pour les snapshots hebdo). 2. Migrer vers `compute_positions_v2_fx`. 3. Déprécier `positions.py` ou le transformer en alias. |

### 8.3 Cashflow / Taux d'épargne

| | Détail |
|---|--------|
| **Source actuelle provisoire** | Deux implémentations : `revenus_repository.compute_taux_epargne_mensuel` (utilisé par `taux_epargne_panel.py`) et `cashflow.compute_savings_metrics` (utilisé par `native_milestones.py` et `projections.py`) |
| **Source cible** | `services.cashflow.compute_savings_metrics` — point d'entrée unique pour tous les KPIs cashflow |
| **Transition** | 1. `taux_epargne_panel.py` migre de `revenus_repository.compute_taux_epargne_mensuel` vers `cashflow.compute_savings_metrics`. 2. `revenus_repository.compute_taux_epargne_mensuel` reste comme wrapper temporaire puis est supprimé. |

### 8.4 Liquidités

| | Détail |
|---|--------|
| **Source actuelle provisoire** | `services.liquidites._compute_liquidites_like_overview` — fonction privée (préfixe `_`) appelée directement par le panel |
| **Source cible** | `services.liquidites.get_liquidites_summary(conn, person_id)` — renommer en fonction publique |
| **Transition** | Renommer la fonction, mettre à jour l'import dans `liquidites_panel.py`. |

### 8.5 Patrimoine personne (lecture historique)

| | Détail |
|---|--------|
| **Source actuelle provisoire** | `services.repositories.list_patrimoine_snapshots` — lecture brute de la table |
| **Source cible** | `services.snapshots.get_person_weekly_series(conn, person_id)` (à créer) — getter dédié symétrique à `family_snapshots.get_family_weekly_series` |
| **Transition** | 1. Créer le getter dans `snapshots.py`. 2. Les écrans migrent vers ce getter. 3. `repositories.list_patrimoine_snapshots` reste pour l'admin/debug. |

---

## 9. Projections — Définition SSOT Complète

### 9.1 Patrimoine initial projeté

| Élément | Source | Fonction |
|---------|--------|----------|
| Patrimoine net de départ | Dernier snapshot (personne ou famille) | `projections.get_projection_base_for_scope` |
| Ventilation par classe d'actifs | Dernier snapshot : `liquidites`, `bourse`, `immobilier`, `private_equity`, `entreprises` | Idem |
| Override utilisateur | Champ `initial_net_worth_override` dans `ScenarioParams` — redistribution proportionnelle automatique | `projections.run_projection` |
| Exclusion résidence principale | `projections.get_primary_residence_value_for_scope` → soustrait la quote-part RP de `immobilier` et `net_worth` | `get_projection_base_for_scope(exclude_primary_residence=True)` |

### 9.2 Hypothèses utilisateur

Stockées dans la table `projection_scenarios` (CRUD via `goals_projection_repository`) :

| Hypothèse | Champ DB | Défaut |
|-----------|----------|--------|
| Rendement liquidités (% annuel) | `return_liquidites_pct` | Dépend du preset |
| Rendement bourse (% annuel) | `return_bourse_pct` | Dépend du preset |
| Rendement immobilier (% annuel) | `return_immobilier_pct` | Dépend du preset |
| Rendement Private Equity (% annuel) | `return_pe_pct` | Dépend du preset |
| Rendement entreprises (% annuel) | `return_entreprises_pct` | Dépend du preset |
| Inflation (% annuel) | `inflation_pct` | Dépend du preset |
| Croissance revenus (% annuel) | `income_growth_pct` | Dépend du preset |
| Croissance dépenses (% annuel) | `expense_growth_pct` | Dépend du preset |
| Épargne mensuelle (override) | `monthly_savings_override` | `None` (calcul auto) |
| Patrimoine initial (override) | `initial_net_worth_override` | `None` (dernier snapshot) |
| Horizon (années) | `horizon_years` | 10 |
| Multiple FIRE | `fire_multiple` | 25 |
| Exclure résidence principale | `exclude_primary_residence` | `False` |

Les **presets** (pessimiste / réaliste / optimiste) sont stockés dans `simulation_preset_settings` et gérés par `services.simulation_presets_repository`. Chaque preset inclut un `savings_factor` qui ajuste l'épargne mensuelle (0.85 pessimiste, 1.0 réaliste, 1.15 optimiste).

### 9.3 Rendements appliqués

- Conversion annuel → mensuel : `(1 + r_annuel/100)^(1/12) - 1`
- Chaque classe d'actifs croît indépendamment chaque mois : `actif *= (1 + r_mensuel)`
- La croissance totale est la somme des croissances par classe
- Le rendement pondéré affiché dans l'UI (via `compute_weighted_return`) est indicatif, pas utilisé dans la simulation

### 9.4 Cashflow injecté

- **Source** : moyenne 12 mois des revenus/dépenses via `projections.compute_average_income_expenses_for_person/family`
- **Override** : si `monthly_savings_override` est défini, il remplace le calcul
- **Croissance** : sans override, revenus et dépenses croissent chaque mois selon `income_growth_pct` / `expense_growth_pct`
- **Injection** : l'épargne mensuelle (`revenus - dépenses`) est ajoutée aux **liquidités** chaque mois

### 9.5 Jalons / Milestones

Définis dans `services.native_milestones.NATIVE_MILESTONE_DEFINITIONS` :

| Catégorie | Métrique source | Unité | Nb de seuils |
|-----------|----------------|-------|--------------|
| Patrimoine net | `net_worth` | EUR | 30 seuils (1k → 10M) |
| Liquidités | `liquidities` | EUR | 10 seuils (500 → 50k) |
| Bourse | `stocks` | EUR | 20 seuils (500 → 2M) |
| Taux d'épargne 12m | `savings_rate_12m` | % | 10 seuils (5% → 60%) |
| Capacité d'épargne mensuelle | `monthly_savings_capacity` | EUR | variable |
| Progression FIRE | `fire_progress` | % | variable |
| Immobilier | `real_estate_value` | EUR | variable |

**Calcul** : `native_milestones.get_scope_milestone_metrics` agrège la base de projection + les métriques cashflow, puis `compute_current_milestone` détermine le niveau atteint et la progression vers le suivant.

### 9.6 Distinction réel vs simulé

| | Réel | Simulé |
|---|------|--------|
| **Source** | Snapshots hebdo (`patrimoine_snapshots*`) + tables `revenus`/`depenses` | `projections.run_projection` |
| **Colonnes** | `patrimoine_net`, `bourse`, `liquidites`, etc. (tables snapshot) | `projected_net_worth`, `projected_net_worth_real` (ajusté inflation), `projected_*` par classe |
| **Ajustement inflation** | Non applicable (valeurs nominales historiques) | `projected_net_worth_real = net_worth / inflation_factor` (facteur cumulé mois par mois) |
| **FIRE** | Progression réelle = `net_worth / fire_target * 100` (basé sur dépenses réelles) | Progression simulée = tracking mensuel avec dépenses croissantes, colonne `fire_progress_pct` + `is_fire_reached` |
| **Décomposition** | N/A | `cumulative_growth` (rendements) et `cumulative_contributions` (épargne) trackés séparément |

---

## 10. Politique de Nommage des Futurs Services

### 10.1 Services à créer

| Service | Fichier | Justification |
|---------|---------|---------------|
| `get_live_bourse_positions(conn, person_id)` | `services/bourse_analytics.py` | Encapsuler la logique actuellement dispersée dans `bourse_global_panel.py` |
| `get_person_weekly_series(conn, person_id)` | `services/snapshots.py` | Symétrie avec `family_snapshots.get_family_weekly_series` |
| `get_liquidites_summary(conn, person_id)` | `services/liquidites.py` | Remplacer la fonction privée `_compute_liquidites_like_overview` |

### 10.2 Modules existants qui restent

| Module | Rôle | Statut |
|--------|------|--------|
| `services/cashflow.py` | SSOT cashflow et taux d'épargne | **Conservé** — déjà créé, à promouvoir comme seul point d'entrée |
| `services/bourse_analytics.py` | SSOT analytics bourse (perf, séries, capital investi) | **Conservé** — sera enrichi avec `get_live_bourse_positions` |
| `services/projections.py` | SSOT projections patrimoine | **Conservé** |
| `services/native_milestones.py` | SSOT milestones / gamification | **Conservé** |
| `services/family_snapshots.py` | SSOT série famille | **Conservé** |
| `services/snapshots.py` | SSOT snapshots personne | **Conservé** — sera enrichi avec getter dédié |
| `services/credits.py` | SSOT crédits | **Conservé** |
| `services/vue_ensemble_metrics.py` | SSOT métriques vue d'ensemble | **Conservé** |

### 10.3 Modules à déprécier / transformer

| Module | Devenir |
|--------|---------|
| `services/portfolio.py` | **Wrapper temporaire** → `compute_positions_v2_fx` sera appelé uniquement par `bourse_analytics`, pas directement par l'UI |
| `services/positions.py` | **À supprimer** après migration des appelants vers `portfolio.compute_positions_v2_fx` |
| `services/calculations.py` | **À évaluer** — `solde_compte` et `cashflow_mois` sont des utilitaires bas niveau, pourraient rester ou être absorbés |

### 10.4 Modules qu'on ne crée PAS

| Module proposé | Raison du refus |
|----------------|-----------------|
| `services/bourse_live.py` | Redondant — tout centraliser dans `bourse_analytics.py` |
| `services/family_metrics.py` | Redondant — `family_dashboard.py` + `family_snapshots.py` couvrent déjà le besoin |
| `services/patrimoine.py` | Trop générique — les snapshots + vue_ensemble_metrics suffisent |
| `services/epargne.py` | Redondant — `cashflow.py` couvre déjà le taux d'épargne et la capacité d'épargne |
