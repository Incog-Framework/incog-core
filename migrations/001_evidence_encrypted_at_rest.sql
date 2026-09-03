-- 001: store evidence as ciphertext instead of plaintext (Decision 4)
--
-- SQLAlchemy's create_all() only creates missing tables; it will NOT alter an
-- existing evidence_vault. This migration must be run by hand against any
-- database that already has the old schema, or evidence inserts will fail.
--
-- *** DESTRUCTIVE ***
-- Existing evidence_vault rows hold decrypted plaintext. They cannot be
-- converted: the original encrypted blob was never stored, so there is nothing
-- to migrate them from. Decision 4 requires plaintext evidence to be purged, so
-- this deletes them. Take a backup first if any of that data still matters.
--
-- Usage:
--   psql "$DATABASE_URL" -f migrations/001_evidence_encrypted_at_rest.sql

BEGIN;

DELETE FROM evidence_vault;

ALTER TABLE evidence_vault DROP COLUMN IF EXISTS decrypted_text;

-- [12-byte IV][ciphertext||16-byte GCM tag], exactly as received from the device.
ALTER TABLE evidence_vault ADD COLUMN IF NOT EXISTS ciphertext BYTEA NOT NULL;

-- Non-sensitive identifiers lifted from the verified plaintext, for lookup.
ALTER TABLE evidence_vault ADD COLUMN IF NOT EXISTS session_id VARCHAR;
ALTER TABLE evidence_vault ADD COLUMN IF NOT EXISTS device_timestamp TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_evidence_vault_session_id
    ON evidence_vault (session_id);

COMMIT;
