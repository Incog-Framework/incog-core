"""SessionID / TimestampMs must survive Phase 4 -> Phase 7.

A decision, an explanation, or a piece of evidence that cannot be tied back
to the Ghost State session it came from is much less useful downstream, so
this suite runs the pipeline end to end in BOTH modes and checks every
artifact:

    packet mode  ->  session context present everywhere it belongs
    csv mode     ->  session context absent everywhere (no session exists)

The CSV half matters as much as the packet half: a stale session_context.json
left over from an earlier packet run must never get attached to a CSV-sourced
decision.

Slow - it invokes the real pipeline (TensorFlow, SHAP, LIME) twice.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

EXAMPLE_PACKET = DATA_DIR / "sensor_packet.json"

# Artifacts that must carry session context on the packet path.
# (filename, key for the id, key for the timestamp)
SESSION_AWARE_ARTIFACTS = [
    ("session_context.json", "SessionID", "TimestampMs"),
    ("decision.json", "SessionID", "TimestampMs"),
    ("xai_output.json", "SessionID", "TimestampMs"),
    ("human_explanation.json", "SessionID", "TimestampMs"),
    ("intervention.json", "SessionID", "SessionTimestampMs"),
    ("final_system_report.json", "SessionID", "SessionTimestampMs"),
    (
        Path("forensic_evidence") / "evidence_manifest.json",
        "SessionID",
        "SessionTimestampMs"
    )
]


def read(relative):
    return json.loads((DATA_DIR / relative).read_text(encoding="utf-8"))


def run(command):
    result = subprocess.run(
        [sys.executable, *command],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise AssertionError(
            f"{' '.join(command)} failed:\n"
            f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}"
        )


def run_phase7_tail():
    """Intervention -> forensics -> report, the artifacts the pipeline omits."""

    run(["phase7/intervention.py"])
    run(["phase7/forensics.py"])
    run(["phase7/generate_report.py"])


# ============================================================
# Packet path
# ============================================================

def test_packet_path_propagates_session_to_every_phase7_artifact():
    run(["run_ai_pipeline.py", "--source", "packet", "--skip-visualizations"])
    run_phase7_tail()

    expected = read("session_context.json")

    session_id = expected["SessionID"]
    timestamp = expected["TimestampMs"]

    assert isinstance(session_id, str) and session_id
    assert isinstance(timestamp, int)

    for artifact, id_key, timestamp_key in SESSION_AWARE_ARTIFACTS:
        document = read(artifact)

        assert id_key in document, f"{artifact} lost {id_key}"

        assert document[id_key] == session_id, (
            f"{artifact}: {id_key}={document[id_key]!r}, "
            f"expected {session_id!r}"
        )

        assert document[timestamp_key] == timestamp, (
            f"{artifact}: {timestamp_key}={document[timestamp_key]!r}, "
            f"expected {timestamp}"
        )


def test_explicit_packet_argument_overrides_the_default():
    """--packet PATH is what points the pipeline at a real capture."""

    source = json.loads(EXAMPLE_PACKET.read_text(encoding="utf-8"))
    source["sessionId"] = "SESS-OVERRIDE01"
    source["timestampMs"] = 1_711_111_111_111

    with tempfile.TemporaryDirectory() as folder:
        capture = Path(folder) / "override_capture.json"
        capture.write_text(json.dumps(source), encoding="utf-8")

        run([
            "run_ai_pipeline.py",
            "--packet", str(capture),
            "--skip-visualizations"
        ])
        run_phase7_tail()

    for artifact, id_key, timestamp_key in SESSION_AWARE_ARTIFACTS:
        document = read(artifact)

        assert document[id_key] == "SESS-OVERRIDE01", (
            f"{artifact} did not pick up the --packet capture"
        )
        assert document[timestamp_key] == 1_711_111_111_111


def test_packet_array_capture_is_accepted():
    """A session export is naturally an array of 2 s snapshots."""

    source = json.loads(EXAMPLE_PACKET.read_text(encoding="utf-8"))

    first = dict(source, sessionId="SESS-ARRAY001")
    second = dict(source, sessionId="SESS-ARRAY002")

    with tempfile.TemporaryDirectory() as folder:
        capture = Path(folder) / "array_capture.json"
        capture.write_text(json.dumps([first, second]), encoding="utf-8")

        run(["phase4/process_sensor_packet.py", "--packet", str(capture)])

    # the single-shot pipeline scores the first packet, like the phone
    # scoring one 2 s snapshot
    assert read("session_context.json")["SessionID"] == "SESS-ARRAY001"


# ============================================================
# CSV path
# ============================================================

def test_csv_path_carries_no_session_anywhere():
    # seed a stale context first: the CSV path must clear it, not inherit it
    run(["run_ai_pipeline.py", "--source", "packet", "--skip-visualizations"])

    assert (DATA_DIR / "session_context.json").exists()

    run(["run_ai_pipeline.py", "--source", "csv", "--skip-visualizations"])
    run_phase7_tail()

    assert not (DATA_DIR / "session_context.json").exists(), (
        "the CSV path must remove a stale session_context.json, not leave a "
        "previous session attached to a CSV-sourced decision"
    )

    for artifact, id_key, timestamp_key in SESSION_AWARE_ARTIFACTS[1:]:
        document = read(artifact)

        assert id_key not in document, (
            f"{artifact} carries {id_key} on the CSV path, where no session "
            f"exists"
        )
        assert timestamp_key not in document


# ============================================================
# Mode switching must not change the AI logic
# ============================================================

def test_switching_input_mode_does_not_change_thresholds_or_model():
    """Only the feature source changes between modes - nothing downstream."""

    run(["run_ai_pipeline.py", "--source", "packet", "--skip-visualizations"])
    packet_decision = read("decision.json")
    packet_xai = read("xai_output.json")

    run(["run_ai_pipeline.py", "--source", "csv", "--skip-visualizations"])
    csv_decision = read("decision.json")
    csv_xai = read("xai_output.json")

    assert packet_decision["Threshold"] == csv_decision["Threshold"] == 0.80

    assert (
        packet_xai["DecisionThreshold"] == csv_xai["DecisionThreshold"] == 0.80
    )

    # both modes produce the same document shape, session keys aside
    ignore = {"SessionID", "TimestampMs"}

    assert set(packet_xai) - ignore == set(csv_xai) - ignore, (
        "the two input modes produced different XAI document shapes"
    )


def test_restore_packet_mode_artifacts():
    """Leave the repo in packet-mode state, the pipeline default."""

    run(["run_ai_pipeline.py", "--source", "packet", "--skip-visualizations"])
    run_phase7_tail()

    assert "SessionID" in read("decision.json")


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_packet_path_propagates_session_to_every_phase7_artifact,
        test_explicit_packet_argument_overrides_the_default,
        test_packet_array_capture_is_accepted,
        test_csv_path_carries_no_session_anywhere,
        test_switching_input_mode_does_not_change_thresholds_or_model,
        test_restore_packet_mode_artifacts
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
