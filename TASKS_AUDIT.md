# Audit Complet — Suivie Patrimoine Desktop

> **Date** : 5 avril 2026 (mis a jour apres corrections)
> **Scope** : ~60 fichiers analyses, ~15 000 lignes de code
> **Stack** : PyQt6, SQLite/Turso, Plotly, yfinance, pandas
> **Branche** : fix/audit-bugs

---

# PARTIE 1 — Bugs Restants

---

# PARTIE 2 — Code Mort et Fichiers Inutiles Restants

---

## DEAD-04 | `legacy_streamlit/` — ancienne application Streamlit

| **Dossier** | `legacy_streamlit/` (~20 fichiers) |
|---|---|
| **Statut** | LEGACY |

**Description** : Ancienne interface Streamlit complete. L'app PyQt6 est fonctionnelle et ce dossier n'est plus necessaire.

**Action** : Supprimer ou archiver dans une branche git dediee.

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


## Statistiques


### AM-15 | Performance TWR correcte
**Idee** : Implementer le vrai TWR qui neutralise les flux (depots/retraits).
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

# Taches Restantes (par priorite)

| # | Tache | Ref | Impact | Effort |
|---|-------|-----|--------|--------|
| 1 | Consolider le schema SQL dans `db/schema.sql` | BUG-25 | ELEVE | 2-3h |
| 2 | Ajouter indicateur visuel quand taux FX manquent | BUG-08 | ELEVE | 1h |
| 3 | Ajouter FK + warning pour `payer_account_id` | BUG-05 | MOYEN | 30 min |
| 4 | Vectoriser `_bank_cash_asof_eur` dans snapshots | BUG-09 | MOYEN | 1-2h |
| 5 | Supprimer `legacy_streamlit/` | DEAD-04 | FAIBLE | 5 min |
| 6 | Supprimer dead code guard `bourse_analytics` | DEAD-06 | FAIBLE | 5 min |
| 7 | Nettoyer `cols.txt`, `comments.txt` | DEAD-07 | FAIBLE | 5 min |
| 8 | Cleanup thread refs dans import_page | BUG-21 | FAIBLE | 10 min |
| 9 | Verifier `seed_minimal()` double init | BUG-07 | FAIBLE | 15 min |

---

# Bilan de l'Audit

| Categorie | Total | Corriges | Restants |
|-----------|-------|----------|----------|
| Bugs critiques/eleves | 10 | 8 | 2 |
| Bugs moyens | 12 | 9 | 3 |
| Bugs faibles | 3 | 1 | 2 |
| Code mort | 7 | 4 | 3 |
| Ameliorations | 10 | — | 10 |
| Visions | 2 | — | 2 |

**Bugs corriges dans cette session (branche fix/audit-bugs)** :
- BUG-01 : Singleton DB protege avec `threading.Lock`
- BUG-02 : `_ensure_person` race condition → `INSERT OR IGNORE`
- BUG-04 : Deduplication TR avec ISIN via jointure assets
- BUG-10 : `sens_flux_safe()` centralise, retourne 0 pour types inconnus
- BUG-13 : Validation montants negatifs dans import CSV depenses
- BUG-14 : Purge mois avant re-insert Bankin (plus de doublons)
- BUG-15 : Validation `account_id != None` avant import credit
- BUG-16 : Guard `quit()/wait()` avant remplacement thread (bourse)
- BUG-17 : Guard thread (famille_page, 2 endroits)
- BUG-18 : `closeEvent` avec cleanup thread MainWindow
- BUG-19 : `enterprise_history` source unique dans entreprises_repository
- BUG-20 : Signal FilterBar connecte une seule fois
- BUG-22 : `_broker_cash_asof_native` importe au lieu de duplique
- BUG-23 : `requirements.txt` regenere (encodage corrige, streamlit retire)
- BUG-24 : Logger info sur ticker_account_map override
- DEAD-01/02/03 : Suppression enums.py, cache.py, formatters.py
- DEAD-05 : streamlit retire de requirements.txt
