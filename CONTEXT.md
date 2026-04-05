# Suivie Patrimoine Desktop — CONTEXT

> Fichier de référence pour comprendre rapidement le projet.
> Maintenu manuellement. Dernière mise à jour : 2026-03-19.

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
│   └── schema.sql                  # Schéma SQLite complet (CREATE TABLE IF NOT EXISTS)
├── models/
│   └── enums.py                    # Enums AccountType, AssetType, TxType
├── services/                       # Toute la logique métier (~25 fichiers)
│   ├── db.py                       # init_db(), seed_minimal(), migrations
│   ├── repositories.py             # Requêtes génériques (people, accounts, assets, tx)
│   ├── imports.py                  # Import CSV dépenses/revenus + Bankin
│   ├── tr_import.py                # Import Trade Republic via pytr
│   ├── credits.py                  # Calcul tableau d'amortissement
│   ├── snapshots.py                # Snapshots hebdomadaires personnels
│   ├── family_snapshots.py         # Snapshots hebdomadaires familiaux
│   ├── bourse_analytics.py         # Analytique portefeuille bourse
│   ├── pricing.py                  # Fetch prix via yfinance
│   ├── fx.py                       # Taux de change (Frankfurter)
│   ├── private_equity.py           # PE — valorisation projets
│   ├── depenses_repository.py      # Dépenses mensuelles
│   ├── revenus_repository.py       # Revenus mensuels
│   └── …                           # diagnostics, sankey, portfolio, positions, market…
├── qt_ui/
│   ├── main_window.py              # Fenêtre principale + sidebar navigation
│   ├── pages/
│   │   ├── famille_page.py         # Dashboard famille (snapshots, diagnostic, flux)
│   │   ├── personnes_page.py       # Dashboard individuel (8 onglets + onglets comptes)
│   │   └── import_page.py          # Page d'import (CSV, Bankin, Trade Republic, crédit)
│   ├── panels/                     # ~15 panneaux réutilisables (un par type de vue)
│   └── widgets/                    # Widgets Qt custom (PlotlyView, DataTable, KpiCard…)
└── utils/                          # Helpers (formatters, validators, cache)
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
| `fx_rates` | Taux de change en cache |
| `patrimoine_snapshots_weekly` | Snapshots hebdo par personne |
| `patrimoine_snapshots_family_weekly` | Snapshots hebdo agrégés famille |

---

## Flux de navigation

```
main.py
  └── MainWindow
        ├── Sidebar (3 boutons + raccourcis personnes)
        └── QStackedWidget
              ├── FamillePage       — vue macro famille
              ├── PersonnesPage     — vue détaillée par personne
              └── ImportPage        — saisie / import de données
```

La `PersonnesPage` contient 8 onglets fixes + des onglets dynamiques (un par compte de la personne sélectionnée). Chaque type de compte affiche un panel dédié.

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
- Pas d'export des données (PDF, Excel)
- Pas de notifications ou alertes (ex: seuil de dépenses dépassé)
- Pas de mode multi-utilisateur (réseau)
- Pas d'import automatique planifié (cron-like)
- La page Entreprises est basique (saisie manuelle uniquement)

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

## Points d'attention pour les futures modifications

- **Toujours passer par `services/`** pour la logique métier, pas directement dans les pages/panels.
- **Migrations DB** : ajouter les `ALTER TABLE` dans `services/db.py` → fonction `ensure_people_columns()` ou équivalent (appelée depuis `init_db()`). Le schéma `db/schema.sql` utilise `CREATE TABLE IF NOT EXISTS` mais ne gère pas les colonnes ajoutées après coup.
- **Connexion DB** : utiliser `self._conn` (passé au constructeur de chaque page/panel). Ne pas recréer de connexion depuis un panel.
- **Threads Qt** : les opérations longues (pytr, rebuild snapshots, fetch prix) doivent tourner dans un `QThread` pour ne pas bloquer l'UI. Voir `_ExportThread` dans `import_page.py` et `RebuildThread` dans `famille_page.py` comme modèles.
- **Format des dates en base** : toujours `YYYY-MM-DD` (string). Les mois sont stockés `YYYY-MM-01`.
- **Montants en base** : toujours positifs dans `transactions.amount`. Le sens (entrant/sortant) est porté par `transactions.type`.
