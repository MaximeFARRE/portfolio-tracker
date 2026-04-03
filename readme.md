# SUIVI DES CORRECTIONS (Changelog)

## Mois 1

### ✅ Tâche 1 : Sauvegarde automatique & Logs persistants (Terminé)
- **Logs persistants (BUG-23 / AM-20)** : Configuration du logger vers `~/.patrimoine/logs/patrimoine.log` avec rotation (5 fichiers de 5Mo max). Gère désormais correctement la capture sécurisée des erreurs globales.
- **Sauvegarde automatique globale (BUG-24 / AM-21)** : Sauvegarde locale déclenchée à la fermeture, copiant les bases `.db` et Turso (`.db-info`) vers `~/.patrimoine/backups/`. Une rétention de 10 copies est configurée localement.
- **Correction des lookbacks manquants** : Le paramètre `fallback_lookback_days` ajusté de 365 à 3650 jours (10 ans) dans les snapshots de `services/snapshots.py`.

---
*En attente de la prochaine tâche (BUG-01: Connexion DB).*
