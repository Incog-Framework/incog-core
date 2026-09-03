# Incog Backend (Phases 11–12)

FastAPI + PostgreSQL/PostGIS service that receives emergency signals from the
Android client, stores them with their location, verifies attached AES-256-GCM
evidence, and alerts the user's emergency contacts over SMS and/or a webhook.

Owner: Chirag. Tracked in issue #4.

Replaces the earlier `ARCHITECTURE.md`, `DISPATCHER_SETUP.md` and
`DISPATCHER_QUICKSTART.md`, which described the pre-Decision-1/4 design
(Fernet, hardcoded geofence, militarised vocabulary) and were no longer
accurate.

---

## Layout

| File | Purpose |
|---|---|
| `main.py` | FastAPI app: endpoints, models, alert dispatch |
| `evidence_crypto.py` | AES-256-GCM decode/verify. No DB or web imports, so it is unit-testable standalone |
| `schemas.py` | Pydantic request/response models |
| `tracker.py` | Local simulator standing in for the Android client (dev only) |
| `migrations/` | Hand-run SQL; `create_all()` does not alter existing tables |
| `tests/` | pytest suite, no database required |

---

## Running it

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # then fill it in
uvicorn main:app --reload
```

Tests:

```bash
python -m pytest tests/ -q
```

The suite runs without Postgres — the DB session is stubbed and `conftest.py`
pins the environment so it can never reach a real database or send real SMS.

Simulator, against a running server:

```bash
python tracker.py
```

Responder dashboard: <http://localhost:8000/map> (prompts for the API key).

---

## Endpoints

All require an API key except `/map`, which asks for one in the browser.
Send it as `X-Incog-Key`. The old `X-Agent-Key` header is still accepted so
existing clients keep working, but it logs a deprecation warning.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/sos` | Record a signal, alert contacts, store evidence |
| `GET` | `/api/v1/sos` | Latest position per device |
| `POST` | `/api/v1/dispatch/test` | Send a test alert |
| `GET` | `/api/v1/dispatch/status` | Report dispatcher configuration |
| `GET` | `/map` | Responder dashboard |

### `POST /api/v1/sos`

```json
{
  "device_id": "demo-device-01",
  "latitude": 12.9412,
  "longitude": 77.5652,
  "is_stealth_active": true,
  "encrypted_evidence": "<base64, optional>"
}
```

```json
{
  "status": "success",
  "message": "Emergency signal recorded.",
  "signal_id": 42,
  "evidence_stored": true
}
```

`device_id` is restricted to letters, digits, hyphens and underscores — it
reaches log lines and SMS bodies. Coordinates are bounds-checked.

| Status | Meaning |
|---|---|
| 200 | Signal recorded |
| 400 | Evidence malformed or failed authentication |
| 403 | Missing or invalid API key |
| 422 | Payload failed validation |
| 503 | Evidence attached but `EVIDENCE_AES_KEY` is not configured |

### ⚠️ Do not retry on 400 or 503

The signal is committed and contacts are alerted *before* evidence is
processed, so a bad blob costs the evidence but never the location fix or the
alert. A 400/503 from this endpoint therefore means **"evidence rejected"**,
not "request failed" — the signal is already stored.

**A client that retries on these statuses will file a duplicate signal and text
every emergency contact a second time.** Each rejection message names the
signal id and says so explicitly. Retry only on 5xx other than 503, or on a
network-level failure.

---

## Evidence: AES-256-GCM

Wire format, produced by `CryptoManager.kt::encrypt()` in the security module:

```
[ 12-byte random IV ][ ciphertext || 16-byte GCM auth tag ]
```

...base64-encoded into `encrypted_evidence`. Java's `Cipher` appends the GCM
tag to the ciphertext, which is exactly the layout Python's `AESGCM.decrypt()`
expects, so the two interoperate with no repacking. Neither side uses
associated data. Plaintext is the UTF-8 JSON of `EvidencePackage`.

`tests/test_evidence_crypto.py` pins this with a fixed known-answer vector and
asserts the 28-byte overhead (12 IV + 16 tag); if either side ever changes the
layout, those tests fail rather than the format silently drifting.

### Encrypted at rest

The backend decrypts **in memory only**, to verify the GCM tag and read two
non-sensitive fields (`sessionId`, `timestamp`) for triage. What it persists is
the **original ciphertext**. Plaintext is never written to disk — the old
`evidence_vault.decrypted_text` column is gone.

### ⚠️ Blocked on the security module

`SecurityOrchestrator.kt` currently calls `CryptoManager.generate256BitKey()`,
making a **fresh random key per emergency** that is returned in-process and
shared with nobody. Per the team decision the backend expects a **pre-shared
key** in `EVIDENCE_AES_KEY`.

Until Gagan changes the orchestrator to load that shared key, evidence
decryption cannot work end-to-end. The backend side is complete and tested
against the format; it is the key exchange that is outstanding.

Separately, the security pipeline currently emits evidence as LSB stego
**images**, not as a base64 blob — so the transport for `encrypted_evidence`
still needs agreeing between us.

---

## Environment variables

> **`.env.example` in this repo is stale.** It still lists `ENCRYPTION_KEY` and
> `AGENT_SECRET_KEY`. Update it to match the table below.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL with PostGIS |
| `INCOG_API_KEY` | yes | Sent as `X-Incog-Key`. Falls back to `AGENT_SECRET_KEY` (deprecated) |
| `EVIDENCE_AES_KEY` | no | Base64 of 32 raw bytes. Unset ⇒ evidence refused with 503, SOS unaffected |
| `ENABLE_SMS_DISPATCH` | no | Default `true` |
| `TWILIO_ACCOUNT_SID` | if SMS | |
| `TWILIO_AUTH_TOKEN` | if SMS | |
| `TWILIO_PHONE_NUMBER` | if SMS | |
| `EMERGENCY_CONTACTS` | if SMS | Comma-separated, with country code |
| `ENABLE_WEBHOOK_DISPATCH` | no | Default `false` |
| `DISPATCH_WEBHOOK_URL` | if webhook | |
| `MAP_DEFAULT_LAT` / `MAP_DEFAULT_LON` | no | Dashboard fallback centre, defaults to BMSCE |
| `C2_SERVER_URL`, `DEVICE_ID`, `SIM_START_LAT`, `SIM_START_LON` | no | `tracker.py` only |

Generate secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"           # INCOG_API_KEY
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"  # EVIDENCE_AES_KEY
```

---

## Database

```
emergency_signals
  id, device_id, timestamp, is_stealth_active
  location  GEOMETRY(POINT, 4326)
  indexes: (device_id, timestamp), GiST on location

evidence_vault
  id, signal_id -> emergency_signals.id
  ciphertext        BYTEA      -- [IV][ct||tag], as received
  session_id        VARCHAR    -- triage metadata from verified plaintext
  device_timestamp  TIMESTAMP
  timestamp
```

`create_all()` only creates missing tables. An existing database must be
migrated by hand:

```bash
psql "$DATABASE_URL" -f migrations/001_evidence_encrypted_at_rest.sql
```

**That migration deletes existing `evidence_vault` rows.** They hold plaintext
that cannot be converted back to ciphertext, and Decision 4 requires purging it.

`GET /api/v1/sos` uses a `ROW_NUMBER()` window function to take the latest row
per device — `DISTINCT ON` was non-deterministic about which row it returned.

---

## Geofencing

Removed. The old implementation hardcoded a London polygon labelled "restricted
enemy zone" and *revoked* a user's stealth on entering it, which is backwards
for a safety product. `is_stealth_active` is now stored exactly as the client
reports it; the backend never overrides it.

Safety-meaningful geofencing (alerting when someone leaves a safe area) is
deferred to its own issue.

---

## Alerting

Dispatch runs on a background thread, so a slow Twilio call never delays the
acknowledgement to someone in danger. Failures are logged, not retried — a
message queue with retries is the obvious next step.

If neither SMS nor a webhook is configured, dispatch is a logged no-op.

---

## Known gaps

- Key exchange with the security module is unresolved (see above).
- No retry or delivery confirmation on alerts.
- No rate limiting; a device could spam alerts.
- Endpoint tests stub the database — no PostGIS integration test yet.
- `__pycache__/main.cpython-314.pyc` is committed at the repo root and should
  be removed (the `chore/remove-junk-files` branch may already cover it).
