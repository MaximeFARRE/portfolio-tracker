# Patrimoine Desktop

Application **desktop PyQt6** de suivi patrimonial familial.

L'objectif est de centraliser les comptes, transactions, crédits, investissements (bourse, private equity, immobilier, entreprises), puis de produire des vues exploitables:
- vue famille consolidée,
- vue détaillée par personne,
- diagnostics de qualité des données,
- import assisté des données bancaires et Trading Republic.

## Ce que fait l'application

- Suivi multi-personnes et multi-comptes (`BANQUE`, `PEA`, `CTO`, `CRYPTO`, `CREDIT`, etc.).
- Dashboard famille avec KPIs, évolution hebdomadaire, répartitions et classements.
- Dashboard individuels par onglet:
  - vue d'ensemble,
  - dépenses / revenus,
  - crédits et amortissement,
  - private equity,
  - entreprises,
  - immobilier,
  - liquidités,
  - bourse globale.
- Import de données:
  - CSV dépenses / revenus,
  - CSV Bankin,
  - Trading Republic (via `pytr`),
  - configuration crédit + génération d'amortissement.
- Historique des imports avec rollback (annulation d'un batch).
- Rebuild automatique des snapshots au lancement pour garder les vues à jour.
- Sauvegardes automatiques à la fermeture + logs persistants.

## Stack technique

- **UI**: PyQt6
- **Visualisation**: Plotly (rendu embarqué via QWebEngine)
- **Données**: SQLite local (WAL)
- **Sync distant (optionnel)**: Turso/libsql (embedded replica)
- **Data processing**: pandas, numpy
- **Marché / FX**: yfinance

## Architecture (résumé)

- `main.py`: point d'entrée, cycle de vie app, logging, backup.
- `core/`: gestion de connexion DB.
- `services/`: logique métier (calculs, snapshots, imports, pricing, diagnostics...).
- `qt_ui/`: interface PyQt6 (pages, panels, widgets).
- `db/schema.sql`: schéma SQL initial.
- `tests/`: tests unitaires sur les briques métier.

Le code historique Streamlit est archivé dans `legacy_streamlit/`.

## Installation

### Prérequis

- Python 3.11+ (recommandé)
- pip
- Environnement desktop avec support PyQt6/QWebEngine

### Setup rapide (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Lancement

```powershell
python main.py
```

Au premier lancement, la base est initialisée et seedée automatiquement.

## Configuration

### Base locale (par défaut)

Aucune variable d'environnement nécessaire.

### Turso/libsql (optionnel)

Si ces variables sont présentes, l'application utilise une embedded replica synchronisée:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

Exemple PowerShell:

```powershell
$env:TURSO_DATABASE_URL="libsql://..."
$env:TURSO_AUTH_TOKEN="..."
python main.py
```

## Données locales, logs et backups

Le dossier utilisateur est `~/.patrimoine` avec:

- `logs/patrimoine.log`: logs applicatifs avec rotation.
- `backups/`: backups automatiques des bases SQLite.

Un backup est aussi accessible depuis la page **Paramètres**.

## Tests

Des tests sont présents dans `tests/` (`calculations`, `credits`, `imports`, `snapshots`).

```powershell
pytest -q
```

## Build exécutable (optionnel)

Des fichiers PyInstaller sont inclus:

- `patrimoine.spec`
- `Patrimoine Desktop.spec`

Exemple:

```powershell
pyinstaller patrimoine.spec
```

## Roadmap courte

- Améliorer encore la robustesse des imports hétérogènes.
- Ajouter plus de contrôle sur les règles de valorisation.
- Continuer l'industrialisation des diagnostics et tests.

## Licence

Projet **privé** à usage personnel/familial.
