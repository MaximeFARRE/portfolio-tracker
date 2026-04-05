# Audit Complet — Suivie Patrimoine Desktop

> **Date** : 5 avril 2026
> **Scope** : ~60 fichiers analysés, ~15 000 lignes de code
> **Stack** : PyQt6, SQLite/Turso, Plotly, yfinance, pandas
> **Branche** : feature/tr-multi-account

---

# PARTIE 1 — Bugs, Erreurs et Problemes Actuels

---

## BUG-01 | Connexion DB singleton non thread-safe

| | |
|---|---|
| **Gravite** | CRITIQUE |
| **Fichiers** | `core/db_connection.py` (L18-29) |
| **Statut** | OUVERT |

**Description** : `get_connection()` utilise un pattern singleton (`_conn`) sans `threading.Lock()`. Si deux threads appellent `get_connection()` simultanement, deux connexions peuvent etre creees (race condition entre le test `if _conn is None` et l'assignation).

**Impact** : Bien que les `QThread` de l'app utilisent deja `get_conn()` pour creer leurs propres connexions (bon pattern), le singleton UI reste vulnerable si un thread secondaire appelle `get_connection()` par erreur.

**Correction** :
```python
import threading
_lock = threading.Lock()

def get_connection():
    global _conn
    with _lock:
        if _conn is None:
            # ... init
            _conn = get_conn()
        return _conn
```

**Note** : Les `QThread` (import TR, rebuild, preview) utilisent correctement `get_conn()` pour creer des connexions isolees — c'est un bon pattern deja en place.

---

## BUG-02 | `_ensure_person` — race condition INSERT/SELECT

| | |
|---|---|
| **Gravite** | ELEVE |
| **Fichier** | `services/imports.py` (L216-223) |
| **Statut** | OUVERT |

**Description** : Entre le `SELECT` et le `INSERT`, un autre processus pourrait inserer la meme personne. Le `SELECT` final pourrait retourner 2+ lignes.

**Correction** : Utiliser `INSERT OR IGNORE INTO people(name) VALUES (?)` puis `SELECT`.

---

## BUG-03 | Signal reconnexion dans `_refresh_people`

| | |
|---|---|
| **Gravite** | CORRIGE |
| **Fichier** | `qt_ui/pages/import_page.py` (L1390-1393) |
| **Statut** | CORRIGE |

**Description** : Le code utilise maintenant un flag `_person_signal_connected` pour eviter les connexions multiples du signal `currentIndexChanged`. Bon pattern defensif.

---

## BUG-04 | Deduplication TR insuffisante (manque ISIN)

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/tr_import.py` (L636-641) |
| **Statut** | OUVERT |

**Description** : La deduplication se base sur `(date, account_id, type, ABS(amount - ?) < 0.01)` sans inclure l'asset_id/ISIN. Deux achats differents du meme montant le meme jour sont consideres comme doublons.

**Correction** : Ajouter `asset_id` dans la requete de deduplication.

---

## BUG-05 | `payer_account_id` — pas de FK, echec silencieux

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/credits.py` (L356-360), `db/schema.sql` (L91) |
| **Statut** | PARTIELLEMENT CORRIGE |

**Description** : La colonne `payer_account_id` existe maintenant dans le schema (via migration dans db.py L365), mais :
- Pas de contrainte `FOREIGN KEY` vers `accounts(id)`
- Le code retourne silencieusement `0.0` si `payer_account_id` est NULL (L356-360) au lieu de logger un warning

**Correction** : Ajouter la FK dans le schema et logger un warning quand la valeur est NULL.

---

## BUG-06 | Fichier `app.py` legacy Streamlit

| | |
|---|---|
| **Gravite** | CORRIGE |
| **Fichier** | Racine du projet |
| **Statut** | CORRIGE |

**Description** : Le fichier `app.py` racine n'existe plus. Le code legacy est dans `legacy_streamlit/`.

---

## BUG-07 | `seed_minimal()` double execution schema

| | |
|---|---|
| **Gravite** | FAIBLE |
| **Fichier** | `services/db.py` |
| **Statut** | A VERIFIER |

**Description** : Verifier si `seed_minimal()` appelle toujours `init_db()` en interne, ce qui doublerait l'execution du schema au demarrage.

---

## BUG-08 | `convert_weekly` retourne 0.0 si taux FX manquant

| | |
|---|---|
| **Gravite** | ELEVE |
| **Fichier** | `services/market_history.py` (L234-248) |
| **Statut** | PARTIELLEMENT CORRIGE |

**Description** : La fonction retourne maintenant `0.0` (au lieu de `amount` brut comme avant) quand le taux FX est introuvable. C'est plus securitaire (pas de surévaluation) mais **silencieux** — un actif USD entier disparait du patrimoine sans alerte visible.

**Correction** : Ajouter un indicateur visuel dans le dashboard quand des taux FX manquent (flag dans le snapshot ou compteur d'alertes).

---

## BUG-09 | Performance snapshots — `.apply(lambda, axis=1)`

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/snapshots.py` (L94, L105) |
| **Statut** | OUVERT |

**Description** : `_bank_cash_asof_eur` charge toutes les transactions (limit=200000, L83) puis filtre en memoire. Les `.apply(lambda r: ..., axis=1)` sont 10-100x plus lents que des operations vectorisees.

**Correction** :
1. `WHERE date <= ?` dans la requete SQL
2. Remplacer `.apply(lambda)` par `df["type"].map(sens_flux_dict) * df["amount"]`
3. Cache les transactions par personne pendant un rebuild batch

---

## BUG-10 | `sens_flux` — comportement incoherent entre modules

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `utils/validators.py` (L44-49), `services/snapshots.py` |
| **Statut** | OUVERT |

**Description** : `validators.sens_flux()` leve `ValueError` pour un type inconnu. La version locale dans `snapshots.py` (`_sens_flux`) retourne +1. Comportement incoherent.

**Correction** : Unifier en une seule fonction centralise qui logue un warning et retourne 0 pour les types inconnus.

---

## BUG-11 | `SyncedLibsqlConn.__exit__` — singleton

| | |
|---|---|
| **Gravite** | CORRIGE |
| **Fichier** | `services/db.py` (L45-57) |
| **Statut** | CORRIGE |

**Description** : Le `__exit__` ne ferme plus la connexion (commentaire L55 : "On ne ferme PAS ici: singleton partage"). Bon comportement.

---

## BUG-12 | `DB_PATH` relatif

| | |
|---|---|
| **Gravite** | CORRIGE |
| **Fichier** | `services/db.py` (L15) |
| **Statut** | CORRIGE |

**Description** : Utilise maintenant `Path(__file__).resolve().parent.parent` pour construire des chemins absolus.

---

## BUG-13 | Pas de validation CSV avant import

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/imports.py` (L62-126) |
| **Statut** | OUVERT |

**Description** : L'import CSV depenses/revenus n'effectue aucune validation : pas de controle de categories, montants negatifs, dates futures.

---

## BUG-14 | Import Bankin — doublons depenses/revenus

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/imports.py` (L329-335) |
| **Statut** | OUVERT |

**Description** : L'import Bankin fait des `INSERT INTO depenses/revenus` sans verifier l'existence. Chaque re-import **additionne** les montants au lieu de remplacer.

**Correction** : Utiliser `INSERT OR REPLACE` ou `DELETE` avant `INSERT` pour les mois importes.

---

## BUG-15 | `account_id = None` dans import credit

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `qt_ui/pages/import_page.py` (L1444-1451) |
| **Statut** | OUVERT |

**Description** : Si aucun compte credit n'est selectionne (`currentData()` retourne `None`), l'appel a `upsert_credit` passera `account_id=None`, violant la contrainte `NOT NULL`.

**Correction** : Verifier `account_id is not None` avant de proceder.

---

## BUG-16 | Thread non arrete avant remplacement (`compte_bourse_panel`)

| | |
|---|---|
| **Gravite** | ELEVE |
| **Fichier** | `qt_ui/panels/compte_bourse_panel.py` (L189-191) |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : Chaque appel a `_on_refresh_prices()` cree un nouveau `PriceRefreshThread` sans arreter l'ancien. Si l'utilisateur clique rapidement, plusieurs threads tournent en parallele.

**Correction** :
```python
if self._thread is not None and self._thread.isRunning():
    self._thread.quit()
    self._thread.wait()
```

---

## BUG-17 | Thread remplacement sans cleanup (`famille_page`)

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `qt_ui/pages/famille_page.py` (L463) |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : `RebuildAllThread` est cree sans arreter l'eventuel thread precedent. Meme probleme que BUG-16.

---

## BUG-18 | Pas de cleanup thread au closeEvent (MainWindow)

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `qt_ui/main_window.py` |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : `MainWindow` ne surcharge pas `closeEvent()` pour arreter proprement le `AutoRebuildThread` avant fermeture. Risque de crash au shutdown.

**Correction** :
```python
def closeEvent(self, event):
    if self._rebuild_thread and self._rebuild_thread.isRunning():
        self._rebuild_thread.quit()
        self._rebuild_thread.wait()
    super().closeEvent(event)
```

---

## BUG-19 | `enterprise_history` — table definie 2 fois, colonnes differentes

| | |
|---|---|
| **Gravite** | ELEVE |
| **Fichier** | `services/db.py` (L337-350), `services/entreprises_repository.py` (L47-59) |
| **Statut** | OUVERT |

**Description** : La table `enterprise_history` est definie dans **deux fichiers** avec des colonnes potentiellement differentes (`effective_date` vs `changed_at`). La premiere definition gagne (IF NOT EXISTS).

**Correction** : Consolider dans `db/schema.sql` uniquement.

---

## BUG-20 | Signal potentiel multi-connexion dans `data_table.py`

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `qt_ui/widgets/data_table.py` (L532) |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : Si `set_filter_config()` est appele plusieurs fois sur un `DataTableWidget` existant, le signal `filters_changed` peut etre connecte plusieurs fois (le guard `if self._filter_bar is None` protege la creation, mais pas la reconnexion si le bar existe deja).

**Correction** : Disconnecter avant de reconnecter :
```python
try:
    self._filter_bar.filters_changed.disconnect()
except:
    pass
self._filter_bar.filters_changed.connect(self._on_advanced_filter_changed)
```

---

## BUG-21 | Thread references non nettoyees (`import_page`)

| | |
|---|---|
| **Gravite** | FAIBLE |
| **Fichier** | `qt_ui/pages/import_page.py` (L762, L834) |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : `_preview_thread` et `_export_thread` sont stockes comme attributs mais jamais supprimes apres completion. Fuite memoire legere.

---

## BUG-22 | `_broker_cash_asof_native` duplique entre 2 modules

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/snapshots.py` (L114-131), `services/bourse_analytics.py` (L20-51) |
| **Statut** | OUVERT |

**Description** : Meme logique metier dupliquee. Si un bug est corrige dans un fichier, l'autre reste bugge.

**Correction** : Extraire dans un module commun (`services/calculations.py` ou `services/positions.py`).

---

## BUG-23 | `requirements.txt` corrompu (encodage BOM)

| | |
|---|---|
| **Gravite** | ELEVE |
| **Fichier** | `requirements.txt` |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : Le fichier a un encodage BOM corrompu — chaque caractere est separe par des espaces. `pip install -r requirements.txt` echouera.

**Correction** : Regenerer avec `pip freeze > requirements.txt` dans un environnement propre.

---

## BUG-24 | `ticker_account_map` peut rediriger vers le mauvais compte

| | |
|---|---|
| **Gravite** | MOYEN |
| **Fichier** | `services/tr_import.py` (L631-633) |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : Le `ticker_account_map` peut overrider silencieusement le `account_id` passe a la fonction. Si le mapping est incorrect, les transactions vont dans le mauvais compte sans alerte.

**Correction** : Logger un warning quand l'override est applique.

---

## BUG-25 | Schema SQL eclate entre fichiers

| | |
|---|---|
| **Gravite** | ELEVE (structurel) |
| **Fichier** | `db/schema.sql`, `services/db.py`, `services/immobilier_repository.py`, `services/entreprises_repository.py`, `services/isin_resolver.py` |
| **Statut** | OUVERT (NOUVEAU) |

**Description** : Le schema de la base est reparti entre 5+ fichiers. Tables manquantes dans `schema.sql` :
- `enterprise_history` (dans db.py + entreprises_repository.py)
- `immobiliers`, `immobilier_shares`, `immobilier_history` (dans immobilier_repository.py)
- `isin_ticker_cache` (dans isin_resolver.py)
- `rebuild_watermarks` (dans snapshots.py)

Les colonnes `import_batch_id` sont ajoutees via `ALTER TABLE` dans db.py au lieu d'etre dans le `CREATE TABLE` initial.

**Impact** : Impossible de recreer la base a partir de `schema.sql` seul. Risque de divergence entre definitions.

**Correction** : Consolider toutes les definitions dans `db/schema.sql` comme source unique de verite.

---

# PARTIE 2 — Code Mort et Fichiers Inutiles

---

## DEAD-01 | `models/enums.py` — defini mais jamais importe

| **Fichier** | `models/enums.py` (33 lignes) |
|---|---|
| **Statut** | CODE MORT |

**Description** : `AccountType`, `AssetType`, `TxType` sont definis mais **jamais importes nulle part**. Le code utilise des string literals partout (`"BANQUE"`, `"PEA"`, `"ACHAT"`). De plus les valeurs des enums ne correspondent pas aux conventions du schema (ex: enum `CASH` vs schema `BANQUE`).

**Action** : Supprimer le fichier ou refactorer tout le code pour utiliser les enums.

---

## DEAD-02 | `utils/cache.py` — legacy Streamlit

| **Fichier** | `utils/cache.py` (17 lignes) |
|---|---|
| **Statut** | CODE MORT |

**Description** : `cached_conn()` et `reset_cache()` sont des vestiges Streamlit. Jamais importes par le code Qt.

**Action** : Supprimer.

---

## DEAD-03 | `utils/formatters.py` — doublon de `format_monnaie.py`

| **Fichier** | `utils/formatters.py` (6 lignes) |
|---|---|
| **Statut** | CODE MORT |

**Description** : Definit une fonction `eur()` qui duplique celle de `format_monnaie.py`. Jamais importe nulle part.

**Action** : Supprimer.

---

## DEAD-04 | `legacy_streamlit/` — ancienne application Streamlit

| **Dossier** | `legacy_streamlit/` (~20 fichiers) |
|---|---|
| **Statut** | LEGACY |

**Description** : Ancienne interface Streamlit complete. L'app PyQt6 est fonctionnelle et ce dossier n'est plus necessaire.

**Action** : Supprimer ou archiver dans une branche git dediee.

---

## DEAD-05 | `streamlit==1.52.2` dans requirements.txt

| **Fichier** | `requirements.txt` |
|---|---|
| **Statut** | DEPENDANCE INUTILE |

**Description** : Streamlit est toujours liste comme dependance alors que l'app est 100% PyQt6.

**Action** : Retirer de requirements.txt (apres regeneration du fichier).

---

## DEAD-06 | `bourse_analytics.py` — dead code guard

| **Fichier** | `services/bourse_analytics.py` (L100-103) |
|---|---|
| **Statut** | CODE MORT |

**Description** : Le guard `if years <= 0` est du code mort car `raw_days > 0` est deja verifie 2 lignes au-dessus.

**Action** : Supprimer le guard superflu.

---

## DEAD-07 | Fichiers de reference orphelins

| **Fichiers** | `cols.txt`, `comments.txt` |
|---|---|
| **Statut** | A EVALUER |

**Description** : Fichiers texte a la racine qui semblent etre des notes de dev. Non references par le code.

**Action** : Supprimer ou deplacer dans un dossier `docs/`.

---

# PARTIE 3 — Ameliorations Possibles

---

## UX / UI

### AM-01 | Barre de recherche globale
**Idee** : Recherche rapide (personne, compte, actif, transaction) dans le header.
**Difficulte** : Moyen | **Priorite** : Moyenne

### AM-02 | Breadcrumb de navigation
**Idee** : Afficher `Personnes > Maxime > PEA Trade Republic` dans le header.
**Difficulte** : Facile | **Priorite** : Moyenne

### AM-03 | Theme clair / sombre
**Idee** : Toggle theme. Le `theme.py` centralise facilite l'implementation.
**Difficulte** : Moyen | **Priorite** : Moyenne

---

## Graphiques Plotly

### AM-04 | Tooltips enrichis
**Idee** : Tooltips avec detail (montant par categorie, variation %) au survol.
**Difficulte** : Facile | **Priorite** : Moyenne

### AM-05 | Stacked Area pour allocation patrimoniale
**Idee** : Aires empilees montrant l'evolution de chaque classe d'actifs.
**Difficulte** : Moyen | **Priorite** : Haute

### AM-06 | Treemap allocation detaillee
**Idee** : Treemap interactif avec zoom (categorie > compte > actif).
**Difficulte** : Moyen | **Priorite** : Moyenne

---

## Filtres et Donnees

### AM-07 | Filtres avances sur tableaux de transactions
**Idee** : Filtres par type, date, montant, categorie sur tous les tableaux.
**Difficulte** : Moyen | **Priorite** : Haute

### AM-08 | Import Bankin : detection de doublons
**Idee** : Comparer avec transactions existantes et marquer les doublons avant import.
**Difficulte** : Moyen | **Priorite** : Haute

### AM-09 | Import TR : detection PEA vs CTO automatique
**Idee** : Detecter automatiquement si un ISIN est PEA-compatible (FR, IE, etc.).
**Difficulte** : Moyen | **Priorite** : Moyenne

---

## Performance

### AM-10 | Lazy-loading des onglets
**Idee** : Ne charger les donnees d'un onglet que quand l'utilisateur clique dessus.
**Difficulte** : Facile | **Priorite** : Haute

### AM-11 | Cache memoire pour requetes repetees
**Idee** : Cache `list_accounts()`, `list_people()`, snapshots pendant la session.
**Difficulte** : Moyen | **Priorite** : Moyenne

---

## Export

### AM-12 | Export Excel/CSV des donnees
**Idee** : Bouton "Exporter" sur chaque tableau.
**Difficulte** : Facile | **Priorite** : Moyenne

### AM-13 | Export PDF du bilan patrimonial
**Idee** : PDF recapitulatif mensuel avec KPIs, graphiques, positions.
**Difficulte** : Difficile | **Priorite** : Moyenne

---

## Statistiques

### AM-14 | Comparaison temporelle (mois vs mois, annee vs annee)
**Idee** : Widget de comparaison de deux periodes.
**Difficulte** : Moyen | **Priorite** : Moyenne

### AM-15 | Performance TWR correcte
**Idee** : Implementer le vrai TWR qui neutralise les flux (depots/retraits).
**Difficulte** : Difficile | **Priorite** : Moyenne

---

## Multi-personnes

### AM-16 | Comptes joints / partages
**Idee** : Lier un compte a plusieurs personnes avec % de repartition.
**Difficulte** : Difficile | **Priorite** : Moyenne

---

## Robustesse (Structurel)

### AM-17 | Versioning du schema DB
**Idee** : Ajouter un compteur de version dans la DB au lieu de `try/except ALTER TABLE`.
**Difficulte** : Moyen | **Priorite** : Haute

### AM-18 | Tests unitaires
**Idee** : Aucun fichier de test n'existe. Le refactoring est risque.
**Difficulte** : Moyen | **Priorite** : Haute

---

# PARTIE 4 — Vision Long Terme

---

## VISION-02 | Projection Patrimoine et Simulateur FIRE

**Idee** : Page de simulation avec parametres modifiables :
- Revenus, depenses, taux d'epargne
- Rendement attendu des investissements
- Inflation
- Objectif FIRE (patrimoine cible = depenses annuelles x 25)
- Graphique de projection sur 10-30 ans avec scenarios (optimiste, pessimiste, median)

**Valeur** : Planification financiere, motivation, prise de decision.
**Difficulte** : Moyen-Difficile | **Horizon** : 3-6 mois

---

## VISION-05 | Suivi d'Objectifs Financiers

**Idee** : Page "Objectifs" :
- Creer un objectif (ex: "Epargne vacances 3000E", "Apport immo 50KE")
- Progress bar, date cible, montant epargne
- Suggestion de montant mensuel necessaire
- Notifications quand objectif atteint

**Valeur** : Motivation et gamification de l'epargne.
**Difficulte** : Moyen | **Horizon** : 3-6 mois

---

# PARTIE 5 — Points Positifs et Architecture

---

## Ce qui est bien fait

- **Separation service/UI** : les `services/` n'importent jamais PyQt6
- **Pattern set_person/refresh** : coherent et extensible
- **Theme centralise** : `theme.py` facilite la maintenance visuelle
- **Widgets reutilisables** : `KpiCard`, `PlotlyView`, `DataTableWidget` bien concus
- **Snapshots as-of** : concept solide de reconstruction du patrimoine semaine par semaine
- **Gestion d'exceptions globale** : `sys.excepthook` + dialog utilisateur (main.py L51-75)
- **Sauvegarde automatique** : backup DB au demarrage avec rotation (main.py L78-131)
- **Logs persistants** : `RotatingFileHandler` configure (main.py L18-40)
- **WAL mode active** : `PRAGMA journal_mode=WAL` (db.py L72)
- **DB_PATH absolu** : `Path(__file__).resolve().parent.parent` (db.py L15)
- **SyncedLibsqlConn.__exit__** : ne ferme plus le singleton
- **Signal guard import_page** : flag `_person_signal_connected`
- **Import history** : systeme de batch + rollback fonctionnel
- **LoadingOverlay** : gestion correcte du cycle de vie des effets de blur
- **AnimatedStack** : cleanup propre des effets d'opacite

---

# Top 10 des Taches Immediates

| # | Tache | Ref | Impact | Effort |
|---|-------|-----|--------|--------|
| 1 | Regenerer `requirements.txt` (fichier corrompu) | BUG-23 | CRITIQUE | 10 min |
| 2 | Consolider le schema SQL dans `db/schema.sql` | BUG-25 | ELEVE | 2-3h |
| 3 | Unifier `enterprise_history` (double definition) | BUG-19 | ELEVE | 30 min |
| 4 | Arreter thread avant remplacement (bourse, famille) | BUG-16, BUG-17 | ELEVE | 30 min |
| 5 | Cleanup thread au `closeEvent` MainWindow | BUG-18 | MOYEN | 15 min |
| 6 | Fix `_ensure_person` race condition | BUG-02 | ELEVE | 15 min |
| 7 | Ajouter ISIN dans dedup TR | BUG-04 | MOYEN | 30 min |
| 8 | Fix doublons import Bankin (INSERT OR REPLACE) | BUG-14 | MOYEN | 30 min |
| 9 | Supprimer code mort (enums.py, cache.py, formatters.py) | DEAD-01/02/03 | FAIBLE | 15 min |
| 10 | Validation `account_id` avant import credit | BUG-15 | MOYEN | 10 min |

---

# Quick Wins — Impact Fort, Effort Faible

| # | Action | Effort | Fichier(s) |
|---|--------|--------|------------|
| 1 | Regenerer requirements.txt | 10 min | `requirements.txt` |
| 2 | Supprimer fichiers morts | 15 min | `models/enums.py`, `utils/cache.py`, `utils/formatters.py` |
| 3 | Guard thread avant remplacement | 30 min | `compte_bourse_panel.py`, `famille_page.py` |
| 4 | `INSERT OR IGNORE` dans `_ensure_person` | 15 min | `services/imports.py` |
| 5 | Validation `account_id != None` | 10 min | `import_page.py` |
| 6 | Logger warning sur ticker_account_map override | 10 min | `services/tr_import.py` |
| 7 | Disconnect signal avant reconnexion data_table | 15 min | `qt_ui/widgets/data_table.py` |
| 8 | closeEvent avec cleanup thread | 15 min | `qt_ui/main_window.py` |

---

# Bilan de l'Audit

| Categorie | Total | Corriges | Ouverts | Nouveaux |
|-----------|-------|----------|---------|----------|
| Bugs critiques/eleves | 10 | 4 | 6 | 4 |
| Bugs moyens | 12 | 0 | 12 | 4 |
| Bugs faibles | 3 | 1 | 2 | 1 |
| Code mort | 7 | — | 7 | 2 |
| Ameliorations | 18 | — | 18 | 2 |
| Visions | 2 | — | 2 | 0 |

**Progres depuis le dernier audit (3 avril 2026)** :
- BUG-03 (signal reconnexion) : CORRIGE
- BUG-06 (app.py legacy) : CORRIGE
- BUG-08 (FX fallback) : PARTIELLEMENT CORRIGE (retourne 0 au lieu du montant brut)
- BUG-11 (SyncedLibsqlConn.__exit__) : CORRIGE
- BUG-12 (DB_PATH relatif) : CORRIGE
- BUG-20 (WAL mode) : CORRIGE
- BUG-23 (logs) : CORRIGE (RotatingFileHandler en place)
- BUG-24 (backup DB) : CORRIGE (backup auto au demarrage)
- AM-03 (animations) : IMPLEMENTE
- AM-04 (indicateurs chargement) : IMPLEMENTE
- AM-06 (range slider Plotly) : IMPLEMENTE

**8 nouveaux bugs detectes** (BUG-16 a BUG-25)
