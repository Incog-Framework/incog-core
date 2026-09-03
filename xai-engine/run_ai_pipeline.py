"""Run the Phase 4 -> 6 + XAI pipeline.

Two Phase 4 entry points, one identical set of downstream stages. Switching
between them changes only where the feature vector comes from - never the AI
logic, the model, the thresholds, or the XAI.

    --source packet   (default) a real SensorPacket JSON capture, the Aarush
                      Phase 3 -> Phase 4 handoff shape. Also emits SessionID /
                      TimestampMs, which propagate all the way to the Phase 7
                      evidence manifest and system report.

    --source csv      data/sensor_data.csv, the development prototype path.
                      No session concept, so no SessionID downstream.

Which packet file the integration path reads, in priority order:

    --packet PATH  ->  $INCOG_SENSOR_PACKET  ->  data/sensor_packet.json

Examples:

    python run_ai_pipeline.py
    python run_ai_pipeline.py --packet data/real_packets/emergency/fall_01.json
    python run_ai_pipeline.py --source csv
"""

import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


PHASE4 = {
    "packet": (
        "PHASE 4 - Sensor Fusion (real SensorPacket)",
        os.path.join("phase4", "process_sensor_packet.py")
    ),
    "csv": (
        "PHASE 4 - Sensor Fusion (CSV prototype)",
        os.path.join("phase4", "sensor_processing.py")
    )
}


def run_step(name, script, script_arguments=()):
    print("\n")
    print("=" * 60)
    print(name)
    print("=" * 60)

    # cwd is pinned to BASE_DIR so the pipeline behaves the same no matter
    # where it was launched from; the scripts resolve their own data paths
    # relative to __file__ anyway.
    result = subprocess.run(
        [sys.executable, script, *script_arguments],
        cwd=BASE_DIR
    )

    if result.returncode != 0:
        print(f"\nFAILED: {name}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--source",
        choices=sorted(PHASE4),
        default="packet",
        help="Phase 4 input: real SensorPacket JSON (default) or the CSV prototype"
    )

    parser.add_argument(
        "--packet",
        help=(
            "path to a real SensorPacket JSON capture. Implies --source packet."
        )
    )

    parser.add_argument(
        "--skip-visualizations",
        action="store_true",
        help="skip the matplotlib SHAP/LIME charts"
    )

    arguments = parser.parse_args()

    source = arguments.source

    if arguments.packet:
        if arguments.source == "csv":
            parser.error(
                "--packet is a SensorPacket capture and cannot be combined "
                "with --source csv"
            )
        source = "packet"

    phase4_name, phase4_script = PHASE4[source]

    phase4_arguments = (
        ["--packet", arguments.packet] if arguments.packet else []
    )

    steps = [
        (phase4_name, phase4_script, phase4_arguments),
        (
            "PHASE 5 - TFLite Prediction",
            os.path.join("phase5", "tflite_predict.py"),
            []
        ),
        (
            "PHASE 6 - Decision Engine",
            os.path.join("phase6", "decision_engine.py"),
            []
        ),
        (
            "XAI - SHAP + LIME",
            os.path.join("xai", "xai_pipeline.py"),
            []
        )
    ]

    for name, script, script_arguments in steps:
        run_step(name, script, script_arguments)

    print("\n")
    print("=" * 60)
    print("INCOG AI PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 60)

    if arguments.skip_visualizations:
        return

    print("\nGenerating XAI visualizations...")

    result = subprocess.run(
        [sys.executable, "-m", "xai.visualize"],
        cwd=BASE_DIR
    )

    if result.returncode != 0:
        raise RuntimeError("XAI visualization failed.")

    print("XAI visualizations generated successfully.")


if __name__ == "__main__":
    main()
