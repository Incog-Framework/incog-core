import json
import os
from datetime import datetime


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DECISION_PATH = os.path.join(
    BASE_DIR,
    "data",
    "decision.json"
)

FEATURE_PATH = os.path.join(
    BASE_DIR,
    "data",
    "feature_vector.csv"
)

XAI_PATH = os.path.join(
    BASE_DIR,
    "data",
    "xai_output.json"
)

OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "data",
    "intervention.json"
)


# ------------------------------------------------------------
# Load decision
# ------------------------------------------------------------

with open(DECISION_PATH, "r") as file:
    decision = json.load(file)


# ------------------------------------------------------------
# Load XAI
# ------------------------------------------------------------

with open(XAI_PATH, "r") as file:
    xai = json.load(file)


# ------------------------------------------------------------
# Determine intervention
# ------------------------------------------------------------

if decision["EmergencyStatus"] is True:

    intervention = {
        "Action": "Emergency Alert",
        "Priority": "HIGH",
        "Message": "Potential emergency condition detected.",
        "RecommendedAction": "Initiate emergency response."
    }

else:

    intervention = {
        "Action": "No Alert",
        "Priority": "LOW",
        "Message": "No emergency condition detected.",
        "RecommendedAction": "Continue monitoring."
    }


# ------------------------------------------------------------
# Create intervention object
# ------------------------------------------------------------

result = {
    "Timestamp": datetime.now().isoformat(),
    "Prediction": decision["Prediction"],
    "Confidence": decision["Confidence"],
    "EmergencyStatus": decision["EmergencyStatus"],
    "DecisionThreshold": decision["Threshold"],
    "Intervention": intervention,
    "XAIAvailable": (
        "SHAP" in xai and
        "LIME" in xai
    )
}

# Carried through only when the real SensorPacket path populated them, so
# this intervention can be tied back to the originating Ghost State session.
if "SessionID" in decision:
    result["SessionID"] = decision["SessionID"]
    result["SessionTimestampMs"] = decision["TimestampMs"]


# ------------------------------------------------------------
# Save
# ------------------------------------------------------------

with open(OUTPUT_PATH, "w") as file:
    json.dump(
        result,
        file,
        indent=4
    )


print("\nINTERVENTION ENGINE")
print("=" * 50)

print(json.dumps(result, indent=4))

print("\nIntervention saved to:")
print(OUTPUT_PATH)