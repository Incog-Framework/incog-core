# What real data this model needs, and why it does not have it yet

> **UPDATE (2026-09-02): real data has been fetched and the deployed model
> has been measured on it.** See **REAL_DATA_FINDINGS.md** — false-positive
> rate is 0.6%–39.8% depending on assumed audio/GPS, and the model fires on
> 40% of walking-downstairs windows. The retraining blocker below still
> stands: no public corpus pairs motion with audio and GPS.
>
> Fetch everything with `python phase5/fetch_datasets.py --all`.

## Current state — read this before quoting any number

`data/training_data.csv` is **30 hand-written rows**. They are linearly
separable on `PeakAcceleration` alone:

| class | PeakAcceleration | MotionVariance | AudioEnergy |
|---|---|---|---|
| Normal (15 rows) | 8.9 – 14.0 | 0.20 – 1.10 | 0.04 – 0.25 |
| Emergency (15 rows) | 16.5 – 26.1 | 12.4 – 40.2 | 0.55 – 0.91 |

There is no overlap in any feature. A single threshold at 15 separates the
whole dataset perfectly, which is why every metric comes out at 1.00 — the
score measures the dataset, not the model.

The reported 100% accuracy / 0% false-positive rate is *not* evidence of
production performance and must not be presented as such.
`phase5/train_tflite_model.py` stamps `production_claim_supported: false` into
the metrics file on every synthetic run so this cannot be quoted by accident.

Real motion corpora **are** now present (`python phase5/fetch_datasets.py
--dataset uci_har,shimfall`) and the deployed model has been measured against
them — see REAL_DATA_FINDINGS.md. What is still missing is data that pairs
motion with audio and GPS, which is what a retrain needs.

## The blocking problem: no single corpus has all five features

The model needs `[PeakAcceleration, MotionVariance, AudioEnergy, GPSVelocity,
PossibleFall]` for the *same moment in time*. Nothing public provides that.

| Corpus | Motion | Falls | Audio | GPS | Verdict |
|---|---|---|---|---|---|
| **ShimFall&ADL** | yes, 50 Hz | **yes**, 9 fall types | no | no | **fetched — the positive source** |
| ~~SisFall~~ | — | — | — | — | **host unreachable (2026-09-02)** |
| **UCI HAR** | yes, 50 Hz | no | no | no | best realistic negatives |
| **WISDM** | yes, 20 Hz | no | no | no | weaker negatives (see below) |
| **RAVDESS** | no | no | **yes** | no | audio scale only |
| **Real captures** | yes | if staged | yes | yes | **the only complete source** |

Combining them means assuming motion and audio are statistically independent
— i.e. pairing a SisFall fall with a RAVDESS scream that has nothing to do
with it. That is a real modelling decision with real consequences, so
`load_combined()` records it in provenance rather than hiding it, and
`prepare()` refuses to train on rows with NaN features instead of quietly
imputing.

## Windowing — must match the phone

Read off the Kotlin, not assumed:

| Property | Value | Source |
|---|---|---|
| Accelerometer rate | ~50 Hz | `SensorCollector`, `SENSOR_DELAY_GAME` |
| History bound | 1000 samples ≈ **20 s** | `SensorCollector.MAX_SAMPLES` |
| Inference cadence | every **2 s** | `GhostStateService.SNAPSHOT_INTERVAL_MS` |
| Accel units | m/s², **gravity included** | Android `TYPE_ACCELEROMETER` |
| Audio | 16 kHz mono PCM16 | `AudioBufferCollector` |

So one training row = one ~20 s window, stepped by 2 s. A corpus at another
rate is resampled to 50 Hz first — `MotionVariance` is rate-sensitive, and
WISDM at 20 Hz upsampled to 50 Hz cannot recover high-frequency content, so
its peak/variance are biased **low**.

## What to supply, in priority order

### 1. Real SensorPacket captures — by far the most valuable

Nothing else removes the fusion assumption. Even a few hundred windows of
genuine captures is worth more than all four public corpora combined,
because the features arrive already correlated and already on the device's
own scale.

```
data/raw/sensor_packets/normal/*.json      # walking, pocket, bag, driving,
                                           # stairs, phone drops, exercise
data/raw/sensor_packets/emergency/*.json   # staged incidents
```

Ask Aarush to serialise `buildSensorPacket()` to disk during Ghost State —
he already builds the packet every 2 s and currently only logs it.

**Negatives matter more than positives here.** The <5% false-positive target
is a statement about ordinary life, so it needs hours of ordinary life. A
phone dropping on a desk produces >15 m/s² and will trip `PossibleFall` — how
often that happens in a normal day is exactly the unknown.

### 2. ShimFall&ADL — real falls  *(fetched)*

<https://zenodo.org/records/3901285> — `python phase5/fetch_datasets.py
--dataset shimfall`

35 subjects, chest Shimmer v2, **50 Hz** (the device rate), 9 fall types +
6 ADLs, 101 samples (2.02 s) per event. CC-BY-NC-ND-4.0 — academic use, and
it stays gitignored.

Two caveats the loader records in provenance: the depositors do not state
**units**, so 1 g is recovered from the dataset's own static postures
(≈35.43 units, scale 0.2768); and events are 2.02 s while the phone scores up
to 20 s, so `MotionVariance` is an upper bound and only `PeakAcceleration` is
device-comparable.

> **SisFall is unreachable.** `sistemic.udea.edu.co` refused connections when
> checked on 2026-09-02. ShimFall replaces it in the same role. The SisFall
> loader is kept in case the host returns.

### 3. UCI HAR — realistic negatives  *(fetched)*

<https://archive.ics.uci.edu/dataset/240/> — `python phase5/fetch_datasets.py
--dataset uci_har`

30 subjects, waist-worn phone, 50 Hz, 10,299 windows, all ADLs (so all true
negatives). Ships subject IDs and activity labels, which is what makes
subject-level splitting and the per-activity false-positive breakdown
possible.

Archive 240 ships the **`Inertial Signals`** distribution: `total_acc_*` in g,
gravity included, pre-windowed to 128 samples (2.56 s) with 50% overlap. The
loader uses it, and prefers the continuous `RawData/acc_exp*.txt` layout
(HAPT, archive 341) when present because that allows true 20 s windows.

### 4. RAVDESS — audio scale only

<https://zenodo.org/record/1188976>

Answers "what does a scream read as on the 0–1 scale", not "what does the
model do". Studio recordings at close mic distance, so it bounds the loud end
optimistically.

## Once real data is present

```bash
python phase5/dataset_adapters.py                     # confirm it is seen
python phase5/train_tflite_model.py --dataset sensor_packets
python phase5/train_tflite_model.py --dataset sensor_packets --write-model
python generate_contract_fixtures.py                  # refresh model hash
```

Then re-vendor the new `.tflite` to Aarush — see "If the model is retrained"
in `CLAUDE.md`. The phone keeps running the old model otherwise.

Evaluation reports accuracy, precision, recall, F1, confusion matrix, ROC-AUC,
false-positive rate and a threshold sweep — at **both** 0.50 and 0.80, since
0.80 is the cutoff that actually dispatches an alert.

### Splitting — implemented

`train_test_split` with stratification is fine for the synthetic rows. For
real windowed data it **leaks**: windows overlap heavily and one person
contributes many of them, so a random split puts near-duplicates on both
sides and inflates every metric.

`train_tflite_model.py` now splits by **subject** (`GroupShuffleSplit`)
whenever the corpus supplies a `Subject` column and has at least 4 subjects,
and records which split was used in the metrics file as `split` /
`split_leaks_across_subjects`. When no subject information exists it falls
back to a random split and prints a warning.
