"""Contract tests for data/xai_output.json - the Phase 6 -> backend handoff.

Two audiences, one document:

  * security-module/AIResult.kt mirrors the ORIGINAL six keys plus the
    optional SessionID/TimestampMs. Those must never be renamed or dropped.
  * Chirag's backend attaches the explanation after evidence arrives, so it
    also needs FeatureValues, TopContributingFeatures and Explanation.

These tests read the committed artifact rather than regenerating it, so they
run without TensorFlow. Regenerate with:
    python run_ai_pipeline.py --source packet
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

XAI_PATH = DATA_DIR / "xai_output.json"
HUMAN_PATH = DATA_DIR / "human_explanation.json"
CONTRACT_PATH = DATA_DIR / "model_contract.json"

sys.path.insert(0, str(BASE_DIR))

from xai.explanation_generator import (      # noqa: E402
    build_explanation,
    rank_contributions
)

# Exactly the fields security-module/AIResult.kt declares as non-optional.
AIRESULT_REQUIRED_KEYS = [
    "Prediction",
    "Confidence",
    "EmergencyStatus",
    "DecisionThreshold",
    "SHAP",
    "LIME"
]

ENRICHMENT_KEYS = [
    "FeatureValues",
    "TopContributingFeatures",
    "Explanation"
]


def xai():
    return json.loads(XAI_PATH.read_text(encoding="utf-8"))


def features():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["featureOrder"]


# ============================================================
# Backwards-compatible core
# ============================================================

def test_airesult_required_keys_are_present():
    document = xai()

    missing = [key for key in AIRESULT_REQUIRED_KEYS if key not in document]

    assert not missing, (
        f"{missing} missing - security-module/AIResult.kt declares these "
        f"non-optional and will fail to deserialize"
    )


def test_prediction_and_status_are_consistent():
    document = xai()

    assert document["Prediction"] in ("Emergency", "Normal")
    assert isinstance(document["EmergencyStatus"], bool)

    if document["EmergencyStatus"]:
        assert document["Prediction"] == "Emergency", (
            "EmergencyStatus=True with Prediction=Normal is contradictory"
        )


def test_emergency_status_agrees_with_the_decision_threshold():
    document = xai()

    threshold = document["DecisionThreshold"]
    confidence = document["Confidence"]

    # Confidence in this file is the 4dp display value, so allow the rounding
    # half-step; the raw-value rule is pinned in
    # phase6/test_decision_threshold.py.
    if document["EmergencyStatus"]:
        assert confidence >= threshold - 5e-5
    else:
        assert confidence < threshold + 5e-5


def test_shap_covers_every_feature():
    document = xai()

    assert sorted(document["SHAP"].keys()) == sorted(features())

    for feature, value in document["SHAP"].items():
        assert isinstance(value, (int, float)), feature


def test_lime_is_populated():
    document = xai()

    assert len(document["LIME"]) > 0

    for value in document["LIME"].values():
        assert isinstance(value, (int, float))


# ============================================================
# Enrichment for the backend
# ============================================================

def test_enrichment_keys_are_present():
    document = xai()

    missing = [key for key in ENRICHMENT_KEYS if key not in document]

    assert not missing, f"{missing} missing from xai_output.json"


def test_feature_values_cover_every_feature_with_the_right_types():
    document = xai()
    values = document["FeatureValues"]

    assert sorted(values.keys()) == sorted(features())

    for name in features()[:-1]:
        assert isinstance(values[name], (int, float)), name

    assert isinstance(values["PossibleFall"], bool)


def test_top_contributing_features_are_ranked_and_complete():
    document = xai()
    contributors = document["TopContributingFeatures"]

    assert len(contributors) == len(features())

    for record in contributors:
        assert set(record) >= {
            "Feature",
            "Contribution",
            "Direction",
            "Description"
        }
        assert record["Direction"] in (
            "increases_emergency_likelihood",
            "decreases_emergency_likelihood"
        )

    magnitudes = [abs(record["Contribution"]) for record in contributors]

    assert magnitudes == sorted(magnitudes, reverse=True), (
        "TopContributingFeatures must be ordered by |contribution|, "
        "strongest first"
    )


def test_top_contributors_match_the_shap_block():
    document = xai()

    from_records = {
        record["Feature"]: record["Contribution"]
        for record in document["TopContributingFeatures"]
    }

    assert from_records == document["SHAP"], (
        "TopContributingFeatures disagrees with the SHAP block - they must "
        "be two views of one explanation"
    )


def test_explanation_is_human_readable_and_non_empty():
    document = xai()
    explanation = document["Explanation"]

    assert explanation["Title"]
    assert len(explanation["Message"]) > 20
    assert explanation["Message"].endswith(".")
    assert isinstance(explanation["Reasons"], list)

    if document["EmergencyStatus"]:
        assert explanation["Reasons"], (
            "an emergency must state at least one reason"
        )


def test_human_explanation_file_agrees_with_the_embedded_block():
    document = xai()
    human = json.loads(HUMAN_PATH.read_text(encoding="utf-8"))

    assert human["Title"] == document["Explanation"]["Title"]
    assert human["Message"] == document["Explanation"]["Message"]
    assert human["Reasons"] == document["Explanation"]["Reasons"]


# ============================================================
# Session propagation
# ============================================================

def test_session_context_propagates_as_a_pair():
    document = xai()

    has_session = "SessionID" in document
    has_timestamp = "TimestampMs" in document

    assert has_session == has_timestamp, (
        "SessionID and TimestampMs must appear together or not at all"
    )

    if has_session:
        assert isinstance(document["SessionID"], str)
        assert isinstance(document["TimestampMs"], int)

        human = json.loads(HUMAN_PATH.read_text(encoding="utf-8"))

        assert human["SessionID"] == document["SessionID"], (
            "session context lost between xai_output and human_explanation"
        )


# ============================================================
# Generator behaviour that the committed artifact cannot show
# ============================================================

def test_normal_outcome_still_carries_full_structure():
    """A suppressed alert needs the same audit trail as a dispatched one."""

    normal = {
        "Prediction": "Normal",
        "Confidence": 0.12,
        "EmergencyStatus": False,
        "DecisionThreshold": 0.8,
        "SHAP": {
            "PeakAcceleration": -0.04,
            "MotionVariance": -0.03,
            "AudioEnergy": 0.002,
            "GPSVelocity": 0.01,
            "PossibleFall": -0.05
        }
    }

    values = {
        "PeakAcceleration": 9.9,
        "MotionVariance": 0.3,
        "AudioEnergy": 0.05,
        "GPSVelocity": 1.1,
        "PossibleFall": False
    }

    explanation = build_explanation(normal, values)

    assert explanation["Title"] == "No Emergency Detected"
    assert explanation["EmergencyStatus"] is False
    assert explanation["FeatureValues"] == values
    assert len(explanation["TopContributingFeatures"]) == 5
    assert "12.0%" in explanation["Message"]
    assert "80%" in explanation["Message"]


def test_emergency_with_no_identifiable_reason_does_not_crash():
    """Regression: this used to raise IndexError and kill the pipeline.

    The model can clear 0.80 on a combination of readings where no single
    feature crosses a reason threshold and no SHAP contribution is positive.
    _join_reasons([]) then indexed an empty list. Reachable in production, so
    it must degrade to a plain message instead of crashing.
    """

    document = {
        "Prediction": "Emergency",
        "Confidence": 0.97,
        "EmergencyStatus": True,
        "DecisionThreshold": 0.8,
        "SHAP": {
            "PeakAcceleration": -0.01,
            "MotionVariance": -0.01,
            "AudioEnergy": -0.01,
            "GPSVelocity": -0.01,
            "PossibleFall": -0.01
        }
    }

    values = {
        "PeakAcceleration": 9.8,
        "MotionVariance": 0.25,
        "AudioEnergy": 0.05,
        "GPSVelocity": 1.2,
        "PossibleFall": False
    }

    explanation = build_explanation(document, values)

    assert explanation["Title"] == "Emergency Detected"
    assert explanation["Reasons"] == []
    assert "97.0%" in explanation["Message"]
    assert explanation["Message"].endswith(".")
    assert len(explanation["TopContributingFeatures"]) == 5


def test_join_reasons_handles_every_arity():
    from xai.explanation_generator import _join_reasons

    assert _join_reasons([]) == ""
    assert _join_reasons(["a"]) == "a"
    assert _join_reasons(["a", "b"]) == "a and b"
    assert _join_reasons(["a", "b", "c"]) == "a, b, and c"


def test_ranking_orders_by_magnitude_not_by_sign():
    """A strongly NEGATIVE driver must outrank a weakly positive one."""

    ranked = rank_contributions(
        {"A": 0.01, "B": -0.90, "C": 0.30}
    )

    assert [record["Feature"] for record in ranked] == ["B", "C", "A"]
    assert ranked[0]["Direction"] == "decreases_emergency_likelihood"


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_airesult_required_keys_are_present,
        test_prediction_and_status_are_consistent,
        test_emergency_status_agrees_with_the_decision_threshold,
        test_shap_covers_every_feature,
        test_lime_is_populated,
        test_enrichment_keys_are_present,
        test_feature_values_cover_every_feature_with_the_right_types,
        test_top_contributing_features_are_ranked_and_complete,
        test_top_contributors_match_the_shap_block,
        test_explanation_is_human_readable_and_non_empty,
        test_human_explanation_file_agrees_with_the_embedded_block,
        test_session_context_propagates_as_a_pair,
        test_normal_outcome_still_carries_full_structure,
        test_emergency_with_no_identifiable_reason_does_not_crash,
        test_join_reasons_handles_every_arity,
        test_ranking_orders_by_magnitude_not_by_sign
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"PASS - {test.__name__}")
            passed += 1
        except Exception as error:
            print(f"FAIL - {test.__name__}: {error}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")

    if failed:
        raise SystemExit(1)
