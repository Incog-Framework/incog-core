import pandas as pd

from feature_extraction import (
    compute_feature_vector,
    validate_and_clean
)


# ============================================================
# Helpers
# ============================================================

def make_normal_readings():
    return pd.DataFrame({
        "acc_x": [0.8, 0.9, 1.0],
        "acc_y": [9.6, 9.7, 9.5],
        "acc_z": [1.2, 1.1, 1.3],
        "gyro_x": [0.1, 0.1, 0.2],
        "audio_energy": [0.05, 0.06, 0.05],
        "gps_speed": [0.0, 0.0, 0.1]
    })


def make_fall_readings():
    return pd.DataFrame({
        "acc_x": [18.2, 20.1, 22.5],
        "acc_y": [4.1, 5.0, 6.2],
        "acc_z": [12.5, 13.0, 14.1],
        "audio_energy": [0.82, 0.85, 0.88],
        "gps_speed": [0.0, 0.0, 0.0]
    })


# ============================================================
# Missing columns
# ============================================================

def test_missing_required_column_raises():
    data = make_normal_readings().drop(columns=["gps_speed"])

    try:
        validate_and_clean(data)
        raise AssertionError("Expected ValueError for missing column")
    except ValueError as error:
        assert "gps_speed" in str(error)


# ============================================================
# Malformed values are coerced / dropped, not crashed on
# ============================================================

def test_non_numeric_values_are_dropped():
    data = make_normal_readings()
    # mimic a CSV column that arrives as mixed/object dtype with a stray
    # non-numeric value, e.g. a corrupted sensor reading
    data["acc_x"] = data["acc_x"].astype(object)
    data.loc[0, "acc_x"] = "not_a_number"

    cleaned = validate_and_clean(data)

    # the malformed row should be dropped, the other 2 remain
    assert len(cleaned) == 2


def test_missing_values_are_dropped():
    data = make_normal_readings()
    data.loc[1, "audio_energy"] = None

    cleaned = validate_and_clean(data)

    assert len(cleaned) == 2


# ============================================================
# Empty / fully invalid data raises rather than silently
# producing a zeroed-out feature vector
# ============================================================

def test_all_invalid_rows_raises():
    data = make_normal_readings()
    data["acc_x"] = "garbage"

    try:
        validate_and_clean(data)
        raise AssertionError("Expected ValueError for no valid readings")
    except ValueError as error:
        assert "No valid sensor readings" in str(error)


def test_empty_dataframe_raises():
    data = make_normal_readings().iloc[0:0]

    try:
        validate_and_clean(data)
        raise AssertionError("Expected ValueError for empty input")
    except ValueError:
        pass


# ============================================================
# Feature correctness
# ============================================================

def test_normal_readings_do_not_flag_fall():
    features = compute_feature_vector(make_normal_readings())

    assert features["PossibleFall"] is False
    assert features["PeakAcceleration"] < 15


def test_fall_readings_flag_possible_fall():
    features = compute_feature_vector(make_fall_readings())

    assert features["PossibleFall"] is True
    assert features["PeakAcceleration"] > 15


def test_extra_unrelated_columns_are_ignored():
    # gyro_x is not one of the required columns; it must not break extraction
    data = make_normal_readings()
    features = compute_feature_vector(data)

    assert set(features.keys()) == {
        "PeakAcceleration",
        "MotionVariance",
        "AudioEnergy",
        "GPSVelocity",
        "PossibleFall"
    }


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_missing_required_column_raises,
        test_non_numeric_values_are_dropped,
        test_missing_values_are_dropped,
        test_all_invalid_rows_raises,
        test_empty_dataframe_raises,
        test_normal_readings_do_not_flag_fall,
        test_fall_readings_flag_possible_fall,
        test_extra_unrelated_columns_are_ignored
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
