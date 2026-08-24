import json
from pathlib import Path


# Project root
BASE_DIR = Path(__file__).resolve().parent.parent

# TFLite prediction file
prediction_path = BASE_DIR / "data" / "prediction_tflite.json"

# Session context (SessionID/Timestamp), written only by the real
# SensorPacket path (phase4/process_sensor_packet.py). The CSV prototype
# path has no session concept, so this is optional.
session_context_path = BASE_DIR / "data" / "session_context.json"

# Output file
decision_path = BASE_DIR / "data" / "decision.json"

# Emergency confidence threshold
THRESHOLD = 0.80


# -----------------------------
# Load TFLite prediction
# -----------------------------

with open(prediction_path, "r") as file:
    prediction_data = json.load(file)


prediction = prediction_data["Prediction"]
confidence = prediction_data["Confidence"]


# -----------------------------
# Load session context, if present
# -----------------------------

session_context = {}

if session_context_path.exists():
    with open(session_context_path, "r") as file:
        session_context = json.load(file)


# -----------------------------
# Decision Logic
# -----------------------------

if prediction == "Emergency" and confidence >= THRESHOLD:
    emergency_status = True
else:
    emergency_status = False


# -----------------------------
# Create decision object
# -----------------------------

decision = {
    "EmergencyStatus": emergency_status,
    "Prediction": prediction,
    "Confidence": confidence,
    "Threshold": THRESHOLD
}

if session_context:
    decision["SessionID"] = session_context.get("SessionID")
    decision["TimestampMs"] = session_context.get("TimestampMs")


# -----------------------------
# Display result
# -----------------------------

print("TFLite Prediction:")
print(json.dumps(prediction_data, indent=4))

print("\nDecision Engine Output:")
print(json.dumps(decision, indent=4))


# -----------------------------
# Save decision
# -----------------------------

with open(decision_path, "w") as file:
    json.dump(decision, file, indent=4)


print("\nDecision saved to:")
print(decision_path)