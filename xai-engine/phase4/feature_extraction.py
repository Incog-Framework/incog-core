import numpy as np
import pandas as pd


# ============================================================
# Constants
# ============================================================

REQUIRED_COLUMNS = [
    "acc_x",
    "acc_y",
    "acc_z",
    "audio_energy",
    "gps_speed"
]

FALL_ACCELERATION_THRESHOLD = 15

FEATURE_ORDER = [
    "PeakAcceleration",
    "MotionVariance",
    "AudioEnergy",
    "GPSVelocity",
    "PossibleFall"
]


# ============================================================
# Validation
# ============================================================

def validate_and_clean(data: pd.DataFrame, required_columns=REQUIRED_COLUMNS) -> pd.DataFrame:
    """Validate required columns exist, coerce to numeric, and drop invalid rows.

    Raises ValueError if required columns are missing or no valid readings remain.
    """

    missing_columns = [
        column
        for column in required_columns
        if column not in data.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing sensor columns: {missing_columns}"
        )

    data = data.copy()

    for column in required_columns:
        data[column] = pd.to_numeric(
            data[column],
            errors="coerce"
        )

    data = data.dropna(subset=required_columns)
    data = data.drop_duplicates()

    if len(data) == 0:
        raise ValueError(
            "No valid sensor readings available."
        )

    return data


# ============================================================
# Shared acceleration math (single source of truth).
#
# Both the CSV prototype path and the real SensorPacket path derive
# PeakAcceleration / MotionVariance / PossibleFall from a magnitude series
# via these two functions, so the definitions can never drift between them.
# ============================================================

def acceleration_magnitude(acc_x, acc_y, acc_z) -> np.ndarray:
    acc_x = np.asarray(acc_x, dtype=float)
    acc_y = np.asarray(acc_y, dtype=float)
    acc_z = np.asarray(acc_z, dtype=float)

    return np.sqrt(acc_x ** 2 + acc_y ** 2 + acc_z ** 2)


def peak_and_variance(magnitudes: np.ndarray) -> tuple:
    """Peak + sample variance (ddof=1) of an acceleration-magnitude series.

    A single sample has no defined sample variance (division by zero); that
    is treated as 0.0 rather than propagating NaN into the model, which
    matters for the real SensorPacket path where the very first packet of a
    session can carry only 1-2 accelerometer samples.
    """

    magnitudes = np.asarray(magnitudes, dtype=float)

    peak = float(np.max(magnitudes))

    if len(magnitudes) >= 2:
        variance = float(np.var(magnitudes, ddof=1))
    else:
        variance = 0.0

    return peak, variance


def possible_fall(peak_acceleration: float) -> bool:
    return peak_acceleration > FALL_ACCELERATION_THRESHOLD


# ============================================================
# Feature computation (assumes already-clean data)
# ============================================================

def compute_feature_vector_from_clean(data: pd.DataFrame) -> dict:
    magnitudes = acceleration_magnitude(
        data["acc_x"],
        data["acc_y"],
        data["acc_z"]
    )

    peak_acceleration, motion_variance = peak_and_variance(magnitudes)
    audio_energy = data["audio_energy"].mean()
    gps_velocity = data["gps_speed"].mean()

    return {
        "PeakAcceleration": round(peak_acceleration, 4),
        "MotionVariance": round(motion_variance, 4),
        "AudioEnergy": round(float(audio_energy), 4),
        "GPSVelocity": round(float(gps_velocity), 4),
        "PossibleFall": bool(possible_fall(peak_acceleration))
    }


# ============================================================
# Public API: raw readings -> feature vector
# ============================================================

def compute_feature_vector(data: pd.DataFrame) -> dict:
    """Validate/clean a raw sensor-readings DataFrame and compute the feature vector.

    A raw DataFrame must contain: acc_x, acc_y, acc_z, audio_energy, gps_speed.
    """

    clean_data = validate_and_clean(data)
    return compute_feature_vector_from_clean(clean_data)
