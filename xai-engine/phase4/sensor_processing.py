import pandas as pd
from pathlib import Path

from feature_extraction import (
    validate_and_clean,
    compute_feature_vector_from_clean,
    REQUIRED_COLUMNS
)


# ============================================================
# 1. Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_PATH = BASE_DIR / "data" / "sensor_data.csv"
OUTPUT_PATH = BASE_DIR / "data" / "feature_vector.csv"

# The CSV prototype has no session concept. If a previous run of the real
# SensorPacket path (process_sensor_packet.py) left a session_context.json
# behind, it must not be attached to this CSV-sourced decision.
SESSION_CONTEXT_PATH = BASE_DIR / "data" / "session_context.json"

if SESSION_CONTEXT_PATH.exists():
    SESSION_CONTEXT_PATH.unlink()


# ============================================================
# 2. Load sensor data
# ============================================================

data = pd.read_csv(INPUT_PATH)

print("Data loaded successfully.")
print("Raw sensor readings:", len(data))


# ============================================================
# 3-5. Validate columns, coerce to numeric, drop invalid rows
# ============================================================

data = validate_and_clean(data, REQUIRED_COLUMNS)

print(
    "Valid sensor readings:",
    len(data)
)


# ============================================================
# 6-9. Compute feature vector
# ============================================================

feature_vector = compute_feature_vector_from_clean(data)


# ============================================================
# 10. Save feature vector
# ============================================================

pd.DataFrame(
    [feature_vector]
).to_csv(
    OUTPUT_PATH,
    index=False
)


# ============================================================
# 11. Display results
# ============================================================

print("\nFeature Vector")
print("=" * 50)

for feature, value in feature_vector.items():
    print(
        f"{feature}: {value}"
    )

print("\nFeature vector saved to:")
print(OUTPUT_PATH)
