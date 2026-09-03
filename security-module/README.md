# Incog Security Module (Phases 7-10)

On-device evidence packaging, AES-256-GCM encryption, fragmentation, and LSB
steganography. Kotlin/Android, package `com.incog.incogsecuritycore`.

## Pipeline

| Phase | Component | What it does |
|-------|-----------|--------------|
| 7 | `EvidencePackage` | Bundles sessionId, timestamp, GPS, audio (Base64), feature vector and the AI/XAI result into one JSON container |
| 8 | `CryptoManager` | AES-256-GCM over the packaged JSON; blob is `[12-byte IV][ciphertext+tag]` |
| 9 | `FragmentationManager` | Slices the blob into fragments, each tagged `[index:2][total:2]` |
| 10 | `SteganographyEngine` | Hides one fragment per carrier image in the pixel LSBs |

`SecurityOrchestrator` drives all four:

- `packageAndEncrypt(...)` -> Phase 7+8, returns the **encrypted blob uploaded to
  the backend over TLS**.
- `hideAtRest(blob, carriers)` -> Phase 9+10, returns stego images for
  **on-device at-rest hiding only** (not the network transport).
- `processEmergencyTrigger(...)` -> both, returning `PipelineResult`.

All three are `suspend` and run the CPU-bound pixel work on `Dispatchers.Default`;
never call the stego/extract helpers directly from the main thread.

`SecurityExtractor` is the inverse (extract from pixels, decrypt) and is used by
the round-trip tests.

## Configuring the shared evidence key

Per team DECISION 1 the app and the backend share one AES-256 key loaded from
config on each side. **The real key is never committed.** Supply it in
`security-module/local.properties` (gitignored, the Android analogue of the
backend's `.env`):

```properties
incog.evidenceKeyBase64=<base64 of 32 random bytes>
```

...or through the `INCOG_EVIDENCE_KEY_BASE64` environment variable for CI.
Generate one with:

```bash
openssl rand -base64 32
```

A clean checkout with neither set falls back to a clearly-marked placeholder so
the project still builds and tests pass. `CryptoManager` logs a warning when the
placeholder is in use, and anything encrypted under it will **not** decrypt on
the backend.

> Known limitation: a single shared key compiled into the APK is recoverable by
> anyone who has the APK, and one leak affects every user. A per-session key
> wrapped with a backend public key would remove that exposure without changing
> the wire format much - worth revisiting after the MVP.

## Running the tests

```bash
cd security-module
./gradlew test
```

Tests run on the JVM via Robolectric (no emulator needed) and cover the full
Phase 7 -> 10 round trip, out-of-order fragment reassembly, carrier capacity
guards, and shared-key loading. The round-trip test writes its stego images to
`app/build/test-results/stego/` for visual inspection.

The build pins a JDK 17 toolchain: Robolectric 4.13 cannot instrument class
files from very new JDKs (e.g. JDK 25).
