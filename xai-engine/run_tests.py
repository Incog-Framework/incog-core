"""Run every xai-engine test suite and summarise.

    python run_tests.py            # all suites
    python run_tests.py --fast     # skip the ones that need TensorFlow

Each suite is a plain script with its own runner, so no pytest is required.
"""

import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (label, path, needs_tensorflow)
SUITES = [
    (
        "Phase 4 - feature extraction (CSV path)",
        os.path.join("phase4", "test_feature_extraction.py"),
        False
    ),
    (
        "Phase 4 - SensorPacket adapter",
        os.path.join("phase4", "test_sensor_packet_adapter.py"),
        False
    ),
    (
        "Phase 4 - SensorPacket contract vs Kotlin",
        os.path.join("phase4", "test_sensor_packet_contract.py"),
        False
    ),
    (
        "Phase 4 - adapter is the sole interface",
        os.path.join("phase4", "test_adapter_is_sole_interface.py"),
        False
    ),
    (
        "Phase 4 - real SensorPacket captures",
        os.path.join("phase4", "test_real_packets.py"),
        False
    ),
    (
        "Phase 4 - Python/Kotlin parity",
        os.path.join("phase4", "test_kotlin_parity.py"),
        False
    ),
    (
        "Phase 4 - cross-language contract sync",
        os.path.join("phase4", "test_contract_sync.py"),
        False
    ),
    (
        "Phase 6 - decision threshold (0.80)",
        os.path.join("phase6", "test_decision_threshold.py"),
        False
    ),
    (
        "XAI - output contract",
        os.path.join("xai", "test_xai_output_contract.py"),
        False
    ),
    (
        "Phase 5 - dataset adapters",
        os.path.join("phase5", "test_dataset_adapters.py"),
        False
    ),
    (
        "XAI - explainer service (backend API)",
        os.path.join("xai", "test_explainer_service.py"),
        True
    ),
    (
        "Phase 5 - TFLite inference over the dataset",
        os.path.join("phase5", "test_tflite_all.py"),
        True
    ),
    (
        "Phase 7 - scenario test cases",
        os.path.join("phase7", "test_cases.py"),
        True
    ),
    (
        "Phase 6 - system validation",
        os.path.join("phase6", "test_system.py"),
        True
    ),
    (
        "Phase 7 - session propagation (Phase 4 -> 7)",
        os.path.join("phase7", "test_session_propagation.py"),
        True
    ),
    (
        "Audio normalization validation",
        os.path.join("phase5", "validate_audio_normalization.py"),
        False
    )
]

# tests in phase4/ import sibling modules by bare name, so that folder has to
# be importable regardless of which directory the suite lives in
CHILD_ENV = dict(os.environ)
CHILD_ENV["PYTHONPATH"] = os.pathsep.join(
    filter(None, [
        os.path.join(BASE_DIR, "phase4"),
        BASE_DIR,
        CHILD_ENV.get("PYTHONPATH", "")
    ])
)

# TensorFlow's C++ layers log to stderr on import; quiet the noise so a real
# failure is visible in the summary
CHILD_ENV["TF_CPP_MIN_LOG_LEVEL"] = "3"


def run(label, script):
    print("\n" + "=" * 66)
    print(label)
    print("=" * 66)

    result = subprocess.run(
        [sys.executable, script],
        cwd=BASE_DIR,
        env=CHILD_ENV,
        capture_output=True,
        text=True
    )

    output = result.stdout.strip()

    if output:
        print(output)

    if result.returncode != 0:
        error = result.stderr.strip()
        if error:
            print(error[-2000:])

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip suites that need TensorFlow"
    )
    arguments = parser.parse_args()

    results = []

    for label, script, needs_tensorflow in SUITES:
        if arguments.fast and needs_tensorflow:
            results.append((label, None))
            continue

        results.append((label, run(label, script)))

    print("\n" + "=" * 66)
    print("SUMMARY")
    print("=" * 66)

    passed = 0
    failed = 0
    skipped = 0

    for label, outcome in results:
        if outcome is None:
            print(f"  SKIP  {label}")
            skipped += 1
        elif outcome:
            print(f"  PASS  {label}")
            passed += 1
        else:
            print(f"  FAIL  {label}")
            failed += 1

    print("=" * 66)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
