---
trigger: always_on
---

# code_guide.md

* Le code doit être simple, lisible et compréhensible rapidement.
* Préférer du code explicite plutôt que compact.
* Éviter les astuces, raccourcis ou optimisations prématurées.
* Préférer 10 lignes claires à 2 lignes difficiles à comprendre.
* Une fonction doit faire une seule chose.
* Une fonction longue doit être découpée.
* Éviter les fonctions de plus de 50 à 100 lignes.
* Utiliser des noms explicites pour les fonctions, variables et fichiers.
* Ne jamais utiliser des noms vagues comme `tmp`, `x`, `data2`, `result_final`.
* Toujours écrire un docstring simple pour les fonctions publiques.
* Préférer des variables intermédiaires si cela rend le code plus clair.
* Éviter plus de 3 niveaux d’imbrication (`if`, `for`, etc.).
* Préférer retourner tôt (`early return`) plutôt que multiplier les blocs imbriqués.
* Toujours typer les arguments et les retours quand c’est possible.
* Regrouper la logique répétée dans une fonction dédiée.
* Ne jamais copier-coller la même logique à plusieurs endroits.
* Toujours garder le même style dans tout le projet.
* Respecter le style et les conventions déjà présents dans le fichier.
* Si une modification devient trop grosse, la découper en plusieurs étapes.
* Quand un fichier dépasse environ 300 à 400 lignes, réfléchir à le découper.
* Une IA doit toujours expliquer brièvement :

  * ce qui était problématique
  * ce qu’elle a changé
  * quels fichiers ont été modifiés
  * ce qu’il reste éventuellement à faire
* Une tâche n’est terminée que si le code est plus simple, plus clair et plus maintenable qu’avant.
