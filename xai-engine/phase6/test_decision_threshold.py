"""Phase 6 decision-threshold tests.

The decision rule must be identical to the on-device Kotlin rule in
mobile-client/.../ai/EmergencyClassifier.kt:

    prediction      = confidence >= 0.50 ? "Emergency" : "Normal"
    emergencyStatus = confidence >= 0.80

Python expresses the same thing as
`prediction == "Emergency" and confidence >= 0.80`, which reduces to the
Kotlin form because `prediction == "Emergency"` IS `confidence >= 0.50`.

Regression pinned here: the decision engine used to threshold the 4dp-rounded
"Confidence" value, so a raw confidence in [0.79995, 0.80) rounded up to 0.8
and was promoted to EmergencyStatus=True - while the phone, comparing the raw
float, returned False for the same packet. It now thresholds "ConfidenceRaw".
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DECISION_ENGINE = BASE_DIR / "phase6" / "decision_engine.py"

PREDICTION_PATH = DATA_DIR / "prediction_tflite.json"
SESSION_PATH = DATA_DIR / "session_context.json"
DECISION_PATH = DATA_DIR / "decision.json"

CLASSIFICATION_THRESHOLD = 0.50
DECISION_THRESHOLD = 0.80


# ============================================================
# Reference rules
# ============================================================

def kotlin_rule(confidence):
    """EmergencyClassifier.kt, verbatim."""

    prediction = (
        "Emergency"
        if confidence >= CLASSIFICATION_THRESHOLD
        else "Normal"
    )

    return prediction, confidence >= DECISION_THRESHOLD


# ============================================================
# Harness: run the real decision_engine.py against a crafted
# prediction file, then restore whatever was there before.
# ============================================================

def _run_decision_engine(prediction_object, session_context=None):
    saved = {
        path: (path.read_text(encoding="utf-8") if path.exists() else None)
        for path in (PREDICTION_PATH, SESSION_PATH, DECISION_PATH)
    }

    try:
        PREDICTION_PATH.write_text(
            json.dumps(prediction_object, indent=4),
            encoding="utf-8"
        )

        if session_context is None:
            if SESSION_PATH.exists():
                SESSION_PATH.unlink()
        else:
            SESSION_PATH.write_text(
                json.dumps(session_context, indent=4),
                encoding="utf-8"
            )

        result = subprocess.run(
            [sys.executable, str(DECISION_ENGINE)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise AssertionError(
                f"decision_engine.py failed:\n{result.stdout}\n{result.stderr}"
            )

        return json.loads(DECISION_PATH.read_text(encoding="utf-8"))

    finally:
        for path, content in saved.items():
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_text(content, encoding="utf-8")


def _predict(confidence):
    prediction = (
        "Emergency"
        if confidence >= CLASSIFICATION_THRESHOLD
        else "Normal"
    )

    return {
        "Prediction": prediction,
        "Confidence": round(confidence, 4),
        "ConfidenceRaw": confidence
    }


# ============================================================
# Threshold behaviour
# ============================================================

def test_exactly_at_threshold_is_an_emergency():
    """0.80 itself must qualify (`>=`, not `>`)."""

    decision = _run_decision_engine(_predict(0.80))

    assert decision["EmergencyStatus"] is True
    assert decision["Threshold"] == DECISION_THRESHOLD


def test_just_below_threshold_is_not_an_emergency():
    decision = _run_decision_engine(_predict(0.7999))

    assert decision["EmergencyStatus"] is False


def test_confident_normal_is_not_an_emergency():
    decision = _run_decision_engine(_predict(0.10))

    assert decision["Prediction"] == "Normal"
    assert decision["EmergencyStatus"] is False


def test_emergency_class_below_decision_threshold_is_held_back():
    """0.50 <= confidence < 0.80 classifies Emergency but must NOT dispatch."""

    decision = _run_decision_engine(_predict(0.65))

    assert decision["Prediction"] == "Emergency"
    assert decision["EmergencyStatus"] is False


# ============================================================
# The rounding regression
# ============================================================

def test_rounding_boundary_matches_the_on_device_rule():
    """Raw confidences that round UP to 0.8 must still not fire.

    This is the exact window where thresholding the rounded value diverged
    from the phone.
    """

    for raw in (0.79995, 0.799951, 0.79996, 0.799999):
        decision = _run_decision_engine(_predict(raw))

        _, expected = kotlin_rule(raw)

        assert decision["EmergencyStatus"] is expected, (
            f"raw={raw}: python={decision['EmergencyStatus']} "
            f"kotlin={expected}"
        )

        # the display value really does round up - i.e. the test is
        # exercising the case it claims to
        assert decision["Confidence"] == 0.8


def test_python_and_kotlin_rules_agree_across_a_sweep():
    """Sweep the whole [0, 1] range at 4dp and compare the two rules."""

    for step in range(0, 10_001):
        confidence = step / 10_000.0

        expected_prediction, expected_status = kotlin_rule(confidence)

        python_prediction = (
            "Emergency"
            if confidence >= CLASSIFICATION_THRESHOLD
            else "Normal"
        )
        python_status = (
            python_prediction == "Emergency"
            and confidence >= DECISION_THRESHOLD
        )

        assert python_prediction == expected_prediction, confidence
        assert python_status == expected_status, confidence


# ============================================================
# Backwards compatibility + session propagation
# ============================================================

def test_older_prediction_file_without_confidence_raw_still_works():
    decision = _run_decision_engine(
        {"Prediction": "Emergency", "Confidence": 0.95}
    )

    assert decision["EmergencyStatus"] is True


def test_session_context_is_propagated_into_the_decision():
    decision = _run_decision_engine(
        _predict(0.97),
        session_context={
            "SessionID": "SESS-THRESH01",
            "TimestampMs": 1_700_000_000_000
        }
    )

    assert decision["SessionID"] == "SESS-THRESH01"
    assert decision["TimestampMs"] == 1_700_000_000_000


def test_decision_has_no_session_keys_without_session_context():
    decision = _run_decision_engine(_predict(0.97))

    assert "SessionID" not in decision
    assert "TimestampMs" not in decision


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_exactly_at_threshold_is_an_emergency,
        test_just_below_threshold_is_not_an_emergency,
        test_confident_normal_is_not_an_emergency,
        test_emergency_class_below_decision_threshold_is_held_back,
        test_rounding_boundary_matches_the_on_device_rule,
        test_python_and_kotlin_rules_agree_across_a_sweep,
        test_older_prediction_file_without_confidence_raw_still_works,
        test_session_context_is_propagated_into_the_decision,
        test_decision_has_no_session_keys_without_session_context
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
