PRAGMA foreign_keys = ON;


-- People
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  tr_phone TEXT                          -- numéro TR pour export pytr
);

-- Accounts (onglets dynamiques)
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  account_type TEXT NOT NULL,  -- BANQUE, LIVRET, PEA, CTO, CRYPTO, IMMOBILIER, CREDIT, PE
  subtype TEXT,                -- pour LIVRET : LIVRET_A, LDDS, LEP, LIVRET_JEUNE, CSL, AUTRE
  institution TEXT,
  currency TEXT NOT NULL DEFAULT 'EUR',
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

-- Assets (pour PEA/CTO/CRYPTO principalement)
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL, -- action, etf, crypto, private_equity, cash_equivalent, immobilier, autre
  currency TEXT NOT NULL DEFAULT 'EUR'
);

-- Transactions (source de vérité)
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL, -- YYYY-MM-DD
  person_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  type TEXT NOT NULL, -- ACHAT, VENTE, DIVIDENDE, DEPOT, RETRAIT, DEPENSE, FRAIS, INTERETS, REMBOURSEMENT_CREDIT, LOYER, IMPOT
  asset_id INTEGER,
  quantity REAL,
  price REAL,
  fees REAL NOT NULL DEFAULT 0,
  amount REAL NOT NULL, -- montant total (positif). Le sens est géré par le type.
  category TEXT,
  note TEXT,
  is_hidden_from_cashflow INTEGER NOT NULL DEFAULT 0,
  is_internal_transfer INTEGER NOT NULL DEFAULT 0,
  deleted_at TEXT,
  import_batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_person_date ON transactions(person_id, date);
CREATE INDEX IF NOT EXISTS idx_tx_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_tx_person_account_date ON transactions(person_id, account_id, date);

-- Dépenses (module indépendant)
CREATE TABLE IF NOT EXISTS depenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    mois TEXT NOT NULL,          -- YYYY-MM-01 (on stocke le mois)
    categorie TEXT NOT NULL,
    montant REAL NOT NULL,
    import_batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_depenses_person_mois
ON depenses(person_id, mois);

-- Revenus (module indépendant)
CREATE TABLE IF NOT EXISTS revenus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    mois TEXT NOT NULL,          -- YYYY-MM-01 (on stocke le mois)
    categorie TEXT NOT NULL,
    montant REAL NOT NULL,
    import_batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_revenus_person_mois
ON revenus(person_id, mois);

-- =========================================================
-- CREDITS
-- =========================================================

CREATE TABLE IF NOT EXISTS credits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,           -- le sous-compte de type CREDIT
  payer_account_id INTEGER,              -- compte bancaire payeur
  nom TEXT NOT NULL,
  banque TEXT,
  type_credit TEXT,                     -- immo / conso / auto / etudiant / autre
  capital_emprunte REAL,
  taux_nominal REAL,
  taeg REAL,
  duree_mois INTEGER,
  mensualite_theorique REAL,
  assurance_mensuelle_theorique REAL,
  date_debut TEXT,                      -- YYYY-MM-DD
  actif INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  FOREIGN KEY(payer_account_id) REFERENCES accounts(id) ON DELETE SET NULL,
  UNIQUE(account_id)                    -- 1 fiche crédit par sous-compte crédit
);

CREATE TABLE IF NOT EXISTS credit_amortissements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  credit_id INTEGER NOT NULL,
  date_echeance TEXT,                   -- YYYY-MM-DD (ou YYYY-MM-01)
  mensualite REAL,
  capital_amorti REAL,
  interets REAL,
  assurance REAL,
  crd REAL,                             -- capital restant dû (estimé)
  annee INTEGER,                        -- pour totaux annuels rapides
  mois INTEGER,                         -- optionnel, utile si tu veux
  FOREIGN KEY(credit_id) REFERENCES credits(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_credit_person ON credits(person_id);
CREATE INDEX IF NOT EXISTS idx_amort_credit_date ON credit_amortissements(credit_id, date_echeance);
CREATE INDEX IF NOT EXISTS idx_amort_credit_annee ON credit_amortissements(credit_id, annee);


-- =========================================
-- Private Equity
-- =========================================

CREATE TABLE IF NOT EXISTS pe_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    platform TEXT, -- ex: Blast, Seedrs, Wiseed...
    project_type TEXT, -- ex: Startup, Fonds, Crowdfunding (optionnel)
    status TEXT NOT NULL DEFAULT 'EN_COURS', -- EN_COURS | SORTI | FAILLITE
    created_at TEXT DEFAULT (DATE('now')),
    exit_date TEXT, -- rempli si SORTI
    note TEXT,
    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE TABLE IF NOT EXISTS pe_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    date TEXT NOT NULL, -- YYYY-MM-DD
    tx_type TEXT NOT NULL, -- INVEST | DISTRIB | FEES | VALO | VENTE
    amount REAL NOT NULL,  -- EUR (positif)
    quantity REAL,         -- optionnel
    unit_price REAL,       -- optionnel
    note TEXT,
    FOREIGN KEY (project_id) REFERENCES pe_projects(id)
);

CREATE INDEX IF NOT EXISTS idx_pe_projects_person ON pe_projects(person_id);
CREATE INDEX IF NOT EXISTS idx_pe_tx_project_date ON pe_transactions(project_id, date);

-- =========================================
-- Private Equity - Cash (liquidité plateforme)
-- =========================================

CREATE TABLE IF NOT EXISTS pe_cash_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    platform TEXT NOT NULL,          -- ex: Blast
    date TEXT NOT NULL,              -- YYYY-MM-DD
    tx_type TEXT NOT NULL,           -- ADJUST | DEPOSIT | WITHDRAW
    amount REAL NOT NULL,            -- EUR, positif
    note TEXT,
    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE INDEX IF NOT EXISTS idx_pe_cash_person_platform_date
ON pe_cash_transactions(person_id, platform, date);


-- =========================================
-- BOURSE / PRICING (V1)
-- =========================================

-- Métadonnées d’actifs (sans toucher la table assets existante)
CREATE TABLE IF NOT EXISTS asset_meta (
  asset_id INTEGER PRIMARY KEY,
  exchange TEXT,
  isin TEXT,
  price_source TEXT DEFAULT 'AUTO',  -- AUTO | MANUAL
  status TEXT DEFAULT 'OK',          -- OK | NOT_FOUND
  FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

-- Alias import (TR et autres sources) : mapping symbole brut -> actif canonique
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

-- Prix cachés (dernier prix connu, stocké par date)
CREATE TABLE IF NOT EXISTS prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL,
  date TEXT NOT NULL,               -- YYYY-MM-DD
  price REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'EUR',
  source TEXT NOT NULL DEFAULT 'AUTO', -- AUTO | MANUAL
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
  UNIQUE(asset_id, date)
);

CREATE INDEX IF NOT EXISTS idx_prices_asset_date ON prices(asset_id, date);

CREATE TABLE IF NOT EXISTS fx_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  base_ccy TEXT NOT NULL,
  quote_ccy TEXT NOT NULL,
  asof TEXT NOT NULL,
  rate REAL NOT NULL,
  UNIQUE(base_ccy, quote_ccy, asof)
);

CREATE INDEX IF NOT EXISTS idx_fx_pair_date
ON fx_rates(base_ccy, quote_ccy, asof);


-- ------------------------------------------------------------
-- BANQUE (container) -> sous-comptes
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bank_subaccounts (
  bank_account_id INTEGER NOT NULL,
  sub_account_id  INTEGER NOT NULL,
  subtype         TEXT    NOT NULL, -- courant / livret / remunere / pel

  PRIMARY KEY (bank_account_id, sub_account_id),
  FOREIGN KEY (bank_account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  FOREIGN KEY (sub_account_id)  REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bank_subaccounts_bank ON bank_subaccounts(bank_account_id);
CREATE INDEX IF NOT EXISTS idx_bank_subaccounts_sub  ON bank_subaccounts(sub_account_id);

-- =========================================
-- WEEKLY MARKET DATA + SNAPSHOTS (V2)
-- =========================================

CREATE TABLE IF NOT EXISTS asset_prices_weekly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  week_date TEXT NOT NULL,          -- YYYY-MM-DD (lundi)
  adj_close REAL NOT NULL,
  currency TEXT,
  source TEXT DEFAULT 'YFINANCE',
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(symbol, week_date)
);

CREATE INDEX IF NOT EXISTS idx_apw_symbol_week
ON asset_prices_weekly(symbol, week_date);

CREATE TABLE IF NOT EXISTS fx_rates_weekly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  base_ccy TEXT NOT NULL,
  quote_ccy TEXT NOT NULL,
  week_date TEXT NOT NULL,          -- YYYY-MM-DD (lundi)
  rate REAL NOT NULL,               -- base -> quote
  source TEXT DEFAULT 'YFINANCE',
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(base_ccy, quote_ccy, week_date)
);

CREATE INDEX IF NOT EXISTS idx_fxw_pair_week
ON fx_rates_weekly(base_ccy, quote_ccy, week_date);

CREATE TABLE IF NOT EXISTS patrimoine_snapshots_weekly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  week_date TEXT NOT NULL,          -- YYYY-MM-DD (lundi)
  created_at TEXT NOT NULL,         -- ISO datetime
  mode TEXT DEFAULT 'MANUAL',       -- MANUAL / REBUILD

  patrimoine_net REAL DEFAULT 0,
  patrimoine_brut REAL DEFAULT 0,

  liquidites_total REAL DEFAULT 0,
  bank_cash REAL DEFAULT 0,
  bourse_cash REAL DEFAULT 0,
  pe_cash REAL DEFAULT 0,

  bourse_holdings REAL DEFAULT 0,
  pe_value REAL DEFAULT 0,
  ent_value REAL DEFAULT 0,
  immobilier_value REAL DEFAULT 0,
  credits_remaining REAL DEFAULT 0,

  notes TEXT,

  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
  UNIQUE(person_id, week_date)
);

CREATE INDEX IF NOT EXISTS idx_psw_person_week
ON patrimoine_snapshots_weekly(person_id, week_date);

CREATE TABLE IF NOT EXISTS patrimoine_snapshots_family_weekly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family_id INTEGER DEFAULT 1,
  week_date TEXT NOT NULL,
  created_at TEXT NOT NULL,
  mode TEXT DEFAULT 'REBUILD',

  patrimoine_net REAL DEFAULT 0,
  patrimoine_brut REAL DEFAULT 0,
  liquidites_total REAL DEFAULT 0,
  bourse_holdings REAL DEFAULT 0,
  pe_value REAL DEFAULT 0,
  ent_value REAL DEFAULT 0,
  immobilier_value REAL DEFAULT 0,
  credits_remaining REAL DEFAULT 0,

  notes TEXT,
  UNIQUE(family_id, week_date)
);

CREATE INDEX IF NOT EXISTS idx_psfw_family_week
ON patrimoine_snapshots_family_weekly(family_id, week_date);

-- =========================================
-- HISTORIQUE DES IMPORTS (AM-19)
-- =========================================

CREATE TABLE IF NOT EXISTS import_batches (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  import_type  TEXT NOT NULL,
  person_id    INTEGER,
  person_name  TEXT,
  account_id   INTEGER,
  account_name TEXT,
  filename     TEXT,
  imported_at  TEXT DEFAULT (datetime('now')),
  nb_rows      INTEGER DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'ACTIVE',
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_import_batches_person
ON import_batches(person_id, imported_at);


-- =========================================
-- OBJECTIFS & PROJECTION
-- =========================================

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
  expected_return_pct REAL NOT NULL DEFAULT 6.0,   -- moyenne pondérée calculée (lecture seule)
  inflation_pct REAL NOT NULL DEFAULT 2.0,
  income_growth_pct REAL NOT NULL DEFAULT 0.0,
  expense_growth_pct REAL NOT NULL DEFAULT 0.0,
  monthly_savings_override REAL,
  fire_multiple REAL NOT NULL DEFAULT 25.0,
  use_real_snapshot_base INTEGER NOT NULL DEFAULT 1,
  initial_net_worth_override REAL,
  -- Rendements par classe d'actif (%)
  return_liquidites_pct   REAL DEFAULT 2.0,
  return_bourse_pct       REAL DEFAULT 7.0,
  return_immobilier_pct   REAL DEFAULT 3.5,
  return_pe_pct           REAL DEFAULT 10.0,
  return_entreprises_pct  REAL DEFAULT 5.0,
  exclude_primary_residence INTEGER NOT NULL DEFAULT 0,
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


-- =========================================
-- PRESETS DE SIMULATION
-- =========================================

CREATE TABLE IF NOT EXISTS simulation_preset_settings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_type      TEXT NOT NULL CHECK(scope_type IN ('family', 'person')),
  scope_id        INTEGER,
  preset          TEXT NOT NULL CHECK(preset IN ('pessimiste', 'realiste', 'optimiste')),
  return_liquidites_pct   REAL NOT NULL DEFAULT 2.0,
  return_bourse_pct       REAL NOT NULL DEFAULT 7.0,
  return_immobilier_pct   REAL NOT NULL DEFAULT 3.5,
  return_pe_pct           REAL NOT NULL DEFAULT 10.0,
  return_entreprises_pct  REAL NOT NULL DEFAULT 5.0,
  inflation_pct       REAL NOT NULL DEFAULT 2.0,
  income_growth_pct   REAL NOT NULL DEFAULT 1.0,
  expense_growth_pct  REAL NOT NULL DEFAULT 1.0,
  fire_multiple       REAL NOT NULL DEFAULT 25.0,
  savings_factor      REAL NOT NULL DEFAULT 1.0,
  CHECK (
    (scope_type = 'family' AND scope_id IS NULL)
    OR (scope_type = 'person' AND scope_id IS NOT NULL)
  ),
  FOREIGN KEY(scope_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_presets_scope
ON simulation_preset_settings(scope_type, scope_id);

-- =========================================
-- SCHEMA VERSIONING
-- =========================================

CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT DEFAULT (datetime('now')),
  description TEXT
);


-- =========================================
-- LEGACY SNAPSHOTS (instantanés ponctuels)
-- =========================================

CREATE TABLE IF NOT EXISTS patrimoine_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  snapshot_date TEXT NOT NULL,        -- 'YYYY-MM-DD'
  created_at TEXT NOT NULL,           -- ISO datetime
  mode TEXT DEFAULT 'AUTO',

  patrimoine_net REAL DEFAULT 0,
  patrimoine_brut REAL DEFAULT 0,

  liquidites_total REAL DEFAULT 0,
  bank_cash REAL DEFAULT 0,
  bourse_cash REAL DEFAULT 0,
  pe_cash REAL DEFAULT 0,

  bourse_holdings REAL DEFAULT 0,
  pe_value REAL DEFAULT 0,
  ent_value REAL DEFAULT 0,
  immobilier_value REAL DEFAULT 0,
  credits_remaining REAL DEFAULT 0,

  notes TEXT,

  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
  UNIQUE(person_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_person_date
ON patrimoine_snapshots(person_id, snapshot_date);


-- =========================================
-- ENTREPRISES
-- =========================================

CREATE TABLE IF NOT EXISTS enterprises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  entity_type TEXT NOT NULL,
  valuation_eur REAL NOT NULL DEFAULT 0,
  debt_eur REAL NOT NULL DEFAULT 0,
  note TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS enterprise_shares (
  enterprise_id INTEGER NOT NULL,
  person_id INTEGER NOT NULL,
  pct REAL NOT NULL DEFAULT 0,
  initial_invest_eur REAL NOT NULL DEFAULT 0,
  cca_eur REAL NOT NULL DEFAULT 0,
  initial_invest_date TEXT,
  PRIMARY KEY (enterprise_id, person_id),
  FOREIGN KEY (enterprise_id) REFERENCES enterprises(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS enterprise_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  enterprise_id INTEGER NOT NULL,
  changed_at TEXT NOT NULL DEFAULT (datetime('now')),
  effective_date TEXT NOT NULL DEFAULT (date('now')),
  valuation_eur REAL NOT NULL,
  debt_eur REAL NOT NULL,
  note TEXT,
  FOREIGN KEY (enterprise_id) REFERENCES enterprises(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eh_ent_date
ON enterprise_history(enterprise_id, effective_date);


-- =========================================
-- IMMOBILIER
-- =========================================

CREATE TABLE IF NOT EXISTS immobiliers (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  name                TEXT    NOT NULL UNIQUE,
  property_type       TEXT    NOT NULL DEFAULT 'AUTRE',
  valuation_eur       REAL    NOT NULL DEFAULT 0,
  debt_eur            REAL    NOT NULL DEFAULT 0,
  monthly_rent_eur    REAL    NOT NULL DEFAULT 0,
  annual_charges_eur  REAL    NOT NULL DEFAULT 0,
  annual_tax_eur      REAL    NOT NULL DEFAULT 0,
  note                TEXT,
  effective_date      TEXT    NOT NULL DEFAULT (date('now')),
  created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS immobilier_shares (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id       INTEGER NOT NULL,
  person_id         INTEGER NOT NULL,
  pct               REAL    NOT NULL DEFAULT 100,
  initial_invest_eur REAL   NOT NULL DEFAULT 0,
  initial_date      TEXT,
  UNIQUE (property_id, person_id),
  FOREIGN KEY (property_id) REFERENCES immobiliers(id) ON DELETE CASCADE,
  FOREIGN KEY (person_id)   REFERENCES people(id)      ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS immobilier_history (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id         INTEGER NOT NULL,
  valuation_eur       REAL    NOT NULL DEFAULT 0,
  debt_eur            REAL    NOT NULL DEFAULT 0,
  monthly_rent_eur    REAL    NOT NULL DEFAULT 0,
  annual_charges_eur  REAL    NOT NULL DEFAULT 0,
  annual_tax_eur      REAL    NOT NULL DEFAULT 0,
  note                TEXT,
  effective_date      TEXT    NOT NULL DEFAULT (date('now')),
  created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (property_id) REFERENCES immobiliers(id) ON DELETE CASCADE
);


-- =========================================
-- ISIN TICKER CACHE
-- =========================================

CREATE TABLE IF NOT EXISTS isin_ticker_cache (
  isin        TEXT PRIMARY KEY,
  ticker      TEXT,
  source      TEXT,
  resolved_at TEXT DEFAULT (datetime('now'))
);


-- =========================================
-- REBUILD WATERMARKS
-- =========================================

CREATE TABLE IF NOT EXISTS rebuild_watermarks (
  scope TEXT NOT NULL,          -- ex: 'WEEKLY_PERSON'
  entity_id INTEGER NOT NULL,   -- person_id
  last_tx_id INTEGER,
  last_tx_created_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(scope, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_rw_scope_entity
ON rebuild_watermarks(scope, entity_id);
