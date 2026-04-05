# Patrimoine Desktop

<p align="center">
  <b>Suivi patrimonial familial en desktop</b><br>
  Centralisez vos comptes, importez vos flux, analysez vos actifs et suivez l'évolution hebdomadaire de votre patrimoine.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/UI-PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6" />
  <img src="https://img.shields.io/badge/Charts-Plotly-3F4F75?logo=plotly&logoColor=white" alt="Plotly" />
  <img src="https://img.shields.io/badge/DB-SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/Sync-Turso%20%28optional%29-111111" alt="Turso optional" />
  <img src="https://img.shields.io/badge/Status-Active%20Development-16a34a" alt="Status" />
</p>

## Sommaire

- [Pourquoi cette application](#pourquoi-cette-application)
- [Fonctionnalités clés](#fonctionnalités-clés)
- [Aperçu de l'interface](#aperçu-de-linterface)
- [Architecture](#architecture)
- [Installation rapide](#installation-rapide)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Tests](#tests)
- [Build exécutable](#build-exécutable)
- [Roadmap](#roadmap)
- [Licence](#licence)

## Pourquoi cette application

`Patrimoine Desktop` répond à un besoin simple: avoir une vue claire, exploitable et consolidée du patrimoine familial, sans dépendre d'un SaaS externe.

Objectifs produit:
- suivre plusieurs personnes et plusieurs types de comptes,
- agréger les transactions et les valorisations dans des vues comparables,
- faciliter les imports de données bancaires/investissement,
- diagnostiquer rapidement la qualité des données et les manques.

## Fonctionnalités clés

- **Consolidation familiale**
  - KPIs patrimoine net/brut,
  - évolution hebdomadaire,
  - répartition par catégories,
  - classements par personne.
- **Analyse par personne**
  - vue d'ensemble,
  - dépenses / revenus,
  - crédits et amortissement,
  - private equity,
  - entreprises,
  - immobilier,
  - liquidités,
  - bourse globale.
- **Gestion multi-comptes**
  - comptes dynamiques par personne (`BANQUE`, `PEA`, `CTO`, `CRYPTO`, `CREDIT`, etc.).
- **Imports assistés**
  - CSV dépenses / revenus,
  - CSV Bankin,
  - Trade Republic via `pytr`,
  - configuration crédit + génération d'amortissement,
  - historique des imports avec rollback.
- **Fiabilité opérationnelle**
  - rebuild automatique des snapshots au démarrage,
  - logs persistants,
  - sauvegardes automatiques à la fermeture,
  - sauvegardes manuelles dans la page Paramètres.


## Architecture

- `main.py`: bootstrap de l'app, logging, cycle de vie, backup.
- `core/`: gestion de connexion base de données.
- `services/`: logique métier (calculs, snapshots, import, pricing, diagnostics...).
- `qt_ui/`: interface PyQt6 (pages, panels, widgets).
- `db/schema.sql`: schéma SQL initial.
- `tests/`: tests unitaires métier.
- `legacy_streamlit/`: ancien socle Streamlit conservé en archive.

## Installation rapide

### Prérequis

- Python `3.11+` recommandé
- `pip`
- Environnement desktop compatible PyQt6/QWebEngine

### Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Lancer l'application

```powershell
python main.py
```

Au premier démarrage, la base locale est initialisée et seedée automatiquement.

## Configuration

### Mode local (par défaut)

Aucune variable d'environnement requise.

### Mode Turso/libsql (optionnel)

Si les variables ci-dessous sont définies, l'app utilise une embedded replica synchronisée:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

Exemple:

```powershell
$env:TURSO_DATABASE_URL="libsql://..."
$env:TURSO_AUTH_TOKEN="..."
python main.py
```

## Utilisation

Workflow conseillé pour une première prise en main:

1. Ouvrir l'app et vérifier les personnes/comptes.
2. Importer les flux (CSV/Bankin/TR) depuis la page **Import**.
3. Lancer un rebuild si nécessaire depuis les onglets **Famille > Diagnostic**.
4. Analyser la vue **Famille** puis les onglets **Personnes**.
5. Vérifier les logs/backups dans **Paramètres**.

## Données, logs et backups

Dossier utilisateur: `~/.patrimoine`

- `logs/patrimoine.log`: logs applicatifs avec rotation.
- `backups/`: backups automatiques SQLite (+ exports manuels possibles).

## Tests

Les tests actuels couvrent notamment:
- `calculations`
- `credits`
- `imports`
- `snapshots`

Commande:

```powershell
pytest -q
```

## Build exécutable

Fichiers PyInstaller disponibles:

- `patrimoine.spec`
- `Patrimoine Desktop.spec`

Exemple:

```powershell
pyinstaller patrimoine.spec
```

## Roadmap

- Renforcer la robustesse des imports hétérogènes.
- Ajouter plus de règles de contrôle de valorisation.
- Étendre la couverture de tests et les diagnostics automatiques.

## Licence

Projet privé, usage personnel/familial.
