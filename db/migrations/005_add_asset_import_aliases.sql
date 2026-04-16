-- Migration 005 : mapping alias import -> actif canonique

CREATE TABLE IF NOT EXISTS asset_import_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_source TEXT NOT NULL,
  raw_symbol TEXT NOT NULL DEFAULT '',
  raw_isin TEXT NOT NULL DEFAULT '',
  canonical_asset_id INTEGER NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  last_used_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(canonical_asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_import_aliases_key
ON asset_import_aliases(import_source, raw_symbol, raw_isin);

CREATE INDEX IF NOT EXISTS idx_asset_import_aliases_source_symbol
ON asset_import_aliases(import_source, raw_symbol);

CREATE INDEX IF NOT EXISTS idx_asset_import_aliases_source_isin
ON asset_import_aliases(import_source, raw_isin);

INSERT OR IGNORE INTO schema_version(version, description)
VALUES (5, 'add asset_import_aliases table for import symbol mapping');
