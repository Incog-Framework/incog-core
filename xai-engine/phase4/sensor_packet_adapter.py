"""
Adapter: Aarush's real SensorPacket (Phase 3 -> Phase 4 contract) -> my feature vector.

Source of truth for the packet shape (do not edit that side; this file only reads it):
    mobile-client/app/src/main/java/com/incog/mobileclient/handoff/SensorPacket.kt
    mobile-client/app/src/main/java/com/incog/mobileclient/ghost/GhostStateService.kt (producer)
    mobile-client/app/src/main/java/com/incog/mobileclient/sensors/SensorCollector.kt
    mobile-client/app/src/main/java/com/incog/mobileclient/sensors/AudioBufferCollector.kt
    mobile-client/CLAUDE.md ("Handoff to Lipika (Phase 3 -> Phase 4)")
    xai-engine/CLAUDE.md (this module's side of the contract)

Expected packet shape (JSON-serialized Kotlin SensorPacket):

    {
        "sessionId": "SESS-XXXXXXXX",
        "timestampMs": 1699999999999,
        "latestAccel": {"timestampMs": ..., "x": f, "y": f, "z": f} | null,
        "latestGyro": {"timestampMs": ..., "x": f, "y": f, "z": f} | null,
        "latestLocation": {"timestampMs": ..., "latitude": f, "longitude": f,
                            "speedMps": f, "accuracyM": f} | null,
        "accelSamples": [{"timestampMs": ..., "x": f, "y": f, "z": f}, ...],  # <=1000, ~50 Hz
        "gyroSamples": [...],   # same shape; not used by these 5 features (see note below)
        "audioRmsEnergy": f,    # RMS of raw 16-bit PCM samples in the last mic read (0..32767 scale)
        "audioBufferedMs": int
    }

Feature <-> packet field mapping:

    PeakAcceleration  <- max(||accel||) over accelSamples                 (m/s^2, includes gravity)
    MotionVariance    <- sample variance (ddof=1) of ||accel|| over accelSamples
    AudioEnergy       <- audioRmsEnergy rescaled from raw PCM16 amplitude to the [0, 1] range the
                          model was trained on (see AUDIO_RMS_FULL_SCALE note below)
    GPSVelocity       <- latestLocation.speedMps, or 0.0 if no GPS fix yet (packet only carries the
                          latest fix, not a windowed series, so there is nothing to average)
    PossibleFall      <- PeakAcceleration > FALL_ACCELERATION_THRESHOLD   (same rule, unchanged)

    gyroSamples/latestGyro are accepted but intentionally unused: the trained model's 5 features
    never included gyroscope data, and this integration does not change the model.

Concrete incompatibility found (see xai-engine/CLAUDE.md "Open coordination items"):
    audioRmsEnergy is the RMS of raw PCM16 samples (0..32767 full-scale), not a pre-normalized
    [0, 1] energy value. The training data's AudioEnergy column is in [0, 1]. This adapter rescales
    by the PCM16 full-scale amplitude (32768) as the best available mapping; it has not been
    validated against real recorded audio and should be checked on-device (compare AudioEnergy
    values for quiet ambient vs. a loud/distress sound) before being trusted for the confidence
    threshold. This is an adapter-side unit conversion, not a model retrain.
"""

import numpy as np

from feature_extraction import (
    acceleration_magnitude,
    peak_and_variance,
    possible_fall
)


# ============================================================
# Constants
# ============================================================

# 16-bit PCM full-scale amplitude, used to rescale audioRmsEnergy (raw PCM
# RMS, 0..32767) into the [0, 1] range the model's AudioEnergy feature was
# trained on. See the module docstring "Concrete incompatibility" note.
AUDIO_RMS_FULL_SCALE = 32768.0


# ============================================================
# The packet schema
#
# Mirrors the Kotlin declarations field-for-field:
#   handoff/SensorPacket.kt      SensorPacket
#   sensors/SensorReading.kt     Vec3Reading, LocationReading
#
# "required" means THIS ADAPTER cannot produce a feature vector without it.
# The other fields are part of the contract and are type-checked when
# present, but a slimmer bridge that omits them still works.
#
# phase4/test_sensor_packet_contract.py parses the actual Kotlin source and
# asserts these names and nullabilities still match, so the schema cannot
# silently drift from Aarush's data classes.
# ============================================================

PACKET_SCHEMA = {
    "sessionId":       {"kotlin": "String",           "required": True},
    "timestampMs":     {"kotlin": "Long",             "required": True},
    "latestAccel":     {"kotlin": "Vec3Reading?",     "required": False},
    "latestGyro":      {"kotlin": "Vec3Reading?",     "required": False},
    "latestLocation":  {"kotlin": "LocationReading?", "required": False},
    "accelSamples":    {"kotlin": "List<Vec3Reading>", "required": True},
    "gyroSamples":     {"kotlin": "List<Vec3Reading>", "required": False},
    "audioRmsEnergy":  {"kotlin": "Double",           "required": True},
    "audioBufferedMs": {"kotlin": "Long",             "required": False}
}

VEC3_SCHEMA = {
    "timestampMs": "Long",
    "x": "Float",
    "y": "Float",
    "z": "Float"
}

LOCATION_SCHEMA = {
    "timestampMs": "Long",
    "latitude": "Double",
    "longitude": "Double",
    "speedMps": "Float",
    "accuracyM": "Float"
}

# Fields the feature computation actually reads out of a sample.
REQUIRED_SAMPLE_AXES = ("x", "y", "z")


# ============================================================
# Validation
# ============================================================

def _is_number(value) -> bool:
    # bool is a subclass of int in Python; a JSON true where a number belongs
    # is a contract violation, not a 1.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_packet(packet: dict) -> None:
    """Raise ValueError if the packet cannot produce a feature vector.

    Error messages name the offending field and say what was expected, so a
    malformed real capture is diagnosable without opening this file.
    """

    if not isinstance(packet, dict):
        raise ValueError(
            f"SensorPacket must be a JSON object, got {type(packet).__name__}."
        )

    missing = [
        field
        for field, spec in PACKET_SCHEMA.items()
        if spec["required"] and field not in packet
    ]

    if missing:
        raise ValueError(
            f"SensorPacket missing required fields: {missing}. "
            f"Expected the JSON form of Kotlin SensorPacket "
            f"(fields: {sorted(PACKET_SCHEMA)})."
        )

    if not isinstance(packet["sessionId"], str) or not packet["sessionId"]:
        raise ValueError(
            f"SensorPacket.sessionId must be a non-empty string, got "
            f"{packet['sessionId']!r}."
        )

    if not _is_number(packet["timestampMs"]):
        raise ValueError(
            f"SensorPacket.timestampMs must be a number (Kotlin Long), got "
            f"{packet['timestampMs']!r}."
        )

    if not _is_number(packet["audioRmsEnergy"]):
        raise ValueError(
            f"SensorPacket.audioRmsEnergy must be a number (Kotlin Double, "
            f"RMS of PCM16 on a 0..32768 scale), got "
            f"{packet['audioRmsEnergy']!r}."
        )

    accel_samples = packet["accelSamples"]

    if not isinstance(accel_samples, list) or len(accel_samples) == 0:
        raise ValueError(
            "SensorPacket.accelSamples is empty - no accelerometer history to "
            "compute PeakAcceleration/MotionVariance from yet. On-device this "
            "happens only in the first moments of a session."
        )

    for index, sample in enumerate(accel_samples):
        if not isinstance(sample, dict):
            raise ValueError(
                f"accelSamples[{index}] must be an object with x/y/z, got "
                f"{type(sample).__name__}."
            )

        for axis in REQUIRED_SAMPLE_AXES:
            if axis not in sample:
                raise ValueError(
                    f"accelSamples[{index}] missing '{axis}': {sample}"
                )

            if not _is_number(sample[axis]):
                raise ValueError(
                    f"accelSamples[{index}].{axis} must be a number "
                    f"(Kotlin Float, m/s^2), got {sample[axis]!r}."
                )

    location = packet.get("latestLocation")

    if location is not None and not isinstance(location, dict):
        raise ValueError(
            f"SensorPacket.latestLocation must be an object or null, got "
            f"{type(location).__name__}."
        )

    if isinstance(location, dict):
        speed = location.get("speedMps")

        if speed is not None and not _is_number(speed):
            raise ValueError(
                f"latestLocation.speedMps must be a number (Kotlin Float, "
                f"m/s) or absent, got {speed!r}."
            )


# ============================================================
# Feature computation
# ============================================================

def compute_feature_vector_from_packet(packet: dict) -> dict:
    """Convert a real SensorPacket (as JSON/dict) into the 5-feature vector.

    Raises ValueError on a malformed/incomplete packet (see validate_packet).
    """

    validate_packet(packet)

    accel_samples = packet["accelSamples"]

    acc_x = [sample["x"] for sample in accel_samples]
    acc_y = [sample["y"] for sample in accel_samples]
    acc_z = [sample["z"] for sample in accel_samples]

    magnitudes = acceleration_magnitude(acc_x, acc_y, acc_z)
    peak_acceleration, motion_variance = peak_and_variance(magnitudes)

    audio_rms_energy = float(packet["audioRmsEnergy"])

    # Clamped at BOTH ends. RMS is non-negative by construction on the device
    # (AudioBufferCollector.computeRms), so the lower clamp never fires for a
    # well-formed packet - it is here so a malformed/negative value from a JSON
    # bridge cannot feed an out-of-contract feature into the model.
    audio_energy = min(max(audio_rms_energy / AUDIO_RMS_FULL_SCALE, 0.0), 1.0)

    # latestLocation is null until the first GPS fix. Kotlin's LocationReading
    # always carries a non-null speedMps, but a JSON bridge can drop the field;
    # treat that the same as "no fix yet" rather than raising KeyError.
    latest_location = packet.get("latestLocation")

    if latest_location and latest_location.get("speedMps") is not None:
        gps_velocity = float(latest_location["speedMps"])
    else:
        gps_velocity = 0.0

    return {
        "PeakAcceleration": round(peak_acceleration, 4),
        "MotionVariance": round(motion_variance, 4),
        "AudioEnergy": round(audio_energy, 4),
        "GPSVelocity": round(gps_velocity, 4),
        "PossibleFall": bool(possible_fall(peak_acceleration))
    }


def session_context_from_packet(packet: dict) -> dict:
    """Session identity for downstream phases.

    Exposed so no other module has to reach into raw packet fields - this
    adapter stays the single place that knows the Kotlin field names.
    """

    validate_packet(packet)

    return {
        "SessionID": packet["sessionId"],
        "TimestampMs": int(packet["timestampMs"])
    }


def extract_from_sensor_packet(packet: dict) -> dict:
    """Full adapter output: session context + the feature vector.

    Returns:
        {
            "SessionID": str,
            "TimestampMs": int,
            "Features": {PeakAcceleration, MotionVariance, AudioEnergy,
                         GPSVelocity, PossibleFall}
        }
    """

    context = session_context_from_packet(packet)

    return {
        "SessionID": context["SessionID"],
        "TimestampMs": context["TimestampMs"],
        "Features": compute_feature_vector_from_packet(packet)
    }


# ============================================================
# Loading real captures
#
# One capture file is either a single SensorPacket object or an array of
# them (GhostStateService builds one every 2 s, so a session export is
# naturally a list). Both are accepted.
# ============================================================

def load_packets(path) -> list:
    """Read a capture file and return its packets as a list of dicts.

    Raises ValueError with the file name on malformed JSON, so a bad capture
    in a batch is identifiable.
    """

    import json
    from pathlib import Path

    path = Path(path)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is not valid JSON: {error}") from error

    packets = payload if isinstance(payload, list) else [payload]

    if not packets:
        raise ValueError(f"{path.name} contains no SensorPackets.")

    return packets


def load_packet(path) -> dict:
    """Read a capture file expected to hold exactly one packet.

    A multi-packet file returns its FIRST packet, because the single-shot
    pipeline scores one packet at a time - same as the phone, which scores
    each 2 s snapshot on its own.
    """

    return load_packets(path)[0]
