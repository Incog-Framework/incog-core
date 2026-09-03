"""Tests for the callable explainer — the backend-facing entry point.

Needs TensorFlow + shap + lime. Writes nothing to disk.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from xai.explainer_service import (         # noqa: E402
    DECISION_THRESHOLD,
    Explainer,
    explain,
    explain_evidence,
    normalise_features,
    to_model_row
)

EMERGENCY_FEATURES = {
    "PeakAcceleration": 24.0967,
    "MotionVariance": 33.5643,
    "AudioEnergy": 0.6561,
    "GPSVelocity": 0.0,
    "PossibleFall": True
}

NORMAL_FEATURES = {
    "PeakAcceleration": 9.8,
    "MotionVariance": 0.25,
    "AudioEnergy": 0.05,
    "GPSVelocity": 1.2,
    "PossibleFall": False
}

# One shared instance: constructing it loads TensorFlow and the background.
EXPLAINER = Explainer()


# ============================================================
# Feature contract
# ============================================================

def test_model_row_is_in_contract_order():
    row = to_model_row(EMERGENCY_FEATURES)

    assert list(row) == [
        24.0967, 33.5643, 0.6561, 0.0, 1.0
    ], list(row)


def test_possible_fall_encodes_as_one_or_zero():
    assert to_model_row(EMERGENCY_FEATURES)[4] == 1.0
    assert to_model_row(NORMAL_FEATURES)[4] == 0.0


def test_missing_feature_is_rejected():
    partial = dict(EMERGENCY_FEATURES)
    del partial["AudioEnergy"]

    try:
        normalise_features(partial)
    except ValueError as error:
        assert "AudioEnergy" in str(error)
        return

    raise AssertionError("expected a missing feature to raise")


def test_string_feature_is_rejected():
    bad = dict(EMERGENCY_FEATURES, PeakAcceleration="24.1")

    try:
        normalise_features(bad)
    except ValueError as error:
        assert "PeakAcceleration" in str(error)
        return

    raise AssertionError("expected a non-numeric feature to raise")


def test_possible_fall_accepts_bool_and_int():
    assert normalise_features(
        dict(EMERGENCY_FEATURES, PossibleFall=1)
    )["PossibleFall"] is True

    assert normalise_features(
        dict(EMERGENCY_FEATURES, PossibleFall=0)
    )["PossibleFall"] is False


# ============================================================
# Explanation shape — must match data/xai_output.json
# ============================================================

def test_explanation_has_the_backend_contract_keys():
    result = EXPLAINER.explain(EMERGENCY_FEATURES)

    for key in (
        "Prediction",
        "Confidence",
        "EmergencyStatus",
        "DecisionThreshold",
        "SHAP",
        "LIME",
        "FeatureValues",
        "TopContributingFeatures",
        "Explanation"
    ):
        assert key in result, f"missing {key}"


def test_shap_covers_every_feature():
    result = EXPLAINER.explain(EMERGENCY_FEATURES, include_lime=False)

    assert sorted(result["SHAP"]) == sorted(EMERGENCY_FEATURES)


def test_top_contributors_agree_with_shap_and_are_ranked():
    result = EXPLAINER.explain(EMERGENCY_FEATURES, include_lime=False)

    from_records = {
        record["Feature"]: record["Contribution"]
        for record in result["TopContributingFeatures"]
    }

    assert from_records == result["SHAP"]

    magnitudes = [
        abs(record["Contribution"])
        for record in result["TopContributingFeatures"]
    ]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_session_context_is_carried_through():
    result = EXPLAINER.explain(
        EMERGENCY_FEATURES,
        session={"SessionID": "SESS-SVC01", "TimestampMs": 1_700_000_000_000},
        include_lime=False
    )

    assert result["SessionID"] == "SESS-SVC01"
    assert result["TimestampMs"] == 1_700_000_000_000


def test_no_session_keys_when_none_supplied():
    result = EXPLAINER.explain(EMERGENCY_FEATURES, include_lime=False)

    assert "SessionID" not in result
    assert "TimestampMs" not in result


def test_lime_can_be_skipped_for_a_cheaper_explanation():
    result = EXPLAINER.explain(EMERGENCY_FEATURES, include_lime=False)

    assert result["LIME"] == {}

    with_lime = EXPLAINER.explain(EMERGENCY_FEATURES, include_lime=True)

    assert len(with_lime["LIME"]) > 0


# ============================================================
# Decision semantics
# ============================================================

def test_normal_features_do_not_raise_an_emergency():
    result = EXPLAINER.explain(NORMAL_FEATURES, include_lime=False)

    assert result["EmergencyStatus"] is False
    assert result["Explanation"]["Title"] == "No Emergency Detected"


def test_device_confidence_wins_over_recomputation():
    """The explanation must describe the decision the phone actually made."""

    result = EXPLAINER.explain(
        NORMAL_FEATURES,
        prediction={"Confidence": 0.97, "ConfidenceRaw": 0.97},
        include_lime=False
    )

    assert result["Confidence"] == 0.97
    assert result["EmergencyStatus"] is True


def test_confidence_disagreement_is_surfaced_not_hidden():
    """A phone running a different model must not be silently explained."""

    result = EXPLAINER.explain(
        NORMAL_FEATURES,
        prediction={"Confidence": 0.97, "ConfidenceRaw": 0.97},
        include_lime=False
    )

    assert "ConfidenceMismatch" in result
    assert result["ConfidenceMismatch"]["reported_by_device"] == 0.97


def test_agreeing_confidence_produces_no_mismatch_block():
    confidence = EXPLAINER.predict(EMERGENCY_FEATURES)

    result = EXPLAINER.explain(
        EMERGENCY_FEATURES,
        prediction={"Confidence": confidence, "ConfidenceRaw": confidence},
        include_lime=False
    )

    assert "ConfidenceMismatch" not in result


def test_emergency_status_uses_the_080_threshold():
    assert DECISION_THRESHOLD == 0.80

    result = EXPLAINER.explain(
        NORMAL_FEATURES,
        prediction={"Confidence": 0.80, "ConfidenceRaw": 0.80},
        include_lime=False
    )
    assert result["EmergencyStatus"] is True

    result = EXPLAINER.explain(
        NORMAL_FEATURES,
        prediction={"Confidence": 0.7999, "ConfidenceRaw": 0.7999},
        include_lime=False
    )
    assert result["EmergencyStatus"] is False


# ============================================================
# Evidence entry point
# ============================================================

def test_explain_evidence_accepts_the_airesult_shape():
    result = explain_evidence({
        "SessionID": "SESS-EV001",
        "TimestampMs": 1_700_000_000_000,
        "Prediction": "Emergency",
        "Confidence": 0.9999,
        "EmergencyStatus": True,
        "FeatureValues": EMERGENCY_FEATURES
    })

    assert result["SessionID"] == "SESS-EV001"
    assert result["Confidence"] == 0.9999
    assert result["SHAP"]


def test_explain_evidence_rejects_a_payload_without_features():
    try:
        explain_evidence({"SessionID": "X", "Confidence": 0.9})
    except ValueError as error:
        assert "FeatureValues" in str(error)
        return

    raise AssertionError("expected evidence without features to raise")


# ============================================================
# Purity — a service must not depend on pipeline files
# ============================================================

def test_explaining_writes_no_files():
    data_dir = BASE_DIR / "data"

    before = {
        path: path.stat().st_mtime
        for path in data_dir.glob("*.json")
    }

    explain(EMERGENCY_FEATURES, include_lime=False)

    after = {
        path: path.stat().st_mtime
        for path in data_dir.glob("*.json")
    }

    changed = [
        path.name
        for path in before
        if path in after and before[path] != after[path]
    ]

    assert not changed, f"explain() wrote to {changed}; it must be pure"


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_model_row_is_in_contract_order,
        test_possible_fall_encodes_as_one_or_zero,
        test_missing_feature_is_rejected,
        test_string_feature_is_rejected,
        test_possible_fall_accepts_bool_and_int,
        test_explanation_has_the_backend_contract_keys,
        test_shap_covers_every_feature,
        test_top_contributors_agree_with_shap_and_are_ranked,
        test_session_context_is_carried_through,
        test_no_session_keys_when_none_supplied,
        test_lime_can_be_skipped_for_a_cheaper_explanation,
        test_normal_features_do_not_raise_an_emergency,
        test_device_confidence_wins_over_recomputation,
        test_confidence_disagreement_is_surfaced_not_hidden,
        test_agreeing_confidence_produces_no_mismatch_block,
        test_emergency_status_uses_the_080_threshold,
        test_explain_evidence_accepts_the_airesult_shape,
        test_explain_evidence_rejects_a_payload_without_features,
        test_explaining_writes_no_files
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
