# CLAUDE.md

## Objectif

Tu travailles sur une application desktop Python / PyQt de suivi de patrimoine.
Ta priorité absolue est :

1. ne rien casser
2. garder le code simple et lisible
3. respecter l’architecture existante
4. éviter toute duplication de logique

Avant toute modification, lire :

* `CONTEXT.md`
* `ARCHITECTURE_SOURCES_DE_VERITE.md`
* éventuellement `AUDIT_GLOBAL_APPLICATION.md`

Le document `ARCHITECTURE_SOURCES_DE_VERITE.md` fait foi si plusieurs implémentations existent.

---

## Principes obligatoires

* Toujours comprendre le rôle du fichier avant de le modifier.
* Toujours faire le plus petit changement possible.
* Toujours préférer enrichir un fichier existant plutôt qu’en créer un nouveau.
* Toujours réutiliser une fonction existante avant d’en créer une autre.
* Ne jamais dupliquer une logique déjà présente ailleurs.
* Ne jamais réécrire un gros fichier entier si quelques fonctions suffisent.
* Ne jamais faire plusieurs refactors importants dans la même tâche.
* Toujours laisser le code plus simple qu’avant.

---

## Architecture à respecter

Toujours respecter cette séparation :

```text
UI → Services → Repository / DB
```

Règles :

* Les pages et panels Qt ne doivent faire que de l’affichage.
* Toute logique métier doit être dans `services/`.
* Les services peuvent appeler des repositories ou la DB.
* La UI ne doit jamais faire directement de SQL ou recalculer un KPI.

Exemples interdits :

* `groupby`, `merge`, `sum`, `iterrows` dans un panel pour recalculer une donnée métier
* appel direct à plusieurs repositories depuis une page Qt
* duplication d’un calcul déjà présent dans un service

---

## Source de vérité

Chaque KPI doit avoir une seule fonction officielle.

Toujours chercher :

* quelle est la source de vérité actuelle ?
* existe-t-il déjà un service officiel ?

Ne jamais créer une deuxième version d’un même calcul.

Si plusieurs fonctions existent déjà, utiliser celle définie dans `ARCHITECTURE_SOURCES_DE_VERITE.md`. 

---

## Quand créer du code

Avant de créer :

1. regarder si une fonction similaire existe déjà
2. regarder si un service proche existe déjà
3. enrichir ce service si possible
4. créer un nouveau module uniquement en dernier recours

Préférer :

* ajouter une fonction à `bourse_analytics.py`
* ajouter une fonction à `cashflow.py`
* ajouter une fonction à `snapshots.py`

Éviter de créer de nouveaux fichiers si ce n’est pas strictement nécessaire.

---

## Style de code attendu

* Code simple, explicite, lisible
* Préférer plusieurs petites fonctions à une grosse
* Une fonction = une responsabilité
* Préférer 10 lignes claires à 2 lignes complexes
* Utiliser des noms explicites
* Ajouter un docstring sur chaque fonction publique
* Utiliser des variables intermédiaires si cela améliore la lisibilité
* Préférer les `early return`
* Éviter plus de 3 niveaux d’imbrication

Mauvais :

```python
x = f(a, b)
```

Bon :

```python
live_positions = get_live_bourse_positions(conn, person_id)
```

---

## Taille cible

* Une fonction devrait idéalement faire moins de 50 lignes
* Un fichier au-delà de 300–400 lignes doit être envisagé pour découpage
* Ne pas ajouter encore plus de logique dans un fichier déjà énorme
* Si un fichier est trop gros, extraire des sous-fonctions privées

---

## Fonctions privées

Ne jamais appeler une fonction commençant par `_` depuis un autre module.

Si une fonction privée doit être utilisée ailleurs :

* créer une fonction publique
* faire appeler la fonction privée depuis cette fonction publique

---

## Gestion des erreurs

* Ne jamais utiliser `except: pass`
* Toujours logger les erreurs et les fallbacks
* Toujours gérer explicitement les cas de données manquantes
* Ne jamais masquer une erreur en renvoyant silencieusement une mauvaise valeur
* Utiliser les fallbacks définis dans l’architecture

---

## Refactor

Toujours refactorer par étapes :

1. créer la nouvelle fonction
2. migrer un seul écran ou un seul appel
3. tester
4. supprimer l’ancien code seulement quand plus rien ne l’utilise

Toujours expliquer :

* ce qui posait problème
* ce qui a été modifié
* quels fichiers ont été touchés
* ce qu’il reste à migrer

---

## Cas spécifiques du projet

* Toujours utiliser `self._conn`, jamais recréer une connexion DB
* Les opérations longues doivent utiliser un `QThread`
* Les dates doivent être au format `YYYY-MM-DD`
* Les mois doivent être stockés en `YYYY-MM-01`
* Les montants dans `transactions.amount` restent positifs ; le sens dépend du type
* Toujours passer par `services/` pour les KPIs
* Les snapshots passés ne doivent jamais être recalculés à la volée
* Les panels bourse ne doivent jamais recalculer eux-mêmes les positions live
* Le cashflow et le taux d’épargne doivent passer uniquement par `cashflow.py`

---

## Avant de terminer une tâche

Toujours vérifier :

* le comportement visible est identique
* aucun calcul métier n’a été ajouté dans la UI
* aucune logique n’a été dupliquée
* aucune fonction privée n’est appelée depuis l’extérieur
* aucun import inutile n’a été ajouté
* le code est plus simple et plus maintenable qu’avant
