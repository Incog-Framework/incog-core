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

# ============================================================
# 1. Paths
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_PATH = os.path.join(
    BASE_DIR,
    "data",
    "training_data.csv"
)

MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.tflite"
)

KERAS_MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.keras"
)

FEATURE_ORDER_PATH = os.path.join(
    BASE_DIR,
    "data",
    "tflite_feature_order.json"
)

METRICS_PATH = os.path.join(
    BASE_DIR,
    "data",
    "tflite_model_metrics.json"
)

# ============================================================
# 2. Reproducibility
# ============================================================

np.random.seed(42)
tf.random.set_seed(42)

# ============================================================
# 3. Load dataset
# ============================================================

data = pd.read_csv(DATA_PATH)

print("==================================================")
print("INCOG. TFLITE MODEL TRAINING")
print("==================================================")

print("\nDataset shape:", data.shape)

# ============================================================
# 4. Features and target
# ============================================================

features = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]

target = "Emergency"

X = data[features].copy()
y = data[target].astype(np.float32)

# Convert PossibleFall to numeric
X["PossibleFall"] = X["PossibleFall"].astype(np.float32)

X = X.astype(np.float32)

print("\nFeatures:")
for feature in features:
    print(" -", feature)

print("\nTarget:", target)

print("\nClass distribution:")
print(data[target].value_counts())

# ============================================================
# 5. Train / test split
# ============================================================

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

print("\nTraining samples:", len(X_train))
print("Testing samples:", len(X_test))

# ============================================================
# 6. Normalization
# ============================================================

normalizer = tf.keras.layers.Normalization()

normalizer.adapt(X_train.values)

# ============================================================
# 7. Build lightweight neural network
# ============================================================

model = tf.keras.Sequential([
    tf.keras.layers.Input(shape=(5,)),

    normalizer,

    tf.keras.layers.Dense(
        8,
        activation="relu"
    ),

    tf.keras.layers.Dense(
        4,
        activation="relu"
    ),

    tf.keras.layers.Dense(
        1,
        activation="sigmoid"
    )
])

# ============================================================
# 8. Compile
# ============================================================

model.compile(
    optimizer=tf.keras.optimizers.Adam(
        learning_rate=0.001
    ),
    loss="binary_crossentropy",
    metrics=["accuracy"]
)

print("\nModel architecture:")
model.summary()

# ============================================================
# 9. Train
# ============================================================

print("\nTraining model...")

history = model.fit(
    X_train,
    y_train,
    epochs=300,
    batch_size=4,
    verbose=0
)

print("Training completed.")


# ============================================================
# 10. Evaluate Keras model
# ============================================================

loss, accuracy = model.evaluate(
    X_test,
    y_test,
    verbose=0
)

keras_probabilities = model.predict(
    X_test,
    verbose=0
).flatten()

keras_predictions = (
    keras_probabilities >= 0.5
).astype(int)

precision = precision_score(
    y_test,
    keras_predictions,
    zero_division=0
)

recall = recall_score(
    y_test,
    keras_predictions,
    zero_division=0
)

f1 = f1_score(
    y_test,
    keras_predictions,
    zero_division=0
)

cm = confusion_matrix(
    y_test,
    keras_predictions
)

print("\n==================================================")
print("MODEL EVALUATION")
print("==================================================")

print("Accuracy :", round(accuracy, 4))
print("Precision:", round(precision, 4))
print("Recall   :", round(recall, 4))
print("F1 Score :", round(f1, 4))

print("\nConfusion Matrix:")
print(cm)

print("\nClassification Report:")
print(
    classification_report(
        y_test,
        keras_predictions,
        zero_division=0
    )
)

# ============================================================
# 11. Save Keras model
# ============================================================

model.save(KERAS_MODEL_PATH)

print("\nKeras model saved:")
print(KERAS_MODEL_PATH)

# ============================================================
# 12. Convert to TFLite
# ============================================================

print("\nConverting model to TFLite...")

converter = tf.lite.TFLiteConverter.from_keras_model(
    model
)

tflite_model = converter.convert()

with open(MODEL_PATH, "wb") as file:
    file.write(tflite_model)

print("TFLite model saved:")
print(MODEL_PATH)

# ============================================================
# 13. Save feature order
# ============================================================

with open(FEATURE_ORDER_PATH, "w") as file:
    json.dump(
        features,
        file,
        indent=4
    )

print("\nFeature order saved:")
print(FEATURE_ORDER_PATH)

# ============================================================
# 14. Save metrics
# ============================================================

metrics = {
    "accuracy": round(float(accuracy), 4),
    "precision": round(float(precision), 4),
    "recall": round(float(recall), 4),
    "f1_score": round(float(f1), 4),
    "test_samples": int(len(X_test)),
    "training_samples": int(len(X_train)),
    "threshold": 0.5
}

with open(METRICS_PATH, "w") as file:
    json.dump(
        metrics,
        file,
        indent=4
    )

print("\nMetrics saved:")
print(METRICS_PATH)

# ============================================================
# 15. Model size
# ============================================================

model_size = os.path.getsize(
    MODEL_PATH
)

print("\nTFLite model size:")
print(
    f"{model_size / 1024:.2f} KB"
)

print("\n==================================================")
print("TRAINING COMPLETE")
print("==================================================")