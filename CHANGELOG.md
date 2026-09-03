# Backend Changelog

## Unreleased — Decisions 1 & 4 (issue #4)

### Evidence encryption (Decision 1)

- Replaced Fernet with **AES-256-GCM**, matching `CryptoManager.kt`'s wire
  format: `[12-byte IV][ciphertext‖16-byte GCM tag]`, base64 in
  `encrypted_evidence`, plaintext being `EvidencePackage` JSON.
- Extracted `evidence_crypto.py`, free of DB and web imports so the format is
  unit-testable on its own.
- Distinct failure modes: tampered/wrong-key → `EvidenceAuthError`, malformed →
  `EvidenceFormatError`, both surfacing as 400 rather than 500.
- Key comes from `EVIDENCE_AES_KEY` (base64 of 32 bytes) and is validated at
  startup. If unset, evidence is refused with 503 while SOS and alerting keep
  working — losing the evidence key must not take the life-critical path down.

> **Blocked:** `SecurityOrchestrator.kt` still generates a fresh random key per
> emergency (`generate256BitKey()`) and shares it with nobody. Evidence cannot
> decrypt end-to-end until it loads the pre-shared key instead. The backend side
> is complete and tested against the format.

### De-militarisation (Decision 4)

- Removed the hardcoded London `RESTRICTED_ZONE_WKT` polygon and the inverted
  geofence that *revoked* a user's stealth on entering it. `is_stealth_active`
  is now stored exactly as the client reports it.
- Reframed vocabulary throughout: agent → user, "restricted enemy zone" and
  "compromised" gone from alerts, logs, the dashboard and the simulator.
- Dashboard retitled to "Incog Safety Dashboard", danger-zone polygon removed,
  now frames the actual data instead of centring on London. Fallback centre is
  configurable and defaults to BMSCE.
- `tracker.py`: "Agent-X-Delta" → configurable `DEVICE_ID`, "intercepted intel"
  → a realistic simulated `EvidencePackage`.

### Evidence encrypted at rest (Decision 4)

- `evidence_vault.decrypted_text` **removed**. The backend now decrypts in
  memory only, to verify the GCM tag and lift `sessionId`/`timestamp` for
  triage, and persists the **original ciphertext** in a new `ciphertext BYTEA`.
- Requires `migrations/001_evidence_encrypted_at_rest.sql`, which **deletes
  existing evidence rows** — they hold plaintext that cannot be converted back.

### Fixes

- **`/map` was broken.** Adding auth to `GET /api/v1/sos` left the dashboard's
  `fetch()` sending no key, so it silently 403'd and rendered nothing. It now
  asks for a key and sends it as a header, held in `sessionStorage` — never in
  the URL, where it would reach browser history and access logs.
- API key comparison is now constant-time (`secrets.compare_digest`).
- Replaced deprecated `datetime.utcnow()`, Pydantic v1 `@validator`, and
  FastAPI `@app.on_event` with their current equivalents.
- `create_all()` moved out of import into the lifespan handler, so the module
  can be imported without a reachable database.

### Auth rename

- `X-Incog-Key` is the current header; `X-Agent-Key` still works but logs a
  deprecation warning.
- `INCOG_API_KEY` is the current variable, falling back to `AGENT_SECRET_KEY`.

### Tests

- 80 tests, none requiring a database (`pytest tests/ -q`).
- Includes a fixed known-answer vector and a 28-byte-overhead assertion pinning
  the Kotlin↔Python format, plus coverage of tampering, wrong keys, truncation,
  the dual auth headers, and that stored evidence contains no plaintext.

### Docs

- `ARCHITECTURE.md`, `DISPATCHER_SETUP.md` and `DISPATCHER_QUICKSTART.md`
  replaced by a single accurate `BACKEND.md`. They described the Fernet +
  geofence design and were misleading.

---

## Earlier

- SOS dispatcher: SMS via Twilio and webhook delivery, dispatched off-thread.
- FastAPI + PostgreSQL/PostGIS signal ingestion with a Leaflet dashboard.
- Connection pooling; `ROW_NUMBER()` replacing a non-deterministic
  `DISTINCT ON` for latest-position-per-device.
