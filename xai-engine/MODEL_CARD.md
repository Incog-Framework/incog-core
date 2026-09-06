# Model card — emergency_model.tflite

**Generated:** 2026-09-06. **Model SHA-256:** `669f4495b28d25ca1e354784a6a0f12523b2fb1a6eaca6114c26753e2e05fd93`
(see `data/model_contract.json`). **Not yet vendored to the phone** — Aarush is blocked on
`feat/real-model` being pushed before he can copy this file to
`mobile-client/app/src/main/assets/emergency_model.tflite`.

## What changed since the last card (2026-09-05)

Aarush reviewed the first real-data retrain and found a safety-critical defect: every fall in
that training fusion was assigned `GPSVelocity = 0` by an activity-keyed heuristic, so the model
learned "moving fast ⇒ not an emergency" — exactly backwards, because it would suppress the alert
precisely when someone is fleeing an attacker at speed. **This retrain fixes that.**
`phase5/dataset_adapters.py:load_fusion()` now samples `GPSVelocity` uniformly from 0–3 m/s,
**independent of Activity and of the Emergency label**, so the model cannot learn any GPS-vs-label
correlation in either direction. Pinned by
`phase5/test_dataset_adapters.py:test_fusion_gps_velocity_is_not_correlated_with_the_label`.

Everything else (datasets, label definition, the AudioEnergy fusion, the feature contract) is
unchanged from the previous card — see below for the full picture, not just the diff.

**AudioEnergy rescale is deliberately deferred.** The previous card flagged that real RAVDESS
distress audio reads far below what the old synthetic data assumed. Aarush's call: ship this model
with AudioEnergy near-dead first, then redefine the scale as a **coordinated** fast-follow (he
changes Kotlin's `AUDIO_RMS_FULL_SCALE`/mapping in the same change as any Python retrain, so the
two sides never drift). Nothing about the audio formula changed in this retrain.

## Datasets

| Corpus | Role | Rows | Real? |
|---|---|---:|---|
| UCI HAR (archive 240) | Negatives — 30 subjects, all-ADL, 50 Hz, waist-worn | 10,299 | yes |
| ShimFall&ADL (Zenodo 3901285) | Positives (falls) + negatives (ADLs) — 35 subjects, chest-worn, 50 Hz | 525 | yes |
| RAVDESS (Zenodo 1188976) | Audio only — 82,532 16 kHz-PCM chunks, used to sample `AudioEnergy` | — | yes |

None of these are committed (`data/raw/` is gitignored). Reproduce with
`python phase5/fetch_datasets.py --dataset uci_har,shimfall,ravdess`.

## Label definition (operational)

**Emergency (1)** = the 9 staged ShimFall fall types (front/back/left/right/steep, hard and soft).
**Normal (0)** = every UCI HAR ADL (laying, sitting, standing, walking, stairs) and every ShimFall
ADL (bending, jumping, sitting, standing, lying down, walking). This is a **fall/collapse**
definition. It does **not** cover Aarush's other named emergency variants — "violent
shaking/struggle" or "fleeing at high GPS velocity" — because no available corpus stages or
records either. Neutralizing GPS (see above) stops the model from actively working *against* the
fleeing case; it does not give it the ability to detect one. See Limitations.

## Preprocessing (must match Kotlin exactly)

Each row = one ~20 s window of accelerometer magnitude at 50 Hz (`SensorCollector.MAX_SAMPLES`,
stepped by `GhostStateService.SNAPSHOT_INTERVAL_MS`), reduced to the 5 features by
`phase4/feature_extraction.py` — the same functions training and on-device inference both call, so
there is one definition, not two. UCI HAR (2.56 s windows) and ShimFall (2.02 s events) are shorter
than the 20 s the phone scores; `PeakAcceleration` carries across window length, `MotionVariance`
does not and is an upper bound (see `DATA_REQUIREMENTS.md`).

**The fusion — read this before trusting a number.** No public corpus records motion and audio for
the same moment, and none records GPS at all. `phase5/dataset_adapters.py:load_fusion()` closes
that gap by construction, not observation:

- **AudioEnergy** is resampled per row from RAVDESS clips matching the row's label (distress
  emotions — angry/fearful/disgust — for Emergency, everything else for Normal). This assumes
  voice distress and body motion are conditionally independent given the label, which is very
  likely false (a real fall can happen in near-silence).
- **GPSVelocity** (revised 2026-09-06) is sampled uniformly from 0–3 m/s, **independent of
  Activity and of the Emergency label** — deliberately non-predictive. It carries no information
  the model could use in either direction, until real GPS+incident captures exist.

Because of this, `is_production_evidence: false` is stamped into every metric this dataset
produces, no matter the score (`data/tflite_model_metrics.json`).

## Honest evaluation

Two separate measurements, because they answer different questions.

**1. On the fusion test set** (subject-level split, 13 of 65 subjects held out, 2,100 rows) — this
measures the classifier's fit to its own (partly constructed) training distribution. Neutralizing
GPS removed a signal the earlier model was silently leaning on, so this number is honestly lower
than the previous card's — that is the fix working, not a regression to be hidden:

| @ dispatch threshold 0.80 | Previous retrain (GPS keyed to label) | **This retrain (GPS neutral)** |
|---|---:|---:|
| Accuracy / Precision / Recall / F1 | 0.997 / 0.983 / 0.905 / 0.942 | 0.992 / 1.000 / 0.730 / 0.844 |
| False-positive rate | 0.05% | 0.0% |
| ROC-AUC | 0.999 | 0.972 |

**2. On real motion only** (UCI HAR + ShimFall, `phase5/evaluate_real_fpr.py`, no fusion, AudioEnergy/
GPSVelocity swept rather than assumed) — this is the number that matters, because it never touches
the constructed pairing:

| | First model (30 synthetic rows) | Previous retrain (GPS keyed to label) | **This retrain (GPS neutral)** |
|---|---:|---:|---:|
| FPR range across the sweep | 0.6% – 39.8% | 0.0% – 10.3% | **0.0% – 5.6%** |
| Most defensible cell (audio 0.05, gps 1.5) | 5.8% | 0.0% | **0.1%** |
| Walking-downstairs fire rate | 40.3% | 0.0% | **0.6%** |
| Jumping fire rate | 100.0% | 0.0% | **8.6%** |
| Recall at gps=0 (realistic, just collapsed) | 67.9% – 99.4% | 92.7% – 95.2% | **75.6% – 83.8%** |
| **Recall at gps=3.0 (fleeing at speed)** | not measured | **0%, every audio level** | **72.1% – 94.6%** |

**The GPS fix is the headline of this retrain.** The previous model's recall *collapsed to 0% the
instant assumed GPS velocity reached 1.5 m/s or higher* — it had learned that fast movement rules
out an emergency, so a person fleeing at speed while also having (say) fallen would never trigger
an alert. That number is now 72–95%, and in most cells recall goes *up*, not down, as assumed GPS
rises (the network still keys mainly on `PeakAcceleration`/`MotionVariance`, and vigorous
real-world motion — which is what a fall or a struggle actually is — happens to correlate with
higher assumed GPS in this sweep; it is not evidence the model detects fleeing, see Limitations).
The false-positive picture stayed materially the same (0.0%–5.6%, essentially all real activities
at 0% at the realistic cell) — fixing the GPS defect did not reopen the false-positive problem the
first retrain solved. Recall at the realistic "just collapsed" cell (gps=0) dropped from ~93% to
~76–84%: that is the honest cost of no longer letting the model use a fabricated GPS=0 shortcut for
falls, not a new bug.

## Limitations — read before deploying

1. **This does not add fleeing-detection capability — it only stops actively working against it.**
   GPS is now *neutral*, not *informative*. The recall-rises-with-GPS pattern above is an artifact
   of vigorous motion correlating with the swept GPS values, not a learned "fleeing" concept. Real
   GPS+incident captures are the only way to teach the model that relationship for real.
2. **AudioEnergy is validated, and the news is still bad — unchanged from the last card, and
   deliberately not fixed here.** RAVDESS distress speech (angry/fearful/disgust, studio-recorded,
   close mic — the loudest realistic case) reads `median 0.0013, p95 0.085` on the current
   `clamp(audioRmsEnergy / 32768, 0, 1)` scale — nowhere near the `0.55–0.91` the old synthetic
   data assumed. A real pocketed phone will read even lower. At this scale AudioEnergy is close to
   a constant near 0 for both classes; the model is effectively running on 4 features. **Per
   Aarush's decision (2026-09-06): ship as-is, redefine the scale as a coordinated fast-follow so
   Python retraining and the Kotlin `AUDIO_RMS_FULL_SCALE`/mapping change together — never one side
   alone.** See `data/audio_validation_report.json` and `phase5/validate_audio_normalization.py`.
3. **No staged "violent shaking/struggle" data anywhere.** Not represented at all.
4. **Body position mismatch.** UCI HAR is waist-worn, ShimFall is chest-strapped; neither is a
   phone loose in a pocket or bag.
5. **Staged, not real, falls.** ShimFall falls are volunteers falling onto a mat.
6. **The fusion pairing is fabricated, not observed** (see Preprocessing). Treat the fusion
   test-set numbers as an upper bound on how well this network CAN fit; treat the real-motion sweep
   as the honest floor.
7. **PossibleFall > 15 is unchanged** and still fires on 39.8% of ordinary vigorous motion on its
   own — the network has learned to override it using `MotionVariance`, but the rule itself is
   still the same blunt threshold flagged in `REAL_DATA_FINDINGS.md`. Not touched here because it
   is a feature-contract change and needs Aarush's sign-off.
8. **Real SensorPacket captures still do not exist.** Everything above is public-corpus data
   through the same feature math as the phone, never a packet the phone itself produced.

## What to do next

1. Push `feat/real-model` so Aarush can re-vendor `data/emergency_model.tflite` →
   `mobile-client/.../assets/emergency_model.tflite` — he is blocked on this.
2. Real GPS+incident captures — the only fix for limitation 1 that doesn't require more
   fabrication, and the only way to actually gain fleeing-detection rather than just stop
   suppressing it.
3. AudioEnergy rescale, coordinated with Aarush's Kotlin change, once the current model is shipped
   and stable.
4. Re-run `phase5/evaluate_real_fpr.py` after any further retrain; it is the regression test —
   specifically watch the recall-at-gps=3.0 column so this fix does not silently regress.
