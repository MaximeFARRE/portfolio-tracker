# SUIVI DES CORRECTIONS (Changelog)

## Mois 1

### ✅ Tâche 1 : Sauvegarde automatique & Logs persistants (Terminé)
- **Logs persistants (BUG-23 / AM-20)** : Configuration du logger vers `~/.patrimoine/logs/patrimoine.log` avec rotation (5 fichiers de 5Mo max). Gère désormais correctement la capture sécurisée des erreurs globales.
- **Sauvegarde automatique globale (BUG-24 / AM-21)** : Sauvegarde locale déclenchée à la fermeture, copiant les bases `.db` et Turso (`.db-info`) vers `~/.patrimoine/backups/`. Une rétention de 10 copies est configurée localement.
- **Correction des lookbacks manquants** : Le paramètre `fallback_lookback_days` ajusté de 365 à 3650 jours (10 ans) dans les snapshots de `services/snapshots.py`.

---
*En attente de la prochaine tâche (BUG-01: Connexion DB).*
###  Tâche 2 : Accès concurrent DB (BUG-01, BUG-17) (Terminé)
- **Sécurisation des threads (QThread)** : Tous les processus asynchrones longs (Imports TR, Rebuild snapshots famille, Refresh Bourse) génèrent désormais **leur propre connexion locale (with get_conn() as local_conn:)** lors de leur exécution un().
- **Prévention de corruption SQLite** : Élimination du passage en paramètre et du partage de l'objet global natif self._conn issu du main thread UI.
###  Tâche 3 : Connexion dynamique Qt (BUG-03) (Terminé)
- Vérification du code source de qt_ui/pages/import_page.py. Le débordement de mémoire ("Memory Leak") causé par la reconnexion récursive du signal currentIndexChanged était en réalité déjà neutralisé par la condition 
ot getattr(self, "_person_signal_connected"). J'ai certifié ce correctif et clos le BUG-03.

###  Tâche 4 : Migration de Schéma Crédit (BUG-05) (Terminé)
- Ajout pur et dur de la colonne payer_account_id à la table credits dans db/schema.sql (évitant les crashs lors d'une reconstruction from scratch, la migration dynamique était une rustine mais le schéma racine était erroné).
###  Tâche 5 : Nettoyage Code Mort (BUG-06) (Terminé)
- Transfert de l'intégralité du socle Streamlit (pp.py, dossiers ui/ et pages/) dans un dossier d'archive claire legacy_streamlit/ afin que le projet PyQt soit désormais la surface principale non ambiguë et d'éviter que ces vieux scripts bloquent des refactorisations globales avec leurs imports obsolètes.

###  Tâche 6 : Démarrage DB Optimisé (BUG-07) (Terminé)
- J'ai procédé à l'audit du fichier services/db.py ainsi que core/db_connection.py. La logique de seeding initial limitait bien les redondances et l'appel cyclique à init_db() n'est plus présent dans le code actuel. 
