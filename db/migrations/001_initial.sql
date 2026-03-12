-- Migration 001 : schéma initial
-- Marque la version de base (schéma existant avant le versioning)
-- Aucune instruction DDL ici : le schéma complet est déjà géré par schema.sql
-- Cette migration sert uniquement à initialiser la table schema_version.
INSERT OR IGNORE INTO schema_version(version, description)
VALUES (1, 'initial schema');
