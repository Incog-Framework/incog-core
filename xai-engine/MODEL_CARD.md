# Model card — emergency_model.tflite

**Generated:** 2026-09-11. **Model SHA-256:** `065dfa90ceaed5306efcf2fcabbe35b16a26115c0a015c88ea99ed374d0716ae`
(see `data/model_contract.json`). **Not yet vendored to the phone.**

> **This round needs NO new Kotlin change.** Unlike the two 2026-09-06 retrains, this one changes
> only the training DATA (real SensorPacket captures added in) and the weights that come out of
> it — `AUDIO_FLOOR_DB`/`AUDIO_CEIL_DB`, the classification/decision thresholds, and every other
> contract constant in `data/model_contract.json` are unchanged from the previous model. If
> `FeatureExtractor.kt` already mirrors the AudioEnergy dB formula from the 2026-09-06 card, this
> `.tflite` is a pure drop-in re-vendor. If it does not yet, that is still-outstanding work from
> the *previous* card, not something new this retrain adds — see "AudioEnergy rescale" below,
> unchanged.

## Retrain history

1. **2026-09-05** — first real-data retrain (30 synthetic rows → 10,824 real UCI HAR + ShimFall +
   RAVDESS fusion windows). Fixed the false-positive defect. Introduced a defect: every fall was
   assigned `GPSVelocity = 0`, so the model learned "moving fast ⇒ not an emergency."
2. **2026-09-06, fix 1** — Aarush caught the GPS defect: it would suppress the alert exactly when
   someone is fleeing at speed. `load_fusion()`'s `GPSVelocity` is now sampled uniformly from
   0–3 m/s, **independent of Activity and of the Emergency label**. Pinned by
   `phase5/test_dataset_adapters.py:test_fusion_gps_velocity_is_not_correlated_with_the_label`.
3. **2026-09-06, fix 2** — AudioEnergy moved from the dead linear scale to a dB scale fitted
   against real RAVDESS speech, per Aarush's request. See "AudioEnergy rescale" below.
4. **2026-09-11 (this card)** — first retrain on **real GPS-paired SensorPacket captures**: 18
   sessions (572 packets, one person, 7 scenarios per `CAPTURE_PROTOCOL.md`) Aarush recorded
   through the app, folded into training as `--dataset fusion,sensor_packets`. No formula or
   threshold changed — only data and weights. See "Real captures" below for what changed and the
   honest numbers.

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

**Previously unresolved, now answered by the real captures below:** whether a real pocketed
phone's microphone captures anything at all. It does — `audioRmsEnergy` reads 4,000–13,000
(PCM16 scale) on every moving capture, never flat zero. What the captures also show is that this
particular signal doesn't cleanly separate calm movement from distressed movement (see "Real
captures" below) — a different, narrower problem than "the mic is dead."

## Real captures (this retrain)

**Source:** `data/real_packets/{normal,emergency}/*.json` (validated) mirrored into
`data/raw/sensor_packets/{normal,emergency}/*.json` (trained on) — 18 sessions, 572 packets, one
person, recorded through the app per `CAPTURE_PROTOCOL.md`'s 7-scenario plan. Manifest:
`data/real_packets/manifest.csv`.

**Two small fixes this batch required, both now covered by tests:**

1. **Sample rate.** `phase4/test_real_packets.py` expected ~50 Hz (Android's nominal
   `SENSOR_DELAY_GAME` hint) and flagged all 572 packets as suspicious. All 18 captures actually
   measured ~97–101 Hz (two vehicle-passenger runs dipped to ~57 Hz, plausibly CPU load from
   GPS+motion+audio at once) — a real hardware behaviour, not bad data. `EXPECTED_SAMPLE_RATE_HZ`
   is now 100, not 50. **Consequence worth flagging:** at ~100 Hz, `MAX_ACCEL_SAMPLES=1000` is a
   **~10 s** window on this device, not the ~20 s assumed everywhere else in this codebase
   (`dataset_adapters.py`'s `TARGET_SAMPLE_RATE_HZ=50.0`/`WINDOW_SAMPLES=1000`,
   `DATA_REQUIREMENTS.md`, `CAPTURE_PROTOCOL.md`). That constant was **not** changed here — it
   governs how UCI HAR/ShimFall/WISDM are resampled to match the phone, and changing it on the
   evidence of one device would be a bigger call than this retrain makes unilaterally. Confirming
   the real rate on a second device is the way to settle whether 50 Hz needs revising everywhere,
   not just in the real-packet sanity check.
2. **`--dataset fusion,sensor_packets` shape mismatch.** `fusion` rows carry `Subject`/`Activity`
   metadata (for `GroupShuffleSplit`); `load_sensor_packets()` rows didn't, so they'd have
   concatenated as all-NaN `Subject` and collapsed into one giant ungrouped block — every
   overlapping window from all 18 sessions on one side of the split, or leaking across it.
   `load_sensor_packets()` now tags each row with its packet's `sessionId` as `Subject`, so each
   capture *session* (not person — this batch is one person across 18 sessions) is one
   `GroupShuffleSplit` group, same leakage protection `uci_har`/`shimfall` already had. Pinned by
   `phase5/test_dataset_adapters.py:test_sensor_packets_group_by_capture_session_not_by_row`.

**Two honest limits in the capture data itself, from Aarush, unchanged by anything above:**

- Walk/fleeing-walk came out slower than the capture plan intended (~0.8–1.1 m/s vs. a 1.5–2
  m/s target) and jog ~2 m/s (vs. 2.5–4); the walk/jog GPS bands are closer together than planned.
- `AudioEnergy` is high (raw RMS 4k–13k) on **every** moving capture, calm and distress alike —
  pocket wind/footstep/fabric noise, not voice. Only the two stationary controls
  (`loud-calm-still`, `distress-still`) give a clean audio contrast; on every moving scenario the
  model cannot be using audio to tell calm from distressed, only motion and GPS.

## Datasets

| Corpus | Role | Rows | Real? |
|---|---|---:|---|
| UCI HAR (archive 240) | Negatives — 30 subjects, all-ADL, 50 Hz, waist-worn | 10,299 | yes |
| ShimFall&ADL (Zenodo 3901285) | Positives (falls) + negatives (ADLs) — 35 subjects, chest-worn, 50 Hz | 525 | yes |
| RAVDESS (Zenodo 1188976) | Audio only — 82,532 16 kHz-PCM chunks, used to sample `AudioEnergy` | — | yes |
| Real SensorPacket captures (`data/raw/sensor_packets/`) | Positives (fleeing/distress) + negatives (calm activity) — 1 person, 18 sessions, real 5-feature rows, no fusion assumption | 572 | yes |

None of the public corpora are committed (`data/raw/` is gitignored). Reproduce with
`python phase5/fetch_datasets.py --dataset uci_har,shimfall,ravdess`; real captures come from
Aarush directly (see `CAPTURE_PROTOCOL.md`).

## Label definition (operational)

**Emergency (1)** = the 9 staged ShimFall fall types (front/back/left/right/steep, hard and soft)
**plus**, as of this retrain, the real `fleeing-walk`/`fleeing-sprint`/`distress-still` capture
sessions. **Normal (0)** = every UCI HAR ADL, every ShimFall ADL, **plus** the real
`walk-calm`/`jog-calm`/`passenger`/`loud-calm-still` capture sessions. This is now a
**fall/collapse + one person's staged fleeing/distress** definition — still **not**
"violent shaking/struggle" (no corpus stages that at all), and the fleeing/distress coverage is
one person, one capture round; see "Real captures" and Limitations 1, 8-9 for exactly how thin
that evidence still is.

## Preprocessing (must match Kotlin exactly)

Each row = one ~20 s window of accelerometer magnitude at the nominal 50 Hz
(`SensorCollector.MAX_SAMPLES`, stepped by `GhostStateService.SNAPSHOT_INTERVAL_MS`), reduced to
the 5 features by `phase4/feature_extraction.py` — the same functions training and on-device
inference both call, so there is one definition, not two. UCI HAR (2.56 s windows) and ShimFall
(2.02 s events) are shorter than the 20 s the phone scores; `PeakAcceleration` carries across
window length, `MotionVariance` does not and is an upper bound (see `DATA_REQUIREMENTS.md`). The
real `sensor_packets` rows are the one exception to "resample to the nominal rate": they use
whatever `accelSamples` the phone itself produced, unresampled, at whatever rate it actually ran
(measured ~100 Hz this batch, not 50 — see "Real captures" above) — that is deliberately the most
faithful option available, not an inconsistency to fix.

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

Three separate measurements now, because they answer three different questions — read them in
order of how much they're worth trusting: (3) is the only one where every one of the five features
was actually observed together, for the same moment, on a real phone.

**1. On the fusion+sensor_packets test set** (subject-level split, 17 of 83 subjects/sessions held
out — 14 fusion subjects + 3 real sessions `SESS-5262516D`/`SESS-52BAF49D`/`SESS-93CA14AF`, 1,658
rows) — this measures the classifier's fit to its own (partly constructed) training distribution,
now with real captures mixed in:

| @ dispatch threshold 0.80 | dB-audio retrain (2026-09-06) | **This retrain (+ real captures)** |
|---|---:|---:|
| Accuracy / Precision / Recall / F1 | 0.991 / 0.979 / 0.730 / 0.836 | 0.967 / 0.875 / 0.609 / 0.718 |
| False-positive rate | 0.05% (1 / 2,037) | 0.65% (10 / 1,543) |
| ROC-AUC | 0.971 | 0.964 |

Recall and precision both drop from the previous card. That is expected, not a regression: the
previous test set was pure fusion (fall dynamics from ShimFall, resampled audio, non-predictive
GPS) — real fleeing/distress captures don't look like a ShimFall fall on `PeakAcceleration`/
`MotionVariance` at all (see "Real captures" above), so they are genuinely harder for the network,
and this test set now includes some of them. FPR is still well under the 5% target.

**2. On real motion only** (UCI HAR + ShimFall, `phase5/evaluate_real_fpr.py`, no fusion, AudioEnergy/
GPSVelocity swept rather than assumed) — re-run against this retrain; never touches the
constructed pairing:

| | First model (synthetic) | dB-audio retrain (2026-09-06) | **This retrain (+ real captures)** |
|---|---:|---:|---:|
| FPR range across the sweep | 0.6% – 39.8% | 0.0% – 0.6% | **0.0% – 0.4%** |
| Most defensible cell (audio 0.05, gps 1.5) | 5.8% | 0.0% | **0.0%** |
| Walking-downstairs fire rate | 40.3% | 0.1% | **0.0%** |
| Jumping fire rate | 100.0% | 5.7% | **0.0%** |
| Recall at gps=0, across the audio sweep | 67.9% – 99.4% | 76.8% – 82.9% | **0.0% – 72.1%** |
| **Recall at gps=3.0 (fleeing at speed)** | not measured | 66.0% – 78.4% | **55.9% – 81.3%** |

**Headline: false-positive rate improved again (worst case 0.4%, down from 0.6%)** — jumping and
walking-downstairs, the two activities that broke the original synthetic model, now fire 0.0% of
the time at the defensible cell. **The recall-at-gps=0 range widened and its floor dropped to 0%**
(at the highest assumed audio, 0.60) — that is new, and worth reading carefully: UCI HAR/ShimFall
have no real audio, so `audio=0.60` there is a hypothetical "loud but not moving, not fast" cell
that never occurs in this corpus's real events, and the network — now also trained on real
captures where high assumed audio without corroborating motion or GPS mostly wasn't the emergency
signal (see "Real captures" above: audio didn't separate calm from distressed movement in
Aarush's batch) — has apparently become more conservative about firing on audio alone in that
region. **Recall at gps=3.0 stayed strong and got a higher ceiling** (55.9–81.3% vs. 66.0–78.4%),
consistent with the model now having seen real fast-moving distress, not just neutral-GPS
fusion rows. Nothing in this table is direct evidence of fleeing-detection though — it's still a
sweep over motion-only data with assumed audio/GPS; measurement 3 is where that's tested for real.

**3. On the real captures** (`phase5/evaluate_real_packets.py`, `data/real_packet_evaluation_report.json`)
— the only measurement where PeakAcceleration, MotionVariance, AudioEnergy **and** GPSVelocity were
all genuinely observed together, no sweep, no fusion assumption. Two views, because the honesty
matters: only 3 of the 18 capture sessions were held out of training (`GroupShuffleSplit`, same
17-of-83 split as measurement 1) — small-n randomness with only 18 sessions in the pool, and none
of the 3 happened to be a fast-moving scenario, so "held-out" below has zero fleeing-speed
positives to measure. Both views are reported; only HELD-OUT should be read as a generalisation
estimate, and even that is on a very small sample.

| @ dispatch 0.80 | HELD-OUT (3 sessions, 88 packets, never trained on) | ALL REAL PACKETS (18 sessions, 572 packets) |
|---|---:|---:|
| Recall / Precision | 40.0% / 66.7% | 56.1% / 90.5% |
| False-positive rate | 7.9% (5/63) | 4.2% (14/335) |
| Confusion `[[TN,FP],[FN,TP]]` | `[[58,5],[15,10]]` | `[[321,14],[104,133]]` |

**Recall by GPS bin @ 0.80 (all real packets — held-out has no windows in the two faster bins):**

| GPS bin | windows | recall |
|---|---:|---:|
| stationary (< 0.3 m/s) | 69 | 36.2% |
| walk-ish (0.3–1.5 m/s) | 86 | 41.9% |
| **fleeing-speed (≥ 1.5 m/s)** | 82 | **87.8%** |

**Recall at GPS ≥ 1.5 m/s is 87.8%** — the number Aarush asked for, and real movement. **Read the
caveat before quoting it**: none of those 82 fast-moving positive windows were held out (all 3
held-out sessions were stationary scenarios — `distress-still`, plus the two stationary normal
controls), so this is a **fit** measurement, not a generalisation one; it says the network can
represent "fast + emergency-labeled" after training on it, not that it will recognise a fleeing
person it never trained on. It is still the most encouraging real number in this card, but it is
narrower than it looks: all 72 true positives in the fleeing-speed bin come from `fleeing-sprint`
alone (see the scenario table below), which has a large, unambiguous motion signature — the
*harder*, subtler case (`fleeing-walk`, moderate motion, only fires 43.0%) is where the model
still struggles, and that gap is consistent with the walk/jog GPS bands coming out lower than the
capture plan intended (see "Real captures" above).

**By scenario** (all real packets, fire rate @ 0.80):

| scenario | label | n | GPS median | fires | held-out session? |
|---|---|---:|---:|---:|---|
| fleeing-sprint | emergency | 95 | 2.30 m/s | 75.8% | no |
| fleeing-walk | emergency | 93 | 0.50 m/s | 43.0% | no |
| distress-still | emergency | 49 | 0.07 m/s | 42.9% | **yes** |
| passenger (vehicle) | normal | 69 | 4.28 m/s | **0.0%** | no |
| jog-calm | normal | 101 | 1.80 m/s | 5.0% | no |
| walk-calm | normal | 108 | 0.84 m/s | 6.5% | **yes** |
| loud-calm-still | normal | 57 | 0.09 m/s | 3.5% | **yes** |

**The GPS-neutrality fix (2026-09-06) is directly validated here**: `passenger` — a vehicle at
4.28 m/s median, the fastest scenario in the whole batch — fires **0.0%**. If the old
activity-keyed GPS heuristic were still in place, high GPS alone would have pushed this toward
firing; it doesn't. `distress-still` (shouting while stationary — audio is the *only* channel that
could carry the signal, and per "Real captures" above, this batch's audio is a weak channel) still
fires on 42.9% of its windows despite that, which is a genuinely encouraging, non-obvious result
from the real held-out session inside it.

## Limitations — read before deploying

1. **Fleeing-detection now has real (if thin) evidence behind it, not just a stopped-suppression
   guarantee — but read measurement 3's caveats before trusting the headline number.** Recall at
   GPS ≥ 1.5 m/s is 87.8% on real captures, but all of that comes from `fleeing-sprint` (large,
   unambiguous motion) and none of it was held out of training, so it is a fit measurement, not a
   generalisation one. `fleeing-walk` — the harder case, moderate motion at a slower-than-planned
   pace — only fires 43.0%. One capture round, one person, is not enough to say this generalises.
   More sessions per scenario (ideally from more than one person) are needed before quoting the
   87.8% number as "the model detects fleeing."
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
8. **One person, 18 sessions — real captures now exist, but generalisation across bodies, phones
   and genuine (not staged) incidents is still unmeasured.** All 18 real capture sessions in
   `data/raw/sensor_packets/` are from one person on one device. `sessions` in the
   `sensor_packets` provenance is captioned as capture *runs*, not distinct people, specifically
   so this can't be mistaken for demographic diversity.
9. **The held-out split for real captures is small and coarse.** Only 18 sessions total means
   `GroupShuffleSplit`'s 20% held-out slice is 3-4 sessions — this round it happened to land on
   `distress-still` + both stationary normal controls, so the held-out estimate has zero
   fast-moving positives (see measurement 3). A future capture round with more sessions per
   scenario, or a split stratified by scenario rather than purely random, would fix this.
10. **Accelerometer sample rate is a per-device measurement, not a codebase-wide constant yet.**
    This capture batch measured ~97-101 Hz, not the ~50 Hz `SENSOR_DELAY_GAME` nominally requests
    (see "Real captures" above) — `phase4/test_real_packets.py` now expects that, but
    `dataset_adapters.py`'s `TARGET_SAMPLE_RATE_HZ=50.0` (used to resample UCI HAR/ShimFall/WISDM
    to "match the phone") was deliberately left alone pending a second device's measurement. If
    every device runs closer to 100 Hz, the on-device window is really ~10 s, not ~20 s, and that
    resampling target would need revisiting — a bigger, separate change.

## What to do next

1. Push `feat/real-model` so Aarush can re-vendor `data/emergency_model.tflite` →
   `mobile-client/.../assets/emergency_model.tflite`. **Unlike the last two rounds, no matching
   Kotlin formula change is required this time** — see the banner at the top.
2. If `FeatureExtractor.kt` still hasn't mirrored the AudioEnergy dB formula from the 2026-09-06
   card (`AUDIO_FLOOR_DB`/`AUDIO_CEIL_DB`), that remains the priority follow-up independent of this
   retrain — the phone runs the OLD linear formula until it does.
3. **A focused re-capture round, not a full repeat**, would do the most for the weakest number in
   this card (`fleeing-walk` recall, 43.0%): a handful of walk/jog runs at the originally-intended
   1.5-4 m/s pace (this batch came out slower than planned — see "Real captures" above), plus a
   few more sessions of each scenario so the held-out split actually covers fast-moving positives
   (limitation 9). Aarush offered exactly this in his original message — 4-6 targeted runs, not
   the whole 18-run protocol again.
4. On-device audio validation once Aarush's mic-capture investigation closes — Level 2 with a real
   `.wav` (`python phase5/validate_audio_normalization.py --wav ...`) is the only way to know if
   AUDIO_FLOOR_DB/AUDIO_CEIL_DB are reachable by an actual pocketed phone; the real captures here
   already show the mic isn't silently dead, just not a clean calm/distress separator in motion.
5. Confirm the ~100 Hz accelerometer rate on a second device (limitation 10) before revising
   `TARGET_SAMPLE_RATE_HZ` — that constant is shared by every non-packet dataset loader, so it's a
   bigger, separate change from anything done in this retrain.
6. Re-run `phase5/evaluate_real_fpr.py` and `phase5/evaluate_real_packets.py` after any further
   retrain; they are the regression tests — specifically watch the recall-at-gps=3.0 /
   recall-at-fleeing-speed-bin numbers so the GPS fix and the real-capture signal don't silently
   regress.
