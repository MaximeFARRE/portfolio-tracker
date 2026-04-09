# Patrimoine Desktop

Application desktop PyQt6 de suivi patrimonial familial (multi-personnes, multi-comptes) avec architecture SSOT stricte.

## Documents de référence (à lire en priorité)

- `ARCHITECTURE.md` : architecture applicative réelle (runtime, couches, conventions).
- `ARCHITECTURE_SOURCES_DE_VERITE.md` : mapping KPI/payload -> fonctions officielles.
- `CONTEXT.md` : contexte produit et périmètre fonctionnel.
- `CLAUDE.md` : règles de développement/refactor obligatoires.

## Principe d'architecture

```text
UI -> Services -> Repository / DB
```

Implications :
- Les pages/panels Qt font l'affichage et l'orchestration légère.
- Les services portent les calculs métier, agrégations, normalisations et fallbacks.
- Les repositories/DB ne sont pas appelés directement par l'UI pour calculer des KPI.

## Stack

- Python 3.11+
- PyQt6 + QWebEngineView
- Plotly
- pandas / numpy
- SQLite (WAL) et option Turso/libsql
- yfinance (prix) + services FX internes

## Démarrage rapide (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## État SSOT (résumé avril 2026)

- **Snapshots** :
  - `services.snapshots.get_person_weekly_series`
  - `services.family_snapshots.get_family_weekly_series`
- **Bourse live** :
  - `services.bourse_analytics.get_live_bourse_positions`
  - `services.bourse_analytics.get_live_bourse_positions_for_account`
- **Cashflow / épargne** :
  - `services.cashflow.get_cashflow_for_scope`
  - `services.cashflow.get_person_monthly_savings_series`
  - `services.cashflow.compute_savings_metrics`
- **Liquidités** :
  - `services.liquidites.get_liquidites_summary`
- **Crédits** :
  - `services.credits.get_crd_a_date`
  - `services.credits.cout_reel_mois_credit_via_bankin`

Pour le détail complet (statut panel par panel, fallback, transitions), se référer à `ARCHITECTURE_SOURCES_DE_VERITE.md`.

## Structure projet (résumé)

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

## Tests

```powershell
pytest -q
```

## Notes importantes

- Les symboles/tickers invalides peuvent générer des warnings yfinance ; ce n'est pas bloquant si les actifs sont volontairement non cotés ou mal mappés.
- Les logs FX hebdo manquants (`convert_weekly`) indiquent des trous de taux dans `fx_rates_weekly` et doivent être traités côté données, pas côté UI.

## Licence

Projet privé (usage personnel/familial).
