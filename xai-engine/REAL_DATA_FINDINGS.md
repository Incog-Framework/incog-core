# Real-data evaluation of the deployed model

**Reproduce:**
```bash
python phase5/fetch_datasets.py --dataset uci_har,shimfall
python phase5/evaluate_real_fpr.py --dataset uci_har,shimfall
```
Raw output: `data/real_evaluation_report.json`.

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
