"""Phase 4, integration path: a real SensorPacket -> the feature vector.

This is the ONLY entry point that reads Aarush's packet format, and it does
so entirely through sensor_packet_adapter - no raw packet field names appear
below. That keeps the adapter as the single Android -> AI interface.

Which packet file is used, in priority order:

    --packet PATH                 explicit
    $INCOG_SENSOR_PACKET          environment, handy for tests/CI
    data/sensor_packet.json       the committed example shape

Outputs are identical in schema to the CSV prototype path
(phase4/sensor_processing.py), so Phase 5 onward cannot tell which entry
point produced them - except that this one also writes session context.

    data/feature_vector.csv     the 5 features
    data/session_context.json   SessionID + TimestampMs
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sensor_packet_adapter import (          # noqa: E402
    extract_from_sensor_packet,
    load_packet
)

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_PACKET_PATH = BASE_DIR / "data" / "sensor_packet.json"
FEATURE_OUTPUT_PATH = BASE_DIR / "data" / "feature_vector.csv"
SESSION_OUTPUT_PATH = BASE_DIR / "data" / "session_context.json"

PACKET_ENV_VAR = "INCOG_SENSOR_PACKET"


def resolve_packet_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit)

    from_environment = os.environ.get(PACKET_ENV_VAR)

    if from_environment:
        return Path(from_environment)

    return DEFAULT_PACKET_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packet",
        help=(
            "path to a SensorPacket JSON capture (single object or an array; "
            f"defaults to ${PACKET_ENV_VAR}, then data/sensor_packet.json)"
        )
    )
    arguments = parser.parse_args()

    packet_path = resolve_packet_path(arguments.packet)

    if not packet_path.exists():
        print(f"SensorPacket file not found: {packet_path}")
        print(
            "\nProvide one with --packet PATH, or set "
            f"${PACKET_ENV_VAR}. See INTEGRATION.md."
        )
        raise SystemExit(2)

    packet = load_packet(packet_path)

    print("SensorPacket loaded.")
    print("Source:", packet_path)

    # ------------------------------------------------------------
    # Adapt packet -> feature vector. Same five features, same order
    # as the CSV path (see sensor_packet_adapter.py for the mapping).
    # ------------------------------------------------------------

    result = extract_from_sensor_packet(packet)

    feature_vector = result["Features"]

    print("SessionID:", result["SessionID"])

    # ------------------------------------------------------------
    # Feature vector - identical schema/consumer as the CSV path, so
    # Phase 5 does not need to know which entry point produced it.
    # ------------------------------------------------------------

    pd.DataFrame([feature_vector]).to_csv(FEATURE_OUTPUT_PATH, index=False)

    # ------------------------------------------------------------
    # Session context, so Phase 6 / XAI / Phase 7 can tag the
    # decision and the evidence with the session it came from.
    # ------------------------------------------------------------

    with open(SESSION_OUTPUT_PATH, "w") as file:
        json.dump(
            {
                "SessionID": result["SessionID"],
                "TimestampMs": result["TimestampMs"],
                "SourcePacket": str(packet_path)
            },
            file,
            indent=4
        )

    print("\nFeature Vector")
    print("=" * 50)

    for feature, value in feature_vector.items():
        print(f"{feature}: {value}")

    print("\nFeature vector saved to:")
    print(FEATURE_OUTPUT_PATH)

    print("\nSession context saved to:")
    print(SESSION_OUTPUT_PATH)


if __name__ == "__main__":
    main()
