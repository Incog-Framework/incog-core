import os

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.keras"
)

# The actual on-device inference artifact (Phase 5). SHAP/LIME must explain
# this model, not the Keras source model, so that explanations correspond
# exactly to what the deployed model outputs.
TFLITE_MODEL_PATH = os.path.join(
    BASE_DIR,
    "data",
    "emergency_model.tflite"
)

DATASET_PATH = os.path.join(
    BASE_DIR,
    "data",
    "training_data.csv"
)

FEATURE_PATH = os.path.join(
    BASE_DIR,
    "data",
    "feature_vector.csv"
)

XAI_OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "data",
    "xai_output.json"
)

FEATURES = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]