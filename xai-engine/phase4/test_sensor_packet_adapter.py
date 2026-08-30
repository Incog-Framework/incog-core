from sensor_packet_adapter import (
    compute_feature_vector_from_packet,
    extract_from_sensor_packet,
    validate_packet,
    AUDIO_RMS_FULL_SCALE
)


# ============================================================
# Helpers - build packets shaped exactly like the real Kotlin
# SensorPacket (see handoff/SensorPacket.kt), serialized to JSON/dict.
# ============================================================

def accel_sample(x, y, z, t=0):
    return {"timestampMs": t, "x": x, "y": y, "z": z}


def make_normal_packet():
    # resting device: ~1g on one axis, low audio, walking-speed GPS fix
    samples = [accel_sample(0.8, 9.6, 1.2, t) for t in range(20)]

    return {
        "sessionId": "SESS-NORMAL01",
        "timestampMs": 1_700_000_000_000,
        "latestAccel": samples[-1],
        "latestGyro": None,
        "latestLocation": {
            "timestampMs": 1_700_000_000_000,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "speedMps": 1.0,
            "accuracyM": 5.0
        },
        "accelSamples": samples,
        "gyroSamples": [],
        "audioRmsEnergy": 500.0,
        "audioBufferedMs": 2000
    }


def make_fall_packet():
    # sharp acceleration spike partway through the window, like an impact
    samples = [accel_sample(0.8, 9.6, 1.2, t) for t in range(10)]
    samples += [accel_sample(18.2, 4.1, 12.5, t) for t in range(10, 20)]

    return {
        "sessionId": "SESS-FALL0001",
        "timestampMs": 1_700_000_005_000,
        "latestAccel": samples[-1],
        "latestGyro": None,
        "latestLocation": None,  # no GPS fix yet (e.g. indoors)
        "accelSamples": samples,
        "gyroSamples": [],
        "audioRmsEnergy": 24000.0,  # loud noise/scream, near PCM16 full scale
        "audioBufferedMs": 2000
    }


# ============================================================
# Validation
# ============================================================

def test_missing_required_field_raises():
    packet = make_normal_packet()
    del packet["audioRmsEnergy"]

    try:
        validate_packet(packet)
        raise AssertionError("Expected ValueError for missing audioRmsEnergy")
    except ValueError as error:
        assert "audioRmsEnergy" in str(error)


def test_empty_accel_samples_raises():
    packet = make_normal_packet()
    packet["accelSamples"] = []

    try:
        validate_packet(packet)
        raise AssertionError("Expected ValueError for empty accelSamples")
    except ValueError as error:
        assert "accelSamples" in str(error)


def test_malformed_accel_sample_raises():
    packet = make_normal_packet()
    packet["accelSamples"][0] = {"timestampMs": 0, "x": 0.8, "y": 9.6}  # missing 'z'

    try:
        validate_packet(packet)
        raise AssertionError("Expected ValueError for malformed accel sample")
    except ValueError as error:
        assert "'z'" in str(error)


# ============================================================
# Single-sample window does not crash (real early-session edge case:
# the very first packet can carry only 1 accelerometer sample)
# ============================================================

def test_single_accel_sample_gives_zero_variance_not_nan():
    packet = make_normal_packet()
    packet["accelSamples"] = [accel_sample(0.8, 9.6, 1.2, 0)]

    features = compute_feature_vector_from_packet(packet)

    assert features["MotionVariance"] == 0.0
    assert features["PeakAcceleration"] > 0


# ============================================================
# Feature correctness against the real packet shape
# ============================================================

def test_normal_packet_does_not_flag_fall():
    features = compute_feature_vector_from_packet(make_normal_packet())

    assert features["PossibleFall"] is False
    assert features["PeakAcceleration"] < 15
    assert 0.0 <= features["AudioEnergy"] <= 1.0


def test_fall_packet_flags_possible_fall():
    features = compute_feature_vector_from_packet(make_fall_packet())

    assert features["PossibleFall"] is True
    assert features["PeakAcceleration"] > 15


def test_missing_gps_fix_defaults_to_zero_velocity():
    features = compute_feature_vector_from_packet(make_fall_packet())

    assert features["GPSVelocity"] == 0.0


def test_audio_rms_is_rescaled_into_zero_one_range():
    packet = make_normal_packet()
    packet["audioRmsEnergy"] = AUDIO_RMS_FULL_SCALE * 2  # clamp check: above full scale

    features = compute_feature_vector_from_packet(packet)

    assert features["AudioEnergy"] == 1.0


def test_feature_order_matches_model_contract():
    features = compute_feature_vector_from_packet(make_normal_packet())

    assert list(features.keys()) == [
        "PeakAcceleration",
        "MotionVariance",
        "AudioEnergy",
        "GPSVelocity",
        "PossibleFall"
    ]


# ============================================================
# Session context is carried through
# ============================================================

def test_session_and_timestamp_are_carried_through():
    result = extract_from_sensor_packet(make_fall_packet())

    assert result["SessionID"] == "SESS-FALL0001"
    assert result["TimestampMs"] == 1_700_000_005_000
    assert "PeakAcceleration" in result["Features"]


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_missing_required_field_raises,
        test_empty_accel_samples_raises,
        test_malformed_accel_sample_raises,
        test_single_accel_sample_gives_zero_variance_not_nan,
        test_normal_packet_does_not_flag_fall,
        test_fall_packet_flags_possible_fall,
        test_missing_gps_fix_defaults_to_zero_velocity,
        test_audio_rms_is_rescaled_into_zero_one_range,
        test_feature_order_matches_model_contract,
        test_session_and_timestamp_are_carried_through
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
