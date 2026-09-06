"""Tests for the dataset layer.

Real-corpus tests skip cleanly when the data is not present, so this suite is
useful in a fresh clone and does real work once
`python phase5/fetch_datasets.py` has run.

Writes nothing to disk.
"""

import sys
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "phase5"))
sys.path.insert(0, str(BASE_DIR / "phase4"))

from dataset_adapters import (              # noqa: E402
    AUDIO_RMS_FULL_SCALE,
    COLUMNS,
    DatasetUnavailable,
    FEATURE_ORDER,
    GRAVITY_MPS2,
    LOADERS,
    METADATA_COLUMNS,
    TARGET,
    TARGET_SAMPLE_RATE_HZ,
    WINDOW_SAMPLES,
    available_datasets,
    features_from_window,
    load_dataset,
    pcm16_rms_to_audio_energy,
    resample_to_target_rate,
    windows_from_magnitudes
)

# Corpora that carry a real Emergency label of each class.
LABELLED = ("shimfall",)
NEGATIVE_ONLY = ("uci_har", "wisdm")


def _available(name):
    return available_datasets().get(name, {}).get("available", False)


def _skip(name):
    print(f"    SKIP - {name} not fetched (python phase5/fetch_datasets.py)")


# ============================================================
# Windowing / feature helpers
# ============================================================

def test_window_geometry_matches_the_device():
    assert WINDOW_SAMPLES == 1000
    assert TARGET_SAMPLE_RATE_HZ == 50.0
    # 1000 samples at 50 Hz = the 20 s rolling history in SensorCollector
    assert WINDOW_SAMPLES / TARGET_SAMPLE_RATE_HZ == 20.0


def test_short_recording_still_yields_one_window():
    """The phone scores a not-yet-full buffer early in a session."""

    windows = list(windows_from_magnitudes(np.ones(50)))

    assert len(windows) == 1
    assert len(windows[0]) == 50


def test_long_recording_is_windowed_at_the_device_stride():
    windows = list(windows_from_magnitudes(np.ones(1200)))

    assert all(len(window) == WINDOW_SAMPLES for window in windows)
    # 1200 samples, 1000-wide, stride 100 -> starts at 0 and 100
    assert len(windows) == 3


def test_empty_series_yields_nothing():
    assert list(windows_from_magnitudes(np.array([]))) == []


def test_resampling_preserves_duration_not_sample_count():
    # 2 s at 20 Hz -> 2 s at 50 Hz
    resampled = resample_to_target_rate(np.ones(40), source_rate_hz=20.0)

    assert len(resampled) == 100


def test_resampling_is_a_noop_at_the_target_rate():
    original = np.arange(10, dtype=float)
    resampled = resample_to_target_rate(original, source_rate_hz=50.0)

    assert np.array_equal(original, resampled)


def test_features_from_window_uses_the_phase4_definitions():
    """Peak, ddof=1 variance and the >15 fall rule, same as on-device."""

    row = features_from_window(
        np.array([3.0, 5.0]),
        audio_energy=0.25,
        gps_velocity=1.0
    )

    assert row["PeakAcceleration"] == 5.0
    assert row["MotionVariance"] == 2.0        # ddof=1, not 1.0
    assert row["PossibleFall"] is False

    assert features_from_window(
        np.array([16.0]), 0.0, 0.0
    )["PossibleFall"] is True

    # exactly 15 is NOT a fall
    assert features_from_window(
        np.array([15.0]), 0.0, 0.0
    )["PossibleFall"] is False


def test_audio_mapping_matches_the_device_formula():
    assert pcm16_rms_to_audio_energy(np.zeros(16)) == 0.0
    assert pcm16_rms_to_audio_energy(
        np.full(16, -AUDIO_RMS_FULL_SCALE)
    ) == 1.0


# ============================================================
# Registry contract
# ============================================================

def test_every_loader_is_callable_or_raises_dataset_unavailable():
    for name, loader in LOADERS.items():
        try:
            frame, provenance = loader()
        except DatasetUnavailable as error:
            # the whole point: an absent corpus must say what to supply
            assert str(error).strip(), f"{name} raised an empty message"
            continue

        for column in COLUMNS:
            assert column in frame.columns, f"{name} missing {column}"

        for key in ("dataset", "is_synthetic", "caveat"):
            assert key in provenance, f"{name} provenance missing {key}"


def test_unknown_dataset_name_is_rejected_clearly():
    try:
        load_dataset("not_a_real_dataset")
    except KeyError as error:
        assert "Registered" in str(error)
        return

    raise AssertionError("expected KeyError for an unknown dataset")


def test_synthetic_is_flagged_as_not_production_evidence():
    _, provenance = load_dataset("synthetic")

    assert provenance["is_synthetic"] is True
    assert provenance.get("is_production_evidence") is False


# ============================================================
# Real corpora
# ============================================================

def test_shimfall_has_both_classes_and_real_subjects():
    if not _available("shimfall"):
        _skip("shimfall")
        return

    frame, provenance = load_dataset("shimfall")

    assert provenance["is_synthetic"] is False
    assert set(frame[TARGET].unique()) == {0, 1}
    assert provenance["subjects"] >= 30
    assert provenance["sample_rate_hz"] == 50.0

    # units were inferred, and that must be recorded rather than hidden
    calibration = provenance["units_calibration"]
    assert calibration["documented_by_depositors"] is False
    assert 0.1 < calibration["scale_to_mps2"] < 1.0


def test_shimfall_calibration_puts_gravity_where_physics_says():
    """After scaling, a near-static posture must read about 1 g."""

    if not _available("shimfall"):
        _skip("shimfall")
        return

    frame, _ = load_dataset("shimfall")

    static = frame[frame["Activity"] == "adl_sittingonchair"]

    if not len(static):
        _skip("shimfall static postures")
        return

    median_peak = float(static["PeakAcceleration"].median())

    # a seated person peaks somewhat above 1 g but nowhere near a fall
    assert GRAVITY_MPS2 * 0.8 < median_peak < GRAVITY_MPS2 * 2.0, median_peak


def test_uci_har_is_negatives_only_with_subjects_and_activities():
    if not _available("uci_har"):
        _skip("uci_har")
        return

    frame, provenance = load_dataset("uci_har")

    assert set(frame[TARGET].unique()) == {0}, "UCI HAR is ADLs only"
    assert provenance["is_synthetic"] is False
    assert provenance["subjects"] >= 20

    for column in ("Subject", "Activity"):
        assert column in frame.columns


def test_real_corpora_leave_unmeasured_channels_as_nan():
    """Audio/GPS must be NaN, never quietly imputed."""

    for name in LABELLED + NEGATIVE_ONLY:
        if not _available(name):
            continue

        frame, provenance = load_dataset(name)

        assert frame["AudioEnergy"].isna().all(), (
            f"{name} invented an AudioEnergy value"
        )
        assert frame["GPSVelocity"].isna().all(), (
            f"{name} invented a GPSVelocity value"
        )
        assert "AudioEnergy" in provenance["missing"]


def test_metadata_columns_survive_load_dataset():
    if not _available("uci_har"):
        _skip("uci_har")
        return

    frame, _ = load_dataset("uci_har")

    kept = [column for column in METADATA_COLUMNS if column in frame.columns]

    assert kept, (
        "Subject/Activity were dropped; subject-level splitting depends on them"
    )


def test_real_peaks_are_physically_plausible():
    """A sanity check on the unit conversions across every real corpus."""

    for name in LABELLED + NEGATIVE_ONLY:
        if not _available(name):
            continue

        frame, _ = load_dataset(name)

        peaks = frame["PeakAcceleration"]

        # nothing below a resting reading, nothing beyond ~10 g
        assert peaks.min() >= 0.0, name
        assert peaks.median() > 5.0, (
            f"{name} median peak {peaks.median()} is below resting gravity - "
            f"values are probably in g rather than m/s^2"
        )
        assert peaks.max() < 10 * GRAVITY_MPS2, (
            f"{name} max peak {peaks.max()} exceeds 10 g - unit conversion "
            f"is probably wrong"
        )


def test_fusion_pairs_real_motion_with_ravdess_audio_and_flags_it_honestly():
    """The fused dataset must never be silently mistaken for a real capture.

    RAVDESS is not tracked by available_datasets() (it lives in
    AUDIO_LOADERS, not LOADERS - it yields audio only, not trainable 5-feature
    rows on its own), so this cannot be gated with _available("ravdess") - it
    would always read False and the test would always skip. Attempt the load
    and only skip on the exception the loaders actually raise.
    """

    try:
        frame, provenance = load_dataset("fusion")
    except DatasetUnavailable:
        _skip("fusion (needs uci_har + shimfall + ravdess)")
        return

    assert not frame[FEATURE_ORDER].isna().any().any(), (
        "fusion rows must have every feature populated - that is the point"
    )
    assert set(frame[TARGET].unique()) == {0, 1}

    # the pairing is constructed, not observed - this must never read True
    assert provenance["is_production_evidence"] is False
    assert provenance["is_synthetic"] is False
    assert "fusion_method" in provenance

    # AudioEnergy must actually separate by label, or the fusion did nothing
    by_label = frame.groupby(TARGET)["AudioEnergy"].median()
    assert by_label[1] > by_label[0], (
        "Emergency rows should skew toward RAVDESS distress audio"
    )


def test_fusion_gps_velocity_is_not_correlated_with_the_label():
    """Aarush, 2026-09-06: an activity-keyed GPS heuristic taught the model
    'moving fast = not an emergency', which would suppress the alert exactly
    when someone is fleeing at speed. GPSVelocity must carry no signal about
    the label until real GPS+incident captures exist - this pins that down
    as a regression test, not just a comment.
    """

    try:
        frame, _ = load_dataset("fusion")
    except DatasetUnavailable:
        _skip("fusion (needs uci_har + shimfall + ravdess)")
        return

    by_label = frame.groupby(TARGET)["GPSVelocity"].mean()

    assert abs(by_label[1] - by_label[0]) < 0.3, (
        f"GPSVelocity means differ by label (Normal={by_label[0]:.3f}, "
        f"Emergency={by_label[1]:.3f}) - this would let the model use GPS "
        f"as an emergency/normal signal, which is the exact bug being "
        f"guarded against"
    )


def test_feature_order_is_stable_across_every_corpus():
    for name in LOADERS:
        if not _available(name):
            continue

        frame, _ = load_dataset(name)

        assert list(frame.columns)[:len(FEATURE_ORDER)] == FEATURE_ORDER, name


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_window_geometry_matches_the_device,
        test_short_recording_still_yields_one_window,
        test_long_recording_is_windowed_at_the_device_stride,
        test_empty_series_yields_nothing,
        test_resampling_preserves_duration_not_sample_count,
        test_resampling_is_a_noop_at_the_target_rate,
        test_features_from_window_uses_the_phase4_definitions,
        test_audio_mapping_matches_the_device_formula,
        test_every_loader_is_callable_or_raises_dataset_unavailable,
        test_unknown_dataset_name_is_rejected_clearly,
        test_synthetic_is_flagged_as_not_production_evidence,
        test_shimfall_has_both_classes_and_real_subjects,
        test_shimfall_calibration_puts_gravity_where_physics_says,
        test_uci_har_is_negatives_only_with_subjects_and_activities,
        test_real_corpora_leave_unmeasured_channels_as_nan,
        test_metadata_columns_survive_load_dataset,
        test_fusion_pairs_real_motion_with_ravdess_audio_and_flags_it_honestly,
        test_fusion_gps_velocity_is_not_correlated_with_the_label,
        test_real_peaks_are_physically_plausible,
        test_feature_order_is_stable_across_every_corpus
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            print(f"PASS - {test.__name__}")
            passed += 1
        except Exception as error:
            print(f"FAIL - {test.__name__}: {error}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")

    if failed:
        raise SystemExit(1)
