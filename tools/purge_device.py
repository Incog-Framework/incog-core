"""
Delete every signal (and its evidence) for one device.

For clearing test/simulator data out of a database without needing psql.
Inspects by default; only deletes when passed --apply.

    python tools/purge_device.py Agent-X-Delta
    python tools/purge_device.py Agent-X-Delta --apply

DATABASE_URL is read from the shell environment first, then .env:

    PowerShell:  $env:DATABASE_URL = "<url>"
    bash:        export DATABASE_URL="<url>"
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Captured before load_dotenv, which would make every source look like the shell.
_FROM_SHELL = os.environ.get("DATABASE_URL") is not None

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL is not set (checked the shell environment and .env)")

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    sys.exit(__doc__)
DEVICE_ID = args[0]
APPLY = "--apply" in sys.argv


def describe_target(url: str) -> str:
    from urllib.parse import urlparse

    p = urlparse(url)
    return f"{p.hostname or '?'}:{p.port or 5432}/{(p.path or '/').lstrip('/') or '?'}"


# ALWAYS confirm this is the database the deployed service actually uses.
print(f"target database: {describe_target(DATABASE_URL)}")
print(f"source of URL  : {'shell environment' if _FROM_SHELL else '.env file'}")
print(f"device_id      : {DEVICE_ID}\n")

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False
try:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM emergency_signals WHERE device_id = %s", (DEVICE_ID,)
        )
        signal_count = cur.fetchone()[0]

        # evidence_vault.signal_id references emergency_signals.id, so dependent
        # rows have to go first or the delete fails on the foreign key.
        cur.execute(
            "SELECT count(*) FROM evidence_vault WHERE signal_id IN "
            "(SELECT id FROM emergency_signals WHERE device_id = %s)",
            (DEVICE_ID,),
        )
        evidence_count = cur.fetchone()[0]

        print(f"  signals to delete : {signal_count}")
        print(f"  evidence to delete: {evidence_count}")

        if signal_count == 0:
            print("\nNothing to do.")
            sys.exit(0)

        cur.execute(
            "SELECT DISTINCT device_id FROM emergency_signals "
            "WHERE device_id <> %s ORDER BY device_id",
            (DEVICE_ID,),
        )
        keeping = [r[0] for r in cur.fetchall()]
        print(f"  devices kept      : {', '.join(keeping) if keeping else '(none)'}")

        if not APPLY:
            print("\nRe-run with --apply to delete.")
            sys.exit(0)

        cur.execute(
            "DELETE FROM evidence_vault WHERE signal_id IN "
            "(SELECT id FROM emergency_signals WHERE device_id = %s)",
            (DEVICE_ID,),
        )
        deleted_evidence = cur.rowcount
        cur.execute(
            "DELETE FROM emergency_signals WHERE device_id = %s", (DEVICE_ID,)
        )
        deleted_signals = cur.rowcount

    conn.commit()
    print(f"\nDeleted {deleted_signals} signal(s) and {deleted_evidence} evidence row(s).")
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
