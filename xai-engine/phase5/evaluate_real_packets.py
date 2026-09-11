"""Honest evaluation of the retrained model against Aarush's real captures.

WHY THIS IS A SEPARATE SCRIPT FROM evaluate_real_fpr.py
---------------------------------------------------------
evaluate_real_fpr.py sweeps AudioEnergy/GPSVelocity because its corpora
(UCI HAR, ShimFall, WISDM) don't record either channel - the sweep is the
honest way to report a number when two of five inputs are unmeasured.

The real SensorPacket captures under data/real_packets/ (mirrored into
data/raw/sensor_packets/ for training - see CAPTURE_PROTOCOL.md) have NO
unmeasured channels: audio and GPS were captured for the same moment as the
motion. Sweeping them here would throw away real information, so this script
scores the actual observed five-feature rows and reports a real confusion
matrix - no assumption, no surface.

TRAIN/TEST HONESTY
-------------------
train_tflite_model.py --dataset fusion,sensor_packets splits by Subject
(GroupShuffleSplit, RANDOM_SEED=42, test_size=0.2) so whole capture SESSIONS
land on one side only. This script reproduces that exact split (same seed,
same combined dataset) so it can separate:

  - HELD-OUT sessions: never seen in training -> the number that means
    something about generalisation.
  - TRAIN sessions: were fitted on -> reported for transparency only, not
    as evidence of anything.

Both are reported; only the held-out numbers should be quoted as evidence.

USAGE
    python phase5/evaluate_real_packets.py
    python phase5/evaluate_real_packets.py --model data/emergency_model.tflite
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "phase5"))

from dataset_adapters import (              # noqa: E402
    FEATURE_ORDER,
    TARGET,
    load_combined,
    load_dataset
)

REAL_PACKETS_DIR = BASE_DIR / "data" / "real_packets"
MANIFEST_PATH = REAL_PACKETS_DIR / "manifest.csv"
REPORT_PATH = BASE_DIR / "data" / "real_packet_evaluation_report.json"

RANDOM_SEED = 42
TEST_SIZE = 0.2                 # must match train_tflite_model.py's default
DECISION_THRESHOLD = 0.80
CLASSIFICATION_THRESHOLD = 0.50

GPS_BINS = [
    ("stationary (<0.3 m/s)", 0.0, 0.3),
    ("walk-ish (0.3-1.5 m/s)", 0.3, 1.5),
    ("fleeing-speed (>=1.5 m/s)", 1.5, float("inf"))
]


def load_session_scenarios():
    """sessionId -> {scenario, run, label} from data/real_packets/manifest.csv."""

    if not MANIFEST_PATH.exists():
        return {}

    frame = pd.read_csv(MANIFEST_PATH)
    lookup = {}

    for _, row in frame.iterrows():
        file_name = str(row["file"])
        # "capture-SESS-5262516D-1788963515299.json" -> "SESS-5262516D"
        parts = file_name.split("-")

        if len(parts) < 3:
            continue

        session_id = f"{parts[1]}-{parts[2]}"

        lookup[session_id] = {
            "scenario": row["name"],
            "run": int(row["run"]),
            "label": row["label"]
        }

    return lookup


def reproduce_training_split(subjects):
    """Which Subject groups train_tflite_model.py held out, deterministically.

    Same GroupShuffleSplit call, same seed, same test_size as
    train_tflite_model.py's --dataset fusion,sensor_packets run - this MUST
    stay in sync with that script's split call or "held out" here stops
    meaning "never seen in training".
    """

    from sklearn.model_selection import GroupShuffleSplit

    splitter = GroupShuffleSplit(
        n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_SEED
    )

    train_index, test_index = next(
        splitter.split(np.zeros(len(subjects)), groups=subjects)
    )

    held_out_groups = set(subjects.iloc[test_index])

    return held_out_groups


def load_interpreter(model_path):
    import tensorflow as tf

    interpreter = tf.lite.Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()

    return (
        interpreter,
        interpreter.get_input_details()[0]["index"],
        interpreter.get_output_details()[0]["index"]
    )


def score(model_path, frame):
    interpreter, input_index, output_index = load_interpreter(model_path)

    features = frame[FEATURE_ORDER].copy()
    features["PossibleFall"] = features["PossibleFall"].astype(np.float32)
    values = features.to_numpy(dtype=np.float32)

    out = np.empty(len(values), dtype=np.float64)

    for row in range(len(values)):
        interpreter.set_tensor(input_index, values[row:row + 1])
        interpreter.invoke()
        out[row] = float(interpreter.get_tensor(output_index)[0][0])

    return out


def confusion(y_true, confidences, threshold):
    predictions = (confidences >= threshold).astype(int)

    tn = int(np.sum((y_true == 0) & (predictions == 0)))
    fp = int(np.sum((y_true == 0) & (predictions == 1)))
    fn = int(np.sum((y_true == 1) & (predictions == 0)))
    tp = int(np.sum((y_true == 1) & (predictions == 1)))

    negatives = tn + fp
    positives = fn + tp

    return {
        "threshold": threshold,
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "confusion_matrix_layout": "[[TN, FP], [FN, TP]]",
        "false_positive_rate": round(fp / negatives, 4) if negatives else None,
        "recall": round(tp / positives, 4) if positives else None,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "negatives": negatives,
        "positives": positives
    }


def recall_by_gps_bin(frame, confidences, threshold):
    results = []

    positives = frame[frame[TARGET] == 1]
    positive_confidences = confidences[frame[TARGET].to_numpy() == 1]

    for label, low, high in GPS_BINS:
        mask = (positives["GPSVelocity"] >= low) & (positives["GPSVelocity"] < high)
        n = int(mask.sum())

        if n == 0:
            results.append({"bin": label, "windows": 0, "recall": None})
            continue

        fired = positive_confidences[mask.to_numpy()] >= threshold

        results.append({
            "bin": label,
            "windows": n,
            "recall": round(float(np.mean(fired)), 4)
        })

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(BASE_DIR / "data" / "emergency_model.tflite")
    )
    parser.add_argument(
        "--held-out-sessions",
        default=None,
        help=(
            "comma-separated SESS-... ids already known to have been held "
            "out by the training run (train_tflite_model.py prints this as "
            "part of its 'Split:' line). Skips recomputing load_combined() "
            "(which redecodes ~82k RAVDESS clips, several minutes) when the "
            "list from that exact run is already known. Omitted: "
            "recomputed from scratch, which is the more robust default if "
            "you are not sure the list still matches the current data/model."
        )
    )
    arguments = parser.parse_args()

    model_path = Path(arguments.model)

    real, real_provenance = load_dataset("sensor_packets")
    real_session_ids = set(real["Subject"].unique())

    if arguments.held_out_sessions is not None:
        held_out_real_sessions = {
            s.strip() for s in arguments.held_out_sessions.split(",") if s.strip()
        } & real_session_ids
    else:
        combined, _ = load_combined(["fusion", "sensor_packets"])
        held_out_groups = reproduce_training_split(combined["Subject"])
        held_out_real_sessions = held_out_groups & real_session_ids

    train_real_sessions = real_session_ids - held_out_real_sessions

    held_out_mask = real["Subject"].isin(held_out_real_sessions)
    held_out = real[held_out_mask].reset_index(drop=True)
    trained_on = real[~held_out_mask].reset_index(drop=True)

    scenarios = load_session_scenarios()

    print("=" * 68)
    print("REAL-PACKET EVALUATION - data/real_packets/ (mirrored for training)")
    print("=" * 68)
    print(f"\nModel               : {model_path}")
    print(f"Real capture sessions: {len(real_session_ids)} "
          f"({real_provenance['packets_normal']} normal + "
          f"{real_provenance['packets_emergency']} emergency packets)")
    print(f"  held out of training: {len(held_out_real_sessions)} sessions, "
          f"{len(held_out)} packets")
    print(f"  seen during training: {len(train_real_sessions)} sessions, "
          f"{len(trained_on)} packets")

    if not len(held_out):
        print(
            "\nWARNING: no real capture session landed in the held-out "
            "split this run (small-n randomness with only 18 sessions in "
            "the pool). The 'ALL REAL PACKETS' numbers below still cover "
            "every scenario, but every session in them was at least "
            "partially trained on - report that honestly, do not call it "
            "a held-out estimate."
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path.relative_to(BASE_DIR)),
        "random_seed": RANDOM_SEED,
        "test_size": TEST_SIZE,
        "real_sessions_total": len(real_session_ids),
        "real_sessions_held_out": sorted(held_out_real_sessions),
        "real_sessions_seen_in_training": sorted(train_real_sessions),
        "real_packets_total": int(len(real))
    }

    for subset_name, subset in (
        ("held_out", held_out),
        ("seen_in_training", trained_on),
        ("all_real_packets", real)
    ):
        if not len(subset):
            report[subset_name] = None
            continue

        confidences = score(model_path, subset)
        y_true = subset[TARGET].to_numpy()

        entry = {
            "packets": int(len(subset)),
            "sessions": int(subset["Subject"].nunique()),
            "at_classification_0.50": confusion(
                y_true, confidences, CLASSIFICATION_THRESHOLD
            ),
            "at_dispatch_0.80": confusion(
                y_true, confidences, DECISION_THRESHOLD
            ),
            "recall_by_gps_bin_at_0.80": recall_by_gps_bin(
                subset, confidences, DECISION_THRESHOLD
            ),
            "recall_by_gps_bin_at_0.50": recall_by_gps_bin(
                subset, confidences, CLASSIFICATION_THRESHOLD
            )
        }

        report[subset_name] = entry

        print(f"\n{'-' * 68}\n{subset_name.upper()} "
              f"({entry['packets']} packets, {entry['sessions']} sessions)"
              f"\n{'-' * 68}")

        for label, at in (
            ("classification 0.50", entry["at_classification_0.50"]),
            ("DISPATCH 0.80", entry["at_dispatch_0.80"])
        ):
            print(
                f"  {label:22s} recall={at['recall']}  "
                f"precision={at['precision']}  fpr={at['false_positive_rate']}  "
                f"confusion={at['confusion_matrix']}"
            )

        print("  recall by GPS bin @0.80:")
        for cell in entry["recall_by_gps_bin_at_0.80"]:
            print(f"    {cell['bin']:28s} n={cell['windows']:3d}  "
                  f"recall={cell['recall']}")

    # ------------------------------------------------------------
    # Per-scenario breakdown (manifest.csv), on the full real set
    # ------------------------------------------------------------

    if scenarios:
        real_with_scenario = real.copy()
        real_with_scenario["Scenario"] = real_with_scenario["Subject"].map(
            lambda sid: scenarios.get(sid, {}).get("scenario", "unknown")
        )
        real_with_scenario["HeldOut"] = real_with_scenario["Subject"].isin(
            held_out_real_sessions
        )

        confidences = score(model_path, real)
        real_with_scenario["Confidence"] = confidences
        real_with_scenario["Fired_0.80"] = confidences >= DECISION_THRESHOLD

        print(f"\n{'-' * 68}\nBY SCENARIO (all real packets)\n{'-' * 68}")
        print(f"  {'scenario':<20}{'label':<11}{'n':>5}{'gps med':>9}"
              f"{'fires':>8}{'held-out':>10}")

        per_scenario = []

        for (scenario_name, label), group in real_with_scenario.groupby(
            ["Scenario", TARGET]
        ):
            fire_rate = float(group["Fired_0.80"].mean())
            gps_median = float(group["GPSVelocity"].median())
            any_held_out = bool(group["HeldOut"].any())

            per_scenario.append({
                "scenario": scenario_name,
                "label": "emergency" if label == 1 else "normal",
                "windows": int(len(group)),
                "gps_median": round(gps_median, 3),
                "fire_rate_at_0.80": round(fire_rate, 4),
                "includes_held_out_session": any_held_out
            })

            print(
                f"  {scenario_name:<20}"
                f"{'emergency' if label == 1 else 'normal':<11}"
                f"{len(group):>5}{gps_median:>9.2f}{fire_rate:>8.1%}"
                f"{'yes' if any_held_out else 'no':>10}"
            )

        report["by_scenario"] = per_scenario

    REPORT_PATH.write_text(json.dumps(report, indent=4), encoding="utf-8")
    print(f"\nReport: {REPORT_PATH}")


if __name__ == "__main__":
    main()
