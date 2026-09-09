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
    AudioEnergy       <- audioRmsEnergy rescaled to [0, 1] on a dB (not linear) scale - see
                          AUDIO_FLOOR_DB / AUDIO_CEIL_DB below
    GPSVelocity       <- latestLocation.speedMps, or 0.0 if no GPS fix yet (packet only carries the
                          latest fix, not a windowed series, so there is nothing to average)
    PossibleFall      <- PeakAcceleration > FALL_ACCELERATION_THRESHOLD   (same rule, unchanged)

    gyroSamples/latestGyro are accepted but intentionally unused: the trained model's 5 features
    never included gyroscope data, and this integration does not change the model.

AudioEnergy scale (revised 2026-09-06 - dB, not linear):
    The original `audioRmsEnergy / 32768` linear mapping was validated against real RAVDESS
    distress speech and found dead on arrival: even a studio-recorded, close-mic scream read
    median 0.0013 / p95 0.085 - nowhere near usable. Linear RMS ratios of quiet-to-loud speech
    only span about 1.5 orders of magnitude, while human hearing (and "how loud is this,
    relatively") is logarithmic - so a dB scale was chosen instead, per Aarush's request, and
    the FLOOR_DB/CEIL_DB below were fitted against the real RAVDESS distribution, not guessed:

        AudioEnergy = clamp((20*log10(max(audioRmsEnergy, 1) / 32768) - AUDIO_FLOOR_DB)
                             / (AUDIO_CEIL_DB - AUDIO_FLOOR_DB), 0, 1)

    See AUDIO_FLOOR_DB / AUDIO_CEIL_DB below for exactly how those two numbers were derived and
    what they mean, and data/audio_validation_report.json for the full RAVDESS calibration.
    This is a **lockstep** change: Kotlin's FeatureExtractor must apply the identical formula
    and constants in the same change, or the phone and the trained model disagree about what a
    given microphone reading means (train/serve skew). Never edit one side alone.

    Still open, not fixed by this rescale: whether a real pocketed phone's microphone captures
    anything at all (Aarush is separately verifying this - some on-device sessions read a flat
    0.0). A rescale of a signal that isn't arriving changes nothing.
"""

import math

import numpy as np

from feature_extraction import (
    acceleration_magnitude,
    peak_and_variance,
    possible_fall
)


# ============================================================
# Constants
# ============================================================

# 16-bit PCM full-scale amplitude - the reference audioRmsEnergy is expressed
# relative to, in the log-ratio below. Not itself the on/off switch for the
# feature's usable range any more; AUDIO_FLOOR_DB/AUDIO_CEIL_DB are.
AUDIO_RMS_FULL_SCALE = 32768.0

# dB(x) = 20*log10(max(x, 1) / AUDIO_RMS_FULL_SCALE) - always <= 0 dB, floored
# at 20*log10(1/32768) = -90.3 dB (one PCM16 count) so a genuinely-zero
# reading never hits -inf.
#
# AUDIO_FLOOR_DB / AUDIO_CEIL_DB were fitted 2026-09-06 against
# data/raw/ravdess (82,532 real 1024-frame chunks, angry/fearful/disgust =
# "distress" vs every other emotion), not guessed:
#
#     dB(rms), by percentile          distress   non-distress
#     p90                              -26.8         -34.4
#     p95  ("a loud vocalisation")     -21.4         -29.8
#     p99                              -14.2         -22.9
#
# Distress reads a consistent ~7-9 dB louder than non-distress at every
# percentile from p90 up - a real, honest signal, but a modest one; RAVDESS
# is studio speech, not room ambience, so there is no true "silence" class to
# anchor against, only "calm speech" vs "distressed speech". FLOOR_DB/CEIL_DB
# are chosen so the p95 ("scream") of distress lands at ~0.88 and the p95
# ("loudest ordinary talking") of non-distress lands at ~0.18, per Aarush's
# request. That forces a NARROW 12 dB window (dictated by the ~8 dB real gap
# between the two p95s, not chosen freely) - which means this scale is
# proportionally more sensitive to microphone gain/distance drift than a
# wider window would be. That tradeoff is real: ask before widening it to
# "fix" gain sensitivity, because it will also compress distress/non-distress
# apart-ness back down. Below AUDIO_FLOOR_DB reads 0.0 (the large majority of
# both classes - most 64 ms chunks of speech are pauses, not vocalisation);
# above AUDIO_CEIL_DB reads 1.0.
AUDIO_FLOOR_DB = -32.0
AUDIO_CEIL_DB = -20.0


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

    # dB scale (see AUDIO_FLOOR_DB / AUDIO_CEIL_DB above). max(x, 1) floors
    # the ratio at one PCM16 count before the log, so true digital silence
    # (rms=0, or a malformed negative value from a JSON bridge) maps to the
    # scale's -90.3 dB floor instead of -inf, and clamped at both ends after.
    audio_db = 20.0 * math.log10(max(audio_rms_energy, 1.0) / AUDIO_RMS_FULL_SCALE)
    audio_energy = min(
        max((audio_db - AUDIO_FLOOR_DB) / (AUDIO_CEIL_DB - AUDIO_FLOOR_DB), 0.0),
        1.0
    )

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
