import json
import pandas as pd
from pathlib import Path

from sensor_packet_adapter import extract_from_sensor_packet


# ============================================================
# 1. Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_PATH = BASE_DIR / "data" / "sensor_packet.json"
FEATURE_OUTPUT_PATH = BASE_DIR / "data" / "feature_vector.csv"
SESSION_OUTPUT_PATH = BASE_DIR / "data" / "session_context.json"


# ============================================================
# 2. Load SensorPacket (Aarush's Phase 3 -> Phase 4 handoff)
# ============================================================

with open(INPUT_PATH, "r") as file:
    packet = json.load(file)

print("SensorPacket loaded.")
print("SessionID:", packet.get("sessionId"))


# ============================================================
# 3. Adapt packet -> feature vector (same 5 features, same order,
#    as the CSV path - see sensor_packet_adapter.py for the mapping)
# ============================================================

result = extract_from_sensor_packet(packet)

feature_vector = result["Features"]


# ============================================================
# 4. Save feature vector (identical schema/consumer as the CSV
#    path - Phase 5 does not need to know which Phase 4 entry
#    point produced it)
# ============================================================

pd.DataFrame(
    [feature_vector]
).to_csv(
    FEATURE_OUTPUT_PATH,
    index=False
)


# ============================================================
# 5. Save session context (SessionID/Timestamp), so downstream
#    Phase 6 / XAI / Phase 7 can tag the decision with the
#    session it came from
# ============================================================

with open(SESSION_OUTPUT_PATH, "w") as file:
    json.dump(
        {
            "SessionID": result["SessionID"],
            "TimestampMs": result["TimestampMs"]
        },
        file,
        indent=4
    )


# ============================================================
# 6. Display results
# ============================================================

print("\nFeature Vector")
print("=" * 50)

for feature, value in feature_vector.items():
    print(f"{feature}: {value}")

print("\nFeature vector saved to:")
print(FEATURE_OUTPUT_PATH)

print("\nSession context saved to:")
print(SESSION_OUTPUT_PATH)
