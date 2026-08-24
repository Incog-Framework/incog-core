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

DATA_PATH = os.path.join(
    BASE_DIR,
    "data",
    "training_data.csv"
)

# -----------------------------
# Load dataset
# -----------------------------
data = pd.read_csv(DATA_PATH)

features = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]

X = data[features].astype(np.float32).values
y = data["Emergency"].values

# -----------------------------
# Load TFLite model
# -----------------------------
interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)

interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

input_index = input_details[0]["index"]
output_index = output_details[0]["index"]

# -----------------------------
# Run predictions
# -----------------------------
results = []

for i in range(len(X)):

    input_data = np.array([X[i]], dtype=np.float32)

    interpreter.set_tensor(input_index, input_data)

    interpreter.invoke()

    output = interpreter.get_tensor(output_index)

    confidence = float(output[0][0])

    if confidence >= 0.5:
        prediction = 1
    else:
        prediction = 0

    results.append({
        "Actual": int(y[i]),
        "Prediction": prediction,
        "Confidence": confidence
    })

# -----------------------------
# Display results
# -----------------------------
results_df = pd.DataFrame(results)

print("\nTFLite Test Results")
print("=" * 60)

print(results_df.to_string(index=False))

# -----------------------------
# Accuracy
# -----------------------------
accuracy = (
    results_df["Actual"] ==
    results_df["Prediction"]
).mean()

print("\n" + "=" * 60)

print(f"TFLite Accuracy: {accuracy * 100:.2f}%")

print("=" * 60)

# -----------------------------
# Save results
# -----------------------------
output_path = os.path.join(
    BASE_DIR,
    "data",
    "tflite_test_results.csv"
)

results_df.to_csv(
    output_path,
    index=False
)

print("\nResults saved to:")
print(output_path)