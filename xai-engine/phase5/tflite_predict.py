import os
import json
import numpy as np
import pandas as pd
import tensorflow as tf

# -----------------------------
# Paths
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.tflite"
)

FEATURE_PATH = os.path.join(
    BASE_DIR,
    "data",
    "feature_vector.csv"
)

OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "data",
    "prediction_tflite.json"
)

# -----------------------------
# Load feature vector
# -----------------------------
data = pd.read_csv(FEATURE_PATH)

features = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]

values = data[features].iloc[0].astype(np.float32).values

input_data = np.array([values], dtype=np.float32)

print("\nInput Feature Values:")
print(dict(zip(features, values)))

# -----------------------------
# Load TFLite model
# -----------------------------
interpreter = tf.lite.Interpreter(
    model_path=MODEL_PATH
)

interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

input_index = input_details[0]["index"]
output_index = output_details[0]["index"]

# -----------------------------
# Prediction
# -----------------------------
interpreter.set_tensor(
    input_index,
    input_data
)

interpreter.invoke()

output = interpreter.get_tensor(
    output_index
)

confidence = float(output[0][0])

# -----------------------------
# Classification
# -----------------------------
if confidence >= 0.5:
    prediction = "Emergency"
else:
    prediction = "Normal"

# -----------------------------
# Prediction object
#
# "Confidence" stays rounded to 4dp: it is the display/handoff value and
# downstream consumers (security-module AIResult.kt, phase7 report) already
# read it at that precision.
#
# "ConfidenceRaw" is the full-precision model output and is what the decision
# engine MUST threshold on. Thresholding the rounded value promoted any raw
# confidence in [0.79995, 0.80) to "Emergency", which the on-device Kotlin
# path (EmergencyClassifier, raw comparison) would not do - a divergence in
# the safety-critical decision. See phase6/test_decision_threshold.py.
# -----------------------------
prediction_object = {
    "Prediction": prediction,
    "Confidence": round(confidence, 4),
    "ConfidenceRaw": confidence
}

print("\nTFLite Prediction:")
print(prediction_object)

# -----------------------------
# Save output
# -----------------------------
with open(OUTPUT_PATH, "w") as file:
    json.dump(
        prediction_object,
        file,
        indent=4
    )

print("\nPrediction saved to:")
print(OUTPUT_PATH)
