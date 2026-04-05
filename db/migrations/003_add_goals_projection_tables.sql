-- Migration 003 : Objectifs & Projection (tables de base)

CREATE TABLE IF NOT EXISTS financial_goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('family', 'person')),
  scope_id INTEGER,
  category TEXT,
  target_amount REAL NOT NULL DEFAULT 0,
  current_amount REAL NOT NULL DEFAULT 0,
  target_date TEXT,
  priority TEXT DEFAULT 'NORMAL',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  CHECK (
    (scope_type = 'family' AND scope_id IS NULL)
    OR (scope_type = 'person' AND scope_id IS NOT NULL)
  ),
  FOREIGN KEY(scope_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_financial_goals_scope_status
ON financial_goals(scope_type, scope_id, status);

CREATE TABLE IF NOT EXISTS projection_scenarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('family', 'person')),
  scope_id INTEGER,
  is_default INTEGER NOT NULL DEFAULT 0,
  horizon_years INTEGER NOT NULL DEFAULT 10,
  expected_return_pct REAL NOT NULL DEFAULT 6.0,
  inflation_pct REAL NOT NULL DEFAULT 2.0,
  income_growth_pct REAL NOT NULL DEFAULT 0.0,
  expense_growth_pct REAL NOT NULL DEFAULT 0.0,
  monthly_savings_override REAL,
  fire_multiple REAL NOT NULL DEFAULT 25.0,
  use_real_snapshot_base INTEGER NOT NULL DEFAULT 1,
  initial_net_worth_override REAL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  CHECK (
    (scope_type = 'family' AND scope_id IS NULL)
    OR (scope_type = 'person' AND scope_id IS NOT NULL)
  ),
  FOREIGN KEY(scope_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projection_scenarios_scope
ON projection_scenarios(scope_type, scope_id);

CREATE INDEX IF NOT EXISTS idx_projection_scenarios_scope_default
ON projection_scenarios(scope_type, scope_id, is_default);

INSERT OR IGNORE INTO schema_version(version, description)
VALUES (3, 'add goals and projection tables');
