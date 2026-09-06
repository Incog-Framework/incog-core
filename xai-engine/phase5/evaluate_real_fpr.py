"""Measure the DEPLOYED model's false-positive rate on real human activity.

This does not retrain anything. It scores data/emergency_model.tflite - the
exact artifact vendored into mobile-client - over real accelerometer
recordings, windowed to the on-device geometry, and reports how often it
would have fired.

WHY THIS RATHER THAN A RETRAIN
------------------------------
The <5% false-positive target is a claim about ordinary life: how often does
an alert fire when nothing is wrong. That question is answered entirely by
NEGATIVES, and real negatives are abundant (UCI HAR, WISDM are ADLs only).
Retraining additionally needs real positives paired with real audio and GPS,
which no public corpus provides - see DATA_REQUIREMENTS.md. So the deployed
model can be honestly measured today even though it cannot yet be honestly
retrained.

THE UNMEASURED CHANNELS - read this before quoting a number
-----------------------------------------------------------
None of these corpora record audio or GPS. The model takes five features, so
two of them have to come from somewhere. Rather than silently imputing a
convenient value, this script sweeps AudioEnergy and GPSVelocity across
plausible ranges and reports FPR as a SURFACE.

That matters because the direction of the bias is not obvious. In the
synthetic training data, emergencies have GPSVelocity near 0 and normals have
0.2-4.0, so assuming "stationary" pushes the model TOWARD firing. A single
imputed value could understate or overstate the true rate by a lot; the
spread across the sweep is the honest uncertainty.

A headline number is only quoted for the sweep cell that is most defensible
for the corpus (quiet room, and the GPS speed implied by the activity), and
it is always reported alongside the full range.

USAGE
    python phase5/evaluate_real_fpr.py --dataset uci_har
    python phase5/evaluate_real_fpr.py --dataset uci_har,wisdm
    python phase5/evaluate_real_fpr.py --dataset shimfall     (has positives)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "phase5"))
sys.path.insert(0, str(BASE_DIR / "phase4"))

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from dataset_adapters import (              # noqa: E402
    DatasetUnavailable,
    FEATURE_ORDER,
    TARGET,
    load_dataset
)

MODEL_PATH = BASE_DIR / "data" / "emergency_model.tflite"
REPORT_PATH = BASE_DIR / "data" / "real_evaluation_report.json"

CLASSIFICATION_THRESHOLD = 0.50
DECISION_THRESHOLD = 0.80
FALSE_POSITIVE_TARGET = 0.05

# The two channels no motion corpus records. Swept, never silently imputed.
AUDIO_SWEEP = [0.0, 0.05, 0.15, 0.35, 0.60]
GPS_SWEEP = [0.0, 0.5, 1.5, 3.0]

# The cell quoted as the headline for a motion corpus: a quiet indoor lab
# (low but non-zero audio) and walking-pace GPS. Both are defensible for
# UCI HAR / WISDM / ShimFall, which were recorded indoors while moving.
DEFENSIBLE_AUDIO = 0.05
DEFENSIBLE_GPS = 1.5


def load_interpreter():
    import tensorflow as tf

    interpreter = tf.lite.Interpreter(model_path=str(MODEL_PATH))
    interpreter.allocate_tensors()

    return (
        interpreter,
        interpreter.get_input_details()[0]["index"],
        interpreter.get_output_details()[0]["index"]
    )


def score(features):
    """Confidence for each row, through the real TFLite graph."""

    interpreter, input_index, output_index = load_interpreter()

    values = np.asarray(features, dtype=np.float32)
    out = np.empty(len(values), dtype=np.float64)

    for row in range(len(values)):
        interpreter.set_tensor(input_index, values[row:row + 1])
        interpreter.invoke()
        out[row] = float(interpreter.get_tensor(output_index)[0][0])

    return out


def build_matrix(frame, audio_energy, gps_velocity):
    """Feature matrix in model order, with the two channels substituted in."""

    return np.column_stack([
        frame["PeakAcceleration"].to_numpy(dtype=np.float32),
        frame["MotionVariance"].to_numpy(dtype=np.float32),
        np.full(len(frame), audio_energy, dtype=np.float32),
        np.full(len(frame), gps_velocity, dtype=np.float32),
        frame["PossibleFall"].to_numpy().astype(np.float32)
    ])


def rate(confidences, threshold):
    return float(np.mean(confidences >= threshold)) if len(confidences) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="uci_har")
    parser.add_argument(
        "--max-windows",
        type=int,
        default=20000,
        help="cap for runtime; windows are subsampled evenly, not truncated"
    )
    arguments = parser.parse_args()

    names = [n.strip() for n in arguments.dataset.split(",") if n.strip()]

    frames = []
    provenances = []

    for name in names:
        try:
            frame, provenance = load_dataset(name)
        except DatasetUnavailable as error:
            print(error)
            raise SystemExit(2)

        frames.append(frame)
        provenances.append(provenance)

    import pandas as pd

    data = pd.concat(frames, ignore_index=True)

    if len(data) > arguments.max_windows:
        step = len(data) // arguments.max_windows
        data = data.iloc[::step].reset_index(drop=True)

    negatives = data[data[TARGET] == 0]
    positives = data[data[TARGET] == 1]

    print("=" * 68)
    print("REAL-DATA EVALUATION OF THE DEPLOYED MODEL")
    print("=" * 68)
    print(f"\nModel    : data/emergency_model.tflite  (NOT retrained)")
    print(f"Datasets : {', '.join(names)}")
    print(f"Windows  : {len(data)}  ({len(negatives)} negative, "
          f"{len(positives)} positive)")

    for provenance in provenances:
        print(f"\n  [{provenance['dataset']}] {provenance['caveat']}")

    # ------------------------------------------------------------
    # Motion feature distribution - the interesting part on its own
    # ------------------------------------------------------------

    print("\n" + "-" * 68)
    print("REAL MOTION FEATURES (before the model sees them)")
    print("-" * 68)

    for label, subset in (("negatives", negatives), ("positives", positives)):
        if not len(subset):
            continue

        peak = subset["PeakAcceleration"]
        variance = subset["MotionVariance"]
        fall_rate = float(subset["PossibleFall"].mean())

        print(
            f"  {label:10s} peak: med={peak.median():7.2f} "
            f"p95={peak.quantile(0.95):7.2f} max={peak.max():7.2f}   "
            f"var: med={variance.median():8.2f}"
        )
        print(
            f"             PossibleFall (peak > 15) fires on "
            f"{fall_rate:.1%} of these windows"
        )

    # ------------------------------------------------------------
    # The sweep
    # ------------------------------------------------------------

    print("\n" + "-" * 68)
    print("FALSE-POSITIVE RATE at the 0.80 dispatch threshold")
    print("  rows = assumed AudioEnergy, cols = assumed GPSVelocity (m/s)")
    print("-" * 68)

    header = "  audio\\gps " + "".join(f"{g:>10.1f}" for g in GPS_SWEEP)
    print(header)

    sweep = []
    headline = None

    for audio in AUDIO_SWEEP:
        cells = []

        for gps in GPS_SWEEP:
            confidences = score(build_matrix(negatives, audio, gps))

            false_positive_rate = rate(confidences, DECISION_THRESHOLD)

            entry = {
                "audio_energy": audio,
                "gps_velocity": gps,
                "false_positive_rate_at_0.80": false_positive_rate,
                "false_positive_rate_at_0.50": rate(
                    confidences, CLASSIFICATION_THRESHOLD
                ),
                "windows": int(len(negatives))
            }

            sweep.append(entry)
            cells.append(false_positive_rate)

            if audio == DEFENSIBLE_AUDIO and gps == DEFENSIBLE_GPS:
                headline = entry

        print(
            f"  {audio:>9.2f} "
            + "".join(f"{c:>9.1%} " for c in cells)
        )

    rates = [entry["false_positive_rate_at_0.80"] for entry in sweep]

    print(
        f"\n  range across the sweep: {min(rates):.1%} - {max(rates):.1%}"
    )

    if headline:
        print(
            f"  most defensible cell (audio={DEFENSIBLE_AUDIO}, "
            f"gps={DEFENSIBLE_GPS}): "
            f"{headline['false_positive_rate_at_0.80']:.1%}"
        )

    # ------------------------------------------------------------
    # Which activities actually trip it - the actionable part
    # ------------------------------------------------------------

    per_activity = []

    if "Activity" in negatives.columns:
        print("\n" + "-" * 68)
        print(
            f"FALSE POSITIVES BY ACTIVITY "
            f"(audio={DEFENSIBLE_AUDIO}, gps={DEFENSIBLE_GPS})"
        )
        print("-" * 68)
        print(
            f"  {'activity':<24}{'windows':>9}{'peak>15':>10}"
            f"{'fires':>9}"
        )

        for activity, group in negatives.groupby("Activity"):
            confidences = score(
                build_matrix(group, DEFENSIBLE_AUDIO, DEFENSIBLE_GPS)
            )

            entry = {
                "activity": str(activity),
                "windows": int(len(group)),
                "possible_fall_rate": round(
                    float(group["PossibleFall"].mean()), 4
                ),
                "false_positive_rate_at_0.80": rate(
                    confidences, DECISION_THRESHOLD
                )
            }

            per_activity.append(entry)

            print(
                f"  {entry['activity']:<24}{entry['windows']:>9}"
                f"{entry['possible_fall_rate']:>9.1%}"
                f"{entry['false_positive_rate_at_0.80']:>9.1%}"
            )

        per_activity.sort(
            key=lambda item: item["false_positive_rate_at_0.80"],
            reverse=True
        )

    # ------------------------------------------------------------
    # Recall, when the corpus has real positives
    # ------------------------------------------------------------

    recall_sweep = []

    if len(positives):
        print("\n" + "-" * 68)
        print("RECALL on real positives at the 0.80 threshold")
        print("-" * 68)
        print(header)

        for audio in AUDIO_SWEEP:
            cells = []

            for gps in GPS_SWEEP:
                confidences = score(build_matrix(positives, audio, gps))
                recall = rate(confidences, DECISION_THRESHOLD)

                recall_sweep.append({
                    "audio_energy": audio,
                    "gps_velocity": gps,
                    "recall_at_0.80": recall,
                    "windows": int(len(positives))
                })
                cells.append(recall)

            print(
                f"  {audio:>9.2f} "
                + "".join(f"{c:>9.1%} " for c in cells)
            )

    # ------------------------------------------------------------
    # Verdict
    # ------------------------------------------------------------

    print("\n" + "=" * 68)

    worst = max(rates)
    best = min(rates)

    if worst < FALSE_POSITIVE_TARGET:
        verdict = "MET_ACROSS_ENTIRE_SWEEP"
        print(
            f"False-positive rate is below the "
            f"{FALSE_POSITIVE_TARGET:.0%} target for EVERY assumption "
            f"about the unmeasured channels (worst case {worst:.1%})."
        )
    elif best >= FALSE_POSITIVE_TARGET:
        verdict = "MISSED_ACROSS_ENTIRE_SWEEP"
        print(
            f"False-positive rate EXCEEDS the {FALSE_POSITIVE_TARGET:.0%} "
            f"target for every assumption (best case {best:.1%}). The target "
            f"is not met on real activity data."
        )
    else:
        verdict = "DEPENDS_ON_UNMEASURED_CHANNELS"
        print(
            f"False-positive rate straddles the "
            f"{FALSE_POSITIVE_TARGET:.0%} target ({best:.1%} - {worst:.1%}) "
            f"depending on assumed audio/GPS. It cannot be called met or "
            f"missed without real captures that measure those channels."
        )

    print("=" * 68)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "data/emergency_model.tflite",
        "model_retrained_by_this_script": False,
        "note": (
            "This script only scores whatever data/emergency_model.tflite "
            "currently is - it never trains. Whether THAT model was itself "
            "produced by a retrain is recorded in data/tflite_model_metrics.json "
            "(data_provenance.dataset), not here."
        ),
        "datasets": names,
        "provenance": provenances,
        "windows_total": int(len(data)),
        "windows_negative": int(len(negatives)),
        "windows_positive": int(len(positives)),
        "decision_threshold": DECISION_THRESHOLD,
        "false_positive_target": FALSE_POSITIVE_TARGET,
        "unmeasured_channels": {
            "features": ["AudioEnergy", "GPSVelocity"],
            "reason": (
                "no public motion corpus records audio or GPS; these were "
                "swept, not imputed"
            ),
            "audio_sweep": AUDIO_SWEEP,
            "gps_sweep": GPS_SWEEP
        },
        "false_positive_sweep": sweep,
        "false_positive_rate_range": [min(rates), max(rates)],
        "headline_cell": headline,
        "recall_sweep": recall_sweep,
        "false_positives_by_activity": per_activity,
        "verdict": verdict,
        "motion_feature_summary": {
            "negative_peak_median": (
                float(negatives["PeakAcceleration"].median())
                if len(negatives) else None
            ),
            "negative_possible_fall_rate": (
                float(negatives["PossibleFall"].mean())
                if len(negatives) else None
            ),
            "positive_peak_median": (
                float(positives["PeakAcceleration"].median())
                if len(positives) else None
            )
        }
    }

    REPORT_PATH.write_text(json.dumps(report, indent=4), encoding="utf-8")

    print(f"\nReport: {REPORT_PATH}")


if __name__ == "__main__":
    main()
