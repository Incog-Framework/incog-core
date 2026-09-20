# Incog Backend — Work Report (Phases 11–12)

**Owner:** Chirag · **Module:** `c2-backend` (FastAPI + PostgreSQL/PostGIS + alert dispatch)
**Period:** 13 Aug – 12 Sep 2026 · **Tracked in:** issue #4

This is a record of *what was built and why*. For how to run and integrate
against the service, see [BACKEND.md](BACKEND.md).

---

## 1. Scope

The backend is the server half of the emergency pipeline. The Android app
detects a threat on-device, the security module encrypts the evidence, and this
service is what receives it:

```
app detects emergency
   │
   ├─ security module encrypts evidence (AES-256-GCM)
   │
   ▼
POST /api/v1/sos  ──►  authenticate
                       validate payload
                       store signal + PostGIS location
                       verify & store evidence (ciphertext)
                       dispatch alerts (background thread)
                          ├─ the user's own trusted contacts
                          └─ responder channel (Discord webhook)
                       │
                       ▼
                  /map  live responder dashboard
```

---

## 2. What was delivered

| Area | Delivered |
|---|---|
| REST API | 5 endpoints, API-key authenticated, Pydantic-validated |
| Persistence | PostgreSQL + PostGIS, spatial index, connection pooling |
| Cryptography | AES-256-GCM evidence decryption interoperating with Kotlin |
| Alerting | Multi-channel dispatch (SMS / WhatsApp / webhook), per-user contacts |
| Dashboard | Authenticated Leaflet map, live positions |
| Operations | Hand-run migration + runner, device purge tool, structured logging |
| Tests | 168, none requiring a database |

**Code size:** ~1,335 lines of production Python, ~1,480 lines of tests,
~270 lines of operational tooling.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/sos` | Ingest a signal, store evidence, dispatch alerts |
| `GET` | `/api/v1/sos` | Latest position per device |
| `POST` | `/api/v1/dispatch/test` | Fire a test alert |
| `GET` | `/api/v1/dispatch/status` | Report dispatcher configuration |
| `GET` | `/map` | Responder dashboard |

---

## 3. Key engineering decisions

**Fernet → AES-256-GCM (team Decision 1).** The security module produces
AES-256-GCM; the original backend used Fernet and could not decrypt it. The
wire format is `[12-byte IV][ciphertext‖16-byte GCM tag]`. Java's `Cipher`
appends the tag to the ciphertext, which is exactly what Python's `AESGCM`
expects, so the two interoperate with no repacking. Pinned by a fixed
known-answer vector and a 28-byte-overhead assertion, so a drift on either side
fails a test instead of silently breaking evidence.

**Evidence encrypted at rest (Decision 4).** The original schema stored
`decrypted_text` — plaintext evidence in the database. The backend now decrypts
**in memory only**, to verify the GCM tag and read two non-sensitive fields for
triage, then persists the *original ciphertext*. This needed no second key: the
device's own ciphertext is what gets stored.

**De-militarisation (Decision 4).** Removed a hardcoded London "restricted
enemy zone" polygon and an inverted geofence that *revoked* a user's stealth on
entering it — backwards for a safety product. Vocabulary reframed across the
API, dashboard, logs and simulator.

**Blank contact means "not configured", not "invalid".** The Android client
defaults contact fields to `""`. Validating strictly would have returned 422 on
every SOS from a user who skipped the setup screen — silently dropping the
emergency of exactly the people least likely to have configured anything.

**Alert failures never cost the signal.** The signal is committed and alerts
dispatched *before* evidence is processed, so a malformed blob costs the
evidence but never the location fix. Dispatch runs on a background thread, so a
slow Twilio call cannot delay acknowledgement to someone in danger.

**Rejections are explicitly non-retryable.** A 400/503 means *evidence
rejected*, not *request failed* — the signal is already stored and contacts
already alerted. Each message says so and names the signal id, because a client
retrying on those would file a duplicate and re-alert everyone.

**The trusted contact is never persisted.** It belongs to someone who never
installed the app. It arrives with the signal, is used for the alert, and is
discarded. Logs show only the last three digits.

**Contact list capped at 10.** Without a ceiling, anyone holding the API key
could post thousands of numbers and use the alert path as a free SMS relay.

**`ROW_NUMBER()` over `DISTINCT ON`.** The original latest-position query was
non-deterministic about which row it returned per device.

---

## 4. Defects found and fixed

| # | Defect | Impact |
|---|---|---|
| 1 | `GET /api/v1/sos` had no authentication | Every user's live location was public |
| 2 | `/map` silently broken by adding that auth | Dashboard 403'd and rendered an empty map |
| 3 | `requirements.txt` stored as UTF-16 | pip could not parse it — Render build failed |
| 4 | `geoalchemy2` and `requests` missing from requirements | Would have crashed at startup after the build "succeeded" |
| 5 | `.gitignore` `.env` rule written in UTF-16 | Git could not parse it; that commit's protection was a no-op |
| 6 | `/dispatch/status` returned the full webhook URL | Anyone with the API key could post to the responder channel |
| 7 | `evidence_vault` schema predated the code | Evidence inserts 500'd in production |
| 8 | Render deploying a stale branch | Fixes appeared to have no effect |
| 9 | Webhook payload had no `content`/`text` field | Discord and Slack would have rejected every alert |
| 10 | Non-deterministic `DISTINCT ON` | Unpredictable dashboard positions |

Items 2 and 9 were introduced during this work and caught before reaching a
demo. Items 3 and 5 share a root cause: PowerShell's `>`, `Out-File` and
`Set-Content` default to UTF-16 or add a BOM.

---

## 5. Security work

**Authentication.** API key via `X-Incog-Key`, compared in constant time so a
wrong key cannot be recovered by timing. The legacy `X-Agent-Key` header is
still accepted so clients keep working across the rename.

**Secret rotation (step 4c).** An early commit contained a `.env`; removing the
file did not remove it from history. Rotated at the providers so the leaked
values are dead:

| Secret | Status |
|---|---|
| `EVIDENCE_AES_KEY` | Rotated, verified decrypting in production |
| `INCOG_API_KEY` | Rotated, old key verified returning 403 |
| Neon `DATABASE_URL` | Rotated, superseded passwords verified rejected |
| Discord webhook | Regenerated after the status-endpoint leak |
| `ENCRYPTION_KEY`, `AGENT_SECRET_KEY` | Retired and deleted |
| Twilio | Never in git history — the leaked `.env` held exactly three values |

Old credentials were verified dead by attempting to use them, not assumed.

**Data minimisation.** Trusted contacts are never written to disk. Evidence is
stored only as ciphertext. Phone numbers are redacted in logs.

---

## 6. Testing

168 tests, running without a database — the session is stubbed, and the test
configuration is pinned so the suite can never reach the live database or send
real messages.

| Suite | Covers |
|---|---|
| `test_evidence_crypto.py` | Wire format, known-answer vector, tampering, wrong keys, truncation |
| `test_api.py` | Auth, validation, evidence handling, dashboard |
| `test_trusted_contact.py` | Per-user contacts, multi-contact, redaction, dedupe |
| `test_dispatch_channel.py` | SMS vs WhatsApp address formatting |
| `test_webhook_payload.py` | Discord/Slack payload compatibility |
| `test_schemas.py` | Coordinate bounds, identifier charset |

The tests deliberately encode *why*, not just *what* — the empty-contact case,
the non-retryable 400, and the plaintext-never-stored assertion all guard
decisions that would otherwise be quietly undone.

---

## 7. Integration contracts

**With the security module (Gagan).** Byte-level agreement on the AES-256-GCM
format, verified against a fixed vector. Uses a pre-shared key, agreed as an
MVP compromise — the alternative, a per-emergency random key, could not be
shared with the backend.

**With the mobile client (Aarush).** `POST /api/v1/sos` accepts optional
trusted contacts, either as a `contacts` array or legacy single fields, so
older builds keep working. The client also texts contacts directly from the
device; the backend reports which of those sends succeeded, making the
redundancy visible to responders.

**With the XAI engine (Lipika).** `AIResult` carries `SHAP`/`LIME` maps inside
the evidence package, so a server-side explainer has a natural seam. Not yet
implemented.

---

## 8. Deployment

Render (free tier) + Neon PostgreSQL with PostGIS. Environment-driven
configuration; no secrets in the repository.

Operational notes worth carrying forward:

- Free-tier cold start is **35–50 seconds**; the client uses a 60s timeout
- `create_all()` does not alter existing tables — schema changes need the
  hand-run migration in `migrations/`
- `run_migration.py` and `tools/purge_device.py` both print the target host
  before acting, after a migration was once applied to the wrong database

---

## 9. Known limitations

Recorded honestly rather than omitted.

1. **Location is stored in plaintext.** `emergency_signals.location` must be a
   real PostGIS geometry for the map and spatial queries to work. The copy
   inside the evidence blob is encrypted; this one is not. "Evidence is
   encrypted at rest" is accurate; "her location is encrypted" would not be.
2. **No PostGIS integration test.** The suite stubs the database, so the SQL
   itself — spatial insert, window query, `BYTEA` round-trip — is exercised
   only in production.
3. **Twilio is unusable on a trial account.** Free-form bodies are rejected on
   both SMS (`572006`) and WhatsApp (`21654`); trial accounts must use
   predefined templates, which cannot carry coordinates. The dispatch code is
   complete and tested and activates on a paid account with no change.
4. **No alert retry or delivery confirmation.** A failed send is logged, not
   retried. A message queue is the obvious next step.
5. **No rate limiting.** A device could spam signals.
6. **Pre-shared evidence key.** One key for all users, shipped in the APK and
   therefore extractable. Acceptable for the MVP; a wrapped per-session key is
   the correct design.
7. **Secrets remain in git history.** Rotating at the providers is what made
   them harmless; scrubbing history rewrites every SHA and needs whole-team
   coordination.
8. **`.env.example` is stale** — placeholders only, so nothing leaks, but it
   lists retired variables.

---

## 10. Commit history

19 backend commits, 13 Aug – 12 Sep 2026. Notable:

| Date | Commit | |
|---|---|---|
| 12 Sep | `1b0016f` | Record secret-rotation status |
| 11 Sep | `ff0c86c` | Alert every trusted contact, not just the first |
| 08 Sep | `c3fdc93` | Report whether the device already texted the contact |
| 08 Sep | `a59e294` | Alert the user's own trusted contact |
| 04 Sep | `9e20cf7` | Stop leaking the webhook URL; add purge tool |
| 04 Sep | `951e65f` | Make webhook payload work with Discord/Slack |
| 04 Sep | `fd97859` | Twilio WhatsApp channel |
| 04 Sep | `a22d773` | Restore missing dependencies; idempotent migration |
| 03 Sep | `30e2fa1` | Make evidence rejections non-retryable |
| 03 Sep | `eded090` | AES-256-GCM, de-militarise, encrypt at rest |
