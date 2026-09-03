"""Human-readable explanation built from the model's own SHAP contributions.

Consumed by Chirag's backend after evidence arrives (the explanation is
attached post-hoc; SHAP/LIME never run on the phone - see Decision 2 in
xai-engine/CLAUDE.md).

Exposes build_explanation() so xai_pipeline can fold the same structure into
data/xai_output.json, and still runs as a script writing
data/human_explanation.json.
"""

import json
import os

import pandas as pd

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


# ============================================================
# FEATURE VALUES
# ============================================================

def read_feature_values(feature_path=FEATURE_PATH):
    """Read the feature vector Phase 5 actually scored, as plain JSON types."""

    row = pd.read_csv(feature_path).iloc[0]

    return {
        "PeakAcceleration": round(float(row["PeakAcceleration"]), 4),
        "MotionVariance": round(float(row["MotionVariance"]), 4),
        "AudioEnergy": round(float(row["AudioEnergy"]), 4),
        "GPSVelocity": round(float(row["GPSVelocity"]), 4),
        # pandas parses the True/False column to numpy.bool_; bool() of the
        # STRING "False" would be True, so never let this become object dtype
        "PossibleFall": bool(row["PossibleFall"])
    }


# ============================================================
# STRUCTURED CONTRIBUTIONS
# ============================================================

def rank_contributions(contributions, feature_values=None):
    """Rank features by |SHAP contribution|, strongest first.

    Returns a list of records rather than a bare dict so the backend can
    render "top N drivers" without re-deriving the ordering, and so each
    driver carries the value it was computed from.
    """

    ranked = sorted(
        contributions.items(),
        key=lambda item: abs(item[1]),
        reverse=True
    )

    records = []

    for feature, contribution in ranked:
        record = {
            "Feature": feature,
            "Contribution": round(float(contribution), 6),
            "Direction": (
                "increases_emergency_likelihood"
                if contribution > 0
                else "decreases_emergency_likelihood"
            ),
            "Description": FEATURE_PHRASES.get(feature, feature)
        }

        if feature_values and feature in feature_values:
            record["Value"] = feature_values[feature]

        records.append(record)

    return records


def reasons_from_contributions(contributions):
    """Features that actually pushed the model toward "Emergency".

    Driven by the model's own weighting rather than by fixed thresholds
    unrelated to what it learned.
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


def _fallback_reasons(values):
    """Used only when SHAP was unavailable/empty for this instance.

    Still derived from the actual feature values, never a hardcoded case.
    """

    reasons = []

    if values["PeakAcceleration"] > 15:
        reasons.append("unusually high acceleration")

    if values["MotionVariance"] > 10:
        reasons.append("significant motion variation")

    if values["PossibleFall"]:
        reasons.append("a possible fall was detected")

    if values["AudioEnergy"] > 0.5:
        reasons.append("elevated audio activity")

    if values["GPSVelocity"] <= 0.2:
        reasons.append("very low movement speed")

    return reasons


def _join_reasons(reasons):
    if not reasons:
        return ""

    if len(reasons) == 1:
        return reasons[0]

    if len(reasons) == 2:
        return reasons[0] + " and " + reasons[1]

    return ", ".join(reasons[:-1]) + ", and " + reasons[-1]


# ============================================================
# EXPLANATION
# ============================================================

def build_explanation(xai, feature_values):
    """Build the human-readable explanation block.

    Reasons, TopContributingFeatures and FeatureValues are emitted for BOTH
    outcomes: a suppressed alert needs an audit trail just as much as a
    dispatched one - "why did it NOT fire" is a real forensic question.
    """

    prediction = xai["Prediction"]
    confidence = xai["Confidence"]
    emergency = xai["EmergencyStatus"]
    shap_contributions = xai.get("SHAP", {})

    top_contributors = rank_contributions(
        shap_contributions,
        feature_values
    )

    reasons = reasons_from_contributions(shap_contributions)

    if emergency:
        if feature_values["PossibleFall"] and "a possible fall" not in reasons:
            reasons.append("a possible fall")

        if not reasons:
            reasons = _fallback_reasons(feature_values)

        title = "Emergency Detected"

        if reasons:
            message = (
                f"An emergency was detected with {confidence * 100:.1f}% "
                "confidence. The system detected signs of "
                + _join_reasons(reasons)
                + "."
            )
        else:
            # Reachable: the model can clear 0.80 on a combination of
            # features where none individually crosses a reason threshold and
            # no SHAP contribution is positive. Saying so plainly is far
            # better than crashing the pipeline, and it is a genuine signal
            # that the decision deserves a human look.
            message = (
                f"An emergency was detected with {confidence * 100:.1f}% "
                "confidence, but no single sensor reading stands out as the "
                "cause - the model reached this from the combination of "
                "readings rather than one dominant factor. Review the "
                "contributing features below."
            )

    else:
        title = "No Emergency Detected"

        if reasons:
            message = (
                "No emergency was detected. Some signals pointed that way - "
                + _join_reasons(reasons)
                + f" - but overall confidence reached only "
                f"{confidence * 100:.1f}%, below the "
                f"{xai['DecisionThreshold'] * 100:.0f}% threshold required "
                "to raise an alert."
            )
        else:
            message = (
                "No emergency was detected. The sensor readings do not "
                "currently indicate an emergency condition "
                f"(confidence {confidence * 100:.1f}%, threshold "
                f"{xai['DecisionThreshold'] * 100:.0f}%)."
            )

    explanation = {
        "Title": title,
        "Message": message,
        "Prediction": prediction,
        "Confidence": round(confidence, 4),
        "EmergencyStatus": emergency,
        "DecisionThreshold": xai["DecisionThreshold"],
        "Reasons": reasons,
        "TopContributingFeatures": top_contributors,
        "FeatureValues": feature_values
    }

    # Carried through only when the real SensorPacket path populated them.
    if "SessionID" in xai:
        explanation["SessionID"] = xai["SessionID"]
        explanation["TimestampMs"] = xai["TimestampMs"]

    return explanation


# ============================================================
# SCRIPT ENTRY POINT
# ============================================================

def main():
    with open(XAI_PATH, "r") as file:
        xai = json.load(file)

    feature_values = read_feature_values()

    explanation = build_explanation(xai, feature_values)

    with open(OUTPUT_PATH, "w") as file:
        json.dump(explanation, file, indent=4)

    print("\nHUMAN-READABLE EMERGENCY EXPLANATION")
    print("=" * 60)

    print("\n" + explanation["Title"])
    print("\n" + explanation["Message"])

    print("\nSaved to:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
