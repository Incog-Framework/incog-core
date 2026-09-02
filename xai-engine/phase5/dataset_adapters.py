"""Pluggable training-data sources for the emergency model.

WHY THIS EXISTS
---------------
The committed training_data.csv is 30 hand-written rows that are linearly
separable on PeakAcceleration alone (every Normal <= 14.0, every Emergency
>= 16.5). A model scores 100% on it without learning anything. Those numbers
are NOT evidence of production performance and must never be reported as if
they were.

This module is the seam where real data plugs in. Every adapter returns the
same thing, so train_tflite_model.py does not care where the rows came from:

    (DataFrame[FEATURE_ORDER + "Emergency"], provenance: dict)

WINDOWING - must match on-device inference
------------------------------------------
Read off the real Kotlin (SensorCollector.MAX_SAMPLES, SENSOR_DELAY_GAME,
GhostStateService.SNAPSHOT_INTERVAL_MS):

    * accelerometer runs at SENSOR_DELAY_GAME, ~50 Hz
    * history is bounded to 1000 samples => a ~20 second rolling window
    * a packet is built and scored every 2 seconds

So one training row = one ~20 s window of accelerometer magnitude, stepped by
2 s. A dataset sampled at a different rate must be resampled to ~50 Hz first,
or its MotionVariance will not be on the same scale as what the phone
produces. Features are computed by importing phase4 rather than
reimplementing, so training rows and on-device rows come from one definition.

HONESTY RULES
-------------
* An adapter whose data is not present raises DatasetUnavailable with the
  exact files it needs. It never substitutes, simulates, or interpolates.
* Provenance travels with the data and is written into the metrics file, so
  a synthetic result can never be mistaken for a real one downstream.
* The real-dataset loaders below are written against each corpus's PUBLISHED
  format. They are unverified against actual archives because those archives
  are not in this repo - see DATA_REQUIREMENTS.md.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "phase4"))

from feature_extraction import (            # noqa: E402
    FEATURE_ORDER,
    acceleration_magnitude,
    peak_and_variance,
    possible_fall
)

DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"

TARGET = "Emergency"
COLUMNS = FEATURE_ORDER + [TARGET]

# Optional per-row provenance a loader may supply. Carried through when
# present because a random split leaks on windowed sensor data: consecutive
# windows overlap heavily, and several recordings come from one person, so
# train/test must be split by SUBJECT to mean anything.
METADATA_COLUMNS = ["Subject", "Activity"]

# On-device inference geometry (see module docstring).
TARGET_SAMPLE_RATE_HZ = 50.0
WINDOW_SAMPLES = 1000            # SensorCollector.MAX_SAMPLES
WINDOW_STRIDE_SAMPLES = 100      # 2 s at 50 Hz, SNAPSHOT_INTERVAL_MS

GRAVITY_MPS2 = 9.80665


class DatasetUnavailable(Exception):
    """Raised when a real dataset is not present on disk.

    Carries the concrete instructions for supplying it, so the failure is
    actionable instead of just "file not found".
    """


# ============================================================
# Shared windowing / feature computation
# ============================================================

def resample_to_target_rate(magnitudes, source_rate_hz):
    """Linearly resample a magnitude series to TARGET_SAMPLE_RATE_HZ.

    MotionVariance and PeakAcceleration are both rate-sensitive: the same
    motion sampled at 20 Hz and at 50 Hz yields different statistics, so a
    corpus recorded at another rate cannot be fed in as-is.
    """

    magnitudes = np.asarray(magnitudes, dtype=float)

    if source_rate_hz == TARGET_SAMPLE_RATE_HZ:
        return magnitudes

    duration_s = len(magnitudes) / source_rate_hz
    target_count = int(duration_s * TARGET_SAMPLE_RATE_HZ)

    if target_count < 2:
        return magnitudes[:1]

    source_times = np.arange(len(magnitudes)) / source_rate_hz
    target_times = np.arange(target_count) / TARGET_SAMPLE_RATE_HZ

    return np.interp(target_times, source_times, magnitudes)


def windows_from_magnitudes(magnitudes,
                            window=WINDOW_SAMPLES,
                            stride=WINDOW_STRIDE_SAMPLES):
    """Yield rolling windows matching the on-device history buffer.

    A recording shorter than one full window still yields a single partial
    window: on the phone, the first ~20 s of a session are scored against a
    not-yet-full buffer, so those rows are real inference conditions rather
    than something to discard.
    """

    magnitudes = np.asarray(magnitudes, dtype=float)

    if len(magnitudes) == 0:
        return

    if len(magnitudes) <= window:
        yield magnitudes
        return

    for start in range(0, len(magnitudes) - window + 1, stride):
        yield magnitudes[start:start + window]


def features_from_window(magnitudes, audio_energy, gps_velocity):
    """Build one feature row using the SAME functions Phase 4 uses.

    Importing peak_and_variance/possible_fall rather than reimplementing them
    is what guarantees a training row and an on-device row mean the same
    thing.
    """

    peak, variance = peak_and_variance(magnitudes)

    return {
        "PeakAcceleration": round(peak, 4),
        "MotionVariance": round(variance, 4),
        "AudioEnergy": round(float(audio_energy), 4),
        "GPSVelocity": round(float(gps_velocity), 4),
        "PossibleFall": bool(possible_fall(peak))
    }


def magnitudes_from_xyz(frame, columns=("x", "y", "z"), scale=1.0):
    """Acceleration magnitude series from a 3-axis frame, scaled to m/s^2."""

    return acceleration_magnitude(
        frame[columns[0]].to_numpy() * scale,
        frame[columns[1]].to_numpy() * scale,
        frame[columns[2]].to_numpy() * scale
    )


# ============================================================
# Audio: the device's own AudioEnergy definition, in Python
#
# Mirrors the two Kotlin pieces that together produce the feature:
#   AudioBufferCollector.computeRms   RMS over signed PCM16 samples
#   FeatureExtractor                  / 32768, clamped
#
# Kept dependency-free (numpy only) so it runs anywhere; the stdlib audioop
# module that would otherwise do this was removed in Python 3.13.
# ============================================================

AUDIO_RMS_FULL_SCALE = 32768.0
DEVICE_SAMPLE_RATE_HZ = 16000        # AudioBufferCollector.SAMPLE_RATE


def pcm16_rms(samples):
    """RMS of signed 16-bit PCM samples - AudioBufferCollector.computeRms."""

    samples = np.asarray(samples, dtype=np.float64)

    if samples.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(samples ** 2)))


def pcm16_rms_to_audio_energy(samples):
    """Full device mapping: PCM16 samples -> the model's AudioEnergy feature."""

    return min(max(pcm16_rms(samples) / AUDIO_RMS_FULL_SCALE, 0.0), 1.0)


def read_wav_as_pcm16_mono_16k(path):
    """Decode a WAV to the device's capture format: mono, 16 kHz, PCM16.

    Matches AudioRecord(MIC, 16000, CHANNEL_IN_MONO, ENCODING_PCM_16BIT) so
    RMS values computed here are on the same scale as audioRmsEnergy.
    """

    import wave

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    if width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    elif width == 1:
        # 8-bit WAV is unsigned; centre it and scale to the 16-bit range
        samples = (
            np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0
        ) * 256.0
    elif width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 65536.0
    else:
        raise ValueError(f"unsupported sample width {width} bytes in {path}")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if rate != DEVICE_SAMPLE_RATE_HZ and len(samples) > 1:
        target_count = int(len(samples) * DEVICE_SAMPLE_RATE_HZ / rate)
        samples = np.interp(
            np.linspace(0, len(samples) - 1, target_count),
            np.arange(len(samples)),
            samples
        )

    return np.clip(np.round(samples), -32768, 32767)


def _require(path, dataset, instructions):
    if not path.exists():
        raise DatasetUnavailable(
            f"\n{dataset} is not available.\n"
            f"  Expected at: {path}\n"
            f"{instructions}\n"
            f"  See xai-engine/DATA_REQUIREMENTS.md for the full checklist.\n"
        )

    return path


# ============================================================
# synthetic - the committed prototype rows
# ============================================================

def load_synthetic():
    path = DATA_DIR / "training_data.csv"

    data = pd.read_csv(path)

    provenance = {
        "dataset": "synthetic",
        "source": str(path.relative_to(BASE_DIR)),
        "is_synthetic": True,
        "is_production_evidence": False,
        "real_windows": 0,
        "subjects": 0,
        "caveat": (
            "30 hand-written rows, linearly separable on PeakAcceleration "
            "alone. Useful only as a pipeline smoke test. Metrics from this "
            "dataset say nothing about real-world accuracy or false-positive "
            "rate."
        )
    }

    return data, provenance


# ============================================================
# sensor_packets - real captures from the phone (highest fidelity)
# ============================================================

def load_sensor_packets():
    """Real SensorPacket JSON captured from Ghost State sessions.

    This is the only source that needs no assumptions at all: the packets are
    exactly what the phone would have scored, so features come straight
    through phase4's adapter.

    Expected layout - one JSON file per capture, or one JSON array per file:

        data/raw/sensor_packets/emergency/*.json
        data/raw/sensor_packets/normal/*.json

    The containing folder supplies the label, so captures must be sorted by
    hand into the two folders when they are recorded.
    """

    import json

    sys.path.insert(0, str(BASE_DIR / "phase4"))
    from sensor_packet_adapter import compute_feature_vector_from_packet

    root = RAW_DIR / "sensor_packets"

    _require(
        root,
        "Real SensorPacket captures",
        "  Provide: Ghost State captures exported from the device, sorted as\n"
        "    data/raw/sensor_packets/emergency/*.json  (staged incidents)\n"
        "    data/raw/sensor_packets/normal/*.json     (everyday activity)\n"
        "  Each file is one SensorPacket object, or an array of them."
    )

    rows = []
    counts = {"emergency": 0, "normal": 0}

    for label_name, label in (("normal", 0), ("emergency", 1)):
        folder = root / label_name

        if not folder.is_dir():
            continue

        for path in sorted(folder.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            packets = payload if isinstance(payload, list) else [payload]

            for packet in packets:
                features = compute_feature_vector_from_packet(packet)
                features[TARGET] = label
                rows.append(features)
                counts[label_name] += 1

    if not rows:
        raise DatasetUnavailable(
            f"\nNo SensorPacket captures found under {root}.\n"
            f"  The folders exist but contain no .json files.\n"
        )

    provenance = {
        "dataset": "sensor_packets",
        "source": str(root.relative_to(BASE_DIR)),
        "is_synthetic": False,
        "is_production_evidence": True,
        "real_windows": len(rows),
        "packets_normal": counts["normal"],
        "packets_emergency": counts["emergency"],
        "caveat": (
            "Captured packets carry all five features with no cross-dataset "
            "fusion, so this is the highest-fidelity source. Generalisation "
            "still depends on how many distinct people, devices and "
            "situations were captured."
        )
    }

    return pd.DataFrame(rows, columns=COLUMNS), provenance


# ============================================================
# SisFall - the only corpus here with real falls
# ============================================================

def load_sisfall():
    """SisFall: 38 subjects, 19 ADLs + 15 fall types, accel+gyro at 200 Hz.

    Format (per the SisFall documentation): files named like
    D01_SA01_R01.txt (ADL) and F01_SA01_R01.txt (fall), comma-separated,
    first three columns are the ADXL345 axes as raw 13-bit counts at +/-16 g:

        acceleration_in_g = (2 * 16 / 2**13) * raw

    Provides: PeakAcceleration, MotionVariance, PossibleFall.
    Does NOT provide: AudioEnergy, GPSVelocity.
    """

    root = RAW_DIR / "sisfall"

    _require(
        root,
        "SisFall",
        "  Download the SisFall dataset and extract the per-subject folders\n"
        "  (SA01..SA23, SE01..SE15) into data/raw/sisfall/ so the tree is\n"
        "    data/raw/sisfall/SA01/D01_SA01_R01.txt\n"
        "    data/raw/sisfall/SA01/F01_SA01_R01.txt\n"
        "  NOTE: do not commit the archive - data/raw/ is gitignored."
    )

    adxl_scale_g = (2 * 16) / (2 ** 13)

    rows = []
    subjects = set()

    for path in sorted(root.rglob("*.txt")):
        kind = path.name[0].upper()

        if kind not in ("D", "F"):
            continue

        label = 1 if kind == "F" else 0

        frame = pd.read_csv(
            path,
            header=None,
            usecols=[0, 1, 2],
            names=["x", "y", "z"],
            sep=r"\s*,\s*",
            engine="python",
            comment=";"
        ).apply(pd.to_numeric, errors="coerce").dropna()

        if frame.empty:
            continue

        magnitudes = magnitudes_from_xyz(
            frame,
            scale=adxl_scale_g * GRAVITY_MPS2
        )

        magnitudes = resample_to_target_rate(magnitudes, source_rate_hz=200.0)

        for window in windows_from_magnitudes(magnitudes):
            row = features_from_window(
                window,
                audio_energy=np.nan,      # not in this corpus
                gps_velocity=np.nan
            )
            row[TARGET] = label
            rows.append(row)

        subjects.add(path.parent.name)

    if not rows:
        raise DatasetUnavailable(
            f"\nNo SisFall recordings parsed under {root}.\n"
            f"  Expected D*.txt / F*.txt files inside per-subject folders.\n"
        )

    provenance = {
        "dataset": "sisfall",
        "source": str(root.relative_to(BASE_DIR)),
        "is_synthetic": False,
        "is_production_evidence": True,
        "real_windows": len(rows),
        "subjects": len(subjects),
        "provides": ["PeakAcceleration", "MotionVariance", "PossibleFall"],
        "missing": ["AudioEnergy", "GPSVelocity"],
        "caveat": (
            "Waist-mounted sensor, staged falls by volunteers onto mats - "
            "not the same distribution as a phone in a pocket during a real "
            "incident. AudioEnergy and GPSVelocity are NaN and must be "
            "supplied by fusion or the feature set reduced."
        )
    }

    return pd.DataFrame(rows, columns=COLUMNS), provenance


# ============================================================
# UCI HAR - realistic negatives
# ============================================================

def load_uci_har():
    """UCI HAR: 30 subjects, waist-worn smartphone, 50 Hz - realistic negatives.

    Two distributions exist and this handles whichever is present:

    A) "Inertial Signals" - what UCI archive 240 actually ships, and what
       fetch_datasets.py downloads: total_acc_{x,y,z}_{train,test}.txt,
       already windowed into 128 samples (2.56 s) at 50 Hz with 50% overlap,
       in g, gravity included - the same quantity Android's
       TYPE_ACCELEROMETER reports. Ships subject_*.txt and y_*.txt, so
       subject IDs and activity labels come through.

    B) RawData/acc_exp*.txt - the HAPT distribution (archive 341):
       continuous recordings from which true 20 s windows can be cut.
       Preferred when present, because it matches the on-device window
       exactly.

    All six activities are ADLs, so EVERY window is a true NEGATIVE. That is
    precisely what the <5% false-positive target needs.

    CAVEAT for distribution A: windows are 2.56 s, not the 20 s the phone
    scores. PeakAcceleration carries over (a peak is a peak); MotionVariance
    does NOT - variance over 2.56 s of activity exceeds variance over 20 s of
    mostly-quiet history containing the same motion. Treat it as an upper
    bound.
    """

    root = RAW_DIR / "uci_har"

    _require(
        root,
        "UCI HAR",
        "  Download UCI archive 240 (Human Activity Recognition Using\n"
        "  Smartphones) and extract so that either tree exists:\n"
        "    data/raw/uci_har/UCI HAR Dataset/train/Inertial Signals/...\n"
        "    data/raw/uci_har/RawData/acc_exp01_user01.txt\n"
        "  `python phase5/fetch_datasets.py --dataset uci_har` does this."
    )

    raw_data = next(
        (path for path in root.rglob("RawData") if path.is_dir()),
        None
    )

    if raw_data is not None and any(raw_data.glob("acc_exp*.txt")):
        return _load_uci_har_rawdata(raw_data)

    return _load_uci_har_inertial(root)


def _load_uci_har_inertial(root):
    """Distribution A - the pre-windowed Inertial Signals."""

    signals_dirs = [
        path for path in root.rglob("Inertial Signals") if path.is_dir()
    ]

    if not signals_dirs:
        raise DatasetUnavailable(
            f"\nUCI HAR: neither RawData/ nor 'Inertial Signals/' found "
            f"under {root}.\n"
        )

    dataset_root = signals_dirs[0].parent.parent

    activity_names = {}
    labels_file = dataset_root / "activity_labels.txt"

    if labels_file.exists():
        for line in labels_file.read_text(encoding="utf-8").splitlines():
            parts = line.split()

            if len(parts) == 2:
                activity_names[int(parts[0])] = parts[1]

    rows = []
    subjects = set()
    activities = {}

    for split in ("train", "test"):
        signals = dataset_root / split / "Inertial Signals"

        if not signals.is_dir():
            continue

        try:
            axes = [
                np.loadtxt(signals / f"total_acc_{axis}_{split}.txt")
                for axis in ("x", "y", "z")
            ]
        except OSError:
            continue

        subject_ids = np.loadtxt(
            dataset_root / split / f"subject_{split}.txt",
            dtype=int
        )
        activity_ids = np.loadtxt(
            dataset_root / split / f"y_{split}.txt",
            dtype=int
        )

        # total_acc is in g and includes gravity, matching TYPE_ACCELEROMETER
        magnitudes = np.sqrt(
            sum(axis ** 2 for axis in axes)
        ) * GRAVITY_MPS2

        for index in range(len(magnitudes)):
            row = features_from_window(
                magnitudes[index],
                audio_energy=np.nan,
                gps_velocity=np.nan
            )

            row[TARGET] = 0
            row["Subject"] = f"S{int(subject_ids[index])}"

            activity = activity_names.get(
                int(activity_ids[index]),
                str(activity_ids[index])
            )

            row["Activity"] = activity
            activities[activity] = activities.get(activity, 0) + 1

            rows.append(row)
            subjects.add(int(subject_ids[index]))

    if not rows:
        raise DatasetUnavailable(
            f"\nUCI HAR: no Inertial Signals windows parsed under {root}.\n"
        )

    provenance = {
        "dataset": "uci_har",
        "distribution": "inertial_signals",
        "source": str(root.relative_to(BASE_DIR)),
        "citation": (
            "Anguita et al., A Public Domain Dataset for Human Activity "
            "Recognition Using Smartphones, ESANN 2013; UCI archive 240"
        ),
        "is_synthetic": False,
        "is_production_evidence": True,
        "real_windows": len(rows),
        "subjects": len(subjects),
        "activities": activities,
        "sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
        "window_samples": 128,
        "window_seconds": 2.56,
        "window_overlap": "50%",
        "provides": ["PeakAcceleration", "MotionVariance", "PossibleFall"],
        "missing": ["AudioEnergy", "GPSVelocity"],
        "caveat": (
            "NEGATIVES ONLY - all six activities are ADLs, so this cannot "
            "train a classifier alone, but it is exactly the right corpus "
            "for false-positive rate on ordinary activity. Windows are "
            "2.56 s with 50% overlap, not the 20 s the phone scores: "
            "PeakAcceleration carries over, MotionVariance is an upper "
            "bound. Waist-mounted, which is close to a trouser pocket."
        )
    }

    return pd.DataFrame(rows), provenance


def _load_uci_har_rawdata(raw):
    """Distribution B - continuous RawData, cut into true 20 s windows."""

    rows = []
    subjects = set()

    for path in sorted(raw.glob("acc_exp*.txt")):
        frame = pd.read_csv(
            path,
            sep=r"\s+",
            header=None,
            names=["x", "y", "z"]
        ).apply(pd.to_numeric, errors="coerce").dropna()

        if frame.empty:
            continue

        magnitudes = magnitudes_from_xyz(frame, scale=GRAVITY_MPS2)

        subject = path.stem.split("_")[-1]

        for window in windows_from_magnitudes(magnitudes):
            row = features_from_window(
                window,
                audio_energy=np.nan,
                gps_velocity=np.nan
            )
            row[TARGET] = 0
            row["Subject"] = subject
            row["Activity"] = "mixed_adl"
            rows.append(row)

        subjects.add(subject)

    if not rows:
        raise DatasetUnavailable(
            f"\nUCI HAR: no acc_exp*.txt parsed under {raw}.\n"
        )

    provenance = {
        "dataset": "uci_har",
        "distribution": "rawdata",
        "source": str(raw.relative_to(BASE_DIR)),
        "is_synthetic": False,
        "is_production_evidence": True,
        "real_windows": len(rows),
        "subjects": len(subjects),
        "sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
        "window_samples": WINDOW_SAMPLES,
        "window_seconds": WINDOW_SAMPLES / TARGET_SAMPLE_RATE_HZ,
        "provides": ["PeakAcceleration", "MotionVariance", "PossibleFall"],
        "missing": ["AudioEnergy", "GPSVelocity"],
        "caveat": (
            "NEGATIVES ONLY - all activities are ADLs. Continuous RawData "
            "cut into true 20 s windows, so these ARE device-comparable, "
            "including MotionVariance."
        )
    }

    return pd.DataFrame(rows), provenance

# ============================================================
# WISDM - additional negatives, but under-sampled
# ============================================================

def load_wisdm():
    """WISDM accelerometer activity data (phone in pocket).

    Sampled at 20 Hz, well below the ~50 Hz the phone runs at, so windows are
    upsampled before feature extraction. Interpolation cannot recreate the
    high-frequency content a real 50 Hz trace has, which biases
    PeakAcceleration and MotionVariance LOW. Treat WISDM-derived rows as a
    weaker negative source than UCI HAR.
    """

    root = RAW_DIR / "wisdm"

    _require(
        root,
        "WISDM",
        "  Place the WISDM raw activity file so the tree is\n"
        "    data/raw/wisdm/WISDM_ar_v1.1_raw.txt\n"
        "  (semicolon-terminated rows: user,activity,timestamp,x,y,z)."
    )

    candidates = sorted(root.glob("*raw*.txt"))

    if not candidates:
        raise DatasetUnavailable(
            f"\nNo WISDM raw .txt file found under {root}.\n"
        )

    frame = pd.read_csv(
        candidates[0],
        header=None,
        names=["user", "activity", "timestamp", "x", "y", "z"],
        on_bad_lines="skip"
    )

    # the z column carries a trailing ';' in the published file
    frame["z"] = pd.to_numeric(
        frame["z"].astype(str).str.rstrip(";"),
        errors="coerce"
    )
    frame["x"] = pd.to_numeric(frame["x"], errors="coerce")
    frame["y"] = pd.to_numeric(frame["y"], errors="coerce")
    frame = frame.dropna(subset=["x", "y", "z", "user"])

    rows = []

    for user, group in frame.groupby("user"):
        magnitudes = magnitudes_from_xyz(group)   # already m/s^2
        magnitudes = resample_to_target_rate(magnitudes, source_rate_hz=20.0)

        for window in windows_from_magnitudes(magnitudes):
            row = features_from_window(
                window,
                audio_energy=np.nan,
                gps_velocity=np.nan
            )
            row[TARGET] = 0
            rows.append(row)

    if not rows:
        raise DatasetUnavailable(f"\nNo usable WISDM rows parsed under {root}.\n")

    provenance = {
        "dataset": "wisdm",
        "source": str(candidates[0].relative_to(BASE_DIR)),
        "is_synthetic": False,
        "is_production_evidence": True,
        "real_windows": len(rows),
        "subjects": int(frame["user"].nunique()),
        "provides": ["PeakAcceleration", "MotionVariance", "PossibleFall"],
        "missing": ["AudioEnergy", "GPSVelocity"],
        "caveat": (
            "NEGATIVES ONLY, and recorded at 20 Hz then upsampled to 50 Hz. "
            "Upsampling cannot restore missing high-frequency content, so "
            "peak/variance are biased low relative to real device data."
        )
    }

    return pd.DataFrame(rows, columns=COLUMNS), provenance


# ============================================================
# RAVDESS - the audio half only
# ============================================================

def load_ravdess_audio_energy():
    """AudioEnergy distributions from RAVDESS, on the phone's own scale.

    RAVDESS filenames encode emotion in the third field, e.g.
    03-01-06-01-02-01-12.wav -> emotion 06 (fearful).

    Each clip is converted the way the device does it: mono, 16 kHz, PCM16,
    then RMS per read-chunk, then / 32768 (AudioBufferCollector.computeRms +
    FeatureExtractor.AUDIO_RMS_FULL_SCALE).

    Returns a DataFrame of AudioEnergy values with a distress flag. This does
    NOT produce trainable 5-feature rows on its own - it is the audio half of
    a fusion, and the reference distribution for the Task 3 audio validation.
    """

    root = RAW_DIR / "ravdess"

    _require(
        root,
        "RAVDESS",
        "  Place the RAVDESS speech audio so the tree is\n"
        "    data/raw/ravdess/Actor_01/03-01-06-01-02-01-01.wav\n"
        "  (Audio_Speech_Actors_01-24.zip, extracted)."
    )

    # emotion codes: 01 neutral 02 calm 03 happy 04 sad
    #                05 angry 06 fearful 07 disgust 08 surprised
    DISTRESS_EMOTIONS = {"05", "06", "07"}

    # AudioRecord read chunk is AudioRecord.getMinBufferSize(...); 1024
    # frames is a representative value for 16 kHz mono PCM16.
    CHUNK_FRAMES = 1024

    records = []

    for path in sorted(root.rglob("*.wav")):
        parts = path.stem.split("-")

        if len(parts) < 3:
            continue

        samples = read_wav_as_pcm16_mono_16k(path)

        for start in range(0, len(samples) - CHUNK_FRAMES + 1, CHUNK_FRAMES):
            chunk = samples[start:start + CHUNK_FRAMES]

            records.append({
                "AudioEnergy": round(pcm16_rms_to_audio_energy(chunk), 4),
                "AudioRmsEnergy": round(pcm16_rms(chunk), 2),
                "Emotion": parts[2],
                "IsDistress": parts[2] in DISTRESS_EMOTIONS,
                "Actor": path.parent.name
            })

    if not records:
        raise DatasetUnavailable(f"\nNo RAVDESS .wav files parsed under {root}.\n")

    provenance = {
        "dataset": "ravdess",
        "source": str(root.relative_to(BASE_DIR)),
        "is_synthetic": False,
        "is_production_evidence": False,
        "real_windows": len(records),
        "provides": ["AudioEnergy"],
        "missing": ["PeakAcceleration", "MotionVariance", "GPSVelocity", "PossibleFall"],
        "caveat": (
            "Studio-recorded acted emotion at close mic distance. Real "
            "pocket-muffled audio at unknown distance will sit far lower on "
            "the same scale, so this bounds the LOUD end only - it is not a "
            "substitute for on-device measurement."
        )
    }

    return pd.DataFrame(records), provenance


# ============================================================
# ShimFall&ADL - real falls AND real ADLs, at the device's 50 Hz
#
# Replaces SisFall, whose host (sistemic.udea.edu.co) is unreachable.
# ============================================================

# Gravity in this dataset's units, measured from its own near-static postures
# (see _shimfall_gravity_reference). A chest-strapped accelerometer at rest
# reads exactly 1 g, so the median magnitude of sitting/lying/standing IS the
# dataset's representation of 1 g. Recomputed at load time, never hardcoded.
SHIMFALL_STATIC_CLASSES = (
    "adl_sittingonchair",
    "adl_liedown",
    "adl_standingfromchair"
)

SHIMFALL_SAMPLE_RATE_HZ = 50.0
SHIMFALL_SAMPLES_PER_EVENT = 101


def _shimfall_load_dat(path):
    rows = []

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()

        if len(parts) == 3:
            try:
                rows.append([float(part) for part in parts])
            except ValueError:
                continue

    return np.asarray(rows, dtype=float)


def _shimfall_gravity_reference(root):
    """What '1 g' equals in this dataset's undocumented units.

    The depositors state the sensor, the rate and the layout, but NOT the
    units - the raw magnitudes sit around 35, which is neither m/s^2 (9.81)
    nor g (1.0). Rather than guess a scale factor, it is derived from
    physics: a body-worn accelerometer held still measures exactly 1 g, so
    the median magnitude across the near-static postures is 1 g expressed in
    whatever units the file uses.

    Returns (gravity_in_dataset_units, number_of_files_used).
    """

    medians = []

    for activity in SHIMFALL_STATIC_CLASSES:
        for path in sorted(root.glob(f"{activity}_*.dat")):
            samples = _shimfall_load_dat(path)

            if samples.size:
                medians.append(
                    float(np.median(np.sqrt((samples ** 2).sum(axis=1))))
                )

    if not medians:
        raise DatasetUnavailable(
            f"\nShimFall: no static-posture files under {root}, so the unit "
            f"scale cannot be derived. Expected e.g. adl_sittingonchair_1.dat\n"
        )

    return float(np.median(medians)), len(medians)


def load_shimfall():
    """ShimFall&ADL: 35 subjects, chest Shimmer v2, 50 Hz, 101 samples/event.

    Zenodo record 3901285, CC-BY-NC-ND-4.0. Cite:
      T. Althobaiti, S. Katsigiannis, N. Ramzan, Sensors 20(13), 3777, 2020.

    Provides: PeakAcceleration, MotionVariance, PossibleFall, and a real
    Emergency label (9 fall types vs 6 ADLs).
    Does NOT provide: AudioEnergy, GPSVelocity.

    TWO CAVEATS THAT LIMIT WHAT THIS CAN PROVE
    ------------------------------------------
    1. Units are undocumented and are recovered from the data's own static
       postures (see _shimfall_gravity_reference). Physically sound, but an
       inference - it is recorded in provenance so it can be challenged.

    2. Each event is 101 samples = 2.02 s, while the phone scores a window of
       up to 1000 samples = 20 s. PeakAcceleration survives that difference
       (a peak is a peak), but MotionVariance does NOT: variance over a 2 s
       burst is far higher than over 20 s of mostly-quiet history containing
       the same burst. Treat ShimFall MotionVariance as an UPPER BOUND, not
       as a device-comparable value.
    """

    root = RAW_DIR / "shimfall"

    _require(
        root,
        "ShimFall&ADL",
        "  Download Data.zip from https://zenodo.org/records/3901285 and\n"
        "  extract the .dat files directly into data/raw/shimfall/ so the\n"
        "  tree is\n"
        "    data/raw/shimfall/adl_walk_1.dat\n"
        "    data/raw/shimfall/frontfall_hard_1.dat\n"
        "  License CC-BY-NC-ND-4.0 - academic use, do not redistribute."
    )

    gravity_units, static_files = _shimfall_gravity_reference(root)
    scale = GRAVITY_MPS2 / gravity_units

    rows = []
    subjects = set()
    activities = {}

    for path in sorted(root.glob("*.dat")):
        stem = path.stem

        # adl_<activity>_<subject>.dat | <type>fall_<soft|hard>_<subject>.dat
        parts = stem.rsplit("_", 1)

        if len(parts) != 2 or not parts[1].isdigit():
            continue

        activity, subject = parts[0], parts[1]
        label = 0 if activity.startswith("adl_") else 1

        samples = _shimfall_load_dat(path)

        if samples.size == 0:
            continue

        magnitudes = np.sqrt((samples ** 2).sum(axis=1)) * scale

        # already 50 Hz - no resampling, so no interpolation artefacts
        for window in windows_from_magnitudes(magnitudes):
            row = features_from_window(
                window,
                audio_energy=np.nan,
                gps_velocity=np.nan
            )
            row[TARGET] = label
            row["Subject"] = f"P{subject}"
            row["Activity"] = activity
            rows.append(row)

        subjects.add(subject)
        activities[activity] = activities.get(activity, 0) + 1

    if not rows:
        raise DatasetUnavailable(
            f"\nNo ShimFall .dat files parsed under {root}.\n"
        )

    frame = pd.DataFrame(rows)

    provenance = {
        "dataset": "shimfall",
        "source": str(root.relative_to(BASE_DIR)),
        "citation": (
            "Althobaiti, Katsigiannis, Ramzan, Sensors 20(13) 3777, 2020; "
            "Zenodo 3901285; CC-BY-NC-ND-4.0"
        ),
        "is_synthetic": False,
        "is_production_evidence": True,
        "real_windows": len(rows),
        "subjects": len(subjects),
        "activities": activities,
        "sample_rate_hz": SHIMFALL_SAMPLE_RATE_HZ,
        "samples_per_event": SHIMFALL_SAMPLES_PER_EVENT,
        "event_duration_s": round(
            SHIMFALL_SAMPLES_PER_EVENT / SHIMFALL_SAMPLE_RATE_HZ, 3
        ),
        "provides": ["PeakAcceleration", "MotionVariance", "PossibleFall"],
        "missing": ["AudioEnergy", "GPSVelocity"],
        "units_calibration": {
            "documented_by_depositors": False,
            "method": (
                "1 g recovered as the median magnitude of near-static "
                "postures (sitting/lying/standing-from-chair)"
            ),
            "gravity_in_dataset_units": round(gravity_units, 4),
            "static_files_used": static_files,
            "scale_to_mps2": round(scale, 6)
        },
        "caveat": (
            "Chest-strapped sensor, staged falls in a lab - not a phone in a "
            "pocket during a real incident. Units are INFERRED from static "
            "postures, not documented. Events are 2.02 s while the phone "
            "scores up to 20 s, so MotionVariance is an upper bound and is "
            "NOT device-comparable; PeakAcceleration is."
        )
    }

    return frame, provenance


# ============================================================
# Registry
# ============================================================

LOADERS = {
    "shimfall": load_shimfall,
    "synthetic": load_synthetic,
    "sensor_packets": load_sensor_packets,
    "sisfall": load_sisfall,
    "uci_har": load_uci_har,
    "wisdm": load_wisdm
}

# Not in LOADERS: it yields AudioEnergy only, not trainable 5-feature rows.
AUDIO_LOADERS = {
    "ravdess": load_ravdess_audio_energy
}


def available_datasets():
    """Which registered datasets can actually be loaded right now."""

    status = {}

    for name, loader in LOADERS.items():
        try:
            data, provenance = loader()
            status[name] = {
                "available": True,
                "rows": len(data),
                "is_synthetic": provenance["is_synthetic"]
            }
        except DatasetUnavailable:
            status[name] = {"available": False, "rows": 0, "is_synthetic": None}
        except Exception as error:                      # noqa: BLE001
            status[name] = {"available": False, "error": str(error)}

    return status


def load_dataset(name):
    """Load one registered dataset. Raises DatasetUnavailable if absent."""

    if name not in LOADERS:
        raise KeyError(
            f"Unknown dataset '{name}'. Registered: {sorted(LOADERS)}"
        )

    data, provenance = LOADERS[name]()

    missing = [column for column in COLUMNS if column not in data.columns]

    if missing:
        raise ValueError(
            f"adapter '{name}' returned columns {list(data.columns)}, "
            f"missing {missing}"
        )

    # Carry Subject/Activity through when the loader supplied them, so
    # training can split by subject instead of leaking across overlapping
    # windows from the same person.
    present_metadata = [
        column for column in METADATA_COLUMNS if column in data.columns
    ]

    return data[COLUMNS + present_metadata], provenance


def load_combined(names):
    """Concatenate several datasets, keeping a provenance record for each.

    Fusing corpora that measure different things (motion from one, audio from
    another) assumes those channels are independent, which is a real modelling
    decision - it is recorded in provenance rather than hidden.
    """

    frames = []
    provenances = []

    for name in names:
        data, provenance = load_dataset(name)
        frames.append(data)
        provenances.append(provenance)

    combined = pd.concat(frames, ignore_index=True)

    return combined, {
        "dataset": "+".join(names),
        "is_synthetic": all(item["is_synthetic"] for item in provenances),
        "is_production_evidence": all(
            item.get("is_production_evidence", False) for item in provenances
        ),
        "components": provenances,
        "caveat": (
            "Combined from multiple corpora. Any feature that one component "
            "does not measure arrives as NaN and must be handled explicitly "
            "before training."
        )
    }


if __name__ == "__main__":
    print("\nDATASET AVAILABILITY")
    print("=" * 60)

    for name, status in available_datasets().items():
        mark = "available" if status["available"] else "NOT PRESENT"
        extra = f"  rows={status['rows']}" if status["available"] else ""
        print(f"  {name:16s} {mark}{extra}")

    print("\nAudio-only sources:")

    for name, loader in AUDIO_LOADERS.items():
        try:
            records, _ = loader()
            print(f"  {name:16s} available  rows={len(records)}")
        except DatasetUnavailable:
            print(f"  {name:16s} NOT PRESENT")

    print("\nSee xai-engine/DATA_REQUIREMENTS.md for what to supply.")
