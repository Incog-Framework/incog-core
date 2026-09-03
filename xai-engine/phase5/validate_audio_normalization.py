"""Validate the AudioEnergy mapping: audioRmsEnergy -> [0, 1].

THE CONTRACT (read off the real code, not the handoff prose)
------------------------------------------------------------
  AudioBufferCollector.kt   16 kHz mono, ENCODING_PCM_16BIT
                            lastRmsEnergy = sqrt(mean(sample^2)) over the
                            signed 16-bit samples of ONE AudioRecord read
  SensorPacket.kt           audioRmsEnergy: Double  (that RMS, 0..32768)
  FeatureExtractor.kt       audioEnergy = (audioRmsEnergy / 32768)
                                            .coerceAtMost(1.0)
  sensor_packet_adapter.py  audio_energy = clamp(rms / 32768, 0, 1)

WHAT THIS SCRIPT CAN AND CANNOT ESTABLISH
-----------------------------------------
It runs two levels of check, and reports them separately because they are
NOT the same claim:

  LEVEL 1 - arithmetic.  Signals with an analytically known RMS (silence,
    full-scale square, full-scale sine) confirm the Python mapping is the
    formula above. Always runs. Proves the unit conversion, nothing more.

  LEVEL 2 - calibration. Real recordings show where quiet ambient, ordinary
    speech and a scream actually LAND in [0, 1], which is what decides
    whether AudioEnergy is a useful model input or a near-constant. Runs
    only when real audio is present; otherwise it reports NOT VALIDATED.

A passing Level 1 is not a validated feature. The one measurement that
settles it - what a pocketed phone reads during a real incident - can only
come from the device.

USAGE
    python phase5/validate_audio_normalization.py
    python phase5/validate_audio_normalization.py --wav path/to/recording.wav
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "phase5"))
sys.path.insert(0, str(BASE_DIR / "phase4"))

from dataset_adapters import (              # noqa: E402
    AUDIO_RMS_FULL_SCALE,
    DEVICE_SAMPLE_RATE_HZ,
    DatasetUnavailable,
    load_ravdess_audio_energy,
    pcm16_rms,
    pcm16_rms_to_audio_energy,
    read_wav_as_pcm16_mono_16k
)
from sensor_packet_adapter import compute_feature_vector_from_packet  # noqa: E402

REPORT_PATH = BASE_DIR / "data" / "audio_validation_report.json"

CHUNK_FRAMES = 1024


# ============================================================
# LEVEL 1 - arithmetic
# ============================================================

def level1_arithmetic():
    """Signals whose RMS is known in closed form."""

    checks = []

    def check(name, samples, expected_energy, tolerance=1e-4):
        actual = pcm16_rms_to_audio_energy(samples)
        passed = abs(actual - expected_energy) <= tolerance

        checks.append({
            "signal": name,
            "expected_audio_energy": round(expected_energy, 6),
            "actual_audio_energy": round(actual, 6),
            "rms": round(pcm16_rms(samples), 2),
            "passed": bool(passed)
        })

    check("silence", np.zeros(CHUNK_FRAMES), 0.0)

    # every sample at negative full scale -> RMS exactly 32768 -> exactly 1.0
    check("full_scale_square", np.full(CHUNK_FRAMES, -32768.0), 1.0)

    # sine at full amplitude -> RMS = A/sqrt(2)
    time = np.arange(DEVICE_SAMPLE_RATE_HZ)
    sine = np.round(32767 * np.sin(2 * np.pi * 440 * time / DEVICE_SAMPLE_RATE_HZ))
    check("full_scale_sine_440hz", sine, (32767 / np.sqrt(2)) / AUDIO_RMS_FULL_SCALE, 1e-3)

    # half-amplitude sine -> half the energy of the above
    check(
        "half_scale_sine_440hz",
        np.round(sine / 2),
        (32767 / 2 / np.sqrt(2)) / AUDIO_RMS_FULL_SCALE,
        1e-3
    )

    # above full scale must clamp, never exceed 1.0
    check("above_full_scale_clamps", np.full(CHUNK_FRAMES, -32768.0) * 3, 1.0)

    return checks


def level1_adapter_agreement():
    """The adapter must apply exactly the same mapping as the helper."""

    checks = []

    for rms in (0.0, 1.0, 500.0, 16384.0, 32768.0, 99999.0, -500.0):
        packet = {
            "sessionId": "SESS-AUDIOVAL",
            "timestampMs": 0,
            "accelSamples": [{"timestampMs": 0, "x": 1.0, "y": 0.0, "z": 0.0}],
            "audioRmsEnergy": rms,
            "latestLocation": None
        }

        actual = compute_feature_vector_from_packet(packet)["AudioEnergy"]
        expected = round(min(max(rms / AUDIO_RMS_FULL_SCALE, 0.0), 1.0), 4)

        checks.append({
            "audioRmsEnergy": rms,
            "expected_audio_energy": expected,
            "actual_audio_energy": actual,
            "in_unit_range": 0.0 <= actual <= 1.0,
            "passed": bool(actual == expected and 0.0 <= actual <= 1.0)
        })

    return checks


# ============================================================
# LEVEL 2 - calibration against real audio
# ============================================================

def _summarise(energies, label):
    energies = np.asarray(energies, dtype=float)

    return {
        "label": label,
        "chunks": int(energies.size),
        "min": round(float(energies.min()), 4),
        "p05": round(float(np.percentile(energies, 5)), 4),
        "median": round(float(np.median(energies)), 4),
        "p95": round(float(np.percentile(energies, 95)), 4),
        "max": round(float(energies.max()), 4),
        "mean": round(float(energies.mean()), 4)
    }


def level2_from_wav(path):
    samples = read_wav_as_pcm16_mono_16k(path)

    energies = [
        pcm16_rms_to_audio_energy(samples[start:start + CHUNK_FRAMES])
        for start in range(0, len(samples) - CHUNK_FRAMES + 1, CHUNK_FRAMES)
    ]

    if not energies:
        raise ValueError(f"{path} is shorter than one {CHUNK_FRAMES}-frame chunk")

    return _summarise(energies, path.name)


def level2_from_ravdess():
    records, provenance = load_ravdess_audio_energy()

    distress = records[records["IsDistress"]]["AudioEnergy"]
    calm = records[~records["IsDistress"]]["AudioEnergy"]

    return {
        "source": provenance["source"],
        "caveat": provenance["caveat"],
        "distress": _summarise(distress, "distress (angry/fearful/disgust)"),
        "non_distress": _summarise(calm, "non-distress"),
        "separated": bool(np.median(distress) > np.median(calm))
    }


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wav",
        action="append",
        default=[],
        help="a real recording to profile (repeatable)"
    )
    arguments = parser.parse_args()

    print("=" * 64)
    print("AUDIO NORMALIZATION VALIDATION")
    print("=" * 64)

    print("\nContract under test:")
    print(f"  AudioEnergy = clamp(audioRmsEnergy / {AUDIO_RMS_FULL_SCALE:.0f}, 0, 1)")
    print(f"  audioRmsEnergy = RMS of signed PCM16 @ {DEVICE_SAMPLE_RATE_HZ} Hz mono")

    # ---------------- Level 1 ----------------

    print("\n" + "-" * 64)
    print("LEVEL 1 - arithmetic (proves the unit conversion only)")
    print("-" * 64)

    arithmetic = level1_arithmetic()

    for check in arithmetic:
        mark = "PASS" if check["passed"] else "FAIL"
        print(
            f"  [{mark}] {check['signal']:24s} "
            f"rms={check['rms']:>9.2f}  "
            f"energy={check['actual_audio_energy']:.6f} "
            f"(expected {check['expected_audio_energy']:.6f})"
        )

    agreement = level1_adapter_agreement()

    print("\n  adapter agreement (sensor_packet_adapter):")
    for check in agreement:
        mark = "PASS" if check["passed"] else "FAIL"
        print(
            f"  [{mark}] audioRmsEnergy={check['audioRmsEnergy']:>10.1f} "
            f"-> AudioEnergy={check['actual_audio_energy']}"
        )

    level1_passed = all(
        check["passed"] for check in arithmetic + agreement
    )

    # ---------------- Level 2 ----------------

    print("\n" + "-" * 64)
    print("LEVEL 2 - calibration against real audio")
    print("-" * 64)

    level2 = {"status": "NOT_VALIDATED", "profiles": []}

    for raw_path in arguments.wav:
        path = Path(raw_path)

        if not path.exists():
            print(f"  [SKIP] {path} does not exist")
            continue

        profile = level2_from_wav(path)
        level2["profiles"].append(profile)

        print(
            f"  {profile['label']}: median={profile['median']} "
            f"p95={profile['p95']} max={profile['max']}"
        )

    try:
        ravdess = level2_from_ravdess()
        level2["ravdess"] = ravdess

        print(
            f"  RAVDESS distress    : median="
            f"{ravdess['distress']['median']} p95={ravdess['distress']['p95']}"
        )
        print(
            f"  RAVDESS non-distress: median="
            f"{ravdess['non_distress']['median']} "
            f"p95={ravdess['non_distress']['p95']}"
        )
    except DatasetUnavailable:
        print("  [SKIP] RAVDESS not present (data/raw/ravdess)")

    if level2["profiles"] or "ravdess" in level2:
        level2["status"] = "PARTIAL_CORPUS_ONLY"

    if level2["status"] == "NOT_VALIDATED":
        print(
            "\n  No real audio supplied - the calibration question is OPEN.\n"
            "  Unanswered: where do quiet ambient / speech / a scream land in\n"
            "  [0, 1] when the phone is in a pocket? If everything real lands\n"
            "  below ~0.05, AudioEnergy is close to a constant and the model\n"
            "  is effectively running on four features, not five.\n"
            "  The training data assumes 0.04-0.25 normal and 0.55-0.91\n"
            "  emergency; NOTHING has confirmed those ranges are reachable."
        )

    # ---------------- Report ----------------

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": {
            "formula": "clamp(audioRmsEnergy / 32768, 0, 1)",
            "full_scale": AUDIO_RMS_FULL_SCALE,
            "sample_rate_hz": DEVICE_SAMPLE_RATE_HZ,
            "encoding": "PCM16 mono"
        },
        "level1_arithmetic": {
            "passed": level1_passed,
            "checks": arithmetic,
            "adapter_agreement": agreement,
            "establishes": (
                "the Python mapping implements the documented formula and "
                "matches the Kotlin one"
            ),
            "does_not_establish": (
                "that real recorded audio produces useful values in [0, 1]"
            )
        },
        "level2_calibration": level2,
        "device_validation_outstanding": level2["status"] != "DEVICE_VALIDATED",
        "how_to_close": (
            "Log packet.audioRmsEnergy from GhostStateService during a real "
            "Ghost State session - quiet room, normal conversation, shouting, "
            "phone in a pocket - and compare the resulting AudioEnergy values "
            "against the 0.04-0.91 range the training data assumes."
        )
    }

    REPORT_PATH.write_text(json.dumps(report, indent=4), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"Level 1 (arithmetic) : {'PASS' if level1_passed else 'FAIL'}")
    print(f"Level 2 (calibration): {level2['status']}")
    print(f"\nReport: {REPORT_PATH}")
    print("=" * 64)

    if not level1_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
