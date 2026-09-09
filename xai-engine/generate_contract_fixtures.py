"""Emit the machine-readable AI contract + golden feature vectors.

These two artifacts exist so the Python (training/XAI) side and the Kotlin
(on-device inference) side can be pinned to the SAME numbers by tests instead
of by comments that drift:

    data/model_contract.json         constants + model IO shape + model hash
    data/golden_feature_vectors.json SensorPacket -> expected feature vector

Kotlin consumes the golden vectors from
mobile-client/app/src/test/.../ai/FeatureExtractorTest.kt; Python consumes them
from phase4/test_kotlin_parity.py. If the two ever disagree, one of the two
ports has drifted and the test fails on both sides.

Run:  python generate_contract_fixtures.py
"""

import hashlib
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(BASE_DIR / "phase4"))

from feature_extraction import (            # noqa: E402
    FALL_ACCELERATION_THRESHOLD,
    FEATURE_ORDER
)
from sensor_packet_adapter import (         # noqa: E402
    AUDIO_CEIL_DB,
    AUDIO_FLOOR_DB,
    AUDIO_RMS_FULL_SCALE,
    compute_feature_vector_from_packet
)

DATA_DIR = BASE_DIR / "data"
MODEL_PATH = DATA_DIR / "emergency_model.tflite"
CONTRACT_PATH = DATA_DIR / "model_contract.json"
GOLDEN_PATH = DATA_DIR / "golden_feature_vectors.json"

# Thresholds are defined once here and asserted against every place they are
# duplicated (phase5/tflite_predict.py, phase6/decision_engine.py,
# data/model_metadata.json, and the Kotlin constants) by test_contract_sync.py.
CLASSIFICATION_THRESHOLD = 0.50
DECISION_THRESHOLD = 0.80


def _sample(x, y, z, t=0):
    return {"timestampMs": t, "x": x, "y": y, "z": z}


def _packet(name, samples, audio_rms, speed_mps, session="SESS-GOLDEN"):
    return {
        "name": name,
        "packet": {
            "sessionId": session,
            "timestampMs": 1_700_000_000_000,
            "latestAccel": samples[-1],
            "latestGyro": None,
            "latestLocation": (
                None
                if speed_mps is None
                else {
                    "timestampMs": 1_700_000_000_000,
                    "latitude": 12.9716,
                    "longitude": 77.5946,
                    "speedMps": speed_mps,
                    "accuracyM": 5.0
                }
            ),
            "accelSamples": samples,
            "gyroSamples": [],
            "audioRmsEnergy": audio_rms,
            "audioBufferedMs": 2000
        }
    }


# ------------------------------------------------------------------
# Golden cases. Chosen to pin the exact behaviours that are easy to get
# wrong when porting: ddof=1 vs population variance, the <2-sample rule,
# the audio clamp, the missing-GPS fallback, and PossibleFall being
# evaluated on the UNROUNDED peak.
# ------------------------------------------------------------------

CASES = [
    _packet(
        "single_sample_zero_variance",
        [_sample(3.0, 4.0, 0.0)],          # magnitude exactly 5.0
        0.0,
        None
    ),
    _packet(
        "two_samples_ddof1_variance",
        [_sample(3.0, 0.0, 0.0), _sample(5.0, 0.0, 0.0)],
        # mags [3,5] -> ddof=1 variance 2.0 (population variance would be 1.0)
        16384.0,                            # -6.02 dB, above AUDIO_CEIL_DB -> clamps to 1.0
        2.5
    ),
    _packet(
        "resting_device_no_fall",
        [_sample(0.8, 9.6, 1.2, t) for t in range(20)],
        500.0,
        1.0
    ),
    _packet(
        "impact_spike_flags_fall",
        [_sample(0.8, 9.6, 1.2, t) for t in range(10)]
        + [_sample(18.2, 4.1, 12.5, t) for t in range(10, 20)],
        24000.0,
        None                                # no GPS fix -> 0.0
    ),
    _packet(
        "audio_above_full_scale_clamps_to_one",
        [_sample(1.0, 0.0, 0.0)],
        AUDIO_RMS_FULL_SCALE * 2,
        0.0
    ),
    _packet(
        "peak_just_below_fall_threshold",
        [_sample(15.0, 0.0, 0.0)],          # 15.0 is NOT > 15 -> False
        0.0,
        0.0
    ),
    _packet(
        "peak_just_above_fall_threshold",
        [_sample(15.001, 0.0, 0.0)],
        0.0,
        0.0
    )
]


def main():
    golden = [
        {
            "name": case["name"],
            "packet": case["packet"],
            "expected": compute_feature_vector_from_packet(case["packet"])
        }
        for case in CASES
    ]

    GOLDEN_PATH.write_text(
        json.dumps(
            {
                "description": (
                    "SensorPacket -> feature-vector golden cases. Python and "
                    "Kotlin feature extraction must both reproduce 'expected' "
                    "to within 1e-4 (float32 sensor samples + rounding mode "
                    "differ; see xai-engine/CLAUDE.md)."
                ),
                "tolerance": 1e-4,
                "featureOrder": FEATURE_ORDER,
                "cases": golden
            },
            indent=4
        ),
        encoding="utf-8"
    )

    model_sha256 = (
        hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
        if MODEL_PATH.exists()
        else None
    )

    CONTRACT_PATH.write_text(
        json.dumps(
            {
                "description": (
                    "Single source of truth for the constants shared by the "
                    "Python training/XAI side and the Kotlin on-device side."
                ),
                "featureOrder": FEATURE_ORDER,
                # The Kotlin FeatureVector property for each feature. Not
                # derivable by a naive camelCase rule (GPSVelocity is
                # gpsVelocity, not gPSVelocity), so it is pinned explicitly
                # and checked by phase4/test_contract_sync.py.
                "kotlinPropertyNames": {
                    "PeakAcceleration": "peakAcceleration",
                    "MotionVariance": "motionVariance",
                    "AudioEnergy": "audioEnergy",
                    "GPSVelocity": "gpsVelocity",
                    "PossibleFall": "possibleFall"
                },
                "fallAccelerationThreshold": FALL_ACCELERATION_THRESHOLD,
                "audioRmsFullScale": AUDIO_RMS_FULL_SCALE,
                "audioFloorDb": AUDIO_FLOOR_DB,
                "audioCeilDb": AUDIO_CEIL_DB,
                "audioEnergyFormula": (
                    "clamp((20*log10(max(audioRmsEnergy,1)/audioRmsFullScale) "
                    "- audioFloorDb) / (audioCeilDb - audioFloorDb), 0, 1) "
                    "- revised 2026-09-06, dB not linear; see "
                    "sensor_packet_adapter.py AUDIO_FLOOR_DB for derivation"
                ),
                "classificationThreshold": CLASSIFICATION_THRESHOLD,
                "decisionThreshold": DECISION_THRESHOLD,
                "modelInputShape": [1, len(FEATURE_ORDER)],
                "modelOutputShape": [1, 1],
                "modelDtype": "float32",
                "normalization": (
                    "baked into the .tflite as a Keras Normalization layer - "
                    "feed RAW feature values, do not pre-normalize"
                ),
                "possibleFallEncoding": "1.0 / 0.0",
                "possibleFallUsesUnroundedPeak": True,
                "modelFile": "data/emergency_model.tflite",
                "modelSha256": model_sha256,
                "modelMustMatchAsset": (
                    "mobile-client/app/src/main/assets/emergency_model.tflite"
                )
            },
            indent=4
        ),
        encoding="utf-8"
    )

    print(f"Wrote {GOLDEN_PATH.relative_to(BASE_DIR)} ({len(golden)} cases)")
    print(f"Wrote {CONTRACT_PATH.relative_to(BASE_DIR)}")
    print(f"Model sha256: {model_sha256}")


if __name__ == "__main__":
    main()
