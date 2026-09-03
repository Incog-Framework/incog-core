"""Validate real SensorPacket captures from the device.

Nothing here fabricates data. With no captures present the suite reports what
is missing and passes, so it can sit in the standard test run today and start
doing real work the moment Aarush delivers files.

WHERE IT LOOKS
    $INCOG_REAL_PACKETS        if set
    data/real_packets/         otherwise

    data/real_packets/
      normal/*.json            everyday activity
      emergency/*.json         staged incidents
      *.json                   unsorted captures are checked too

Each file is one SensorPacket object or an array of them.

WHAT IT CHECKS
    1. every capture parses and satisfies the adapter's schema
    2. features come out inside their contractual ranges
    3. the capture actually looks like device data - sample rate, window
       length, timestamp monotonicity, audio scale - measured against the
       on-device geometry rather than assumed

Point 3 is the useful part on delivery day: a capture can be perfectly valid
JSON and still be wrong (mic permission denied so audioRmsEnergy is flat
zero, or a debug build sampling at the wrong rate). Those are reported as
DIAGNOSTICS, not failures, because only Lipika can judge whether an odd
number is a bug or a genuine recording.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sensor_packet_adapter import (          # noqa: E402
    AUDIO_RMS_FULL_SCALE,
    compute_feature_vector_from_packet,
    load_packets,
    session_context_from_packet,
    validate_packet
)

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_REAL_PACKET_DIR = BASE_DIR / "data" / "real_packets"
REAL_PACKET_ENV_VAR = "INCOG_REAL_PACKETS"

# On-device geometry, read off the Kotlin (see CLAUDE.md).
EXPECTED_SAMPLE_RATE_HZ = 50.0
MAX_ACCEL_SAMPLES = 1000              # SensorCollector.MAX_SAMPLES
SAMPLE_RATE_TOLERANCE = 0.5           # accept 25-75 Hz before complaining

# Earth gravity is ~9.81 m/s^2; a resting phone reads about that. A window
# whose peak is far below that suggests the values are in g, not m/s^2.
MIN_PLAUSIBLE_RESTING_PEAK = 5.0


def real_packet_dir() -> Path:
    override = os.environ.get(REAL_PACKET_ENV_VAR)

    return Path(override) if override else DEFAULT_REAL_PACKET_DIR


def capture_files():
    """Every .json capture under the configured directory, sorted."""

    root = real_packet_dir()

    if not root.is_dir():
        return []

    return sorted(
        path
        for path in root.rglob("*.json")
        if path.name != "README.md"
    )


def label_for(path):
    """Folder name supplies the label when captures are sorted."""

    for parent in path.parents:
        if parent.name in ("normal", "emergency"):
            return parent.name

    return "unlabelled"


def _no_captures():
    files = capture_files()

    if files:
        return False

    print(
        f"    SKIP - no real captures in {real_packet_dir()}\n"
        f"           set ${REAL_PACKET_ENV_VAR} or drop .json captures into\n"
        f"           data/real_packets/{{normal,emergency}}/ - see INTEGRATION.md"
    )
    return True


# ============================================================
# 1. Schema
# ============================================================

def test_every_capture_satisfies_the_packet_schema():
    if _no_captures():
        return

    checked = 0

    for path in capture_files():
        for index, packet in enumerate(load_packets(path)):
            try:
                validate_packet(packet)
            except ValueError as error:
                raise AssertionError(
                    f"{path.name} packet[{index}]: {error}"
                ) from error

            checked += 1

    print(f"    {checked} packets validated against the schema")


def test_every_capture_carries_session_context():
    if _no_captures():
        return

    sessions = set()

    for path in capture_files():
        for index, packet in enumerate(load_packets(path)):
            context = session_context_from_packet(packet)

            assert context["SessionID"], f"{path.name}[{index}]: empty SessionID"
            assert context["TimestampMs"] > 0, (
                f"{path.name}[{index}]: TimestampMs must be a real epoch value"
            )

            sessions.add(context["SessionID"])

    print(f"    {len(sessions)} distinct session(s): {sorted(sessions)}")


# ============================================================
# 2. Features
# ============================================================

def test_features_are_within_contractual_ranges():
    if _no_captures():
        return

    for path in capture_files():
        for index, packet in enumerate(load_packets(path)):
            features = compute_feature_vector_from_packet(packet)
            where = f"{path.name}[{index}]"

            assert features["PeakAcceleration"] >= 0, where
            assert features["MotionVariance"] >= 0, where
            assert 0.0 <= features["AudioEnergy"] <= 1.0, (
                f"{where}: AudioEnergy {features['AudioEnergy']} outside [0,1]"
            )
            assert features["GPSVelocity"] >= 0, where
            assert isinstance(features["PossibleFall"], bool), where

            # PossibleFall must agree with the peak it was derived from
            assert features["PossibleFall"] == (
                features["PeakAcceleration"] > 15
            ) or abs(features["PeakAcceleration"] - 15) < 1e-4, (
                f"{where}: PossibleFall disagrees with PeakAcceleration"
            )


def test_feature_extraction_is_deterministic():
    """Same capture twice must give byte-identical features."""

    if _no_captures():
        return

    for path in capture_files():
        for packet in load_packets(path):
            assert (
                compute_feature_vector_from_packet(packet)
                == compute_feature_vector_from_packet(packet)
            ), f"{path.name}: feature extraction is not deterministic"


# ============================================================
# 3. Diagnostics - does this look like real device data?
# ============================================================

def _sample_rate(packet):
    samples = packet["accelSamples"]

    stamps = [
        sample.get("timestampMs")
        for sample in samples
        if isinstance(sample.get("timestampMs"), (int, float))
    ]

    if len(stamps) < 2:
        return None

    span_ms = stamps[-1] - stamps[0]

    if span_ms <= 0:
        return None

    return (len(stamps) - 1) * 1000.0 / span_ms


def test_captures_look_like_device_data():
    """Reports oddities without failing - judgement calls stay with Lipika."""

    if _no_captures():
        return

    notes = []
    audio_values = []
    peak_values = []

    for path in capture_files():
        for index, packet in enumerate(load_packets(path)):
            where = f"{path.name}[{index}]"

            samples = packet["accelSamples"]

            if len(samples) > MAX_ACCEL_SAMPLES:
                notes.append(
                    f"{where}: {len(samples)} accel samples exceeds the "
                    f"on-device bound of {MAX_ACCEL_SAMPLES}"
                )

            rate = _sample_rate(packet)

            if rate is not None:
                low = EXPECTED_SAMPLE_RATE_HZ * (1 - SAMPLE_RATE_TOLERANCE)
                high = EXPECTED_SAMPLE_RATE_HZ * (1 + SAMPLE_RATE_TOLERANCE)

                if not low <= rate <= high:
                    notes.append(
                        f"{where}: ~{rate:.1f} Hz, expected around "
                        f"{EXPECTED_SAMPLE_RATE_HZ:.0f} Hz - MotionVariance "
                        f"will not be on the trained scale"
                    )

            stamps = [
                sample.get("timestampMs")
                for sample in samples
                if isinstance(sample.get("timestampMs"), (int, float))
            ]

            if stamps and stamps != sorted(stamps):
                notes.append(f"{where}: accelSamples timestamps are not monotonic")

            features = compute_feature_vector_from_packet(packet)

            audio_values.append(features["AudioEnergy"])
            peak_values.append(features["PeakAcceleration"])

            if features["PeakAcceleration"] < MIN_PLAUSIBLE_RESTING_PEAK:
                notes.append(
                    f"{where}: peak {features['PeakAcceleration']} m/s^2 is "
                    f"below resting gravity - are these values in g rather "
                    f"than m/s^2?"
                )

    if audio_values and all(value == 0.0 for value in audio_values):
        notes.append(
            f"AudioEnergy is 0.0 in ALL {len(audio_values)} packets - the mic "
            f"permission was probably denied, or audioRmsEnergy was never "
            f"populated. The model would be running on four live features."
        )

    print(f"    packets analysed: {len(peak_values)}")

    if peak_values:
        print(
            f"    PeakAcceleration  min={min(peak_values):.3f} "
            f"max={max(peak_values):.3f}"
        )
        print(
            f"    AudioEnergy       min={min(audio_values):.4f} "
            f"max={max(audio_values):.4f} "
            f"(raw RMS scale 0..{AUDIO_RMS_FULL_SCALE:.0f})"
        )

    if notes:
        print(f"    DIAGNOSTICS ({len(notes)}) - review before training:")
        for note in notes:
            print(f"      - {note}")
    else:
        print("    no diagnostics - captures look consistent with the contract")


def test_report_label_balance():
    """Negatives drive the false-positive target, so count them."""

    if _no_captures():
        return

    counts = {}

    for path in capture_files():
        label = label_for(path)
        counts[label] = counts.get(label, 0) + len(load_packets(path))

    print(f"    label counts: {counts}")

    if counts.get("unlabelled"):
        print(
            "      note: unlabelled captures cannot be used for training - "
            "sort them into normal/ or emergency/"
        )


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    print(f"Real-capture directory: {real_packet_dir()}")

    tests = [
        test_every_capture_satisfies_the_packet_schema,
        test_every_capture_carries_session_context,
        test_features_are_within_contractual_ranges,
        test_feature_extraction_is_deterministic,
        test_captures_look_like_device_data,
        test_report_label_balance
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
