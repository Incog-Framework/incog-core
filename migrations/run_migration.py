"""
Apply a migration without needing the psql client installed.

Inspects by default; only mutates when passed --apply.

    python migrations/run_migration.py                 # show current schema
    python migrations/run_migration.py --apply         # run migration 001

DATABASE_URL is read from the environment or .env, the same way main.py loads it.
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

MIGRATION = Path(__file__).with_name("001_evidence_encrypted_at_rest.sql")

# An existing DATABASE_URL in the environment wins over .env, so you can point
# this at a specific database without editing any file:
#     PowerShell:  $env:DATABASE_URL = "<url>"
#     bash:        export DATABASE_URL="<url>"
# Captured before load_dotenv, which would otherwise make every source look
# like the environment.
_FROM_SHELL = os.environ.get("DATABASE_URL") is not None

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is not set (checked the environment and .env)")


def describe_target(url: str) -> str:
    """host/database of the target, with credentials stripped."""
    from urllib.parse import urlparse

    p = urlparse(url)
    return f"{p.hostname or '?'}:{p.port or 5432}/{(p.path or '/').lstrip('/') or '?'}"


# ALWAYS confirm this is the database the application actually uses. A local
# .env can easily point somewhere other than the deployed service.
print(f"target database: {describe_target(DATABASE_URL)}")
print(f"source of URL  : {'shell environment' if _FROM_SHELL else '.env file'}\n")


def show_schema(cur):
    cur.execute("SELECT to_regclass('public.evidence_vault')")
    if cur.fetchone()[0] is None:
        print("  evidence_vault: DOES NOT EXIST")
        print("  -> no migration needed; the app creates it correctly on startup")
        return None

    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'evidence_vault' ORDER BY ordinal_position"
    )
    columns = cur.fetchall()
    print("  evidence_vault columns:")
    for name, dtype in columns:
        print(f"    - {name} ({dtype})")

    names = {c[0] for c in columns}
    cur.execute("SELECT count(*) FROM evidence_vault")
    rows = cur.fetchone()[0]
    print(f"  rows: {rows}")

    if "ciphertext" in names:
        print("  -> already migrated")
        return False
    print("  -> OLD SCHEMA: 'ciphertext' is missing, so evidence inserts fail with 500")
    if "decrypted_text" in names and rows:
        print(f"  -> WARNING: {rows} row(s) of PLAINTEXT evidence will be DELETED")
    return True


def main():
    apply = "--apply" in sys.argv
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True  # the .sql file manages its own BEGIN/COMMIT
    try:
        with conn.cursor() as cur:
            print("BEFORE:")
            needs = show_schema(cur)

            if not apply:
                if needs:
                    print("\nRe-run with --apply to migrate.")
                return

            if needs is None:
                print("\nNothing to do.")
                return

            print(f"\nApplying {MIGRATION.name} ...")
            cur.execute(MIGRATION.read_text(encoding="utf-8"))
            for notice in conn.notices:
                print("  " + notice.strip())

            print("\nAFTER:")
            show_schema(cur)
            print("\nDone.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
