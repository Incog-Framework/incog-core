# Security Module — Phases 7–10 (Gagan)

On-device evidence packaging, AES-256-GCM encryption, fragmentation, and LSB steganography.
Kotlin/Android, package `com.incog.incogsecuritycore`.

**Status: complete, merged, integrated, and verified.** Remaining work is configuration and one
stale doc entry — no outstanding code.

---

## 1. Where the code lives

Originally a standalone Gradle project at `security-module/`. Aarush's integration commit
`ae90a75` (PR #11) moved it verbatim into the app as an Android **library module**:

```
mobile-client/security/
├── build.gradle.kts                                   # key injection via BuildConfig
└── src/
    ├── main/java/com/incog/incogsecuritycore/
    │   ├── AIResult.kt                 # Lipika's xai_output.json contract, Kotlin-side
    │   ├── EvidencePackage.kt          # Phase 7 container (+ GPSData, FeatureVector)
    │   ├── CryptoManager.kt            # Phase 8 AES-256-GCM + shared-key loading
    │   ├── FragmentationManager.kt     # Phase 9 slicing + ordered reassembly
    │   ├── SteganographyEngine.kt      # Phase 10 LSB embed
    │   ├── SecurityExtractor.kt        # inverse: extract + decrypt
    │   └── SecurityOrchestrator.kt     # drives Phases 7→10
    └── test/java/com/incog/incogsecuritycore/
        ├── Phase7To10PipelineTest.kt
        ├── FragmentationManagerTest.kt
        ├── SteganographyCapacityTest.kt
        └── CryptoManagerKeyTest.kt
```

The standalone `security-module/` directory no longer exists on `main`. Any local copy is a stale
leftover.

---

## 2. What each phase does

| Phase | Component | Behaviour |
|---|---|---|
| 7 | `EvidencePackage` | Bundles `sessionId`, `timestamp`, GPS, audio (Base64), the 5-feature vector, and Lipika's AI/XAI result into one JSON container |
| 8 | `CryptoManager` | AES-256-GCM over that JSON. Blob = `[12-byte IV][ciphertext + 16-byte tag]` |
| 9 | `FragmentationManager` | Slices the blob into fragments, each tagged `[index:2][total:2]` |
| 10 | `SteganographyEngine` | Hides one fragment per carrier image in pixel LSBs (1 bit/pixel, 4-byte length prefix) |

`SecurityOrchestrator` exposes three `suspend` entry points, all running CPU-bound work on
`Dispatchers.Default`:

- `packageAndEncrypt(...)` → Phases 7+8, returns the **encrypted blob uploaded to the backend**
- `hideAtRest(blob, carriers)` → Phases 9+10, returns stego images for **on-device at-rest hiding only**
- `processEmergencyTrigger(..., embedAtRest)` → runs both, returns `PipelineResult(sessionId, encryptedBlob, stegoImages)`

Returns `null` and discards silently when `aiResult.emergencyStatus` is false, per the Phase 6→7
handoff rule.

---

## 3. Decision 1 — implemented

**Agreed:** AES-256-GCM on both sides; pre-shared MVP key; upload the encrypted blob directly over
TLS; steganography stays as on-device at-rest hiding, not the network format.

**a) Blob exposed for direct upload.** The orchestrator was split so the encrypted blob is
available without going through stego. `embedAtRest = false` skips the pixel work entirely when the
device only needs to upload.

**b) Shared key replaces the per-session random key.** `CryptoManager.generate256BitKey()` was
removed (zero references remain in any `.kt` file) and replaced by:

- `loadSharedKey()` — reads `BuildConfig.EVIDENCE_KEY_BASE64`
- `parseSharedKey(base64Key, isPlaceholder)` — validates exactly 32 bytes of Base64, with explicit errors

Live wiring, verified in `main`:

```
mobile-client/security/src/main/java/com/incog/incogsecuritycore/SecurityOrchestrator.kt:81
    CryptoManager.encrypt(rawPayload, CryptoManager.loadSharedKey())
```

No key value exists anywhere in the repo. A clean checkout falls back to a clearly-named
placeholder so the project still builds; `CryptoManager` logs a warning when it's in use, and
`BuildConfig.EVIDENCE_KEY_IS_PLACEHOLDER` exposes that state for verification.

`PipelineResult` deliberately carries **no** `SecretKey` — there is no per-session secret to pass
around any more.

---

## 4. Code-review defects — all three fixed

1. **Silent data loss on carrier overflow.** `embedData` previously truncated when it ran out of
   pixels, producing a stego image that could never be decrypted, surfacing only as a GCM failure
   much later. Now `require(totalBits <= pixels.size)` with an actionable message, plus
   `maxPayloadBytes(bitmap)`. Extraction rejects images too small for the length prefix and payload
   sizes that are negative or exceed the carrier (overflow-safe via `Long`). `hideAtRest`
   pre-checks the carrier pool against the chunk size and fails fast.

2. **Fragments carried no ordering.** Every fragment now has a 4-byte `[index:2][total:2]` header.
   `reassembleData` is order-independent and rejects duplicates, gaps (naming the missing indices),
   mismatched totals, and malformed fragments — so multi-image or out-of-order delivery reassembles
   correctly instead of silently corrupting the blob.

3. **ANR risk from per-pixel access.** Per-pixel `getPixel`/`setPixel` replaced with single-pass
   `getPixels()`/`setPixels()` (zero per-pixel calls remain). Orchestrator entry points are
   `suspend` on `Dispatchers.Default`.

Also removed the duplicated AES-GCM implementation in `SecurityExtractor.decryptPayload`, which now
delegates to `CryptoManager.decrypt` so the two directions can't drift apart.

---

## 5. Tests — 32 passing

Robolectric on the JVM, no emulator required.

```bash
cd mobile-client && ./gradlew :security:test
```

| Suite | Tests | Covers |
|---|---|---|
| `Phase7To10PipelineTest` | 6 | Full 7→10 round trip; blob decrypts with the config key; blob produced with `embedAtRest = false`; shuffled stego images still reassemble; non-emergency discarded silently; undersized carrier pool rejected |
| `FragmentationManagerTest` | 11 | Header contents; in-order and shuffled reassembly; missing/duplicate/foreign/malformed fragment rejection |
| `SteganographyCapacityTest` | 7 | Capacity math; exact-capacity round trip; oversized embed rejected; non-carrier extract rejected; only LSBs disturbed |
| `CryptoManagerKeyTest` | 7 | Key is 256-bit AES; stable across calls; wrong-length and blank keys rejected; wrong key fails GCM auth |
| `ExampleUnitTest` | 1 | Android template stub |

**Last verified run:** 4 Sep 2026, 32 tests / 0 failures / 0 skipped, via
`./gradlew test --rerun-tasks` (full recompile, build cache bypassed) with the **real shared key**
loaded — confirmed by `EVIDENCE_KEY_IS_PLACEHOLDER = false` in the generated `BuildConfig.java`.

The round-trip test writes its stego images to `build/test-results/stego/` for visual inspection.

---

## 6. The backend seam (for Chirag)

The app uploads the encrypted blob over TLS. **No steganography or fragmentation on the network
path** — the server needs no stego extraction and no fragment reassembly.

**Cipher:** AES-256-GCM, 128-bit tag, no AAD.
**Blob layout:** `[12-byte IV][ciphertext || 16-byte GCM tag]`, Base64 in `encrypted_evidence`.

Java appends the tag to the ciphertext, which is exactly what Python's `AESGCM.decrypt` expects:

```python
nonce, ct = blob[:12], blob[12:]
evidence = json.loads(AESGCM(key).decrypt(nonce, ct, None))
```

**Decrypted plaintext** is UTF-8 JSON:

```json
{
  "sessionId": "...", "timestamp": 0,
  "gps": {"lat": 0.0, "lng": 0.0},
  "audioBase64": "...",
  "featureVector": {"peakAcceleration":0.0,"motionVariance":0.0,"audioEnergy":0.0,
                    "gpsVelocity":0.0,"possibleFall":false},
  "aiResult": {"SessionID":"...","TimestampMs":0,"Prediction":"Emergency","Confidence":0.0,
               "EmergencyStatus":true,"DecisionThreshold":0.8,"SHAP":{},"LIME":{}}
}
```

`aiResult` keys are PascalCase (mirroring Lipika's `xai_output.json` field-for-field); everything
else is camelCase. SHAP/LIME arrive empty from the device — they run server-side/async per
Decision 2.

Backend counterpart already exists in `main`: `evidence_crypto.py` and
`tests/test_evidence_crypto.py`.

---

## 7. Configuration required

Three values, all per-machine in **`mobile-client/local.properties`** (gitignored via
`mobile-client/.gitignore:15`). **Never committed.**

| Property | Consumed by | BuildConfig field | Env var |
|---|---|---|---|
| `incog.evidenceKeyBase64` | `security/build.gradle.kts` | `EVIDENCE_KEY_BASE64` | `INCOG_EVIDENCE_KEY_BASE64` |
| `incog.backendUrl` | `app/build.gradle.kts:20` | `BACKEND_SOS_URL` | `INCOG_BACKEND_URL` |
| `incog.agentKey` | `app/build.gradle.kts:21` | `AGENT_KEY` | `INCOG_AGENT_KEY` |

Generate a key with `openssl rand -base64 32`. Verify the real one loaded:

```bash
grep EVIDENCE_KEY_IS_PLACEHOLDER \
  mobile-client/security/build/generated/source/buildConfig/debug/com/incog/incogsecuritycore/BuildConfig.java
```

Must read `false`. Defaults are `https://example.invalid/api/v1/sos` and
`PLACEHOLDER-AGENT-KEY` — uploads silently go nowhere until these are set.

The evidence key is coordinated with the backend out-of-band and must match byte-for-byte on both
sides. Compare by fingerprint rather than re-sending the key:

```bash
python3 -c "import base64,hashlib;print(hashlib.sha256(base64.b64decode('<key>')).hexdigest()[:16])"
```

---

## 8. History

| Ref | What |
|---|---|
| `e761d02` | Initial Phase 7–10 pipeline: AES-256-GCM, LSB stego, extraction/decryption |
| `1849975` | Wired Lipika's real `AIResult` into the pipeline; replaced mock data; added Robolectric round-trip test |
| `67e23e4` | **PR #8** — Decision 1 (shared key + uploadable blob) and the three code-review bug fixes. Closes issue #3 |
| `ae90a75` | **PR #11** (Aarush) — moved the module into `mobile-client/security` as a library, wired capture → AI → encrypt → upload |

`67e23e4` is an ancestor of `origin/main`; the integration preserved the source and tests verbatim
(100% renames).

---

## 9. Known limitations

- **Shared key is extractable from the APK.** A single pre-shared key compiled into the app is
  recoverable by anyone holding the APK, and one leak affects every user. It protects evidence in
  transit and at rest, but not against an attacker with the app. The stretch design — a per-session
  key wrapped with a backend public key — removes that exposure without changing the wire format
  much. Accepted for MVP.
- **Key rotation is a rebuild.** Changing the key means editing `local.properties` and rebuilding.
- **Carrier images are synthetic in tests.** Real built-in theme PNGs as `R.drawable.*` assets are
  not wired yet; tests generate solid-colour bitmaps.
- **Stego is at-rest only.** Nothing extracts fragments from stego images server-side. That was a
  deliberate Decision 1 scope cut.
- **Audio is whatever the app flushes.** The module Base64-encodes the bytes it's handed;
  `AudioBufferCollector.snapshotPcm()` on the capture side decides what those are.

---

## 10. Known doc inconsistency

`BACKEND.md:23` still lists this as an open action item assigned to Gagan:

> `SecurityOrchestrator.kt` still calls `CryptoManager.generate256BitKey()`, minting a fresh random
> key per emergency that is shared with nobody.

**This is stale.** It was fixed in PR #8 and merged. `generate256BitKey` no longer exists in any
`.kt` file — the only remaining occurrences are in `BACKEND.md` (lines 23, 186) and
`CHANGELOG.md:19`. Those three references should be updated so nobody plans around them.
