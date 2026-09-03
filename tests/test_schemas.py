"""Validation rules for the SOS payload."""

import pytest
from pydantic import ValidationError

from schemas import SignalRecord, SOSPayload, SOSResponse


def valid_payload(**overrides):
    base = {
        "device_id": "demo-device-01",
        "latitude": 12.9412,
        "longitude": 77.5652,
        "is_stealth_active": True,
    }
    base.update(overrides)
    return base


def test_accepts_a_well_formed_payload():
    payload = SOSPayload(**valid_payload())
    assert payload.device_id == "demo-device-01"
    assert payload.encrypted_evidence is None


def test_evidence_is_optional():
    payload = SOSPayload(**valid_payload(encrypted_evidence="QUJD"))
    assert payload.encrypted_evidence == "QUJD"


@pytest.mark.parametrize("latitude", [90.0, -90.0, 0.0])
def test_accepts_latitude_bounds(latitude):
    assert SOSPayload(**valid_payload(latitude=latitude)).latitude == latitude


@pytest.mark.parametrize("latitude", [90.1, -90.1, 1000.0])
def test_rejects_out_of_range_latitude(latitude):
    with pytest.raises(ValidationError):
        SOSPayload(**valid_payload(latitude=latitude))


@pytest.mark.parametrize("longitude", [180.0, -180.0, 0.0])
def test_accepts_longitude_bounds(longitude):
    assert SOSPayload(**valid_payload(longitude=longitude)).longitude == longitude


@pytest.mark.parametrize("longitude", [180.1, -180.1, 999.0])
def test_rejects_out_of_range_longitude(longitude):
    with pytest.raises(ValidationError):
        SOSPayload(**valid_payload(longitude=longitude))


@pytest.mark.parametrize("device_id", ["abc", "demo-device-01", "user_42", "A1"])
def test_accepts_valid_device_ids(device_id):
    assert SOSPayload(**valid_payload(device_id=device_id)).device_id == device_id


@pytest.mark.parametrize(
    "device_id",
    [
        "has space",
        "semi;colon",
        "quote'injection",
        "<script>",
        "emoji-🚨",
        "slash/es",
    ],
)
def test_rejects_device_ids_with_unsafe_characters(device_id):
    # These end up in log lines and SMS bodies, so keep the charset tight.
    with pytest.raises(ValidationError):
        SOSPayload(**valid_payload(device_id=device_id))


def test_rejects_empty_device_id():
    with pytest.raises(ValidationError):
        SOSPayload(**valid_payload(device_id=""))


def test_rejects_overlong_device_id():
    with pytest.raises(ValidationError):
        SOSPayload(**valid_payload(device_id="a" * 51))


def test_requires_coordinates():
    with pytest.raises(ValidationError):
        SOSPayload(device_id="abc", is_stealth_active=True)


def test_response_defaults_evidence_stored_to_false():
    response = SOSResponse(status="success", message="ok", signal_id=1)
    assert response.evidence_stored is False


def test_signal_record_reads_from_orm_row_attributes():
    """get_all_signals returns SQLAlchemy Rows, not dicts."""

    class Row:
        id = 1
        device_id = "demo-device-01"
        timestamp = __import__("datetime").datetime(2026, 1, 1, 12, 0, 0)
        is_stealth_active = True
        latitude = 12.9412
        longitude = 77.5652

    record = SignalRecord.model_validate(Row())
    assert record.device_id == "demo-device-01"
    assert record.latitude == 12.9412
