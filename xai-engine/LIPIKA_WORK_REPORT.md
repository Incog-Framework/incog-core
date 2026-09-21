# Lipika's AI and XAI Work Report

**Project:** INCOG personal-safety system  
**Owner:** Lipika  
**Scope:** XAI engine, Phases 4-6, and server-side explainability  
**Repository branch:** `feat/real-model`  
**Latest implementation commit:** `d20a350` (2026-09-11)

## Executive summary

Implemented the AI pipeline that converts Aarush's Android `SensorPacket` into
five model features, runs emergency classification with the TFLite model,
applies the emergency decision threshold, and produces SHAP/LIME explanations.
The work also adds cross-language contract checks, real-data evaluation,
dataset adapters, reproducible model training, session metadata propagation,
and Phase 7 handoff artifacts.

The latest model was retrained using 572 real GPS-paired SensorPacket captures
from 18 sessions, in addition to UCI HAR, ShimFall, and RAVDESS-derived
training data. The model and metrics are committed, but the combined result is
explicitly **not a production claim**: the real capture batch represents one
person and has limited held-out scenario coverage.

## Delivered functionality

### Phase 4: sensor feature extraction and Android contract

- Added a single `SensorPacket` adapter that owns Android JSON field names,
  schema validation, loading, feature extraction, and session context.
- Implemented the fixed five-feature vector, in this order:
  `PeakAcceleration`, `MotionVariance`, `AudioEnergy`, `GPSVelocity`,
  `PossibleFall`.
- Matched Python feature mathematics to the Kotlin implementation:
  - peak acceleration is the maximum 3-axis magnitude, including gravity;
  - motion variance is sample variance (`ddof=1`), or `0.0` for fewer than two
    samples;
  - GPS uses the latest location speed, defaulting to `0.0`;
  - possible fall is `PeakAcceleration > 15` on the unrounded value;
  - gyro fields are accepted for compatibility but intentionally unused because
    the trained model has five inputs.
- Replaced the invalid linear audio normalization with the fitted dB mapping:

  ```text
  AudioEnergy = clamp((20*log10(max(audioRmsEnergy, 1)/32768) + 32.0) / 12.0, 0, 1)
  AUDIO_FLOOR_DB = -32.0
  AUDIO_CEIL_DB = -20.0
  ```

- Added generated contract fixtures containing constants, model shape, model
  hash, and seven golden feature vectors.
- Added Python/Kotlin parity and contract tests, including checks that the
  adapter is the only code reading raw Android packet fields.
- Added real-packet validation for schema, timestamps, sample counts, sample
  rate, feature ranges, labels, and flat-zero audio diagnostics.

### Phase 5: training, TFLite inference, and evaluation

- Added dataset download and adapter support for UCI HAR, ShimFall&ADL, and
  RAVDESS.
- Added fusion training that keeps the five-input tensor stable while making
  the missing channels explicit:
  - RAVDESS supplies label-matched audio values;
  - GPS is sampled uniformly from 0-3 m/s independently of activity and label,
    preventing the model from learning that fast movement means normal.
- Added real SensorPacket training support from
  `data/raw/sensor_packets/{normal,emergency}`.
- Grouped real packets by capture session during train/test splitting to avoid
  leakage between overlapping windows from the same session.
- Retrained and exported the Keras model and `emergency_model.tflite`.
- Added real false-positive-rate evaluation over UCI HAR and ShimFall, with
  audio/GPS sweeps clearly reported as assumptions rather than joint captures.
- Added real-packet evaluation reporting held-out and all-capture results,
  including recall by GPS-speed bin and by capture scenario.

### Phase 6: decision engine

- Implemented the two-stage classification/dispatch behavior:
  - classification: confidence `>= 0.50` means `Emergency`;
  - dispatch: raw confidence `>= 0.80` means `EmergencyStatus=true`.
- Ensured threshold comparisons use `ConfidenceRaw`, not the display-rounded
  confidence value.
- Preserved `SessionID` and `TimestampMs` in the decision output.

### XAI and downstream handoff

- Added a backend-facing explainer service for the deployed `.tflite` model.
- Added SHAP and LIME explanations, feature values, ranked contributions,
  direction, human-readable title/message/reasons, and visualizations.
- Kept explanations server-side because SHAP/LIME are too slow for the phone.
- Propagated session metadata and feature values through the XAI output and
  Phase 7 intervention, evidence manifest, and final system report.
- Added output-contract tests for the fields consumed by the security and
  backend modules.

## Current model and validation results

### Training sources

| Source | Role | Size |
|---|---|---:|
| UCI HAR | Real ordinary-activity motion negatives | 10,299 windows, 30 subjects |
| ShimFall&ADL | Real motion plus staged falls and ADLs | 525 windows, 35 subjects |
| RAVDESS | AudioEnergy calibration and fusion sampling | 82,532 audio chunks |
| Android SensorPacket captures | Real five-feature paired captures | 572 packets, 18 sessions, one person |

### Latest combined test set

The latest fusion plus SensorPacket split uses `GroupShuffleSplit` and contains
9,738 training samples and 1,658 test samples.

| Metric at dispatch threshold 0.80 | Result |
|---|---:|
| Accuracy | 96.68% |
| Precision | 87.50% |
| Recall | 60.87% |
| F1 | 71.79% |
| False-positive rate | 0.65% (10/1,543 negatives) |
| ROC-AUC | 0.964 |

### Real SensorPacket results

On all 572 real packets, recall at GPS `>= 1.5 m/s` was 87.8%. This is a fit
measurement, not a generalization claim: none of the three held-out sessions
contained fast-moving positive examples. The held-out result across three
sessions was 40.0% recall, 66.7% precision, and 7.9% false-positive rate.

Scenario results on all real packets:

| Scenario | Label | Packets | Fire rate |
|---|---|---:|---:|
| fleeing-sprint | Emergency | 95 | 75.8% |
| fleeing-walk | Emergency | 93 | 43.0% |
| distress-still | Emergency | 49 | 42.9% |
| passenger | Normal | 69 | 0.0% |
| jog-calm | Normal | 101 | 5.0% |
| walk-calm | Normal | 108 | 6.5% |
| loud-calm-still | Normal | 57 | 3.5% |

The RAVDESS-fitted dB mapping measured p95 AudioEnergy of `0.8823` for
distress speech and `0.182` for non-distress speech. Real phone captures also
confirmed that the microphone produces non-zero values, although moving
captures had high ambient pocket noise in both calm and distress scenarios.

## Important limitations and handoff items

1. **Kotlin must mirror AudioEnergy dB normalization.**
   `FeatureExtractor.kt` must use the exact formula and `-32.0` / `-20.0`
   constants before the retrained model is vendored to the phone. The contract
   test is designed to fail once the Kotlin source is present but mismatched.
2. **Android JSON production is still an integration task.**
   `SensorPacket` is currently a plain Kotlin data class and does not yet
   serialize captures to JSON. Add serialization while preserving the default
   property names, then send one packet through the adapter to close the
   round-trip check.
3. **The real capture set is one person and mostly staged scenarios.** More
   ordinary negatives and multiple people/devices are needed before making a
   production performance claim.
4. **Fleeing-walk is difficult.** Its captured GPS speed was lower than the
   target range, and its fire rate is lower than fleeing-sprint.
5. **Moving audio is not a clean distress signal in this capture round.**
   Pocket wind, footsteps, and fabric noise raised AudioEnergy for both calm
   and distress movement.
6. **The 50 Hz versus approximately 100 Hz question remains device-dependent.**
   These captures measured roughly 97-101 Hz on this device, while public
   corpora are resampled around 50 Hz. The current real-packet sanity check
   accepts the observed device rate without changing the training contract.
7. The latest model is marked `production_claim_supported: false` in the
   generated metrics and reports. Do not quote the synthetic or fusion metrics
   as field performance.

## Main files delivered

### Documentation and contracts

- `CLAUDE.md` - ownership, feature contract, thresholds, workflow, and open items
- `DATA_REQUIREMENTS.md` - data assumptions and collection requirements
- `INTEGRATION.md` - Android-to-AI runbook and handoff contract
- `CAPTURE_PROTOCOL.md` - real capture procedure
- `MODEL_CARD.md` - model provenance, retrain history, metrics, and limitations
- `REAL_DATA_FINDINGS.md` - historical evaluation and before/after findings
- `data/model_contract.json` - generated cross-language contract
- `data/golden_feature_vectors.json` - generated parity fixtures

### Runtime and training code

- `phase4/feature_extraction.py`
- `phase4/sensor_packet_adapter.py`
- `phase4/process_sensor_packet.py`
- `phase4/sensor_processing.py`
- `phase5/dataset_adapters.py`
- `phase5/fetch_datasets.py`
- `phase5/train_tflite_model.py`
- `phase5/tflite_predict.py`
- `phase5/evaluate_real_fpr.py`
- `phase5/evaluate_real_packets.py`
- `phase5/validate_audio_normalization.py`
- `phase6/decision_engine.py`
- `run_ai_pipeline.py`
- `generate_contract_fixtures.py`

### Explainability and system handoff

- `xai/explainer_service.py`
- `xai/explanation_generator.py`
- `xai/lime_explain.py`
- `xai/tflite_utils.py`
- `xai/xai_pipeline.py`
- `xai/visualize.py`
- `phase7/evaluate_metrics.py`
- `phase7/forensics.py`
- `phase7/intervention.py`
- `phase7/generate_report.py`
- `data/xai_output.json`
- `data/shap_output.json`
- `data/lime_output.json`
- `data/human_explanation.json`
- `data/final_system_report.json`
- `data/forensic_evidence/evidence_manifest.json`

### Tests

- Phase 4: feature extraction, adapter isolation, packet schema, Kotlin parity,
  contract sync, and real-packet validation
- Phase 5: dataset adapters, normalization, TFLite inference, real FPR, and
  real-packet evaluation
- Phase 6: raw decision-threshold behavior and full system cases
- XAI: explainer service and output contract
- Phase 7: session propagation and downstream artifact checks
- `run_tests.py` is the full-suite entry point.

## Commit history of this contribution

| Commit | Date | Contribution |
|---|---|---|
| `c51db4f` | 2026-09-03 | Real-data evaluation, explainer API, contract tests, dataset adapters, and integration pipeline |
| `b344537` | 2026-09-06 | Neutralized GPS-label correlation so fast movement cannot suppress emergency alerts |
| `14eeaab` | 2026-09-07 | Fitted AudioEnergy dB normalization against real RAVDESS speech and retrained the model |
| `d20a350` | 2026-09-11 | Added real GPS-paired SensorPacket training, evaluation, and the latest retrained TFLite model |

## Reproduction commands

Run from `xai-engine`:

```bash
python run_tests.py
python phase4/test_real_packets.py
python phase5/evaluate_real_fpr.py --dataset uci_har,shimfall
python phase5/evaluate_real_packets.py
python run_ai_pipeline.py --packet PATH_TO_SENSOR_PACKET.json
python -m xai.explainer_service --benchmark
```

The latest model SHA-256 is recorded in `data/model_contract.json` and in
`MODEL_CARD.md`. Regenerate contract fixtures after changing feature math,
thresholds, or the model:

```bash
python generate_contract_fixtures.py
```