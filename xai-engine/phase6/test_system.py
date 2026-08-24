import json
import os

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

decision_path = os.path.join(
    BASE_DIR,
    "data",
    "decision.json"
)

xai_path = os.path.join(
    BASE_DIR,
    "data",
    "xai_output.json"
)

print("\nSYSTEM VALIDATION")
print("=" * 50)

# ------------------------------------------------------------
# Decision validation
# ------------------------------------------------------------

with open(decision_path, "r") as file:
    decision = json.load(file)

print("\nDecision:")
print(decision)

assert "Prediction" in decision
assert "Confidence" in decision
assert "EmergencyStatus" in decision
assert "Threshold" in decision

print("\nDecision structure: PASS")


# ------------------------------------------------------------
# XAI validation
# ------------------------------------------------------------

with open(xai_path, "r") as file:
    xai = json.load(file)

print("\nXAI:")
print(xai)

assert "SHAP" in xai
assert "LIME" in xai

print("\nXAI structure: PASS")


# ------------------------------------------------------------
# Final validation
# ------------------------------------------------------------

if (
    decision["Prediction"] == "Emergency"
    and decision["EmergencyStatus"] is True
):
    print("\nEmergency detection: PASS")

elif (
    decision["Prediction"] == "Normal"
    and decision["EmergencyStatus"] is False
):
    print("\nNormal detection: PASS")

else:
    print("\nDecision consistency: FAIL")
    raise SystemExit(1)

print("\n" + "=" * 50)
print("INC0G AI SYSTEM VALIDATION PASSED")
print("=" * 50)