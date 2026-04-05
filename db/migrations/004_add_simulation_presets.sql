-- Migration 004 : Presets de simulation + rendements par classe d'actif

-- Table des presets de simulation (pessimiste / realiste / optimiste) par scope.
-- Note : scope_id est NULL pour la famille, entier pour une personne.
-- L'unicité (scope_type, scope_id, preset) est gérée en couche applicative
-- car SQLite ne garantit pas UNIQUE sur les colonnes nullable.
CREATE TABLE IF NOT EXISTS simulation_preset_settings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_type      TEXT NOT NULL CHECK(scope_type IN ('family', 'person')),
  scope_id        INTEGER,
  preset          TEXT NOT NULL CHECK(preset IN ('pessimiste', 'realiste', 'optimiste')),

  -- Rendements annuels par classe d'actif (%)
  return_liquidites_pct   REAL NOT NULL DEFAULT 2.0,
  return_bourse_pct       REAL NOT NULL DEFAULT 7.0,
  return_immobilier_pct   REAL NOT NULL DEFAULT 3.5,
  return_pe_pct           REAL NOT NULL DEFAULT 10.0,
  return_entreprises_pct  REAL NOT NULL DEFAULT 5.0,

  -- Macro
  inflation_pct       REAL NOT NULL DEFAULT 2.0,
  income_growth_pct   REAL NOT NULL DEFAULT 1.0,
  expense_growth_pct  REAL NOT NULL DEFAULT 1.0,
  fire_multiple       REAL NOT NULL DEFAULT 25.0,
  savings_factor      REAL NOT NULL DEFAULT 1.0,   -- multiplicateur de l'épargne de base

  CHECK (
    (scope_type = 'family' AND scope_id IS NULL)
    OR (scope_type = 'person' AND scope_id IS NOT NULL)
  ),
  FOREIGN KEY(scope_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_presets_scope
ON simulation_preset_settings(scope_type, scope_id);

-- Colonnes per-class sur projection_scenarios (rétrocompatibles via DEFAULT)
ALTER TABLE projection_scenarios ADD COLUMN return_liquidites_pct  REAL DEFAULT 2.0;
ALTER TABLE projection_scenarios ADD COLUMN return_bourse_pct      REAL DEFAULT 7.0;
ALTER TABLE projection_scenarios ADD COLUMN return_immobilier_pct  REAL DEFAULT 3.5;
ALTER TABLE projection_scenarios ADD COLUMN return_pe_pct          REAL DEFAULT 10.0;
ALTER TABLE projection_scenarios ADD COLUMN return_entreprises_pct REAL DEFAULT 5.0;
ALTER TABLE projection_scenarios ADD COLUMN exclude_primary_residence INTEGER NOT NULL DEFAULT 0;

INSERT OR IGNORE INTO schema_version(version, description)
VALUES (4, 'add simulation presets and per-class asset returns');
