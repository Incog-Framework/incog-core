# Real-data evaluation of the deployed model

> **UPDATE (2026-09-06): retrained twice more — a GPS fix, then an AudioEnergy
> rescale.** Everything below this banner describes the ORIGINAL model (30
> synthetic rows) and is kept for the before/after comparison. Full current
> numbers and method: **MODEL_CARD.md**.
>
> **2026-09-05 retrain:** trained on `phase5/dataset_adapters.py:load_fusion()`
> — 10,824 real UCI HAR + ShimFall motion windows, each paired with a
> resampled RAVDESS audio value and, at the time, a hand-set GPS-by-activity
> heuristic that set every fall's `GPSVelocity` to 0. The false-positive fix
> was real (range dropped from **0.6%-39.8%** to **0.0%-10.3%**, every one of
> the 12 real activities fired at **0%** at the defensible cell), but Aarush
> caught a safety-critical side effect: because every fall was labeled
> GPS=0, the model learned "moving fast ⇒ not an emergency" — **recall
> collapsed to 0% whenever assumed GPSVelocity >= 1.5 m/s**. That would
> suppress the alert exactly when someone is fleeing an attacker at speed.
>
> **2026-09-06 retrain (current):** `load_fusion()`'s GPS assignment was
> changed so `GPSVelocity` is now sampled uniformly (0-3 m/s) **independent
> of Activity and of the Emergency label** — pinned by
> `phase5/test_dataset_adapters.py:test_fusion_gps_velocity_is_not_correlated_with_the_label`.
> Recall at GPS=3.0 is now **72%-95%**, not 0%, at every audio level tested.
> The false-positive range held at **0.0%-5.6%**, so the fix did not reopen
> the problem the first retrain solved. This does not teach the model to
> detect fleeing — it only stops the model from actively working against
> that scenario; see MODEL_CARD.md Limitations for why.
>
> **2026-09-06, AudioEnergy rescale:** the RAVDESS audio validation closed
> Level 2 and found the old linear `audioRmsEnergy / 32768` scale dead - real
> distress speech read median 0.0013, p95 0.085, far below the 0.55-0.91 old
> synthetic data assumed. Aarush's initial call was to defer the rescale; he
> then asked for it directly. `sensor_packet_adapter.py` now applies a dB
> scale - `AUDIO_FLOOR_DB=-32.0`, `AUDIO_CEIL_DB=-20.0`, fitted so RAVDESS
> distress p95 -> 0.88 and non-distress p95 -> 0.18, matching his target.
> **This is a lockstep change Kotlin has not mirrored yet** - vendoring this
> retrained model without the matching `FeatureExtractor.kt` change creates
> WORSE train/serve skew on AudioEnergy than before the rescale, not a
> no-op. Full derivation and the retrained numbers: MODEL_CARD.md.

**Reproduce (the OLD model's numbers, for comparison):**
```bash
python phase5/fetch_datasets.py --dataset uci_har,shimfall
python phase5/evaluate_real_fpr.py --dataset uci_har,shimfall   # now scores the NEW model
```
Raw output: `data/real_evaluation_report.json` — this file is overwritten by
whichever model is currently at `data/emergency_model.tflite`, so it now
reflects the retrained model, not the one this write-up was originally about.

Below is the original (pre-retrain) write-up, unedited, as the historical
record of why the retrain happened.

---

The model was **not** retrained and `emergency_model.tflite` is **unchanged** —
it is still byte-identical to the asset `mobile-client` ships. This measures
the artifact that is actually deployed.

## Headline

**The `<5%` false-positive target is not demonstrably met, and the model fires
on ordinary activity far more than intended.**

| | value |
|---|---|
| Real windows scored | **10,824** (10,509 negative / 315 positive) |
| Distinct subjects | **65** (30 UCI HAR + 35 ShimFall) |
| False-positive rate @ 0.80 | **0.6% – 39.8%** across the audio/GPS sweep |
| Most defensible single cell | **5.8%** — above the 5% target |
| Recall on real falls @ 0.80 | 67.9% – 99.4% (87.6% at the same cell) |

## The specific defect

`PossibleFall` is defined as `PeakAcceleration > 15 m/s²`. On real data that
rule does not identify falls — it identifies *movement*:

| Activity | windows | `peak > 15` | model fires |
|---|---:|---:|---:|
| LAYING | 1944 | 0.0% | 0.0% |
| SITTING | 1777 | 0.0% | 0.0% |
| STANDING | 1906 | 0.0% | 0.0% |
| WALKING | 1722 | 73.8% | 0.2% |
| WALKING_UPSTAIRS | 1544 | 93.5% | 0.5% |
| **WALKING_DOWNSTAIRS** | 1406 | 99.6% | **40.3%** |
| **adl_jump** | 35 | 100.0% | **100.0%** |
| adl_bendingandpickingup | 35 | 25.7% | 0.0% |
| adl_liedown | 35 | 2.9% | 2.9% |

Walking downstairs raises an alert **two times in five**. Jumping raises one
**every time**. Both are ordinary, non-emergency activities.

`peak > 15` fires on **39.8%** of all ordinary-activity windows. Static
postures are clean (0%), so the model is not broken everywhere — it fails
specifically on vigorous-but-normal motion.

## Why the model learned this

`data/training_data.csv` is 30 synthetic rows whose Normal class caps
`PeakAcceleration` at **14.0** and whose Emergency class starts at **16.5**,
with no overlap in any feature. Real ADLs routinely reach 20–25 m/s². The
model learned a boundary that simply does not exist in the world, and the
100% accuracy on that dataset measured the dataset, not the model.

## The honesty caveat — read before quoting a number

No public motion corpus records audio or GPS, but the model needs all five
features. Rather than silently imputing the two missing channels, the
evaluator **sweeps** them and reports a surface:

| audio ↓ / gps → | 0.0 | 0.5 | 1.5 | 3.0 |
|---|---:|---:|---:|---:|
| 0.00 | 17.8% | 12.2% | 4.6% | 0.6% |
| 0.05 | 20.9% | 13.9% | **5.8%** | 0.6% |
| 0.15 | 32.5% | 19.1% | 8.2% | 1.0% |
| 0.35 | 39.8% | 38.4% | 14.8% | 2.9% |
| 0.60 | 39.8% | 39.8% | 36.5% | 6.2% |

The spread is the honest uncertainty. `GPSVelocity` dominates it, because the
synthetic training data put emergencies at ~0 m/s and normals at 0.2–4.0 —
so "stationary" alone pushes the model toward firing. **A single quoted FPR
would be meaningless without saying which cell it came from.**

This is exactly why real captures matter: they are the only source that
measures all five channels *for the same moment*.

## Further limitations

- **Window length.** The phone scores up to 20 s (1000 samples @ 50 Hz). UCI
  HAR Inertial Signals are 2.56 s and ShimFall events are 2.02 s.
  `PeakAcceleration` carries across window lengths; `MotionVariance` does
  **not** — over a short active burst it is much higher than over 20 s of
  mostly-quiet history. Treat the variance-driven part as an upper bound.
  The UCI HAP­T/`RawData` distribution would fix this; `load_uci_har()`
  already prefers it when present.
- **Body position.** UCI HAR is waist-mounted (close to a trouser pocket);
  ShimFall is chest-strapped. Neither is a phone loose in a bag.
- **Staged falls.** ShimFall falls are volunteers onto a mat, not real
  incidents.
- **ShimFall units are inferred.** The depositors do not state units; 1 g was
  recovered from the dataset's own static postures (1 g ≈ 35.43 units,
  scale 0.2768). Physically sound, but an inference — recorded in
  `provenance.units_calibration` so it can be challenged.
- **Overlapping windows.** UCI HAR windows overlap 50%, so the 10,299 are not
  fully independent samples.

## What was deliberately *not* done

- **No retrain.** Fixing this needs positives paired with real audio and GPS.
  Training on motion-only would mean either fabricating the two missing
  channels or dropping to a 3-feature model — and the 5-input tensor is a
  locked contract with `FeatureVector.toModelInput()` in `mobile-client`.
  That is a cross-team change, not a unilateral one.
- **No model replacement.** `emergency_model.tflite` is untouched, so the
  hash still matches Aarush's vendored asset.

## Recommendation

1. **Get real captures.** They are now clearly the critical path — they are
   the only way to close the audio/GPS sweep into a single number and the
   only way to retrain honestly.
2. **Expect the `> 15` fall rule to change.** It is the direct cause of the
   downstairs/jump false positives. A duration or jerk criterion, or making
   `PossibleFall` a learned rather than hand-set feature, are the obvious
   candidates — but that changes the feature contract, so it needs Aarush.
3. **Re-run this evaluation after any retrain.** It is the regression test
   for real-world behaviour, and it is cheap.
4. **Do not quote the 100% synthetic metrics anywhere.** `tflite_model_metrics.json`
   already carries `production_claim_supported: false`.

## Data sources

| Corpus | Role | Licence |
|---|---|---|
| UCI HAR (archive 240) | 10,299 negatives, 30 subjects, 50 Hz | UCI terms; Anguita et al., ESANN 2013 |
| ShimFall&ADL (Zenodo 3901285) | 315 falls + 210 ADLs, 35 subjects, 50 Hz | CC-BY-NC-ND-4.0; Althobaiti et al., Sensors 2020 |
| SisFall | **unreachable** — host refuses connections (2026-09-02) | — |

Nothing is committed: `data/raw/` is gitignored.
