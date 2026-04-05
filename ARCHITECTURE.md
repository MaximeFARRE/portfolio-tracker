# Architecture — Suivie Patrimoine Desktop

## Stack technique

| Couche | Technologie |
|---|---|
| UI | **PyQt6** (QMainWindow, QStackedWidget, QTabWidget) |
| Graphiques | **Plotly** rendu via QWebEngineView |
| Base de données | **SQLite local** (dev) ou **Turso/libsql** (prod, embedded replica) |
| Données financières | **yfinance** (prix boursiers, taux FX) |
| Data processing | **pandas**, **numpy** |
| Point d'entrée | `main.py` |

---

## Arborescence

```
Suivie patrimoine desktop/
│
├── main.py                          # Point d'entrée — QApplication, connexion DB, MainWindow
│
├── core/
│   ├── __init__.py
│   └── db_connection.py             # Singleton connexion DB (get_connection / close_connection)
│
├── services/                        # Logique métier — aucun import Qt
│   ├── db.py                        # init_db, seed_minimal, get_conn, SyncedLibsqlConn, migrations
│   ├── repositories.py              # CRUD générique : people, accounts, assets, transactions...
│   ├── calculations.py              # Calculs financiers : solde, cashflow, performance
│   ├── snapshots.py                 # Rebuild snapshots weekly par personne
│   ├── family_snapshots.py          # Rebuild snapshots weekly famille (agrégation)
│   ├── family_dashboard.py          # KPIs famille, séries temporelles, leaderboards
│   ├── bourse_analytics.py          # Analytics portefeuille boursier (PnL, TWR, allocation)
│   ├── credits.py                   # Calculs crédits (amortissement, capital restant)
│   ├── fx.py                        # Taux de change (fetch yfinance, cache weekly)
│   ├── pricing.py                   # Valorisation positions (prix spot × quantité × FX)
│   ├── market_history.py            # Historique prix weekly (asset_prices_weekly)
│   ├── market_repository.py         # Persistance prix/FX weekly en DB
│   ├── positions.py                 # Positions bourse (calcul depuis transactions)
│   ├── portfolio.py                 # Vue globale portefeuille (toutes classes d'actifs)
│   ├── isin_resolver.py             # Résolution ISIN → ticker yfinance
│   ├── imports.py                   # Import générique d'opérations (CSV/manuel)
│   ├── tr_import.py                 # Import spécifique Trading Republic (CSV)
│   ├── diagnostics.py               # Diagnostic par personne (snapshots manquants)
│   ├── diagnostics_global.py        # Diagnostic global (marché, personnes, tickers)
│   ├── depenses_repository.py       # Dépenses : CRUD + agrégations
│   ├── revenus_repository.py        # Revenus : CRUD + agrégations
│   ├── entreprises_repository.py    # Entreprises : CRUD + valorisation
│   ├── pe_cash_repository.py        # Cash Private Equity : CRUD
│   ├── private_equity.py            # Private Equity : calculs (TRI, multiple)
│   ├── private_equity_repository.py # Private Equity : CRUD
│   ├── sankey.py                    # Construction du diagramme Sankey (flux)
│   └── imports.py                   # Import d'opérations
│
├── qt_ui/                           # Interface PyQt6
│   ├── __init__.py
│   │
│   ├── main_window.py               # MainWindow + NavSidebar (3 pages principales)
│   │
│   ├── pages/                       # Pages de premier niveau (chargées dans QStackedWidget)
│   │   ├── __init__.py
│   │   ├── famille_page.py          # Page Famille : 3 onglets (Dashboard, Diagnostic, Flux)
│   │   ├── personnes_page.py        # Page Personnes : sélecteur + 8 onglets fixes + onglets comptes
│   │   └── import_page.py           # Page Import : formulaire import CSV / manuel
│   │
│   ├── panels/                      # Panneaux réutilisables (un panneau = un onglet ou une section)
│   │   ├── __init__.py
│   │   ├── vue_ensemble_panel.py    # Vue d'ensemble personne (snapshot, allocation, évolution)
│   │   ├── depenses_panel.py        # Dépenses par personne (table + graphiques)
│   │   ├── revenus_panel.py         # Revenus par personne (table + graphiques)
│   │   ├── credits_overview_panel.py# Crédits : tableau de bord + amortissement
│   │   ├── private_equity_panel.py  # Private Equity : positions + TRI
│   │   ├── entreprises_panel.py     # Entreprises détenues (valeur, % participation)
│   │   ├── liquidites_panel.py      # Liquidités (cash banque + cash bourse + PE cash)
│   │   ├── bourse_global_panel.py   # Synthèse bourse tous comptes confondus
│   │   ├── ajout_compte_panel.py    # Formulaire ajout de compte (émet signal account_created)
│   │   ├── compte_banque_panel.py   # Panneau compte BANQUE (opérations, solde)
│   │   ├── compte_bourse_panel.py   # Panneau compte PEA/CTO/CRYPTO (positions, PnL)
│   │   ├── compte_credit_panel.py   # Panneau compte CREDIT (tableau amortissement)
│   │   ├── saisie_panel.py          # Formulaire saisie d'opération générique
│   │   └── sankey_panel.py          # Diagramme Sankey des flux financiers
│   │
│   └── widgets/                     # Composants réutilisables bas-niveau
│       ├── __init__.py
│       ├── kpi_card.py              # KpiCard — carte métrique (titre, valeur, tone couleur)
│       ├── metric_label.py          # MetricLabel — étiquette simple (label + valeur)
│       ├── data_table.py            # DataTableWidget — tableau pandas → QTableWidget
│       └── plotly_view.py           # PlotlyView — rendu figure Plotly via QWebEngineView
│
├── utils/
│   ├── cache.py                     # Cache Streamlit (héritage, inutilisé en Qt)
│   ├── format_monnaie.py            # money(val) → "1 234,56 €"
│   ├── formatters.py                # Formateurs génériques (dates, pourcentages)
│   ├── libelles.py                  # afficher_type_compte() — labels lisibles
│   └── validators.py                # Validations (montants, symboles, dates)
│
├── models/
│   └── enums.py                     # Enums : AccountType, TransactionType, etc.
│
├── db/
│   └── schema.sql                   # Schéma SQL complet (tables + index)
│
├── ui/                              # Ancien code Streamlit (non utilisé en Qt, conservé pour référence)
│   └── *.py
│
├── pages/                           # Ancien code Streamlit (non utilisé en Qt)
│   └── *.py
│
├── app.py                           # Ancien point d'entrée Streamlit (non utilisé)
├── requirements.txt                 # Dépendances Python
└── patrimoine.spec                  # Spec PyInstaller (packaging en .exe)
```

---

## Schéma de base de données

```
people                          accounts
  id (PK)                         id (PK)
  name                            person_id (FK → people)
  tr_phone                        name
                                  account_type  (BANQUE|PEA|CTO|CRYPTO|CREDIT|PE|IMMOBILIER)
                                  institution
                                  currency
                                  created_at

assets                          transactions
  id (PK)                         id (PK)
  symbol                          account_id (FK → accounts)
  name                            person_id (FK → people)
  asset_type                      date
  currency                        type  (BUY|SELL|DIVIDEND|DEPOT|RETRAIT|...)
                                  asset_symbol
                                  quantity
                                  price
                                  amount
                                  fees
                                  currency
                                  category
                                  note

── Snapshots weekly ──────────────────────────────────────────────────────────
patrimoine_snapshots             patrimoine_snapshots_weekly
  person_id (FK)                   person_id (FK)
  snapshot_date                    week_date
  patrimoine_net/brut              patrimoine_net/brut
  liquidites_total                 liquidites_total
  bourse_holdings                  bourse_holdings
  pe_value / ent_value             pe_value / ent_value
  credits_remaining                credits_remaining

patrimoine_snapshots_family_weekly
  family_id (DEFAULT 1)
  week_date
  (mêmes colonnes que weekly)

── Marché ────────────────────────────────────────────────────────────────────
asset_prices_weekly              fx_rates_weekly
  symbol                           base_ccy / quote_ccy
  week_date                        week_date
  adj_close                        rate
  currency                         source
  source
```

---

## Flux de données

```
main.py
  └─ get_connection()          ← core/db_connection.py
       └─ init_db() + seed_minimal()  ← services/db.py
  └─ MainWindow(conn)          ← qt_ui/main_window.py
       ├─ FamillePage(conn)    ← qt_ui/pages/famille_page.py
       │     ├─ FamilleDashboardPanel  → services/family_dashboard.py
       │     ├─ DataHealthPanel        → services/diagnostics_global.py
       │     └─ FluxPanel             → services/repositories.py + calculations.py
       │
       ├─ PersonnesPage(conn)  ← qt_ui/pages/personnes_page.py
       │     ├─ [8 onglets fixes] → panels/* → services/*
       │     └─ [onglets comptes] → panels/compte_*_panel.py
       │
       └─ ImportPage(conn)     ← qt_ui/pages/import_page.py
             └─ services/tr_import.py + imports.py
```

---

## Conventions de code

- **Pattern `set_person(person_id) + refresh()`** : tous les panels fixes de `PersonnesPage` implémentent ces deux méthodes. `set_person()` change l'ID courant, `refresh()` recharge les données.
- **QThread pour les opérations longues** : les rebuilds snapshots sont délégués à des `QThread` dédiés (ex : `RebuildAllThread`) avec signaux `finished` / `error`.
- **Connexion DB singleton** : une seule connexion partagée, gérée par `core/db_connection.py`. La couche service ne crée jamais de connexion, elle reçoit `conn` en paramètre.
- **Services sans Qt** : les fichiers `services/` et `utils/` n'importent jamais PyQt6 — séparation stricte logique/UI.
- **Dark theme global** : le stylesheet Qt est défini une seule fois dans `main.py` et s'applique en cascade.
- **Widgets réutilisables** : `KpiCard`, `MetricLabel`, `DataTableWidget`, `PlotlyView` sont les briques de base de toutes les pages.

---

## Pages de navigation

| Page | Fichier | Contenu |
|---|---|---|
| **Famille** | `qt_ui/pages/famille_page.py` | Snapshots weekly famille, diagnostic data, flux globaux |
| **Personnes** | `qt_ui/pages/personnes_page.py` | 8 onglets fixes (vue, dépenses, revenus, crédits, PE, entreprises, liquidités, bourse) + onglets par compte |
| **Import** | `qt_ui/pages/import_page.py` | Import CSV Trading Republic + saisie manuelle |

---

## Types de comptes

| Type | Panel associé | Description |
|---|---|---|
| `BANQUE` | `compte_banque_panel.py` | Compte courant / épargne |
| `PEA` / `CTO` / `CRYPTO` | `compte_bourse_panel.py` | Portefeuille titres |
| `CREDIT` | `compte_credit_panel.py` | Prêt immobilier / conso |
| `PE` / `IMMOBILIER` / autres | `saisie_panel.py` (générique) | Actifs illiquides |
