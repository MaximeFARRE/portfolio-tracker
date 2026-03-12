-- Migration 002 : ajout index composite transactions
CREATE INDEX IF NOT EXISTS idx_tx_person_account_date ON transactions(person_id, account_id, date);
INSERT OR IGNORE INTO schema_version(version, description)
VALUES (2, 'add composite index on transactions(person_id, account_id, date)');
