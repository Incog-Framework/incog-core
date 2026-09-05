-- 001: store evidence as ciphertext instead of plaintext (Decision 4)
--
-- SQLAlchemy's create_all() only creates missing tables; it will NOT alter an
-- existing evidence_vault. This migration upgrades a database that already has
-- the old schema.
--
-- Safe to run unconditionally. It is idempotent and does nothing if the table
-- does not exist yet (the app will create it correctly on startup) or if it has
-- already been migrated.
--
-- *** DESTRUCTIVE on an un-migrated table ***
-- Old evidence_vault rows hold decrypted plaintext. They cannot be converted:
-- the original encrypted blob was never stored, so there is nothing to migrate
-- them from. Decision 4 requires plaintext evidence to be purged, so they are
-- deleted. Take a backup first if that data still matters.
--
-- Usage:
--   psql "$DATABASE_URL" -f migrations/001_evidence_encrypted_at_rest.sql

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.evidence_vault') IS NULL THEN
        RAISE NOTICE 'evidence_vault does not exist - nothing to migrate. The application will create it with the correct schema on startup.';
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'evidence_vault' AND column_name = 'ciphertext'
    ) THEN
        RAISE NOTICE 'evidence_vault is already migrated - nothing to do.';
    ELSE
        -- Plaintext rows that cannot be converted to ciphertext.
        DELETE FROM evidence_vault;

        ALTER TABLE evidence_vault DROP COLUMN IF EXISTS decrypted_text;

        -- [12-byte IV][ciphertext||16-byte GCM tag], exactly as received.
        ALTER TABLE evidence_vault ADD COLUMN ciphertext BYTEA NOT NULL;

        -- Non-sensitive identifiers lifted from the verified plaintext.
        ALTER TABLE evidence_vault ADD COLUMN IF NOT EXISTS session_id VARCHAR;
        ALTER TABLE evidence_vault ADD COLUMN IF NOT EXISTS device_timestamp TIMESTAMP;

        RAISE NOTICE 'evidence_vault migrated to the encrypted-at-rest schema.';
    END IF;

    CREATE INDEX IF NOT EXISTS ix_evidence_vault_session_id
        ON evidence_vault (session_id);
END $$;

COMMIT;
