# Patrimoine Desktop

## 1. Presentation du projet
Application desktop PyQt6 de suivi de patrimoine personnel/familial.

Ce que fait l'application aujourd'hui:
- centraliser comptes, actifs, credits, revenus et depenses,
- calculer des vues consolidees (patrimoine, allocations, cashflow, epargne),
- suivre la bourse (positions live, historique weekly, performance),
- importer des donnees bancaires/bourse,
- simuler des projections patrimoniales (mode legacy et mode prevision avancee).

Contexte technique actuel:
- architecture cible: `UI -> services -> DB`,
- codebase active avec refactors en cours,
- certaines zones historiques ne sont pas encore alignees avec cette cible.

## 2. Fonctionnalites principales actuelles
Fonctionnalites exposees dans l'UI actuelle:
- Vue famille: synthese patrimoine, flux, allocations, tendances.
- Vue personnes: suivi par personne (comptes banque/bourse/credit, immobilier, PE, entreprises, revenus/depenses, epargne, sankey, vue d'ensemble).
- Import:
  - CSV (revenus/depenses, Bankin),
  - Trade Republic (`pytr`) avec mapping vers transactions internes,
  - suivi d'historique d'import / rollback (selon modules services disponibles).
- Bourse:
  - positions live par personne et par compte,
  - performance et series hebdo,
  - refresh prix/FX.
- Credits:
  - gestion credits, amortissements et KPI associes.
- Projections:
  - `goals_projection_page` (moteur V1 `services/projections.py`),
  - prevision avancee (deterministe, Monte Carlo, stress tests) via `services/prevision.py`.
- Parametres:
  - preferences UI/theming et reglages applicatifs existants.

## 3. Architecture simplifiee
```text
qt_ui (pages/panels/widgets)
  -> services (regles metier, calculs, import/export/sync)
    -> repositories/SQL + db/schema+migrations
      -> SQLite locale (ou replica Turso/libsql si configure)
```

Responsabilites (etat reel):
- UI: orchestration ecran + rendu.
- Services: calculs metier, agregations, fallback, consolidation.
- DB: persistance et migrations.

Ecarts connus:
- certains ecrans UI executent encore du SQL direct,
- coexistence de deux domaines de projection (`projections` legacy et `prevision` nouveau).

## 4. Stack utilisee
- Langage: Python 3.x
- UI desktop: PyQt6
- Data/calcul: pandas, numpy
- Visualisation: matplotlib/plotly (selon panel)
- DB locale: SQLite
- Option sync distante: libsql/Turso (variables d'environnement)
- Marche/quotes: yfinance
- Import TR: `pytr`
- Tests: pytest

Note: le fichier `requirements.txt` est large et contient des dependances qui ne sont pas toutes necessaires au runtime desktop pur; un nettoyage est encore a faire.

## 5. Comment lancer l'application
Prerequis:
- Python 3.11+ recommande,
- environnement virtuel conseille.

PowerShell (Windows):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Mode DB:
- par defaut: SQLite locale (`patrimoine.db`),
- si `TURSO_DATABASE_URL` et `TURSO_AUTH_TOKEN` sont definies: mode libsql replica.

Logs et backups:
- logs: `~/.patrimoine/logs/`
- backups auto de DB a la fermeture: `~/.patrimoine/backups/`

## 6. Structure des dossiers importante
```text
main.py                      # point d'entree app
core/                        # bootstrap connexion DB singleton
services/                    # coeur metier (SSOT logique)
qt_ui/                       # pages, panels, composants UI
db/
  schema.sql                 # schema principal
  migrations/                # migrations SQL versionnees
tests/                       # tests unitaires/integration
docs/
  ARCHITECTURE.md            # architecture reelle
  SOURCE_DE_VERITE.md        # verites metier par domaine
  CONTEXT.md                 # contexte technique detaille
```

## 7. Regles de developpement
- Respecter la chaine `UI -> services -> DB`.
- Toute formule metier (finance, agregation, KPI, projection) doit vivre dans `services/`.
- Eviter d'ajouter du SQL metier dans `qt_ui/`.
- Ne pas dupliquer un calcul deja expose par un service canonique.
- Toute nouvelle API metier doit etre referencee dans `docs/SOURCE_DE_VERITE.md`.
- Avant merge: tests pertinents + mise a jour docs racine.

## 8. Emplacement des documents de reference
- [ARCHITECTURE.md](./docs/ARCHITECTURE.md)
- [SOURCE_DE_VERITE.md](./docs/SOURCE_DE_VERITE.md)
- [CONTEXT.md](./docs/CONTEXT.md)
- [AUDIT_GLOBAL.md](./AUDIT_GLOBAL.md)
- [BACKLOG_GLOBAL.md](./BACKLOG_GLOBAL.md)

## 9. Workflow conseille pour ajouter une feature
1. Cadrer le besoin metier et identifier la source de verite concernee.
2. Verifier l'existant dans `services/` pour reutiliser avant de creer.
3. Implementer la logique dans `services/` (API claire, testable).
4. Brancher l'UI sur cette API sans recoder les calculs.
5. Ajouter/adapter les tests (cas nominal + cas limites).
6. Mettre a jour `docs/SOURCE_DE_VERITE.md` si nouvelle autorite metier.
7. Mettre a jour `docs/ARCHITECTURE.md` si impact structurel.

## 10. Workflow conseille pour corriger un bug
1. Reproduire le bug (scenario minimal + donnees).
2. Localiser la couche responsable (UI, service, DB).
3. Corriger a la source (preferer service plutot que patch UI).
4. Ajouter un test de non-regression cible.
5. Verifier les impacts collateraux sur les KPI/projections.
6. Documenter le correctif si la regle metier evolue.

## 11. Pieges connus / dette technique connue
- Double moteur de projection actif:
  - `services/projections.py` (legacy),
  - `services/prevision.py` (nouveau).
- Conversions FX non totalement unifiees (historique weekly vs live/spot + helper local liquidites).
- SQL direct encore present dans plusieurs ecrans UI (`main_window`, `import_page`, certains panels).
- Quelques modules volumineux et multi-responsabilites:
  - `services/snapshots.py`,
  - `qt_ui/pages/import_page.py`,
  - `qt_ui/pages/goals_projection_page.py`,
  - `services/vue_ensemble_metrics.py`.

## 12. Priorites actuelles du projet
1. Unifier la source de verite des projections (facade unique puis migration UI).
2. Recentrer la logique metier hors UI (suppression progressive du SQL direct UI).
3. Unifier la politique FX/valorisation entre modules.
4. Decouper les gros modules critiques pour ameliorer testabilite et maintenabilite.
5. Stabiliser la documentation racine comme reference vivante apres chaque changement.

## Informations encore incertaines
- Le niveau de couverture de tests cible par domaine n'est pas encore formalise dans un standard unique.
- La date de retrait definitive du moteur `services/projections.py` n'est pas fixee.
- Le perimetre exact des dependances runtime minimales (vs dependances historiques) reste a nettoyer.
