import json
import os


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)

XAI_PATH = os.path.join(
    DATA_DIR,
    "xai_output.json"
)

FEATURE_PATH = os.path.join(
    DATA_DIR,
    "feature_vector.csv"
)

OUTPUT_PATH = os.path.join(
    DATA_DIR,
    "human_explanation.json"
)


# ============================================================
# LOAD XAI OUTPUT
# ============================================================

with open(XAI_PATH, "r") as file:
    xai = json.load(file)


# ============================================================
# LOAD FEATURE VECTOR
# ============================================================

import pandas as pd

features = pd.read_csv(
    FEATURE_PATH
).iloc[0]


prediction = xai["Prediction"]
confidence = xai["Confidence"]
emergency = xai["EmergencyStatus"]
shap_contributions = xai.get("SHAP", {})


# ============================================================
# FEATURE -> HUMAN PHRASE MAPPING
# ============================================================

FEATURE_PHRASES = {
    "PeakAcceleration": "unusually high acceleration",
    "MotionVariance": "significant movement variance",
    "AudioEnergy": "elevated audio activity",
    "GPSVelocity": "an abrupt change in movement speed",
    "PossibleFall": "a possible fall"
}

# Contributions below this magnitude are treated as noise, not a driving
# factor in the decision.
CONTRIBUTION_EPSILON = 0.01


def reasons_from_contributions(contributions):
    """Rank features by how much they actually pushed the model toward
    "Emergency" (positive SHAP contribution), instead of re-deriving reasons
    from fixed thresholds unrelated to what the model weighted.
    """

    driving_features = [
        feature
        for feature, value in sorted(
            contributions.items(),
            key=lambda item: item[1],
            reverse=True
        )
        if value > CONTRIBUTION_EPSILON
    ]

    return [
        FEATURE_PHRASES.get(feature, feature)
        for feature in driving_features
        if feature in FEATURE_PHRASES
    ]


# ============================================================
# NORMAL CASE
# ============================================================

if not emergency:

    message = (
        "No emergency was detected. "
        "The sensor readings do not currently indicate "
        "an emergency condition."
    )

    explanation = {
        "Title": "No Emergency Detected",
        "Message": message,
        "Confidence": confidence
    }


# ============================================================
# EMERGENCY CASE
# ============================================================

else:

    reasons = []

    peak_acceleration = float(
        features["PeakAcceleration"]
    )

    motion_variance = float(
        features["MotionVariance"]
    )

    audio_energy = float(
        features["AudioEnergy"]
    )

    gps_velocity = float(
        features["GPSVelocity"]
    )

    possible_fall = bool(
        features["PossibleFall"]
    )


    # --------------------------------------------------------
    # Reasons: driven by which features actually pushed the
    # model's own decision (SHAP contributions), not by fixed
    # thresholds unrelated to what the model weighted.
    # --------------------------------------------------------

    reasons = reasons_from_contributions(shap_contributions)

    if possible_fall and "a possible fall" not in reasons:
        reasons.append("a possible fall")

    # Fallback only if SHAP data was unavailable/empty for this
    # instance - reasons still reflect the actual feature values,
    # never a hardcoded single test case.
    if not reasons:

        if peak_acceleration > 15:
            reasons.append("unusually high acceleration")

        if motion_variance > 10:
            reasons.append("significant motion variation")

        if possible_fall:
            reasons.append("a possible fall was detected")

        if audio_energy > 0.5:
            reasons.append("elevated audio activity")

        if gps_velocity <= 0.2:
            reasons.append("very low movement speed")


    # --------------------------------------------------------
    # Build human-readable sentence
    # --------------------------------------------------------

    if len(reasons) == 1:

        reason_text = reasons[0]

    elif len(reasons) == 2:

        reason_text = (
            reasons[0]
            + " and "
            + reasons[1]
        )

    else:

        reason_text = (
            ", ".join(reasons[:-1])
            + ", and "
            + reasons[-1]
        )


    message = (
        "An emergency was detected with "
        f"{confidence * 100:.1f}% confidence. "
        "The system detected signs of "
        + reason_text
        + "."
    )


    explanation = {

        "Title": "Emergency Detected",

        "Message": message,

        "Confidence": round(
            confidence,
            4
        ),

        "Reasons": reasons,

        "TopContributingFeatures": shap_contributions,

        "FeatureValues": {

            "PeakAcceleration":
                round(
                    peak_acceleration,
                    4
                ),

            "MotionVariance":
                round(
                    motion_variance,
                    4
                ),

            "AudioEnergy":
                round(
                    audio_energy,
                    4
                ),

            "GPSVelocity":
                round(
                    gps_velocity,
                    4
                ),

            "PossibleFall":
                possible_fall
        }
    }


# ============================================================
# SESSION CONTEXT (only when the real SensorPacket path populated it)
# ============================================================

if "SessionID" in xai:
    explanation["SessionID"] = xai["SessionID"]
    explanation["TimestampMs"] = xai["TimestampMs"]


# ============================================================
# SAVE
# ============================================================

with open(
    OUTPUT_PATH,
    "w"
) as file:

    json.dump(
        explanation,
        file,
        indent=4
    )


# ============================================================
# DISPLAY
# ============================================================

print("\nHUMAN-READABLE EMERGENCY EXPLANATION")
print("=" * 60)

print(
    "\n" + explanation["Title"]
)

print(
    "\n" + explanation["Message"]
)

print("\nSaved to:")
print(OUTPUT_PATH)