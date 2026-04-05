# Architecture — Patrimoine Desktop (état actuel)

## Stack technique

| Couche | Technologie |
|---|---|
| UI desktop | PyQt6 (`QMainWindow`, `QStackedWidget`, `QTabWidget`) |
| Widgets graphiques | Plotly via `QWebEngineView` |
| Données/Calcul | `pandas`, `numpy` |
| Base de données | SQLite local (WAL) ou Turso/libsql (embedded replica) |
| Marché/FX | `yfinance` |
| Point d'entrée | `main.py` |

---

## Vue d'ensemble runtime

1. `main.py` initialise logging, handler global d'exception et style Qt global.
2. `core/db_connection.py` crée la connexion singleton :
   - `init_db()` (schema + migrations),
   - `seed_minimal()` (personnes/comptes de base),
   - `ensure_credits_migrations()`.
3. `qt_ui/main_window.py` instancie 4 pages racines :
   - `FamillePage`,
   - `PersonnesPage`,
   - `ImportPage`,
   - `SettingsPage`.
4. Au démarrage, un `AutoRebuildThread` lance un rebuild snapshots hebdo par personne (`rebuild_snapshots_person_from_last`) sans bloquer l'UI.
5. À la fermeture, backup automatique DB (`patrimoine.db` + variante Turso) dans `~/.patrimoine/backups`.

---

## Arborescence projet (code actif)

```text
Suivie patrimoine desktop/
├── main.py
├── ARCHITECTURE.md
├── readme.md
├── requirements.txt
│
├── core/
│   └── db_connection.py               # Singleton DB (init + seed + get/close)
│
├── db/
│   ├── schema.sql                     # Schéma SQL de référence
│   └── migrations/
│       ├── 001_initial.sql            # Initialisation schema_version
│       └── 002_add_indexes.sql        # Index composite transactions
│
├── qt_ui/
│   ├── main_window.py                 # Fenêtre principale + sidebar + navigation
│   ├── theme.py                       # Design tokens + styles + layouts Plotly
│   ├── components/
│   │   ├── animated_stack.py          # Transitions pages
│   │   ├── animated_tab.py            # Onglets animés
│   │   └── skeleton_handler.py        # Gestion placeholders de chargement
│   ├── pages/
│   │   ├── famille_page.py            # Dashboard famille + diagnostic + flux
│   │   ├── personnes_page.py          # Sélecteur personne + onglets fixes + comptes dynamiques
│   │   ├── import_page.py             # Imports CSV/Bankin/TR + crédit + historique/rollback
│   │   └── settings_page.py           # Préférences, backup manuel, logs, infos système
│   ├── panels/
│   │   ├── vue_ensemble_panel.py
│   │   ├── depenses_panel.py
│   │   ├── revenus_panel.py
│   │   ├── credits_overview_panel.py
│   │   ├── private_equity_panel.py
│   │   ├── entreprises_panel.py
│   │   ├── immobilier_panel.py
│   │   ├── liquidites_panel.py
│   │   ├── bourse_global_panel.py
│   │   ├── taux_epargne_panel.py
│   │   ├── ajout_compte_panel.py
│   │   ├── compte_banque_panel.py
│   │   ├── compte_bourse_panel.py
│   │   ├── compte_credit_panel.py
│   │   ├── saisie_panel.py
│   │   └── sankey_panel.py
│   └── widgets/
│       ├── kpi_card.py
│       ├── metric_label.py
│       ├── data_table.py
│       ├── plotly_view.py
│       └── loading_overlay.py
│
├── services/
│   ├── db.py                          # Connexions SQLite/libsql, wrappers compat, init/migrations
│   ├── repositories.py                # Repositories génériques (people/accounts/assets/tx/snapshots)
│   ├── calculations.py                # Solde/cashflow basés flux
│   ├── snapshots.py                   # Snapshots hebdo personne (rebuilds multi-stratégies)
│   ├── family_snapshots.py            # Agrégation famille hebdo
│   ├── family_dashboard.py            # KPIs/allocations/leaderboards famille
│   ├── diagnostics.py                 # Diagnostic bourse as-of
│   ├── diagnostics_global.py          # Data health global
│   ├── market_history.py              # Sync weekly prix/FX as-of
│   ├── market_repository.py           # Upsert/get weekly prices & FX
│   ├── pricing.py                     # Prix live fallback
│   ├── fx.py                          # Conversion devise et FX rates
│   ├── positions.py                   # Positions bourse as-of
│   ├── bourse_analytics.py            # Perf, CAGR, breakdowns, diagnostics tickers
│   ├── portfolio.py                   # Valorisation portefeuille v1/v2 FX
│   ├── depenses_repository.py
│   ├── revenus_repository.py          # Inclut taux d'épargne mensuel
│   ├── credits.py                     # Crédit + amortissement + coût réel
│   ├── entreprises_repository.py
│   ├── immobilier_repository.py
│   ├── private_equity_repository.py
│   ├── private_equity.py
│   ├── pe_cash_repository.py
│   ├── liquidites.py                  # Vue consolidée liquidités
│   ├── sankey.py                      # Données du diagramme de flux
│   ├── imports.py                     # Imports CSV larges + Bankin
│   ├── tr_import.py                   # Flux Trade Republic/pytr + mapping transactions
│   ├── import_history.py              # Batches d'import + rollback
│   ├── isin_resolver.py               # Résolution ISIN -> ticker (+ cache DB)
│   ├── vue_ensemble_metrics.py        # KPIs agrégés page Vue d'ensemble
│   ├── projections.py                 # Scénarios de projection patrimoine
│   └── pdf_export.py                  # Export PDF patrimoine
│
├── utils/
│   ├── format_monnaie.py
│   ├── libelles.py
│   ├── validators.py
│   └── pagination.py
│
├── tests/
│   ├── conftest.py
│   ├── test_calculations.py
│   ├── test_credits.py
│   ├── test_imports.py
│   └── test_snapshots.py
│
└── legacy_streamlit/                  # Archive (ancien socle Streamlit)
```

---

## Navigation UI

### Sidebar (MainWindow)

- `Famille`
- `Personnes`
- `Import`
- `Paramètres`
- Boutons dynamiques par personne (navigation directe vers `PersonnesPage`).

### Page Famille

3 onglets:
- `Snapshots weekly`: KPIs, courbe net hebdo, allocations, leaderboard.
- `Diagnostic`: statut freshness snapshots/marché/tickers + rebuild global.
- `Flux (V1)`: synthèse flux basée transactions (solde, cashflow, dernières ops).

### Page Personnes

- Sélecteur de personne.
- 9 onglets fixes:
  - Vue d'ensemble,
  - Dépenses,
  - Revenus,
  - Crédits,
  - Private Equity,
  - Entreprises,
  - Immobilier,
  - Liquidités,
  - Bourse globale.
- Zone comptes dynamiques par type de compte.

Mapping des comptes dynamiques:
- `BANQUE` -> `CompteBanquePanel`
- `PEA`, `PEA_PME`, `CTO`, `CRYPTO`, `ASSURANCE_VIE`, `PER`, `PEE` -> `CompteBoursePanel`
- `CREDIT` -> `CompteCreditPanel`
- autres types -> `SaisiePanel` générique

### Page Import

Modes d'import:
- Dépenses mensuelles (CSV large)
- Revenus mensuels (CSV large)
- Bankin (transactions)
- Trade Republic (via `pytr`)
- Crédit (fiche + génération amortissement)

Inclut un panneau d'historique des imports (`import_batches`) avec rollback par batch.

### Page Paramètres

- Infos système (DB, logs, backups, versions)
- Préférences (`QSettings`): devise par défaut, délai rebuild auto, retention backups
- Backup manuel / export DB
- Accès dossier logs
- À propos

---

## Architecture base de données

Tables cœur:
- `people`, `accounts`, `assets`, `transactions`
- `depenses`, `revenus`
- `credits`, `credit_amortissements`

Tables marché:
- `prices`, `fx_rates` (historique non-hebdo)
- `asset_prices_weekly`, `fx_rates_weekly` (as-of hebdo)

Tables snapshots:
- `patrimoine_snapshots` (historique legacy)
- `patrimoine_snapshots_weekly` (personne)
- `patrimoine_snapshots_family_weekly` (famille)

Tables classes d'actifs spécifiques:
- `pe_projects`, `pe_transactions`, `pe_cash_transactions`
- `enterprises`, `enterprise_shares`, `enterprise_history`
- `immobiliers`, `immobilier_shares`, `immobilier_history`

Tables techniques:
- `import_batches` (traçabilité imports + rollback)
- `schema_version` (versioning migrations SQL)
- `isin_ticker_cache` (résolution ISIN)
- `rebuild_watermarks` (rebuild backdated-aware)
- `bank_subaccounts` (liens compte banque conteneur -> sous-comptes)

---

## Flux de données clés

### 1) Calcul patrimoine hebdo personne

`transactions + positions + prix weekly + fx weekly + crédits + PE + entreprises + immobilier`
-> `services/snapshots.py`
-> `patrimoine_snapshots_weekly`.

### 2) Agrégation famille

`patrimoine_snapshots_weekly (N personnes)`
-> `services/family_snapshots.py`
-> `patrimoine_snapshots_family_weekly`.

### 3) Import traçable + annulation

`ImportPage` -> `create_batch()` -> import service (`imports.py` / `tr_import.py`) -> `close_batch()`.
En cas d'annulation: `rollback_batch()` supprime les lignes liées (`transactions`/`depenses`/`revenus`) puis passe le batch en `ROLLED_BACK`.

---

## Threading & perf

- Rebuilds lourds exécutés en `QThread` (`AutoRebuildThread`, `RebuildAllThread`, etc.).
- Connexion DB dédiée dans les threads de fond (évite partage unsafe cross-thread).
- SQLite en mode WAL + index composite `transactions(person_id, account_id, date)`.
- Conversion/compat libsql via wrappers `DictRow`, `WrappedCursor`, `SyncedLibsqlConn`.

---

## Conventions de structure

- `services/` contient la logique métier (aucune dépendance Qt).
- `qt_ui/` contient l'assemblage interface + orchestration des actions utilisateur.
- Pattern panel côté `PersonnesPage`: `set_person(person_id)` puis `refresh()`.
- Le thème visuel est centralisé dans `qt_ui/theme.py`.
- Les tests unitaires couvrent en priorité les calculs métier et la cohérence des imports/snapshots.
