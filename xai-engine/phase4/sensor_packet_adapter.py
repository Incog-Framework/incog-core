"""
Adapter: Aarush's real SensorPacket (Phase 3 -> Phase 4 contract) -> my feature vector.

Source of truth for the packet shape (do not edit that side; this file only reads it):
    mobile-client/app/src/main/java/com/incog/mobileclient/handoff/SensorPacket.kt
    mobile-client/app/src/main/java/com/incog/mobileclient/ghost/GhostStateService.kt (producer)
    mobile-client/app/src/main/java/com/incog/mobileclient/sensors/SensorCollector.kt
    mobile-client/app/src/main/java/com/incog/mobileclient/sensors/AudioBufferCollector.kt
    xai-engine/CLAUDE.md (handoff spec)

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
# Validation
# ============================================================

def validate_packet(packet: dict) -> None:
    """Raise ValueError if the packet is missing fields this adapter needs."""

    if not isinstance(packet, dict):
        raise ValueError("SensorPacket must be a JSON object.")

    required_top_level = ["sessionId", "timestampMs", "accelSamples", "audioRmsEnergy"]

    missing = [field for field in required_top_level if field not in packet]

    if missing:
        raise ValueError(f"SensorPacket missing required fields: {missing}")

    accel_samples = packet["accelSamples"]

    if not isinstance(accel_samples, list) or len(accel_samples) == 0:
        raise ValueError(
            "SensorPacket.accelSamples is empty - no accelerometer history to "
            "compute PeakAcceleration/MotionVariance from yet."
        )

    for sample in accel_samples:
        for axis in ("x", "y", "z"):
            if axis not in sample:
                raise ValueError(f"accelSamples entry missing '{axis}': {sample}")


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
    audio_energy = min(audio_rms_energy / AUDIO_RMS_FULL_SCALE, 1.0)

    latest_location = packet.get("latestLocation")
    gps_velocity = float(latest_location["speedMps"]) if latest_location else 0.0

    return {
        "PeakAcceleration": round(peak_acceleration, 4),
        "MotionVariance": round(motion_variance, 4),
        "AudioEnergy": round(audio_energy, 4),
        "GPSVelocity": round(gps_velocity, 4),
        "PossibleFall": bool(possible_fall(peak_acceleration))
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

    validate_packet(packet)

    return {
        "SessionID": packet["sessionId"],
        "TimestampMs": int(packet["timestampMs"]),
        "Features": compute_feature_vector_from_packet(packet)
    }
