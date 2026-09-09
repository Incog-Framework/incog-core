# Model card — emergency_model.tflite

**Generated:** 2026-09-06. **Model SHA-256:** `22763a8b32abaad02887d3b208deba2f2dbda21b46424fa8a12cf1652a1130e6`
(see `data/model_contract.json`). **Not yet vendored to the phone.**

> **Do not vendor this `.tflite` without the matching Kotlin change.** This retrain assumes the
> NEW AudioEnergy dB scale (below). If Aarush copies this file into `mobile-client/assets/` while
> `FeatureExtractor.kt` still computes the OLD linear `audioRmsEnergy / 32768`, the phone will feed
> the model AudioEnergy values on the wrong scale — worse train/serve skew than before this
> rescale, not a neutral no-op. Vendor the model and the Kotlin formula change together.

## Retrain history

1. **2026-09-05** — first real-data retrain (30 synthetic rows → 10,824 real UCI HAR + ShimFall +
   RAVDESS fusion windows). Fixed the false-positive defect. Introduced a defect: every fall was
   assigned `GPSVelocity = 0`, so the model learned "moving fast ⇒ not an emergency."
2. **2026-09-06, fix 1** — Aarush caught the GPS defect: it would suppress the alert exactly when
   someone is fleeing at speed. `load_fusion()`'s `GPSVelocity` is now sampled uniformly from
   0–3 m/s, **independent of Activity and of the Emergency label**. Pinned by
   `phase5/test_dataset_adapters.py:test_fusion_gps_velocity_is_not_correlated_with_the_label`.
3. **2026-09-06, fix 2 (this card)** — AudioEnergy moved from the dead linear scale to a dB scale
   fitted against real RAVDESS speech, per Aarush's request. See "AudioEnergy rescale" below.

## AudioEnergy rescale (this retrain)

The previous card flagged that real RAVDESS distress audio reads far below what the old
`clamp(audioRmsEnergy / 32768, 0, 1)` linear scale's training assumptions expected — median
0.0013, p95 0.085, vs. an assumed 0.55–0.91. Aarush's initial call was to ship with audio near-dead
and defer the rescale; he then asked for the rescale directly, with a target of "scream ~0.8–0.9,
ambient ~0.1–0.2", to be fitted against real data and applied in lockstep with an identical Kotlin
change.

**New formula** (`phase4/sensor_packet_adapter.py`, single source of truth — `phase5/
dataset_adapters.py` imports it, never redefines it):

```
AudioEnergy = clamp((20*log10(max(audioRmsEnergy, 1) / 32768) - AUDIO_FLOOR_DB)
                     / (AUDIO_CEIL_DB - AUDIO_FLOOR_DB), 0, 1)
AUDIO_FLOOR_DB = -32.0        AUDIO_CEIL_DB = -20.0
```

**How FLOOR/CEIL were chosen — read this before copying the numbers into Kotlin.** RAVDESS's real
dB distribution (82,532 chunks) puts distress (angry/fearful/disgust) at p95 = −21.4 dB and
non-distress at p95 = −29.8 dB — separated by a real, honest ~8 dB at every percentile from p90 to
p99, not more. Hitting Aarush's target band forces the window to be **narrow (12 dB)**: that's the
math (`8.4 dB gap / (0.85 − 0.15) target separation ≈ 12 dB`), not a free choice. A narrow window
is proportionally *more* sensitive to microphone gain/distance drift than a wide one would be —
real, not hypothetical, and worth knowing before assuming this is "solved." Measured result on
real RAVDESS audio: distress p95 → **0.8823**, non-distress p95 → **0.182** — squarely on target.
Full derivation: the `AUDIO_FLOOR_DB` docstring in `sensor_packet_adapter.py`.

**This is a lockstep change, not yet complete.** Kotlin's `FeatureExtractor.kt` must apply the
identical formula and these two constants before this is real on-device — nothing here changes
what the phone does until he does. `phase4/test_contract_sync.py` now checks
`AUDIO_FLOOR_DB`/`AUDIO_CEIL_DB` against Kotlin the same way it already checks
`AUDIO_RMS_FULL_SCALE`, gracefully skipped until `mobile-client` carries the matching constants.

**Still unresolved, and this rescale does not touch it:** whether a real pocketed phone's
microphone captures anything at all. Aarush is separately verifying this after some on-device
sessions read a flat 0.0. Rescaling a signal that never arrives changes nothing.

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
  emotions — angry/fearful/disgust — for Emergency, everything else for Normal), converted through
  the dB scale above. This assumes voice distress and body motion are conditionally independent
  given the label, which is very likely false (a real fall can happen in near-silence).
- **GPSVelocity** (revised 2026-09-06) is sampled uniformly from 0–3 m/s, **independent of
  Activity and of the Emergency label** — deliberately non-predictive. It carries no information
  the model could use in either direction, until real GPS+incident captures exist.

Because of this, `is_production_evidence: false` is stamped into every metric this dataset
produces, no matter the score (`data/tflite_model_metrics.json`).

## Honest evaluation

Two separate measurements, because they answer different questions.

**1. On the fusion test set** (subject-level split, 13 of 65 subjects held out, 2,100 rows) — this
measures the classifier's fit to its own (partly constructed) training distribution:

| @ dispatch threshold 0.80 | GPS-fix retrain | **This retrain (+ dB audio)** |
|---|---:|---:|
| Accuracy / Precision / Recall / F1 | 0.992 / 1.000 / 0.730 / 0.844 | 0.991 / 0.979 / 0.730 / 0.836 |
| False-positive rate | 0.0% | 0.05% (1 / 2,037) |
| ROC-AUC | 0.972 | 0.971 |

Essentially unchanged from the GPS-fix retrain — expected, since this dataset's Emergency label is
driven by real fall dynamics (`PeakAcceleration`/`MotionVariance`), and AudioEnergy/GPSVelocity are
both constructed, secondary signals for it. The rescale mattered for what the *number itself means*
(see below), not for how well the network fits.

**2. On real motion only** (UCI HAR + ShimFall, `phase5/evaluate_real_fpr.py`, no fusion, AudioEnergy/
GPSVelocity swept rather than assumed) — this is the number that matters, because it never touches
the constructed pairing:

| | First model (synthetic) | GPS-fix retrain | **This retrain (+ dB audio)** |
|---|---:|---:|---:|
| FPR range across the sweep | 0.6% – 39.8% | 0.0% – 5.6% | **0.0% – 0.6%** |
| Most defensible cell (audio 0.05, gps 1.5) | 5.8% | 0.1% | **0.0%** |
| Walking-downstairs fire rate | 40.3% | 0.6% | **0.1%** |
| Jumping fire rate | 100.0% | 8.6% | **5.7%** |
| Recall at gps=0 (realistic, just collapsed) | 67.9% – 99.4% | 75.6% – 83.8% | **76.8% – 82.9%** |
| **Recall at gps=3.0 (fleeing at speed)** | not measured | 72.1% – 94.6% | **66.0% – 78.4%** |

**Headline: false-positive rate is now below the 5% target for every combination of assumed
audio/GPS tested (worst case 0.6%)** — the first time that has been true across the whole sweep,
not just the "most defensible" cell. **The GPS fix still holds**: recall at gps=3.0 never
collapses to 0% (it did, entirely, before the 2026-09-06 GPS fix); it now sits at 66–78%, a bit
lower than the GPS-fix retrain's 72–95% because this network saw a different (more realistic,
mostly-near-zero) AudioEnergy distribution during training and its response surface shifted with
it — an honest side effect of training on better-calibrated data, not a regression to hide.
Recall at gps=0 held essentially flat (76.8–82.9% vs. 75.6–83.8%). Nothing here is evidence the
model detects fleeing specifically — see Limitations.

## Limitations — read before deploying

1. **This does not add fleeing-detection capability — it only stops actively working against it.**
   GPS is now *neutral*, not *informative*. The recall-rises-with-GPS pattern above is an artifact
   of vigorous motion correlating with the swept GPS values, not a learned "fleeing" concept. Real
   GPS+incident captures are the only way to teach the model that relationship for real — see
   `CAPTURE_PROTOCOL.md` for the concrete capture plan handed to Aarush for this.
2. **AudioEnergy now carries real signal (fitted, not fixed) — but the on-device question is
   still open.** The rescale (see above) makes RAVDESS distress land at p95 ≈ 0.88 and non-distress
   at p95 ≈ 0.18, instead of both being near-zero. That is a real improvement over the linear
   scale, but three caveats remain: (a) it is fitted against studio speech, not a muffled pocketed
   phone — the true on-device distribution is still unmeasured; (b) the ~8 dB real separation
   between distress and non-distress is modest, so the fitted window is narrow (12 dB) and
   proportionally sensitive to mic gain/distance; (c) **it is not live until Aarush mirrors it in
   Kotlin** — see `data/audio_validation_report.json` and `phase5/validate_audio_normalization.py`.
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
2. **Aarush mirrors the AudioEnergy dB formula in `FeatureExtractor.kt`** using the exact
   `AUDIO_FLOOR_DB`/`AUDIO_CEIL_DB` constants above — the phone runs the OLD linear formula until
   he does, which is now a worse mismatch than before the rescale (train/serve skew), not a neutral
   no-op. This is the priority follow-up.
3. Real GPS+incident captures, per `CAPTURE_PROTOCOL.md` — the only fix for limitation 1 that
   doesn't require more fabrication, and the only way to actually gain fleeing-detection rather
   than just stop suppressing it.
4. On-device audio validation once Aarush's mic-capture investigation closes — Level 2 with a real
   `.wav` (`python phase5/validate_audio_normalization.py --wav ...`) is the only way to know if
   AUDIO_FLOOR_DB/AUDIO_CEIL_DB are reachable by an actual pocketed phone.
5. Re-run `phase5/evaluate_real_fpr.py` after any further retrain; it is the regression test —
   specifically watch the recall-at-gps=3.0 column so the GPS fix does not silently regress.
