"""Parity tests: Python feature extraction vs the on-device Kotlin port.

The Kotlin port lives in Aarush's module and is NOT modified from here:
    mobile-client/app/src/main/java/com/incog/mobileclient/ai/FeatureExtractor.kt

Two things are checked:

1. Golden vectors (data/golden_feature_vectors.json) - the same fixture the
   Kotlin unit test is expected to load, so both sides pin to one set of
   numbers instead of to prose.

2. A faithful re-implementation of the Kotlin arithmetic in Python
   (kotlin_reference_extract) run against randomised packets. This catches the
   differences a golden fixture cannot: Kotlin stores accelerometer samples as
   Float (32-bit) while the JSON bridge gives Python float64, and Kotlin's
   round4 is half-away-from-zero while Python's round() is banker's rounding
   on the decimal value.

   Those two effects can move a rounded feature by at most one step of the
   4-decimal grid (1e-4). That bound is asserted, not assumed. A wider
   divergence means one of the ports has actually drifted.
"""

import json
import math
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feature_extraction import FALL_ACCELERATION_THRESHOLD, FEATURE_ORDER
from sensor_packet_adapter import (
    AUDIO_CEIL_DB,
    AUDIO_FLOOR_DB,
    AUDIO_RMS_FULL_SCALE,
    compute_feature_vector_from_packet
)

BASE_DIR = Path(__file__).resolve().parent.parent
GOLDEN_PATH = BASE_DIR / "data" / "golden_feature_vectors.json"

# One step of the 4-decimal rounding grid the feature vector is quantised to.
# The slack absorbs the representation error in the difference itself: two
# values one grid step apart subtract to 0.00010000000000331966, not to
# exactly 1e-4.
ROUNDING_GRID = 1e-4
GRID_SLACK = 1e-9


# ============================================================
# Faithful Python re-implementation of FeatureExtractor.kt
# ============================================================

def _round4_half_up(value):
    """Kotlin `round(v * 10000.0) / 10000.0` - half away from zero.

    Deliberately NOT Python's round(), which is banker's rounding applied to
    the decimal value; reproducing Kotlin's exact rule is the whole point.
    """

    if value >= 0:
        return math.floor(value * 10000.0 + 0.5) / 10000.0

    return -(math.floor(-value * 10000.0 + 0.5) / 10000.0)


def kotlin_reference_extract(packet):
    """Mirror of FeatureExtractor.fromSensorPacket, including Float storage."""

    samples = packet["accelSamples"]

    if not samples:
        return None

    magnitudes = []

    for sample in samples:
        # Vec3Reading stores x/y/z as Kotlin Float
        x = float(np.float32(sample["x"]))
        y = float(np.float32(sample["y"]))
        z = float(np.float32(sample["z"]))

        magnitudes.append(
            math.sqrt(x * x + y * y + z * z)
        )

    peak = max(magnitudes)

    if len(magnitudes) < 2:
        variance = 0.0
    else:
        mean = sum(magnitudes) / len(magnitudes)
        variance = (
            sum((value - mean) ** 2 for value in magnitudes)
            / (len(magnitudes) - 1)
        )

    audio_db = 20.0 * math.log10(
        max(packet["audioRmsEnergy"], 1.0) / AUDIO_RMS_FULL_SCALE
    )
    audio_energy = min(
        max((audio_db - AUDIO_FLOOR_DB) / (AUDIO_CEIL_DB - AUDIO_FLOOR_DB), 0.0),
        1.0
    )

    location = packet.get("latestLocation")

    if location and location.get("speedMps") is not None:
        gps_velocity = float(np.float32(location["speedMps"]))
    else:
        gps_velocity = 0.0

    return {
        "PeakAcceleration": _round4_half_up(peak),
        "MotionVariance": _round4_half_up(variance),
        "AudioEnergy": _round4_half_up(audio_energy),
        "GPSVelocity": _round4_half_up(gps_velocity),
        # NOTE: the UNROUNDED peak, exactly as in FeatureExtractor.kt
        "PossibleFall": peak > FALL_ACCELERATION_THRESHOLD
    }


def _random_packet(rng):
    count = rng.randint(1, 60)

    samples = [
        {
            "timestampMs": index * 20,
            "x": rng.uniform(-30, 30),
            "y": rng.uniform(-30, 30),
            "z": rng.uniform(-30, 30)
        }
        for index in range(count)
    ]

    return {
        "sessionId": "SESS-FUZZ",
        "timestampMs": 1_700_000_000_000,
        "accelSamples": samples,
        "gyroSamples": [],
        "audioRmsEnergy": rng.uniform(0, 40_000),
        "latestLocation": (
            {"speedMps": rng.uniform(0, 30)}
            if rng.random() < 0.7
            else None
        )
    }


# ============================================================
# Golden vectors
# ============================================================

def test_golden_fixture_exists_and_matches_feature_order():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    assert golden["featureOrder"] == FEATURE_ORDER
    assert len(golden["cases"]) > 0


def test_python_reproduces_every_golden_vector():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    for case in golden["cases"]:
        actual = compute_feature_vector_from_packet(case["packet"])

        assert actual == case["expected"], (
            f"{case['name']}: {actual} != {case['expected']}"
        )


def test_kotlin_reference_reproduces_every_golden_vector():
    """The Kotlin arithmetic must land on the same golden numbers too."""

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    tolerance = golden["tolerance"]

    for case in golden["cases"]:
        actual = kotlin_reference_extract(case["packet"])
        expected = case["expected"]

        assert actual["PossibleFall"] == expected["PossibleFall"], case["name"]

        for feature in FEATURE_ORDER[:-1]:
            assert abs(actual[feature] - expected[feature]) <= tolerance, (
                f"{case['name']}/{feature}: "
                f"{actual[feature]} vs {expected[feature]}"
            )


# ============================================================
# Randomised parity
# ============================================================

def test_randomised_packets_agree_within_the_rounding_grid():
    rng = random.Random(20250902)

    worst = {feature: 0.0 for feature in FEATURE_ORDER[:-1]}

    for _ in range(2000):
        packet = _random_packet(rng)

        mine = compute_feature_vector_from_packet(packet)
        theirs = kotlin_reference_extract(packet)

        for feature in FEATURE_ORDER[:-1]:
            worst[feature] = max(
                worst[feature],
                abs(mine[feature] - theirs[feature])
            )

    for feature, delta in worst.items():
        assert delta <= ROUNDING_GRID + GRID_SLACK, (
            f"{feature} diverges by {delta}, more than one 4-decimal step "
            f"({ROUNDING_GRID}) - the ports have drifted, this is not just "
            f"float32/rounding noise"
        )


def test_possible_fall_never_disagrees():
    """PossibleFall is a hard boolean gate, so it must match exactly."""

    rng = random.Random(20250903)

    for _ in range(2000):
        packet = _random_packet(rng)

        assert (
            compute_feature_vector_from_packet(packet)["PossibleFall"]
            == kotlin_reference_extract(packet)["PossibleFall"]
        )


def test_fall_threshold_boundary_is_exclusive_on_both_sides():
    """Exactly 15.0 must NOT be a fall (`>`, not `>=`) in either port."""

    def one(magnitude_x):
        return {
            "sessionId": "S",
            "timestampMs": 0,
            "accelSamples": [
                {"timestampMs": 0, "x": magnitude_x, "y": 0.0, "z": 0.0}
            ],
            "audioRmsEnergy": 0.0,
            "latestLocation": None
        }

    assert compute_feature_vector_from_packet(one(15.0))["PossibleFall"] is False
    assert kotlin_reference_extract(one(15.0))["PossibleFall"] is False

    assert compute_feature_vector_from_packet(one(15.001))["PossibleFall"] is True
    assert kotlin_reference_extract(one(15.001))["PossibleFall"] is True


# ============================================================
# Adapter robustness (Python-side hardening; the Kotlin types make
# these unrepresentable on-device, so there is nothing to mirror)
# ============================================================

def test_location_without_speed_falls_back_to_zero():
    packet = {
        "sessionId": "S",
        "timestampMs": 0,
        "accelSamples": [{"timestampMs": 0, "x": 1.0, "y": 0.0, "z": 0.0}],
        "audioRmsEnergy": 0.0,
        "latestLocation": {"latitude": 1.0, "longitude": 2.0}  # no speedMps
    }

    assert compute_feature_vector_from_packet(packet)["GPSVelocity"] == 0.0


def test_negative_audio_rms_is_clamped_to_zero():
    packet = {
        "sessionId": "S",
        "timestampMs": 0,
        "accelSamples": [{"timestampMs": 0, "x": 1.0, "y": 0.0, "z": 0.0}],
        "audioRmsEnergy": -500.0,
        "latestLocation": None
    }

    assert compute_feature_vector_from_packet(packet)["AudioEnergy"] == 0.0


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_golden_fixture_exists_and_matches_feature_order,
        test_python_reproduces_every_golden_vector,
        test_kotlin_reference_reproduces_every_golden_vector,
        test_randomised_packets_agree_within_the_rounding_grid,
        test_possible_fall_never_disagrees,
        test_fall_threshold_boundary_is_exclusive_on_both_sides,
        test_location_without_speed_falls_back_to_zero,
        test_negative_audio_rms_is_clamped_to_zero
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
