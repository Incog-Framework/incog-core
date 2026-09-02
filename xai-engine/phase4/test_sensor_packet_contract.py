"""Does xai-engine read the SensorPacket exactly as mobile-client declares it?

The adapter's PACKET_SCHEMA is a Python-side mirror of three Kotlin data
classes. This suite parses the ACTUAL Kotlin source and asserts the mirror is
still faithful - field names, nullability, and collection-ness - so the two
sides cannot drift apart silently.

    handoff/SensorPacket.kt    SensorPacket
    sensors/SensorReading.kt   Vec3Reading, LocationReading

The Kotlin half skips cleanly when mobile-client is not checked out, so this
file is useful in an xai-engine-only clone too.

WHAT THIS DOES *NOT* PROVE
--------------------------
SensorPacket is currently a plain Kotlin data class: no @Serializable, no
Gson/Moshi, no serialization dependency in mobile-client/app/build.gradle.kts,
and nothing writes it to JSON. On-device the object goes straight into
EmergencyClassifier.classify(packet).

So the JSON field NAMES below are inferred from the Kotlin property names -
correct for kotlinx.serialization, Gson and Moshi at their defaults, but
unverified round-trip until a real capture exists. test_real_packets.py closes
that gap the moment Aarush provides one.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sensor_packet_adapter import (          # noqa: E402
    LOCATION_SCHEMA,
    PACKET_SCHEMA,
    VEC3_SCHEMA,
    compute_feature_vector_from_packet,
    session_context_from_packet,
    validate_packet
)

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

MOBILE_JAVA = (
    REPO_ROOT
    / "mobile-client" / "app" / "src" / "main" / "java"
    / "com" / "incog" / "mobileclient"
)

SENSOR_PACKET_KT = MOBILE_JAVA / "handoff" / "SensorPacket.kt"
SENSOR_READING_KT = MOBILE_JAVA / "sensors" / "SensorReading.kt"


# ============================================================
# Minimal Kotlin data-class parser
# ============================================================

def parse_data_class(source, name):
    """Return {property: declared type} for one `data class` in `source`.

    Deliberately small: it only has to handle the flat, comment-annotated
    declarations these three classes use.
    """

    match = re.search(
        rf"data class {name}\s*\((.*?)\n\)",
        source,
        re.DOTALL
    )

    if not match:
        raise AssertionError(f"could not find `data class {name}` in source")

    fields = {}

    for line in match.group(1).splitlines():
        # strip line comments and KDoc fragments
        line = re.sub(r"/\*.*?\*/", "", line)
        line = line.split("//")[0].strip().rstrip(",")

        if not line or line.startswith("*") or line.startswith("/"):
            continue

        property_match = re.match(
            r"val\s+(\w+)\s*:\s*([\w<>?.]+)",
            line
        )

        if property_match:
            fields[property_match.group(1)] = property_match.group(2)

    return fields


def _skip_without_kotlin():
    if not SENSOR_PACKET_KT.exists():
        print(
            "    SKIP - mobile-client not checked out "
            f"({SENSOR_PACKET_KT.name} absent)"
        )
        return True

    return False


# ============================================================
# Contract fidelity against the real Kotlin
# ============================================================

def test_packet_schema_matches_kotlin_sensor_packet():
    if _skip_without_kotlin():
        return

    kotlin = parse_data_class(
        SENSOR_PACKET_KT.read_text(encoding="utf-8"),
        "SensorPacket"
    )

    assert set(kotlin) == set(PACKET_SCHEMA), (
        f"field mismatch.\n"
        f"  Kotlin only : {sorted(set(kotlin) - set(PACKET_SCHEMA))}\n"
        f"  Python only : {sorted(set(PACKET_SCHEMA) - set(kotlin))}"
    )

    for field, kotlin_type in kotlin.items():
        assert PACKET_SCHEMA[field]["kotlin"] == kotlin_type, (
            f"{field}: schema says {PACKET_SCHEMA[field]['kotlin']!r}, "
            f"Kotlin declares {kotlin_type!r}"
        )


def test_nullable_kotlin_fields_are_optional_in_the_adapter():
    """A `?` type can arrive as JSON null, so it must never be required."""

    if _skip_without_kotlin():
        return

    kotlin = parse_data_class(
        SENSOR_PACKET_KT.read_text(encoding="utf-8"),
        "SensorPacket"
    )

    for field, kotlin_type in kotlin.items():
        if kotlin_type.endswith("?"):
            assert not PACKET_SCHEMA[field]["required"], (
                f"{field} is nullable in Kotlin ({kotlin_type}) but the "
                f"adapter marks it required - a packet with no GPS fix or no "
                f"gyro would be rejected"
            )


def test_required_fields_are_non_nullable_in_kotlin():
    """Anything the adapter demands must be guaranteed present on-device."""

    if _skip_without_kotlin():
        return

    kotlin = parse_data_class(
        SENSOR_PACKET_KT.read_text(encoding="utf-8"),
        "SensorPacket"
    )

    for field, spec in PACKET_SCHEMA.items():
        if spec["required"]:
            assert not kotlin[field].endswith("?"), (
                f"adapter requires {field}, but Kotlin declares it nullable "
                f"({kotlin[field]}) - it can legitimately be absent"
            )


def test_reading_schemas_match_kotlin():
    if _skip_without_kotlin():
        return

    source = SENSOR_READING_KT.read_text(encoding="utf-8")

    assert parse_data_class(source, "Vec3Reading") == VEC3_SCHEMA
    assert parse_data_class(source, "LocationReading") == LOCATION_SCHEMA


def test_gps_velocity_reads_the_field_kotlin_actually_declares():
    """Guards the exact name `speedMps` on LocationReading."""

    if _skip_without_kotlin():
        return

    location = parse_data_class(
        SENSOR_READING_KT.read_text(encoding="utf-8"),
        "LocationReading"
    )

    assert "speedMps" in location, (
        "LocationReading no longer declares speedMps - GPSVelocity extraction "
        "in sensor_packet_adapter must be updated to the new field name"
    )


# ============================================================
# Validation behaviour on realistic packet shapes
# ============================================================

def _minimal_packet(**overrides):
    packet = {
        "sessionId": "SESS-CONTRACT",
        "timestampMs": 1_700_000_000_000,
        "latestAccel": {"timestampMs": 0, "x": 1.0, "y": 0.0, "z": 0.0},
        "latestGyro": None,
        "latestLocation": None,
        "accelSamples": [{"timestampMs": 0, "x": 1.0, "y": 0.0, "z": 0.0}],
        "gyroSamples": [],
        "audioRmsEnergy": 100.0,
        "audioBufferedMs": 2000
    }
    packet.update(overrides)
    return packet


def test_full_kotlin_shaped_packet_is_accepted():
    """Every declared field present, nothing rejected as unexpected."""

    features = compute_feature_vector_from_packet(_minimal_packet())

    assert set(features) == {
        "PeakAcceleration",
        "MotionVariance",
        "AudioEnergy",
        "GPSVelocity",
        "PossibleFall"
    }


def test_all_nullable_fields_null_is_accepted():
    """The realistic early-session packet: no GPS fix, no gyro yet."""

    packet = _minimal_packet(
        latestAccel=None,
        latestGyro=None,
        latestLocation=None,
        gyroSamples=[]
    )

    features = compute_feature_vector_from_packet(packet)

    assert features["GPSVelocity"] == 0.0


def test_unknown_extra_fields_do_not_break_extraction():
    """A future Kotlin field must not break this adapter."""

    packet = _minimal_packet(batteryLevel=0.82, deviceModel="CPH2487")

    assert compute_feature_vector_from_packet(packet)["PossibleFall"] is False


def test_gyro_is_accepted_but_unused():
    """The model's five features never included gyroscope data."""

    without = compute_feature_vector_from_packet(_minimal_packet())

    with_gyro = compute_feature_vector_from_packet(
        _minimal_packet(
            latestGyro={"timestampMs": 0, "x": 9.0, "y": 9.0, "z": 9.0},
            gyroSamples=[{"timestampMs": 0, "x": 9.0, "y": 9.0, "z": 9.0}]
        )
    )

    assert without == with_gyro


# ============================================================
# Actionable errors on malformed captures
# ============================================================

def _expect_error(packet, fragment):
    try:
        validate_packet(packet)
    except ValueError as error:
        assert fragment in str(error), (
            f"error message {str(error)!r} does not mention {fragment!r}"
        )
        return

    raise AssertionError(f"expected ValueError mentioning {fragment!r}")


def test_error_messages_name_the_offending_field():
    _expect_error(
        _minimal_packet(sessionId=""),
        "sessionId"
    )
    _expect_error(
        _minimal_packet(timestampMs="not-a-number"),
        "timestampMs"
    )
    _expect_error(
        _minimal_packet(audioRmsEnergy=None),
        "audioRmsEnergy"
    )
    _expect_error(
        _minimal_packet(accelSamples=[]),
        "accelSamples"
    )
    _expect_error(
        _minimal_packet(latestLocation={"speedMps": "fast"}),
        "speedMps"
    )


def test_non_numeric_accel_axis_is_reported_with_its_index():
    _expect_error(
        _minimal_packet(
            accelSamples=[
                {"timestampMs": 0, "x": 1.0, "y": 0.0, "z": 0.0},
                {"timestampMs": 0, "x": "bad", "y": 0.0, "z": 0.0}
            ]
        ),
        "accelSamples[1].x"
    )


def test_boolean_is_not_accepted_where_a_number_belongs():
    """JSON true must not silently become 1.0 in a feature."""

    _expect_error(_minimal_packet(audioRmsEnergy=True), "audioRmsEnergy")


def test_packet_that_is_not_an_object_is_rejected():
    _expect_error([1, 2, 3], "must be a JSON object")


# ============================================================
# Session context
# ============================================================

def test_session_context_comes_from_the_adapter():
    context = session_context_from_packet(_minimal_packet())

    assert context == {
        "SessionID": "SESS-CONTRACT",
        "TimestampMs": 1_700_000_000_000
    }


def test_session_context_validates_before_returning():
    try:
        session_context_from_packet(_minimal_packet(accelSamples=[]))
    except ValueError:
        return

    raise AssertionError("expected a malformed packet to be rejected")


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_packet_schema_matches_kotlin_sensor_packet,
        test_nullable_kotlin_fields_are_optional_in_the_adapter,
        test_required_fields_are_non_nullable_in_kotlin,
        test_reading_schemas_match_kotlin,
        test_gps_velocity_reads_the_field_kotlin_actually_declares,
        test_full_kotlin_shaped_packet_is_accepted,
        test_all_nullable_fields_null_is_accepted,
        test_unknown_extra_fields_do_not_break_extraction,
        test_gyro_is_accepted_but_unused,
        test_error_messages_name_the_offending_field,
        test_non_numeric_accel_axis_is_reported_with_its_index,
        test_boolean_is_not_accepted_where_a_number_belongs,
        test_packet_that_is_not_an_object_is_rejected,
        test_session_context_comes_from_the_adapter,
        test_session_context_validates_before_returning
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
