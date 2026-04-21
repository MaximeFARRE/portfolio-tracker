# Suivie Patrimoine Desktop — CONTEXT

> Fichier de référence pour comprendre rapidement le projet.
> Maintenu manuellement. Dernière mise à jour : 2026-04-07.

---

## Ce que fait l'application

Application desktop de **suivi de patrimoine familial**. Elle consolide en un seul endroit :

- Les **comptes bancaires** (courant, livret, PEL…) avec leurs soldes et transactions
- Les **portefeuilles boursiers** (PEA, CTO, crypto) avec les positions, prix de marché et performance
- Les **crédits** (immobilier, conso…) avec tableau d'amortissement généré automatiquement
- Les **investissements en Private Equity** (Blast, Seedrs, etc.) avec suivi des distributions
- Les **participations en entreprises** (valorisation manuelle)
- Les **dépenses et revenus mensuels** par catégorie (style budget)
- Des **snapshots hebdomadaires** du patrimoine net/brut par personne et famille, pour suivre l'évolution dans le temps
- Des **projections patrimoniales** avec scénarios pessimiste/réaliste/optimiste, par classe d'actifs, avec calcul FIRE
- Des **objectifs financiers** (goals) avec suivi de progression et montant mensuel requis
- Des **jalons gamifiés** (milestones) sur 7 catégories (patrimoine net, bourse, épargne, FIRE…)
- Un **diagramme Sankey** pour visualiser les flux de trésorerie
- Un **système de presets** de simulation personnalisables par scope (personne ou famille)

Elle est multi-personnes (chaque membre de la famille a ses propres comptes et données) avec une vue agrégée familiale.

---

## Stack technique

| Couche | Technologie |
|--------|------------|
| GUI | **PyQt6** (widgets natifs + QWebEngineView pour les graphiques Plotly) |
| Graphiques | **Plotly** (embarqué via QWebEngineView) |
| Base de données | **SQLite local** (`patrimoine_turso.db`) ou **Turso** (embedded replica sync) |
| ORM / requêtes | **pandas** + SQL direct (pas d'ORM, requêtes SQL brutes) |
| Prix de marché | **yfinance** (cours boursiers, ETF) |
| Taux de change | **Frankfurter API** (taux EUR/USD/…) |
| Import bancaire | **Bankin CSV export** |
| Import Trade Republic | **pytr** v0.4.6 (`pip install pytr`) — export CSV via l'API WebSocket TR |
| Langage | Python 3.11+ |

---

## Structure du projet

```
.
├── main.py                         # Point d'entrée — lance QApplication + MainWindow
├── core/
│   └── db_connection.py            # Singleton de connexion DB (remplace st.cache_resource)
├── db/
│   ├── schema.sql                  # Schéma SQLite complet (CREATE TABLE IF NOT EXISTS)
│   └── migrations/                 # Migrations incrémentales (003_goals, 004_presets…)
├── models/
│   └── enums.py                    # Enums AccountType, AssetType, TxType
├── services/                       # Toute la logique métier (~33 fichiers)
│   ├── db.py                       # init_db(), seed_minimal(), migrations
│   ├── repositories.py             # Requêtes génériques (people, accounts, assets, tx)
│   ├── imports.py                  # Import CSV dépenses/revenus + Bankin
│   ├── tr_import.py                # Import Trade Republic via pytr
│   ├── credits.py                  # Calcul tableau d'amortissement + CRD
│   ├── snapshots.py                # Snapshots hebdomadaires personnels (rebuild + lecture)
│   ├── family_snapshots.py         # Snapshots hebdomadaires familiaux (SSOT famille)
│   ├── family_dashboard.py         # KPIs et séries agrégées famille
│   ├── bourse_analytics.py         # Analytique portefeuille bourse (perf, CAGR, séries)
│   ├── portfolio.py                # Calcul positions v2 avec FX de bout en bout
│   ├── positions.py                # Calcul positions v1 (à déprécier, cf. ARCHITECTURE)
│   ├── pricing.py                  # Fetch prix live via yfinance
│   ├── fx.py                       # Taux de change live (Frankfurter)
│   ├── market_history.py           # Prix & FX hebdomadaires historiques (avec fallback multi-tier)
│   ├── market_repository.py        # CRUD prix/FX hebdomadaires en base
│   ├── cashflow.py                 # SSOT cashflow : get_cashflow_for_scope + savings metrics
│   ├── projections.py              # Moteur de projection patrimoniale (ScenarioParams, run_projection, FIRE)
│   ├── goals_projection_repository.py  # CRUD objectifs financiers + scénarios utilisateur
│   ├── simulation_presets_repository.py # Presets pessimiste/réaliste/optimiste par scope
│   ├── native_milestones.py        # Jalons gamifiés (7 catégories, calcul dynamique)
│   ├── vue_ensemble_metrics.py     # Métriques vue d'ensemble par personne
│   ├── private_equity.py           # PE — valorisation, KPIs, séries
│   ├── private_equity_repository.py # CRUD projets et transactions PE
│   ├── pe_cash_repository.py       # Cash plateforme PE (Blast…)
│   ├── immobilier_repository.py    # CRUD biens immobiliers + historique valorisation
│   ├── entreprises_repository.py   # CRUD entreprises + parts + historique
│   ├── depenses_repository.py      # Dépenses mensuelles par catégorie
│   ├── revenus_repository.py       # Revenus mensuels par catégorie
│   ├── liquidites.py               # Calcul liquidités (à exposer en public)
│   ├── sankey.py                   # Construction diagramme Sankey cashflow
│   ├── diagnostics.py              # Diagnostic bourse (prix manquants, dernières dates)
│   ├── diagnostics_global.py       # Diagnostic global (snapshots manquants, statut)
│   ├── isin_resolver.py            # Résolution ISIN → ticker
│   ├── import_history.py           # Historique des imports (batch, rollback)
│   ├── calculations.py             # Utilitaires bas niveau (solde_compte, cashflow_mois)
│   └── pdf_export.py               # Export PDF patrimoine
├── qt_ui/
│   ├── main_window.py              # Fenêtre principale + sidebar navigation
│   ├── pages/
│   │   ├── famille_page.py         # Dashboard famille (snapshots, diagnostic, flux)
│   │   ├── personnes_page.py       # Dashboard individuel (onglets fixes + comptes)
│   │   ├── goals_projection_page.py # Objectifs, projections, scénarios, milestones
│   │   ├── import_page.py          # Import (CSV, Bankin, Trade Republic, crédit)
│   │   └── settings_page.py        # Paramètres, presets simulation, backups
│   ├── panels/                     # ~20 panneaux réutilisables (un par type de vue)
│   │   ├── vue_ensemble_panel.py   # Vue d'ensemble patrimoine personne
│   │   ├── bourse_global_panel.py  # Bourse agrégée (positions, perf, allocation)
│   │   ├── compte_bourse_panel.py  # Détail compte bourse individuel
│   │   ├── depenses_panel.py       # Dépenses par mois/catégorie
│   │   ├── revenus_panel.py        # Revenus par mois/catégorie
│   │   ├── taux_epargne_panel.py   # Taux d'épargne historique
│   │   ├── credits_overview_panel.py # Vue d'ensemble crédits
│   │   ├── compte_credit_panel.py  # Détail crédit (amortissement, CRD)
│   │   ├── liquidites_panel.py     # Synthèse liquidités
│   │   ├── immobilier_panel.py     # Biens immobiliers
│   │   ├── entreprises_panel.py    # Participations entreprises
│   │   ├── private_equity_panel.py # Projets PE
│   │   ├── sankey_panel.py         # Diagramme Sankey
│   │   ├── saisie_panel.py         # Saisie manuelle transactions
│   │   ├── ajout_compte_panel.py   # Création de compte
│   │   └── compte_banque_panel.py  # Détail compte bancaire
│   └── widgets/                    # Widgets Qt custom (PlotlyView, DataTable, KpiCard…)
└── utils/                          # Helpers (format_monnaie, validators, pagination, libelles)
```

---

## Schéma de base de données (tables principales)

| Table | Rôle |
|-------|------|
| `people` | Membres de la famille (`id`, `name`, `tr_phone`) |
| `accounts` | Comptes par personne (BANQUE, PEA, CTO, CREDIT, PE, CRYPTO, IMMOBILIER) |
| `assets` | Référentiel d'actifs (symbol/ISIN, nom, type, devise) |
| `transactions` | Source de vérité — tous les mouvements (ACHAT, VENTE, DEPOT, DIVIDENDE…) |
| `depenses` | Dépenses mensuelles par catégorie (format long : `person_id, mois, categorie, montant`) |
| `revenus` | Revenus mensuels par catégorie (même format) |
| `credits` | Fiche crédit (capital, taux, durée, mensualité…) |
| `credit_amortissements` | Tableau d'amortissement généré (une ligne par échéance) |
| `pe_projects` | Projets Private Equity |
| `pe_transactions` | Flux PE (invest, distrib, fees, valo, vente) |
| `pe_cash_transactions` | Cash de plateforme PE (Blast, etc.) |
| `prices` | Prix d'actifs en cache (date, price, source) |
| `fx_rates` | Taux de change en cache (live) |
| `asset_prices_weekly` | Prix hebdomadaires historiques par actif (via yfinance) |
| `fx_rates_weekly` | Taux FX hebdomadaires historiques (via yfinance) |
| `patrimoine_snapshots_weekly` | Snapshots hebdo par personne |
| `patrimoine_snapshots_family_weekly` | Snapshots hebdo agrégés famille |
| `financial_goals` | Objectifs financiers (montant cible, date cible, priorité, statut) |
| `projection_scenarios` | Scénarios de projection (rendements par classe, inflation, horizon…) |
| `simulation_preset_settings` | Presets de simulation par scope (pessimiste/réaliste/optimiste) |
| `immobiliers` | Biens immobiliers (valorisation, type, parts par personne) |
| `immobilier_history` | Historique des valorisations immobilières |
| `enterprises` | Entreprises (valorisation, dette, parts par personne) |
| `enterprise_history` | Historique des valorisations entreprises |
| `enterprise_shares` | Répartition des parts par personne dans chaque entreprise |
| `import_batches` | Historique des imports (pour rollback) |

---

## Flux de navigation

```
main.py
  └── MainWindow
        ├── Sidebar (5 boutons + raccourcis personnes)
        └── QStackedWidget
              ├── FamillePage            — vue macro famille (snapshots, allocation, perf)
              ├── PersonnesPage          — vue détaillée par personne (~20 panels)
              ├── GoalsProjectionPage    — objectifs, projections, scénarios, milestones
              ├── ImportPage             — saisie / import de données
              └── SettingsPage           — paramètres, presets simulation, backups
```

La `PersonnesPage` contient des onglets fixes (vue d'ensemble, bourse globale, dépenses, revenus, taux d'épargne, crédits, liquidités, immobilier, entreprises, PE, Sankey) + des onglets dynamiques (un par compte de la personne sélectionnée). Chaque type de compte affiche un panel dédié.

---

## Import des données — état actuel

### Bankin (transactions bancaires)
- **Statut : ✅ Fonctionnel**
- Import du CSV export Bankin (`Date, Amount, Description, Account Name, Category Name, Parent Category Name`)
- Mapping des catégories Bankin → catégories internes
- Option : alimenter aussi les tables `depenses`/`revenus` mensuelles

### Dépenses / Revenus (CSV mensuel)
- **Statut : ✅ Fonctionnel**
- Format attendu : CSV large (wide) — colonnes `Date | Catégorie 1 | Catégorie 2 | …`
- Transformé en format long (melt) avant insertion

### Trade Republic — PEA / CTO (via pytr)
- **Statut : ✅ Fonctionnel (flux login + export + import CSV)**
- Dépendance externe : `pip install pytr` (déjà dans requirements.txt)
- Le numéro de téléphone est **sauvegardé par personne** en base (`people.tr_phone`)
- **Étape 1 — Login** : `pytr login -n PHONE -p PIN --store_credentials`
  - Trade Republic envoie une notification push sur l'app pour confirmer
  - Si pytr demande un code 4 caractères, un champ apparaît dans l'UI pour le saisir
  - Les credentials sont sauvegardés localement par pytr après connexion
- **Étape 2 — Export** : `pytr export_transactions --outputdir DIR --sort`
  - Utilise les credentials sauvegardés (pas besoin de ressaisir le PIN)
  - Produit `account_transactions.csv` (colonnes FR : `date, type, valeur, note, isin, parts, frais, impôts / taxes, isin2, parts2`)
- **Étape 3 — Preview + Import** : prévisualisation avec détection des doublons, puis insertion

### Crédit
- **Statut : ✅ Fonctionnel**
- Saisie manuelle de la fiche crédit + génération automatique du tableau d'amortissement
- Gestion du différé (partiel / total)

---

## Ce qui ne marche pas encore / limitations connues

### Import Trade Republic
- **Types de transactions non mappés** : les valeurs du champ `type` dans le CSV FR peuvent différer des clés attendues dans `_TR_TYPE_MAP` (ex: pytr peut sortir des libellés localisés). Si une transaction a un type inconnu, elle est catégorisée `ACHAT` ou `VENTE` selon le signe du montant — à surveiller.
- **Distinction PEA / CTO** : pytr exporte tout dans un seul CSV. Si la personne a un PEA ET un CTO sur Trade Republic, toutes les transactions sont importées dans le compte sélectionné dans l'UI. Il n'y a pas encore de détection automatique du type de compte.
- **Prix unitaire** : calculé comme `montant / parts` (approximatif). Trade Republic ne fournit pas directement le cours d'exécution dans l'export CSV standard.
- **Frais de courtage** : Trade Republic est 0 commission, mais les `impôts / taxes` (ex: TTF) sont fusionnés dans la colonne `fees` — OK pour l'instant.

### Snapshots hebdomadaires
- Le rebuild complet (depuis le début) peut être lent si beaucoup d'historique.
- Pas de reconstruction automatique à l'ouverture — bouton manuel dans la page Famille.

### Prix de marché
- Dépend de yfinance (Yahoo Finance). Certains symboles non-US peuvent être mal reconnus ou absents.
- Pas de fallback si yfinance échoue (ex: timeout réseau).
- Les cryptos et actifs non cotés nécessitent une saisie manuelle du prix.

### Bankin
- L'export Bankin n'inclut pas les comptes PEA/CTO — c'est la raison de l'intégration Trade Republic.
- Mapping catégories Bankin → internes figé dans `services/imports.py` (fonction `map_bankin_to_final`). À adapter si Bankin change ses catégories.

### Multi-personnes / comptes partagés
- Pas de notion de compte joint ou de compte partagé entre deux personnes.
- Chaque compte appartient à exactement une personne.

### Authentification / sécurité
- Pas de mot de passe sur l'application.
- Le PIN Trade Republic n'est **jamais** sauvegardé (saisie à chaque fois).
- Les credentials pytr sont sauvegardés localement par pytr dans `%LOCALAPPDATA%\pytr\` (Windows).

### Fonctionnalités absentes / à venir
- Export PDF basique disponible (`services/pdf_export.py`), mais pas d'export Excel
- Pas de notifications ou alertes (ex: seuil de dépenses dépassé)
- Pas de mode multi-utilisateur (réseau)
- Pas d'import automatique planifié (cron-like)

---

## Variables d'environnement

| Variable | Usage | Défaut |
|----------|-------|--------|
| `TURSO_DATABASE_URL` | URL de la base Turso distante | SQLite local si absent |
| `TURSO_AUTH_TOKEN` | Token d'authentification Turso | SQLite local si absent |

Si les variables Turso ne sont pas définies, l'app utilise `patrimoine_turso.db` en local (SQLite standard).

---

## Lancer l'application

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer
python main.py
```

---

## Architecture SSOT (Sources de Vérité)

Le document **`ARCHITECTURE_SOURCES_DE_VERITE.md`** définit de manière exhaustive :

1. **KPI → Service officiel** : pour chaque KPI (patrimoine, positions bourse, cashflow, taux d'épargne, CRD crédit, projections, FIRE…), la fonction exacte à appeler et son état (OK, à unifier, à créer)
2. **Écrans → Services consommés** : quelle page/panel appelle quel service, quelle logique inline est à éliminer, quel service cible après refactor
3. **Politique de fallback** : comportement autorisé quand une donnée manque (snapshot absent, prix stale, FX introuvable, amortissement non généré…)
4. **Source actuelle vs cible** : pour chaque domaine en transition (bourse positions, cashflow, liquidités…), l'état provisoire, la cible, et les étapes
5. **Projections SSOT** : patrimoine initial projeté, hypothèses utilisateur (13 paramètres), rendements par classe, cashflow injecté, milestones, distinction réel vs simulé
6. **Politique de nommage** : services à créer, modules conservés, modules à déprécier, modules refusés

### Principaux services SSOT (état actuel)

| Domaine | Service SSOT | Fonction clé |
|---------|-------------|--------------|
| Patrimoine famille | `family_snapshots` | `get_family_weekly_series` |
| Vue d'ensemble personne | `vue_ensemble_metrics` | `get_vue_ensemble_metrics` |
| Bourse analytics | `bourse_analytics` | `get_bourse_performance_metrics`, `compute_invested_amount_eur_asof` |
| Cashflow | `cashflow` | `get_cashflow_for_scope`, `compute_savings_metrics` |
| Projections | `projections` | `get_projection_base_for_scope`, `run_projection` |
| Milestones | `native_milestones` | `build_native_milestones_for_scope` |
| Crédits | `credits` | `get_crd_a_date`, `build_amortissement` |

### Unifications en cours (Phase 3+)

- **Bourse** : `portfolio.py` + `positions.py` → tout passe par `bourse_analytics.py` (fonction `get_live_bourse_positions` à créer)
- **Cashflow** : `revenus_repository.compute_taux_epargne_mensuel` → migrer vers `cashflow.compute_savings_metrics`
- **Liquidités** : `liquidites._compute_liquidites_like_overview` → exposer en fonction publique
- **Snapshots personne** : créer `snapshots.get_person_weekly_series` (symétrie avec famille)

---

## Points d'attention pour les futures modifications

- **Toujours passer par `services/`** pour la logique métier, pas directement dans les pages/panels. Consulter `ARCHITECTURE_SOURCES_DE_VERITE.md` (sections 5-6) pour savoir quel service appeler pour chaque KPI et chaque écran.
- **Migrations DB** : ajouter les `ALTER TABLE` dans `services/db.py` → fonction `ensure_people_columns()` ou équivalent (appelée depuis `init_db()`). Le schéma `db/schema.sql` utilise `CREATE TABLE IF NOT EXISTS` mais ne gère pas les colonnes ajoutées après coup.
- **Connexion DB** : utiliser `self._conn` (passé au constructeur de chaque page/panel). Ne pas recréer de connexion depuis un panel.
- **Threads Qt** : les opérations longues (pytr, rebuild snapshots, fetch prix) doivent tourner dans un `QThread` pour ne pas bloquer l'UI. Voir `_ExportThread` dans `import_page.py` et `RebuildThread` dans `famille_page.py` comme modèles.
- **Format des dates en base** : toujours `YYYY-MM-DD` (string). Les mois sont stockés `YYYY-MM-01`.
- **Montants en base** : toujours positifs dans `transactions.amount`. Le sens (entrant/sortant) est porté par `transactions.type`.
