"""Train + evaluate the emergency-detection model, and export it to TFLite.

Data comes from phase5/dataset_adapters.py, so a real corpus plugs in without
touching this file:

    python phase5/train_tflite_model.py --dataset synthetic          (default)
    python phase5/train_tflite_model.py --dataset sisfall,uci_har
    python phase5/train_tflite_model.py --dataset sensor_packets --write-model

TWO THINGS THIS SCRIPT REFUSES TO DO
------------------------------------
1. Report synthetic results as production evidence. Provenance travels with
   the data and is stamped into the metrics file; a synthetic run is marked
   production_claim_supported=false no matter how good the numbers look.

2. Overwrite the deployed model by accident. data/emergency_model.tflite is
   byte-identical to the asset the phone ships
   (mobile-client/app/src/main/assets/emergency_model.tflite). Retraining
   breaks that match, so the model is only written with --write-model, and
   the follow-up steps are printed when it happens.

WHY FALSE-POSITIVE RATE IS REPORTED AT 0.80, NOT 0.50
-----------------------------------------------------
0.50 separates the "Emergency" label from "Normal", but nothing is dispatched
below 0.80 (phase6/decision_engine.py, EmergencyClassifier.kt). The rate that
matters to a user is how often an alert actually FIRES on ordinary activity,
so metrics are reported at both cutoffs and the target is judged at 0.80.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import tensorflow as tf

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report,
    roc_auc_score
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(BASE_DIR, "phase5"))

from dataset_adapters import (              # noqa: E402
    DatasetUnavailable,
    FEATURE_ORDER,
    TARGET,
    available_datasets,
    load_combined,
    load_dataset
)

MODEL_PATH = os.path.join(BASE_DIR, "data", "emergency_model.tflite")
KERAS_MODEL_PATH = os.path.join(BASE_DIR, "data", "emergency_model.keras")
FEATURE_ORDER_PATH = os.path.join(BASE_DIR, "data", "tflite_feature_order.json")
METRICS_PATH = os.path.join(BASE_DIR, "data", "tflite_model_metrics.json")

CLASSIFICATION_THRESHOLD = 0.50
DECISION_THRESHOLD = 0.80

# The brief's goal for false positives, judged at the dispatch threshold.
FALSE_POSITIVE_TARGET = 0.05

RANDOM_SEED = 42


# ============================================================
# Metrics
# ============================================================

def evaluate_at(y_true, probabilities, threshold):
    """Full metric set at one decision cutoff, including false-positive rate."""

    predictions = (probabilities >= threshold).astype(int)

    matrix = confusion_matrix(y_true, predictions, labels=[0, 1])

    true_negatives, false_positives, false_negatives, true_positives = (
        matrix.ravel()
    )

    negatives = int(true_negatives + false_positives)
    positives = int(true_positives + false_negatives)

    return {
        "threshold": threshold,
        "accuracy": round(float(accuracy_score(y_true, predictions)), 4),
        "precision": round(
            float(precision_score(y_true, predictions, zero_division=0)), 4
        ),
        "recall": round(
            float(recall_score(y_true, predictions, zero_division=0)), 4
        ),
        "f1_score": round(
            float(f1_score(y_true, predictions, zero_division=0)), 4
        ),
        "confusion_matrix": matrix.tolist(),
        "confusion_matrix_layout": "[[TN, FP], [FN, TP]]",
        # FP / (FP + TN): of all the ordinary moments, how many raised an alarm
        "false_positive_rate": (
            round(float(false_positives) / negatives, 4)
            if negatives
            else None
        ),
        # FN / (FN + TP): of all the real emergencies, how many were missed
        "false_negative_rate": (
            round(float(false_negatives) / positives, 4)
            if positives
            else None
        ),
        "true_negatives": int(true_negatives),
        "false_positives": int(false_positives),
        "false_negatives": int(false_negatives),
        "true_positives": int(true_positives)
    }


def threshold_sweep(y_true, probabilities):
    """FPR/recall across cutoffs, so a threshold can be chosen from evidence."""

    return [
        {
            "threshold": round(threshold, 2),
            "recall": entry["recall"],
            "precision": entry["precision"],
            "false_positive_rate": entry["false_positive_rate"]
        }
        for threshold in np.arange(0.05, 1.0, 0.05)
        for entry in [evaluate_at(y_true, probabilities, float(threshold))]
    ]


# ============================================================
# Data
# ============================================================

def load(dataset_argument):
    names = [name.strip() for name in dataset_argument.split(",") if name.strip()]

    if len(names) == 1:
        data, provenance = load_dataset(names[0])
    else:
        data, provenance = load_combined(names)

    return data, provenance


def prepare(data):
    """Split into X/y, failing loudly on unusable data rather than guessing."""

    incomplete = data[FEATURE_ORDER].isna().any(axis=1).sum()

    if incomplete:
        raise ValueError(
            f"{incomplete} of {len(data)} rows have NaN features.\n"
            f"  A corpus that does not measure every feature (SisFall and "
            f"UCI HAR have no audio or GPS) cannot be trained on directly.\n"
            f"  Either fuse it with a source that supplies the missing "
            f"channels, or drop those features from the model - both are "
            f"modelling decisions, so this script will not pick one for you."
        )

    features = data[FEATURE_ORDER].copy()
    features["PossibleFall"] = features["PossibleFall"].astype(np.float32)

    return features.astype(np.float32), data[TARGET].astype(np.float32)


# ============================================================
# Model
# ============================================================

def build_model(x_train):
    normalizer = tf.keras.layers.Normalization()
    normalizer.adapt(x_train.values)

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(len(FEATURE_ORDER),)),
        # Normalization is baked in so the phone can feed RAW feature values;
        # keep it inside the graph or FeatureVector.toModelInput() breaks.
        normalizer,
        tf.keras.layers.Dense(8, activation="relu"),
        tf.keras.layers.Dense(4, activation="relu"),
        tf.keras.layers.Dense(1, activation="sigmoid")
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss="binary_crossentropy",
        metrics=["accuracy"]
    )

    return model


def tflite_probabilities(tflite_model, features):
    """Score through the actual TFLite artifact, not the Keras model.

    Conversion can shift outputs slightly, and the phone runs the converted
    graph - so the reported metrics must come from it.
    """

    interpreter = tf.lite.Interpreter(model_content=tflite_model)
    interpreter.allocate_tensors()

    input_index = interpreter.get_input_details()[0]["index"]
    output_index = interpreter.get_output_details()[0]["index"]

    values = features.values.astype(np.float32)
    probabilities = np.empty(len(values), dtype=np.float64)

    for row in range(len(values)):
        interpreter.set_tensor(input_index, values[row:row + 1])
        interpreter.invoke()
        probabilities[row] = float(interpreter.get_tensor(output_index)[0][0])

    return probabilities


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--dataset",
        default="synthetic",
        help="registered dataset name, or a comma-separated list to combine"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=300
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2
    )
    parser.add_argument(
        "--write-model",
        action="store_true",
        help=(
            "overwrite data/emergency_model.tflite. Without this the run only "
            "trains and reports - the deployed artifact is left alone."
        )
    )
    parser.add_argument(
        "--list-datasets",
        action="store_true"
    )

    arguments = parser.parse_args()

    if arguments.list_datasets:
        for name, status in available_datasets().items():
            state = "available" if status["available"] else "NOT PRESENT"
            print(f"  {name:16s} {state}")
        return

    np.random.seed(RANDOM_SEED)
    tf.random.set_seed(RANDOM_SEED)

    print("=" * 60)
    print("INCOG - EMERGENCY MODEL TRAINING")
    print("=" * 60)

    try:
        data, provenance = load(arguments.dataset)
    except DatasetUnavailable as error:
        print(error)
        print("Nothing was trained and no artifact was modified.")
        raise SystemExit(2)

    print(f"\nDataset  : {provenance['dataset']}")
    print(f"Rows     : {len(data)}")
    print(f"Synthetic: {provenance['is_synthetic']}")
    print(f"\nCaveat   : {provenance['caveat']}")

    x_all, y_all = prepare(data)

    class_counts = data[TARGET].value_counts().to_dict()
    print(f"\nClass distribution: {class_counts}")

    if len(class_counts) < 2:
        print(
            "\nOnly one class present - this corpus cannot train a classifier "
            "on its own. Combine it with a source for the other class."
        )
        raise SystemExit(2)

    # ------------------------------------------------------------
    # Split by SUBJECT when the corpus identifies people.
    #
    # A random split leaks badly on windowed sensor data: consecutive
    # windows overlap by 18 of their 20 seconds, and one person contributes
    # many windows, so near-duplicates land on both sides and every metric
    # comes out inflated. Grouping by subject measures what actually
    # matters - does this generalise to a person it has never seen.
    # ------------------------------------------------------------

    subjects = data["Subject"] if "Subject" in data.columns else None

    if subjects is not None and subjects.nunique() >= 4:
        from sklearn.model_selection import GroupShuffleSplit

        splitter = GroupShuffleSplit(
            n_splits=1,
            test_size=arguments.test_size,
            random_state=RANDOM_SEED
        )

        train_index, test_index = next(
            splitter.split(x_all, y_all, groups=subjects)
        )

        x_train = x_all.iloc[train_index]
        x_test = x_all.iloc[test_index]
        y_train = y_all.iloc[train_index]
        y_test = y_all.iloc[test_index]

        held_out = sorted(set(subjects.iloc[test_index]))

        split_kind = "subject-level (GroupShuffleSplit)"

        print(
            f"\nSplit: {split_kind} - "
            f"{subjects.nunique()} subjects, "
            f"{len(held_out)} held out: {held_out}"
        )

    else:
        x_train, x_test, y_train, y_test = train_test_split(
            x_all,
            y_all,
            test_size=arguments.test_size,
            random_state=RANDOM_SEED,
            stratify=y_all
        )

        split_kind = "random (stratified)"

        if subjects is None:
            print(
                "\nSplit: random (stratified) - this corpus carries no "
                "Subject column.\n"
                "  WARNING: if these rows are overlapping windows, this "
                "split leaks and the\n"
                "  resulting metrics are optimistic. See DATA_REQUIREMENTS.md."
            )
        else:
            print(
                f"\nSplit: random (stratified) - only "
                f"{subjects.nunique()} subject(s), too few to group on."
            )

    print(f"Training samples: {len(x_train)}")
    print(f"Testing samples : {len(x_test)}")

    model = build_model(x_train)

    print("\nTraining...")
    model.fit(
        x_train,
        y_train,
        epochs=arguments.epochs,
        batch_size=4,
        verbose=0
    )
    print("Training complete.")

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_model = converter.convert()

    probabilities = tflite_probabilities(tflite_model, x_test)

    at_classification = evaluate_at(
        y_test, probabilities, CLASSIFICATION_THRESHOLD
    )
    at_decision = evaluate_at(y_test, probabilities, DECISION_THRESHOLD)

    print("\n" + "=" * 60)
    print("EVALUATION (through the converted TFLite graph)")
    print("=" * 60)

    for label, entry in (
        (f"classification cutoff {CLASSIFICATION_THRESHOLD}", at_classification),
        (f"DISPATCH threshold    {DECISION_THRESHOLD}", at_decision)
    ):
        print(f"\n-- {label} --")
        print(f"  Accuracy           : {entry['accuracy']}")
        print(f"  Precision          : {entry['precision']}")
        print(f"  Recall             : {entry['recall']}")
        print(f"  F1                 : {entry['f1_score']}")
        print(f"  False-positive rate: {entry['false_positive_rate']}")
        print(f"  False-negative rate: {entry['false_negative_rate']}")
        print(f"  Confusion [[TN,FP],[FN,TP]]: {entry['confusion_matrix']}")

    print("\nClassification report (at the dispatch threshold):")
    print(
        classification_report(
            y_test,
            (probabilities >= DECISION_THRESHOLD).astype(int),
            target_names=["Normal", "Emergency"],
            zero_division=0,
            labels=[0, 1]
        )
    )

    # ------------------------------------------------------------
    # The honesty gate
    # ------------------------------------------------------------

    supports_claim = bool(
        provenance.get("is_production_evidence", False)
        and not provenance["is_synthetic"]
    )

    false_positive_rate = at_decision["false_positive_rate"]

    meets_target = (
        supports_claim
        and false_positive_rate is not None
        and false_positive_rate < FALSE_POSITIVE_TARGET
    )

    print("=" * 60)

    if not supports_claim:
        print(
            "DATA PROVENANCE WARNING\n"
            "  These metrics come from synthetic data. They are a pipeline\n"
            "  smoke test, NOT evidence of real-world performance. Do not\n"
            "  quote the accuracy or the false-positive rate in a report,\n"
            f"  and do not claim the <{FALSE_POSITIVE_TARGET:.0%} "
            "false-positive target is met."
        )
    elif meets_target:
        print(
            f"False-positive rate {false_positive_rate:.2%} is below the "
            f"{FALSE_POSITIVE_TARGET:.0%} target on real held-out data."
        )
    else:
        print(
            f"False-positive rate {false_positive_rate} does NOT meet the "
            f"{FALSE_POSITIVE_TARGET:.0%} target."
        )

    print("=" * 60)

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_provenance": provenance,
        "production_claim_supported": supports_claim,
        "false_positive_target": FALSE_POSITIVE_TARGET,
        "meets_false_positive_target": meets_target if supports_claim else None,
        "split": split_kind,
        "split_leaks_across_subjects": not split_kind.startswith("subject-level"),
        "training_samples": int(len(x_train)),
        "test_samples": int(len(x_test)),
        "class_distribution": {str(k): int(v) for k, v in class_counts.items()},
        "roc_auc": (
            round(float(roc_auc_score(y_test, probabilities)), 4)
            if len(set(y_test)) > 1
            else None
        ),
        "at_classification_threshold": at_classification,
        "at_decision_threshold": at_decision,
        "threshold_sweep": threshold_sweep(y_test, probabilities),
        "model_written": bool(arguments.write_model),
        # kept so older readers of this file still find the headline numbers
        "accuracy": at_classification["accuracy"],
        "precision": at_classification["precision"],
        "recall": at_classification["recall"],
        "f1_score": at_classification["f1_score"],
        "threshold": CLASSIFICATION_THRESHOLD
    }

    with open(METRICS_PATH, "w") as file:
        json.dump(metrics, file, indent=4)

    print(f"\nMetrics saved: {METRICS_PATH}")

    if not arguments.write_model:
        print(
            "\nModel NOT written (no --write-model).\n"
            "  data/emergency_model.tflite still matches the asset the phone\n"
            "  ships. Re-run with --write-model when you intend to replace it."
        )
        return

    model.save(KERAS_MODEL_PATH)

    with open(MODEL_PATH, "wb") as file:
        file.write(tflite_model)

    with open(FEATURE_ORDER_PATH, "w") as file:
        json.dump(FEATURE_ORDER, file, indent=4)

    print(f"\nModel written: {MODEL_PATH}")
    print(f"Size: {os.path.getsize(MODEL_PATH) / 1024:.2f} KB")

    print(
        "\nTHE MODEL CHANGED - three follow-ups are now required:\n"
        "  1. python generate_contract_fixtures.py"
        "        (refresh the model hash + golden vectors)\n"
        "  2. Ask Aarush to re-vendor the new .tflite into\n"
        "     mobile-client/app/src/main/assets/emergency_model.tflite\n"
        "     - the phone will otherwise keep running the OLD model.\n"
        "  3. python run_ai_pipeline.py --source packet"
        "     (regenerate SHAP/LIME against the new model)"
    )


if __name__ == "__main__":
    main()
