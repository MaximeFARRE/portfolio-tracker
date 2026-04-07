# Architecture — Patrimoine Desktop (état réel)

> Dernière mise à jour : 2026-04-07

## 1) Principe directeur

Architecture cible stricte :

```text
UI -> Services -> Repository / DB
```

Règles opérationnelles :
- Les pages/panels Qt orchestrent l'affichage et l'état UI.
- Les calculs métier, agrégations et normalisations vivent dans `services/`.
- Les repositories/DB ne sont pas appelés directement depuis l'UI (hors cas legacy explicitement documenté).

## 2) Stack technique

| Couche | Technologie |
|---|---|
| UI desktop | PyQt6 (`QMainWindow`, `QStackedWidget`, `QTabWidget`) |
| Graphiques | Plotly via `QWebEngineView` |
| Data/Calcul | `pandas`, `numpy` |
| Base de données | SQLite local (WAL) ou Turso/libsql (embedded replica) |
| Marché/FX | `yfinance` + services internes (`pricing`, `fx`, `market_history`) |
| Entrée app | `main.py` |

## 3) Runtime principal

1. `main.py` initialise logging + handler d'exception global + thème.
2. `core/db_connection.py` ouvre la connexion singleton et applique init/migrations via `services/db.py`.
3. `qt_ui/main_window.py` instancie les pages racines :
   - `FamillePage`
   - `PersonnesPage`
   - `GoalsProjectionPage`
   - `ImportPage`
   - `SettingsPage`
4. Au démarrage, l'auto-rebuild snapshots hebdo est exécuté en thread, puis l'écran actif est rafraîchi.
5. À la fermeture, backup DB local + variantes nécessaires.

## 4) Structure active (résumé)

```text
.
├── main.py
├── ARCHITECTURE.md
├── ARCHITECTURE_SOURCES_DE_VERITE.md
├── README.md / readme.md
├── core/
├── db/
├── services/
├── qt_ui/
├── utils/
└── tests/
```

Domaines services principaux :
- `snapshots.py`, `family_snapshots.py` : historique patrimoine hebdo.
- `family_dashboard.py` : payloads métier pour la page Famille.
- `bourse_analytics.py` : API métier bourse (live + perf + diagnostics).
- `cashflow.py` : API métier cashflow / épargne.
- `credits.py` : crédits, amortissements, CRD, coûts réels.
- `liquidites.py` : synthèse liquidités (point d'entrée public).
- `vue_ensemble_metrics.py` : payload consolidé de la vue d'ensemble personne.
- `projections.py`, `native_milestones.py` : projections et milestones.

## 5) État SSOT par domaine (2026-04-07)

### 5.1 Snapshots patrimoine
- `services.snapshots.get_person_weekly_series` : **source de lecture personne**.
- `services.family_snapshots.get_family_weekly_series` : **source famille**.
- Les historiques ne doivent pas être recalculés à la volée dans l'UI.

### 5.2 Bourse live
- `services.bourse_analytics.get_live_bourse_positions(conn, person_id)` : **point d'entrée global live**.
- `services.bourse_analytics.get_live_bourse_positions_for_account(conn, account_id)` : **point d'entrée compte**.
- Les panels bourse consomment ces fonctions (plus d'appel UI direct à `portfolio.py`).
- `services.portfolio.py` reste un moteur interne appelé par `bourse_analytics`.

### 5.3 Cashflow / épargne
- `services.cashflow.get_cashflow_for_scope` : base revenus/dépenses par scope.
- `services.cashflow.compute_savings_metrics` : KPI d'épargne.
- `services.cashflow.get_person_monthly_savings_series` : série mensuelle d'épargne personne.
- `services.revenus_repository.compute_taux_epargne_mensuel` est un chemin legacy à éviter pour les nouveaux appels UI.

### 5.4 Liquidités
- `services.liquidites.get_liquidites_summary` : point d'entrée public du panel liquidités.
- Les fonctions privées de `liquidites.py` ne doivent pas être importées depuis l'UI.

### 5.5 Crédits
- `services.credits` centralise : CRD, amortissements, coût réel mensuel Bankin.
- `qt_ui/panels/credits_overview_panel.py` contient encore une partie d'agrégation intermédiaire locale (ciblée pour nettoyage complémentaire, sans urgence bloquante).

## 6) Navigation UI (résumé)

### Sidebar
- Famille
- Personnes
- Objectifs & Projections
- Import
- Paramètres
- Boutons dynamiques par personne

### PersonnesPage
- Onglets fixes : vue d'ensemble, dépenses, revenus, taux d'épargne, crédits, liquidités, bourse globale, immobilier, entreprises, private equity, sankey.
- Onglets dynamiques comptes : banque / bourse / crédit / saisie générique selon type.

## 7) Conventions à respecter

- Toujours utiliser `self._conn` dans les pages/panels.
- Aucun SQL métier dans l'UI.
- Aucun `groupby`/agrégation métier non triviale dans l'UI.
- Toute nouvelle métrique doit avoir un point d'entrée service unique (SSOT).
- Ajouter des logs explicites côté services en cas de données absentes/fallback.

## 8) Documents de référence

- `ARCHITECTURE_SOURCES_DE_VERITE.md` : cartographie KPI -> service officiel et politiques de fallback.
- `CONTEXT.md` : contexte produit + périmètre fonctionnel.
- `CLAUDE.md` : règles de développement/refactor obligatoires.
