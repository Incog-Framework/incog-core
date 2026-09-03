"""Architectural guard: the adapter is the ONLY Android -> AI interface.

Every Kotlin field name (`sessionId`, `accelSamples`, `audioRmsEnergy`, ...)
must appear in exactly one production module: sensor_packet_adapter.py. If a
second module starts reading raw packet fields, a schema change on Aarush's
side stops being a one-file fix and the contract quietly develops two owners.

This is enforced by scanning source text rather than by convention, so it
cannot be forgotten.

Allowed to mention the field names:
  * sensor_packet_adapter.py  - the interface itself
  * test files                - they construct packets as fixtures
  * generate_contract_fixtures.py / validate_audio_normalization.py
                              - they build packets to feed THROUGH the adapter
  * dataset_adapters.py       - prose only; asserted below
"""

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE_DIR / "phase4"))

from sensor_packet_adapter import PACKET_SCHEMA   # noqa: E402

ADAPTER = BASE_DIR / "phase4" / "sensor_packet_adapter.py"

# Modules that legitimately build packet dicts to pass INTO the adapter.
FIXTURE_BUILDERS = {
    "generate_contract_fixtures.py",
    "validate_audio_normalization.py",
    "dataset_adapters.py"
}

# Field names distinctive enough that finding one means packet parsing.
# "timestampMs" is excluded: it also appears in unrelated contexts.
PACKET_FIELDS = sorted(
    field
    for field in PACKET_SCHEMA
    if field != "timestampMs"
)


def production_modules():
    """Every .py in the module except tests and the adapter itself."""

    for path in sorted(BASE_DIR.rglob("*.py")):
        if path.name.startswith("test_"):
            continue

        if path == ADAPTER:
            continue

        if "__pycache__" in path.parts:
            continue

        yield path


def strip_docs_and_comments(source):
    """Drop docstrings and comments, but KEEP ordinary string literals.

    Packet parsing looks like `packet["accelSamples"]` - the field name IS a
    string literal, so stripping literals would erase exactly what this guard
    hunts for. Only prose (docstrings, comments) is removed, since a field
    name mentioned there is documentation rather than parsing.
    """

    source = re.sub(r'"""(?:.|\n)*?"""', "", source)
    source = re.sub(r"'''(?:.|\n)*?'''", "", source)
    source = re.sub(r"#[^\n]*", "", source)

    return source


# ============================================================
# The guard
# ============================================================

def test_no_production_module_parses_raw_packet_fields():
    offenders = []

    for path in production_modules():
        if path.name in FIXTURE_BUILDERS:
            continue

        code = strip_docs_and_comments(
            path.read_text(encoding="utf-8")
        )

        found = [field for field in PACKET_FIELDS if field in code]

        if found:
            offenders.append(
                f"{path.relative_to(BASE_DIR)} references {found}"
            )

    assert not offenders, (
        "these modules read raw SensorPacket fields directly; route them "
        "through phase4/sensor_packet_adapter.py instead:\n  "
        + "\n  ".join(offenders)
    )


def test_fixture_builders_only_construct_packets_never_parse_them():
    """They may build packet dicts, but must not extract features by hand.

    Matched precisely on a `packet[...]` / `packet.get(...)` access rather
    than on the bare field name: these modules legitimately read back their
    OWN result records, which happen to reuse the same keys.
    """

    accessor = re.compile(
        r"packets?\s*(?:\[\s*[\"'](\w+)[\"']\s*\]|\.get\(\s*[\"'](\w+)[\"'])"
    )

    for name in FIXTURE_BUILDERS:
        matches = list(BASE_DIR.rglob(name))

        if not matches:
            continue

        code = strip_docs_and_comments(
            matches[0].read_text(encoding="utf-8")
        )

        accessed = {
            field
            for match in accessor.finditer(code)
            for field in match.groups()
            if field
        }

        assert not accessed, (
            f"{name} reads packet[{sorted(accessed)}] directly - feature "
            f"extraction belongs in sensor_packet_adapter.py"
        )


def test_only_the_adapter_defines_the_schema():
    """PACKET_SCHEMA must have exactly one definition."""

    definitions = [
        path.relative_to(BASE_DIR)
        for path in BASE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
        and re.search(
            r"^PACKET_SCHEMA\s*=",
            path.read_text(encoding="utf-8"),
            re.MULTILINE
        )
    ]

    assert definitions == [Path("phase4") / "sensor_packet_adapter.py"], (
        f"PACKET_SCHEMA is defined in {definitions}; it must live only in "
        f"the adapter"
    )


def test_adapter_exposes_the_full_interface():
    """Everything downstream needs, without touching raw fields."""

    import sensor_packet_adapter as adapter

    for name in (
        "validate_packet",
        "compute_feature_vector_from_packet",
        "session_context_from_packet",
        "extract_from_sensor_packet",
        "load_packet",
        "load_packets",
        "PACKET_SCHEMA",
        "AUDIO_RMS_FULL_SCALE"
    ):
        assert hasattr(adapter, name), f"adapter is missing {name}"


def test_phase4_entry_point_uses_only_adapter_functions():
    """process_sensor_packet.py is the integration entry point."""

    code = (BASE_DIR / "phase4" / "process_sensor_packet.py").read_text(
        encoding="utf-8"
    )

    assert "from sensor_packet_adapter import" in code

    stripped = strip_docs_and_comments(code)

    for field in PACKET_FIELDS:
        assert field not in stripped, (
            f"process_sensor_packet.py reads packet['{field}'] directly; use "
            f"the adapter's helpers"
        )


# ============================================================
# Runner (no pytest dependency required)
# ============================================================

if __name__ == "__main__":
    tests = [
        test_no_production_module_parses_raw_packet_fields,
        test_fixture_builders_only_construct_packets_never_parse_them,
        test_only_the_adapter_defines_the_schema,
        test_adapter_exposes_the_full_interface,
        test_phase4_entry_point_uses_only_adapter_functions
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
