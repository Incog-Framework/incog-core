# Integration runbook — real SensorPackets into the AI pipeline

Everything below already works. Nothing needs code changes when the captures
arrive; you point the pipeline at files and run.

## The one interface

`phase4/sensor_packet_adapter.py` is the **only** module that knows Aarush's
JSON field names. Everything downstream sees a plain feature vector plus a
session context, so a schema change on his side is a one-file change here.
`phase4/test_adapter_is_sole_interface.py` enforces that by scanning source —
if a second module starts reading raw packet fields, the test fails.

## How a real packet flows

```
Aarush: GhostStateService.buildSensorPacket()   every 2 s
   │
   │  exported as JSON  ── the missing link, see "Blocker" below
   ▼
data/real_packets/{normal,emergency}/*.json
   │
   ▼
phase4/process_sensor_packet.py            --packet PATH
   │   └── sensor_packet_adapter.load_packet()      read + schema-validate
   │   └── sensor_packet_adapter.extract_from_sensor_packet()
   │                                                 5 features + session
   ├──▶ data/feature_vector.csv        ← identical schema to the CSV path
   └──▶ data/session_context.json      ← SessionID, TimestampMs, SourcePacket
   │
   ▼
phase5/tflite_predict.py     emergency_model.tflite → Confidence, ConfidenceRaw
   ▼
phase6/decision_engine.py    EmergencyStatus = ConfidenceRaw >= 0.80
   │                         + SessionID, TimestampMs
   ▼
xai/xai_pipeline.py          SHAP + LIME over the same .tflite
   │                         + FeatureValues, TopContributingFeatures,
   │                           Explanation, SessionID, TimestampMs
   ▼
phase7/  intervention.json · evidence_manifest.json · final_system_report.json
         all carrying SessionID + SessionTimestampMs
```

From Phase 5 onward **nothing knows or cares** which Phase 4 entry point ran.
The model, the 0.80 threshold, and the XAI are byte-identical in both modes —
pinned by `phase7/test_session_propagation.py`.

## Switching input modes

| | command | session context |
|---|---|---|
| Development | `python run_ai_pipeline.py --source csv` | none (correctly) |
| Integration | `python run_ai_pipeline.py --source packet` | yes |
| A real capture | `python run_ai_pipeline.py --packet PATH` | yes |

Packet file resolution: `--packet PATH` → `$INCOG_SENSOR_PACKET` →
`data/sensor_packet.json`.

The CSV path actively **deletes** a stale `session_context.json`, so a
previous session can never get attached to a CSV-sourced decision.

## When Aarush delivers captures

**1. Drop them in.**

```
data/real_packets/normal/*.json        everyday activity
data/real_packets/emergency/*.json     staged incidents
```

One `SensorPacket` object per file, or an array of them. The folder name is
the label. Elsewhere on disk? `set INCOG_REAL_PACKETS=D:\captures` instead.

**2. Check what arrived — before trusting any of it.**

```bash
python phase4/test_real_packets.py
```

Validates every packet against the schema and reports diagnostics: estimated
sample rate vs the expected ~50 Hz, sample counts vs the 1000-sample bound,
timestamp monotonicity, feature ranges, label balance, and whether
`AudioEnergy` is flat zero across every packet — which would mean the mic
permission was denied and the model is really running on four live features.

Diagnostics print as notes rather than failures: only you can tell an odd
recording from a bug.

**3. Run one end to end.**

```bash
python run_ai_pipeline.py --packet data/real_packets/emergency/fall_01.json
```

Then read `data/xai_output.json` — it carries the decision, both explanations,
the feature values, and the SessionID.

**4. Run the full suite.**

```bash
python run_tests.py
```

`test_real_packets.py` stops skipping and starts checking the real files.

**5. Only then, consider training.**

```bash
python phase5/dataset_adapters.py                          # confirm visibility
python phase5/train_tflite_model.py --dataset sensor_packets
```

`load_sensor_packets()` reads `data/raw/sensor_packets/{normal,emergency}/`.
Symlink or copy your captures there when you want them used for training as
well as validation — the split is deliberate, so validating a capture is not
the same act as training on it.

Training still refuses to overwrite `emergency_model.tflite` without
`--write-model`, because that file is byte-identical to the asset the phone
ships. See "If the model is retrained" in `CLAUDE.md`.

## Blocker — Aarush's side, not yours

`SensorPacket` is a **plain Kotlin data class**: no `@Serializable`, no
Gson/Moshi, no serialization dependency in `mobile-client/app/build.gradle.kts`,
and nothing currently writes it to JSON. On-device the object goes straight
into `EmergencyClassifier.classify(packet)`.

So **there is no producer of SensorPacket JSON yet.** The field names this
adapter expects are read off his Kotlin property names — correct for
kotlinx.serialization, Gson and Moshi at their defaults, and asserted against
his actual source by `phase4/test_sensor_packet_contract.py`. But the
round-trip is unverified until one real capture exists.

What to ask him for:

1. Add `kotlinx-serialization-json`, mark `SensorPacket`, `Vec3Reading` and
   `LocationReading` `@Serializable`, and write
   `Json.encodeToString(packet)` to a file during Ghost State — he already
   builds the packet every 2 s and only logs it today.
2. **Keep the default property names.** No `@SerialName` renames — the field
   names *are* the contract.
3. Capture negatives generously. The `<5%` false-positive target is a claim
   about ordinary life, so it needs hours of ordinary life, not just staged
   incidents.

One capture file is enough to close the round-trip question. Send it through
step 2 above and the answer is immediate.
