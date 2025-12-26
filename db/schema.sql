PRAGMA foreign_keys = ON;

-- People
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

-- Accounts (onglets dynamiques)
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  account_type TEXT NOT NULL,  -- BANQUE, PEA, CTO, CRYPTO, IMMOBILIER, CREDIT, PE
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
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
  FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
  FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_person_date ON transactions(person_id, date);
CREATE INDEX IF NOT EXISTS idx_tx_account_date ON transactions(account_id, date);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);

-- Dépenses (module indépendant)
CREATE TABLE IF NOT EXISTS depenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    mois TEXT NOT NULL,          -- YYYY-MM-01 (on stocke le mois)
    categorie TEXT NOT NULL,
    montant REAL NOT NULL,
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
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_revenus_person_mois
ON revenus(person_id, mois);
