import os
import json
import numpy as np
import pandas as pd
import tensorflow as tf

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report
)


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATASET_PATH = os.path.join(
    BASE_DIR,
    "data",
    "training_data.csv"
)

MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.tflite"
)

OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "data",
    "final_model_metrics.json"
)


FEATURES = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]


# ============================================================
# LOAD DATA
# ============================================================

data = pd.read_csv(DATASET_PATH)

data["PossibleFall"] = (
    data["PossibleFall"].astype(float)
)

X = data[FEATURES].astype(np.float32)

y = data["Emergency"].astype(int)


# ============================================================
# SAME SPLIT USED DURING TRAINING
# ============================================================

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)


# ============================================================
# LOAD TFLITE MODEL
# ============================================================

interpreter = tf.lite.Interpreter(
    model_path=MODEL_PATH
)

interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

input_index = input_details[0]["index"]
output_index = output_details[0]["index"]


# ============================================================
# PREDICT TEST SET
# ============================================================

predictions = []

probabilities = []


for row in X_test.values:

    input_data = np.array(
        [row],
        dtype=np.float32
    )

    interpreter.set_tensor(
        input_index,
        input_data
    )

    interpreter.invoke()

    probability = float(
        interpreter.get_tensor(
            output_index
        )[0][0]
    )

    probabilities.append(probability)

    predictions.append(
        1 if probability >= 0.5 else 0
    )


# ============================================================
# METRICS
# ============================================================

accuracy = accuracy_score(
    y_test,
    predictions
)

precision = precision_score(
    y_test,
    predictions,
    zero_division=0
)

recall = recall_score(
    y_test,
    predictions,
    zero_division=0
)

f1 = f1_score(
    y_test,
    predictions,
    zero_division=0
)

cm = confusion_matrix(
    y_test,
    predictions
)


# ============================================================
# PRINT
# ============================================================

print("\nFINAL MODEL METRICS")
print("=" * 60)

print("Training Samples:", len(X_train))
print("Testing Samples:", len(X_test))

print("\nAccuracy :", round(accuracy, 4))
print("Precision:", round(precision, 4))
print("Recall   :", round(recall, 4))
print("F1 Score :", round(f1, 4))

print("\nConfusion Matrix:")
print(cm)

print("\nClassification Report:")
print(
    classification_report(
        y_test,
        predictions,
        target_names=[
            "Normal",
            "Emergency"
        ],
        zero_division=0
    )
)


# ============================================================
# SAVE METRICS
# ============================================================

# ------------------------------------------------------------
# FALSE-POSITIVE RATE + PROVENANCE
#
# This script evaluates on data/training_data.csv, which is the 30 synthetic
# rows. Emitting the numbers without saying so lets a 1.00 get quoted as a
# production result, so the provenance is stamped into the artifact itself.
# The authoritative evaluation is phase5/train_tflite_model.py, which reads
# provenance from the dataset adapter.
# ------------------------------------------------------------

true_negatives, false_positives, false_negatives, true_positives = cm.ravel()

negatives = int(true_negatives + false_positives)

false_positive_rate = (
    round(float(false_positives) / negatives, 4)
    if negatives
    else None
)

print("\nFalse-positive rate:", false_positive_rate)

metrics = {
    "data_provenance": {
        "dataset": "synthetic",
        "source": "data/training_data.csv",
        "is_synthetic": True,
        "caveat": (
            "30 hand-written rows, linearly separable on PeakAcceleration "
            "alone. These metrics measure the dataset, not the model."
        )
    },
    "production_claim_supported": False,
    "false_positive_rate": false_positive_rate,
    "confusion_matrix_layout": "[[TN, FP], [FN, TP]]",
    "training_samples": len(X_train),
    "test_samples": len(X_test),
    "accuracy": round(float(accuracy), 4),
    "precision": round(float(precision), 4),
    "recall": round(float(recall), 4),
    "f1_score": round(float(f1), 4),
    "confusion_matrix": cm.tolist(),
    "classification_report": classification_report(
        y_test,
        predictions,
        target_names=[
            "Normal",
            "Emergency"
        ],
        output_dict=True,
        zero_division=0
    )
}


with open(
    OUTPUT_PATH,
    "w"
) as file:

    json.dump(
        metrics,
        file,
        indent=4
    )


print("\nMetrics saved to:")
print(OUTPUT_PATH)
