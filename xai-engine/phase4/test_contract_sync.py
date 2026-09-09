"""Drift detector for the constants duplicated across languages and files.

The same five numbers appear in several places by necessity - Python cannot
import Kotlin constants and vice versa. This test asserts every copy still
agrees with data/model_contract.json:

    Python  phase4/feature_extraction.py      FALL_ACCELERATION_THRESHOLD, FEATURE_ORDER
            phase4/sensor_packet_adapter.py   AUDIO_RMS_FULL_SCALE, AUDIO_FLOOR_DB, AUDIO_CEIL_DB
            phase6/decision_engine.py         THRESHOLD (0.80)
            phase5/tflite_predict.py          classification cutoff (0.50)
            data/model_metadata.json          both thresholds + feature list
            data/tflite_feature_order.json    feature order

    Kotlin  ai/FeatureExtractor.kt            FALL_ACCELERATION_THRESHOLD, AUDIO_RMS_FULL_SCALE,
                                               AUDIO_FLOOR_DB, AUDIO_CEIL_DB
            ai/EmergencyClassifier.kt         CLASSIFICATION_THRESHOLD, DECISION_THRESHOLD
            ai/FeatureVector.kt               model input order

The Kotlin half is read as text (never modified - it is Aarush's module) and
is SKIPPED with a clear message when mobile-client is not checked out, so this
file is useful both in a xai-engine-only clone and in the full monorepo.
"""

import json
import hashlib
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"

CONTRACT_PATH = DATA_DIR / "model_contract.json"

KOTLIN_AI_DIR = (
    REPO_ROOT
    / "mobile-client" / "app" / "src" / "main" / "java"
    / "com" / "incog" / "mobileclient" / "ai"
)

VENDORED_MODEL = (
    REPO_ROOT
    / "mobile-client" / "app" / "src" / "main" / "assets"
    / "emergency_model.tflite"
)

sys.path.insert(0, str(BASE_DIR / "phase4"))

from feature_extraction import (            # noqa: E402
    FALL_ACCELERATION_THRESHOLD,
    FEATURE_ORDER
)
from sensor_packet_adapter import (         # noqa: E402
    AUDIO_CEIL_DB,
    AUDIO_FLOOR_DB,
    AUDIO_RMS_FULL_SCALE
)


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _read_number(path, pattern, label):
    """Pull a single numeric literal out of a source file."""

    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)

    assert match, f"could not find {label} in {path.name}"

    return float(match.group(1))


# ============================================================
# Python side
# ============================================================

def test_python_constants_match_the_contract():
    spec = contract()

    assert FEATURE_ORDER == spec["featureOrder"]
    assert FALL_ACCELERATION_THRESHOLD == spec["fallAccelerationThreshold"]
    assert AUDIO_RMS_FULL_SCALE == spec["audioRmsFullScale"]
    assert AUDIO_FLOOR_DB == spec["audioFloorDb"]
    assert AUDIO_CEIL_DB == spec["audioCeilDb"]


def test_decision_engine_threshold_matches_the_contract():
    value = _read_number(
        BASE_DIR / "phase6" / "decision_engine.py",
        r"^THRESHOLD\s*=\s*([0-9.]+)",
        "THRESHOLD"
    )

    assert value == contract()["decisionThreshold"]


def test_tflite_predict_classification_cutoff_matches_the_contract():
    value = _read_number(
        BASE_DIR / "phase5" / "tflite_predict.py",
        r"if confidence >= ([0-9.]+):",
        "classification cutoff"
    )

    assert value == contract()["classificationThreshold"]


def test_data_artifacts_match_the_contract():
    spec = contract()

    metadata = json.loads(
        (DATA_DIR / "model_metadata.json").read_text(encoding="utf-8")
    )

    assert metadata["features"] == spec["featureOrder"]
    assert metadata["classification_threshold"] == spec["classificationThreshold"]
    assert metadata["decision_threshold"] == spec["decisionThreshold"]

    feature_order = json.loads(
        (DATA_DIR / "tflite_feature_order.json").read_text(encoding="utf-8")
    )

    assert feature_order == spec["featureOrder"]


def test_contract_model_hash_matches_the_model_on_disk():
    spec = contract()

    model_path = BASE_DIR / spec["modelFile"]
    actual = hashlib.sha256(model_path.read_bytes()).hexdigest()

    assert actual == spec["modelSha256"], (
        "emergency_model.tflite changed but data/model_contract.json was not "
        "regenerated - run: python generate_contract_fixtures.py"
    )


# ============================================================
# Kotlin side (read-only; skipped when mobile-client is absent)
# ============================================================

def _skip_without_kotlin():
    if not KOTLIN_AI_DIR.is_dir():
        print(
            "    SKIP - mobile-client not checked out at "
            f"{KOTLIN_AI_DIR.relative_to(REPO_ROOT)}"
        )
        return True

    return False


def test_kotlin_feature_extractor_constants_match_the_contract():
    if _skip_without_kotlin():
        return

    spec = contract()
    path = KOTLIN_AI_DIR / "FeatureExtractor.kt"

    fall = _read_number(
        path,
        r"FALL_ACCELERATION_THRESHOLD\s*=\s*([0-9.]+)",
        "FALL_ACCELERATION_THRESHOLD"
    )
    full_scale = _read_number(
        path,
        r"AUDIO_RMS_FULL_SCALE\s*=\s*([0-9.]+)",
        "AUDIO_RMS_FULL_SCALE"
    )
    floor_db = _read_number(
        path,
        r"AUDIO_FLOOR_DB\s*=\s*(-?[0-9.]+)",
        "AUDIO_FLOOR_DB"
    )
    ceil_db = _read_number(
        path,
        r"AUDIO_CEIL_DB\s*=\s*(-?[0-9.]+)",
        "AUDIO_CEIL_DB"
    )

    assert fall == spec["fallAccelerationThreshold"]
    assert full_scale == spec["audioRmsFullScale"]
    assert floor_db == spec["audioFloorDb"]
    assert ceil_db == spec["audioCeilDb"]


def test_kotlin_classifier_thresholds_match_the_contract():
    if _skip_without_kotlin():
        return

    spec = contract()
    path = KOTLIN_AI_DIR / "EmergencyClassifier.kt"

    classification = _read_number(
        path,
        r"CLASSIFICATION_THRESHOLD\s*=\s*([0-9.]+)",
        "CLASSIFICATION_THRESHOLD"
    )
    decision = _read_number(
        path,
        r"DECISION_THRESHOLD\s*=\s*([0-9.]+)",
        "DECISION_THRESHOLD"
    )

    assert classification == spec["classificationThreshold"]
    assert decision == spec["decisionThreshold"]


def test_kotlin_model_input_order_matches_the_contract():
    if _skip_without_kotlin():
        return

    spec = contract()

    text = (KOTLIN_AI_DIR / "FeatureVector.kt").read_text(encoding="utf-8")

    # Everything between `floatArrayOf(` and the closing paren on its own
    # line. Splitting on the first ")" would truncate at `.toFloat()`.
    body = text.split("floatArrayOf(", 1)[1].split("\n    )", 1)[0]

    expected = [
        spec["kotlinPropertyNames"][feature]
        for feature in spec["featureOrder"]
    ]

    missing = [name for name in expected if name not in body]

    assert not missing, (
        f"toModelInput() does not reference {missing} - the Kotlin model "
        f"input is missing features the model expects"
    )

    positions = [body.index(name) for name in expected]

    assert positions == sorted(positions), (
        "toModelInput() emits the features in a different order than "
        "the contract's featureOrder"
    )


def test_vendored_model_asset_is_identical_to_the_trained_model():
    """The phone must run the exact artifact SHAP/LIME explain."""

    if not VENDORED_MODEL.exists():
        print(
            "    SKIP - mobile-client asset not checked out at "
            f"{VENDORED_MODEL.name}"
        )
        return

    spec = contract()

    vendored = hashlib.sha256(VENDORED_MODEL.read_bytes()).hexdigest()

    assert vendored == spec["modelSha256"], (
        "mobile-client/app/src/main/assets/emergency_model.tflite differs "
        "from xai-engine/data/emergency_model.tflite - the phone is running "
        "a different model than the one that was trained and explained"
    )


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_python_constants_match_the_contract,
        test_decision_engine_threshold_matches_the_contract,
        test_tflite_predict_classification_cutoff_matches_the_contract,
        test_data_artifacts_match_the_contract,
        test_contract_model_hash_matches_the_model_on_disk,
        test_kotlin_feature_extractor_constants_match_the_contract,
        test_kotlin_classifier_thresholds_match_the_contract,
        test_kotlin_model_input_order_matches_the_contract,
        test_vendored_model_asset_is_identical_to_the_trained_model
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
