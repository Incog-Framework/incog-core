# xai-engine — Lipika's scope (Phases 4–6 + XAI)

Sensor feature extraction, TFLite emergency detection, the Decision Engine,
and SHAP/LIME explainability. GitHub issue #5.

> This file was referenced by `phase4/sensor_packet_adapter.py` and by
> Aarush's Kotlin comments long before it existed. It now does.

## Scope boundary

Modify **only** `xai-engine/`. `mobile-client`, `security-module`,
`c2-backend` and `security-vault` are read-only from here — read them for
integration, never edit them.

## Where the work actually runs

Python in this folder **trains and explains**. It does not run in production.

```
Android                                    Server / async
───────                                    ──────────────
SensorPacket  (Aarush, Phase 3)
     │
Kotlin FeatureExtractor  ─┐
     │                    ├─ ports of phase4/*.py
TFLite EmergencyClassifier┘
     │
Decision Engine (>= 0.80)
     │
Evidence ──────────────────────────────▶ Backend (Chirag)
                                              │
                                         SHAP / LIME  ← xai/
                                              │
                                    human-readable explanation
```

**Python and Kotlin feature maths must be identical.** That is enforced by
`phase4/test_kotlin_parity.py` and `phase4/test_contract_sync.py`, not by
comments.

## The five features

Order is fixed and load-bearing — the model takes a flat `[1,5]` tensor:

```
[PeakAcceleration, MotionVariance, AudioEnergy, GPSVelocity, PossibleFall]
```

| Feature | Definition | Notes |
|---|---|---|
| `PeakAcceleration` | `max(‖(x,y,z)‖)` over `accelSamples` | m/s², gravity included |
| `MotionVariance` | **sample** variance, `ddof=1`, of that magnitude series | `0.0` when < 2 samples |
| `AudioEnergy` | `clamp(audioRmsEnergy / 32768, 0, 1)` | see the audio caveat below |
| `GPSVelocity` | `latestLocation.speedMps`, else `0.0` | packet carries only the latest fix |
| `PossibleFall` | `PeakAcceleration > 15` | on the **unrounded** peak; `>`, not `>=` |

Encoded to the model as `1.0/0.0` for the boolean. Normalization is **baked
into the `.tflite`** as a Keras `Normalization` layer, so raw values go in —
do not pre-normalize on either side.

`gyroSamples` / `latestGyro` are accepted and deliberately unused: the trained
model never included gyroscope data.

## Thresholds

| Threshold | Value | Where |
|---|---|---|
| Fall | `> 15` m/s² | `feature_extraction.py`, `FeatureExtractor.kt` |
| Classification | `>= 0.50` → "Emergency" | `tflite_predict.py`, `EmergencyClassifier.kt` |
| **Dispatch** | `>= 0.80` → `EmergencyStatus` | `decision_engine.py`, `EmergencyClassifier.kt` |

Python writes it as `Prediction == "Emergency" and confidence >= 0.80`, which
reduces to Kotlin's `confidence >= 0.80` because `Prediction == "Emergency"`
*is* `confidence >= 0.50`. The two-stage form is kept so the classification /
dispatch split stays visible.

> **Threshold on `ConfidenceRaw`, never on `Confidence`.** `Confidence` is
> rounded to 4 dp for display. Thresholding the rounded value promoted a raw
> confidence in `[0.79995, 0.80)` to `EmergencyStatus=true` while the phone,
> comparing the raw float, returned false for the same packet. Pinned by
> `phase6/test_decision_threshold.py`.

## Cross-language contract

Two generated artifacts keep the ports honest:

- `data/model_contract.json` — constants, model IO shape, model SHA-256
- `data/golden_feature_vectors.json` — packet → expected features, 7 cases

Regenerate after any change to features, thresholds, or the model:

```bash
python generate_contract_fixtures.py
```

`phase4/test_contract_sync.py` asserts every duplicated constant — Python
*and* Kotlin — still matches the contract, and that the `.tflite` the phone
ships is byte-identical to the one that was trained and explained. It skips
the Kotlin half gracefully when `mobile-client/` is not checked out.

## Running things

```bash
python run_ai_pipeline.py                    # real SensorPacket path (default)
python run_ai_pipeline.py --packet PATH      # a specific real capture
python run_ai_pipeline.py --source csv       # CSV prototype path
python run_tests.py                          # everything

python phase4/test_real_packets.py           # validate real captures
python phase5/fetch_datasets.py --list       # public corpora
python phase5/dataset_adapters.py            # what real data is present
python phase5/evaluate_real_fpr.py --dataset uci_har,shimfall
python phase5/validate_audio_normalization.py
python -m xai.explainer_service --benchmark  # backend-facing explainer
```

Phase 4 has two entry points feeding one downstream pipeline:

- `process_sensor_packet.py` — real `SensorPacket` JSON; **emits SessionID /
  TimestampMs**, which propagate all the way to the Phase 7 evidence manifest
  and system report
- `sensor_processing.py` — CSV prototype; no session concept, and it deletes
  any stale `session_context.json` so a previous session is never attached to
  a CSV-sourced decision

Packet file resolution: `--packet PATH` → `$INCOG_SENSOR_PACKET` →
`data/sensor_packet.json`. See **INTEGRATION.md** for the full runbook.

## The adapter is the only Android → AI interface

`phase4/sensor_packet_adapter.py` is the single module that knows Aarush's
JSON field names — it owns `PACKET_SCHEMA`, validation, loading, feature
extraction and session context. A schema change on his side is a one-file
change here.

`phase4/test_adapter_is_sole_interface.py` enforces this by scanning source,
and `phase4/test_sensor_packet_contract.py` parses his actual Kotlin data
classes and asserts `PACKET_SCHEMA` still matches them field-for-field,
including nullability.

> **No JSON producer exists yet.** `SensorPacket` is a plain Kotlin data class
> — no `@Serializable`, no serialization dependency, nothing writes it to disk.
> The expected field names are inferred from his property names (correct for
> kotlinx/Gson/Moshi defaults) and checked against his source, but the
> round-trip is unverified until one real capture arrives. See INTEGRATION.md.

## Handoff out: `data/xai_output.json`

```
Prediction · Confidence · EmergencyStatus · DecisionThreshold · SHAP · LIME
  └─ mirrored by security-module/AIResult.kt — never rename or drop these
SessionID · TimestampMs          (only on the real SensorPacket path)
FeatureValues                    (what was actually scored)
TopContributingFeatures          (ranked by |SHAP|, with values + direction)
Explanation                      (Title / Message / Reasons)
```

The last three are additive for Chirag's backend. If `AIResult.kt` is ever
used to *decode* this file it will need `Json { ignoreUnknownKeys = true }` —
right now it is only ever constructed on-device, so nothing breaks.

SHAP and LIME explain the **`.tflite`**, not the Keras source model
(`xai/tflite_utils.py`), so explanations describe the artifact that actually
ran. They stay server-side — they are far too slow for the phone.

## Open items

**Audio calibration is unvalidated on real audio.** The arithmetic is proven
(`validate_audio_normalization.py`, Level 1) but nobody has measured where
real pocket audio lands in `[0,1]`. The training data assumes 0.04–0.25
normal and 0.55–0.91 emergency. If real audio all lands below ~0.05 the model
is effectively running on four features. Needs a device session.

**The model is trained on 30 synthetic rows, and it does NOT meet the <5%
false-positive target on real activity.** Measured over 10,824 real windows
from 65 subjects (UCI HAR + ShimFall): false-positive rate 0.6%-39.8%
depending on the assumed audio/GPS values, and it fires on 40% of
walking-downstairs windows and 100% of jumping. The `PeakAcceleration > 15`
fall rule identifies movement, not falls - it trips on 39.8% of ordinary
activity. Full write-up in **REAL_DATA_FINDINGS.md**; reproduce with
`python phase5/evaluate_real_fpr.py --dataset uci_har,shimfall`.

The model was deliberately NOT retrained: fixing this needs positives paired
with real audio and GPS, and going motion-only would break the locked
5-feature tensor contract with `FeatureVector.toModelInput()`. Never quote the
synthetic 100% metrics as production performance.

**Float32 / rounding drift.** Kotlin stores samples as `Float` and rounds
half-away-from-zero; Python uses float64 and banker's rounding. Measured
across 20 000 random packets: features differ by at most one 4-decimal step
(1e-4), `PossibleFall` never disagrees, and 1e-4 perturbations flipped the
0.80 decision 0 times in 30 000 trials. Bounded and asserted, not assumed.

## If the model is retrained

`data/emergency_model.tflite` is byte-identical to
`mobile-client/app/src/main/assets/emergency_model.tflite`. Retraining breaks
that, so `train_tflite_model.py` only writes the model with `--write-model`.
After it does:

1. `python generate_contract_fixtures.py` — refresh hash + golden vectors
2. **Ask Aarush to re-vendor the new `.tflite`** — the phone keeps running the
   old model until he does, and nothing else will tell you
3. `python run_ai_pipeline.py --source packet` — regenerate SHAP/LIME
