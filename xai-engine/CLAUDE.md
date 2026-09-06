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
| `AudioEnergy` | `clamp((20·log10(max(rms,1)/32768) − AUDIO_FLOOR_DB) / (AUDIO_CEIL_DB − AUDIO_FLOOR_DB), 0, 1)` | dB scale, revised 2026-09-06 — see below |
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

> **2026-09-06: retrained twice more.** First to fix a safety-critical GPS
> defect Aarush caught - `load_fusion()`'s GPS assignment now samples
> `GPSVelocity` uniformly (0-3 m/s) independent of Activity and of the
> Emergency label, instead of the 2026-09-05 version's activity-keyed
> heuristic that put every fall at GPS=0. Second to move AudioEnergy from a
> dead linear scale to a dB scale fitted against real RAVDESS speech, also
> per Aarush's request - see the AudioEnergy item below; this is a lockstep
> change and Kotlin has not mirrored it yet. Full method, numbers and honesty
> caveats: **MODEL_CARD.md**. The items below are updated to match;
> `REAL_DATA_FINDINGS.md` keeps every older write-up for the before/after
> comparison.

**AudioEnergy is now a dB scale, fitted against real RAVDESS speech
(2026-09-06).** The old linear `clamp(audioRmsEnergy / 32768, 0, 1)` was
validated and found dead - real distress audio (angry/fearful/disgust,
studio-recorded, close mic, the loudest realistic case) read median 0.0013,
p95 0.085, nowhere near the 0.55-0.91 the old training data assumed.

Per Aarush's request, the mapping is now:

```
AudioEnergy = clamp((20*log10(max(audioRmsEnergy,1)/32768) - AUDIO_FLOOR_DB)
                     / (AUDIO_CEIL_DB - AUDIO_FLOOR_DB), 0, 1)
AUDIO_FLOOR_DB = -32.0    AUDIO_CEIL_DB = -20.0
```

`AUDIO_FLOOR_DB`/`AUDIO_CEIL_DB` live in `phase4/sensor_packet_adapter.py`
(single source of truth; `phase5/dataset_adapters.py` imports them, never
redefines them) and are fitted, not guessed: RAVDESS's p95 dB values put
distress at -21.4 dB and non-distress at -29.8 dB - a real but modest ~8 dB
gap that is consistent from p90 to p99. Hitting Aarush's target (distress
p95 -> ~0.85-0.9, non-distress p95 -> ~0.1-0.2) forces a **narrow 12 dB
window**, dictated by that ~8 dB gap, not chosen freely - which makes this
scale proportionally more sensitive to microphone gain/distance than a wider
window would be. Real measured result:
`data/audio_validation_report.json` -> distress p95 = 0.8823, non-distress
p95 = 0.182. See the constant's docstring in `sensor_packet_adapter.py` for
the full derivation and that tradeoff.

**This is a lockstep change - Kotlin must mirror it in the same window.**
Nothing here is complete until Aarush's `FeatureExtractor.kt` applies the
identical formula and constants; `phase4/test_contract_sync.py` now checks
`AUDIO_FLOOR_DB`/`AUDIO_CEIL_DB` in Kotlin against `model_contract.json` the
same way it already does for `AUDIO_RMS_FULL_SCALE`, and will start failing
(usefully) instead of skipping the moment `mobile-client` carries the
matching constants.

**Retrained on this scale** (`phase5/train_tflite_model.py --dataset fusion
--write-model`) - see `MODEL_CARD.md` for the honest before/after numbers.

**Still open, not fixed by this rescale:** whether a real pocketed phone's
microphone captures anything at all. Aarush is separately verifying this -
some on-device sessions read a flat 0.0. A rescale of a signal that never
arrives changes nothing; on-device validation (Level 2 with a real .wav via
`--wav`) is still the only thing that closes this for real.

**The retrained model fixes the false-positive defect, and the GPS defect is
now fixed too.** On the same real-motion sweep (10,824 windows, 65 subjects,
UCI HAR + ShimFall): false-positive rate is **0.0%-5.6%**, and every one of
the 12 real activities fires at effectively **0%** at the defensible cell
(was up to 40.3% on walking-downstairs, 100% on jumping, in the original
synthetic model). The `PeakAcceleration > 15` rule is unchanged and still
trips on 39.8% of ordinary activity on its own, but the network now overrides
it correctly using `MotionVariance`.

**Fixed 2026-09-06:** the 2026-09-05 retrain assigned every fall
`GPSVelocity = 0` via an activity heuristic (no corpus records GPS at all),
so the model learned "moving fast => not an emergency" - recall collapsed to
0% whenever assumed GPSVelocity >= 1.5 m/s. Aarush flagged this as
safety-critical: it would suppress the alert exactly when someone is fleeing
an attacker at speed. `load_fusion()` now samples `GPSVelocity` uniformly
(0-3 m/s) independent of Activity and of the label, per his instruction to
neutralize rather than drop the feature (keeps the `[1,5]` contract stable).
**Recall at GPS=3.0 is now 72%-95%**, not 0%, at every audio level tested -
pinned by
`phase5/test_dataset_adapters.py:test_fusion_gps_velocity_is_not_correlated_with_the_label`.
This does not teach the model to detect fleeing, it only stops the model
actively working against that scenario - real GPS+incident captures are
still the only way to gain that capability. This model should be understood
as a **fall/collapse detector**, not a general emergency detector. Full
write-up: **MODEL_CARD.md**; reproduce with
`python phase5/evaluate_real_fpr.py --dataset uci_har,shimfall`.

The fusion pairing (audio and GPS assigned, not observed) means
`is_production_evidence` is `false` for this dataset no matter the score -
never quote the fusion test-set metrics (99.7% accuracy) as production
performance. The real-motion sweep above is the honest number.

**The new `.tflite` has not been vendored to the phone yet.** Ask Aarush to
copy `data/emergency_model.tflite` to
`mobile-client/app/src/main/assets/emergency_model.tflite` - the phone keeps
running the old (worse) model until he does.

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
