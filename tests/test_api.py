"""
Endpoint-level tests.

The database session is replaced with a stub, so these run without Postgres or
PostGIS. They cover the parts that do not need a real database: authentication,
request validation, evidence handling, and the dashboard.
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient

import main
from evidence_crypto import encrypt_evidence

API_KEY = "test-key-0123456789abcdef"
EVIDENCE_KEY = bytes(range(32))


class StubSession:
    """Minimal stand-in for a SQLAlchemy Session on the write path."""

    def __init__(self):
        self.added = []
        self.commits = 0
        self.rolled_back = False

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        obj.id = 1

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


@pytest.fixture
def session():
    return StubSession()


@pytest.fixture
def client(session, monkeypatch):
    # Alerting is fired off a thread in production; capture it instead so the
    # tests can assert on it deterministically.
    dispatched = []
    monkeypatch.setattr(
        main.dispatcher,
        "dispatch_alert_async",
        lambda **kwargs: dispatched.append(kwargs),
    )

    main.app.dependency_overrides[main.get_db] = lambda: session
    test_client = TestClient(main.app)
    test_client.dispatched = dispatched
    yield test_client
    main.app.dependency_overrides.clear()


def sos_body(**overrides):
    body = {
        "device_id": "demo-device-01",
        "latitude": 12.9412,
        "longitude": 77.5652,
        "is_stealth_active": True,
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
def test_sos_requires_an_api_key(client):
    assert client.post("/api/v1/sos", json=sos_body()).status_code == 403


def test_sos_rejects_a_wrong_api_key(client):
    response = client.post(
        "/api/v1/sos", json=sos_body(), headers={"X-Incog-Key": "wrong"}
    )
    assert response.status_code == 403


def test_sos_accepts_the_current_header(client):
    response = client.post(
        "/api/v1/sos", json=sos_body(), headers={"X-Incog-Key": API_KEY}
    )
    assert response.status_code == 200
    assert response.json()["signal_id"] == 1


def test_sos_still_accepts_the_deprecated_header(client):
    """Aarush's client sends X-Agent-Key; it must keep working through the rename."""
    response = client.post(
        "/api/v1/sos", json=sos_body(), headers={"X-Agent-Key": API_KEY}
    )
    assert response.status_code == 200


def test_listing_signals_requires_a_key(client):
    assert client.get("/api/v1/sos").status_code == 403


def test_dispatch_status_requires_a_key(client):
    assert client.get("/api/v1/dispatch/status").status_code == 403


def test_dispatch_status_does_not_leak_the_webhook_url(client, monkeypatch):
    """
    A Discord/Slack webhook URL embeds its own auth token. Returning it would
    let anyone holding the API key post into that channel, so status reports
    only whether one is configured.
    """
    secret = "https://discord.com/api/webhooks/123456789/SUPERSECRETTOKENVALUE"
    monkeypatch.setattr(main.dispatcher, "webhook_url", secret)
    monkeypatch.setattr(main.dispatcher, "enable_webhook", True)

    response = client.get(
        "/api/v1/dispatch/status", headers={"X-Incog-Key": API_KEY}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["webhook_configured"] is True
    assert "webhook_url" not in body
    assert secret not in response.text
    assert "SUPERSECRETTOKENVALUE" not in response.text


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "override",
    [
        {"latitude": 91.0},
        {"longitude": -181.0},
        {"device_id": "bad id"},
        {"device_id": ""},
    ],
)
def test_sos_rejects_invalid_payloads(client, override):
    response = client.post(
        "/api/v1/sos", json=sos_body(**override), headers={"X-Incog-Key": API_KEY}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Signal handling
# --------------------------------------------------------------------------
def test_signal_is_persisted_with_a_postgis_point(client, session):
    client.post("/api/v1/sos", json=sos_body(), headers={"X-Incog-Key": API_KEY})
    signal = session.added[0]
    assert signal.device_id == "demo-device-01"
    assert signal.location == "SRID=4326;POINT(77.5652 12.9412)"


def test_an_alert_is_dispatched_for_every_signal(client):
    client.post("/api/v1/sos", json=sos_body(), headers={"X-Incog-Key": API_KEY})
    assert len(client.dispatched) == 1
    assert client.dispatched[0]["alert_type"] == "EMERGENCY"
    assert client.dispatched[0]["device_id"] == "demo-device-01"


def test_client_reported_stealth_flag_is_stored_verbatim(client, session):
    """The backend no longer overrides this; there is no geofence to revoke it."""
    client.post(
        "/api/v1/sos",
        json=sos_body(is_stealth_active=False),
        headers={"X-Incog-Key": API_KEY},
    )
    assert session.added[0].is_stealth_active is False


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------
def evidence_blob(**overrides):
    package = {
        "sessionId": "session-abc",
        "timestamp": 1700000000000,
        "gps": {"lat": 12.9412, "lng": 77.5652},
        "audioBase64": "",
        "featureVector": {
            "peakAcceleration": 18.2,
            "motionVariance": 3.1,
            "audioEnergy": 0.8,
            "gpsVelocity": 1.2,
            "possibleFall": True,
        },
        "aiResult": {"Prediction": "emergency", "EmergencyStatus": True},
    }
    package.update(overrides)
    return encrypt_evidence(json.dumps(package).encode(), EVIDENCE_KEY)


def test_valid_evidence_is_accepted_and_reported(client):
    response = client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=evidence_blob()),
        headers={"X-Incog-Key": API_KEY},
    )
    assert response.status_code == 200
    assert response.json()["evidence_stored"] is True


def test_evidence_is_stored_as_ciphertext_not_plaintext(client, session):
    """
    Decision 4: nothing readable may reach the database. The stored bytes must
    be exactly what the device sent, with no plaintext recoverable from them.
    """
    blob = evidence_blob()
    client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=blob),
        headers={"X-Incog-Key": API_KEY},
    )

    evidence = session.added[1]
    assert evidence.ciphertext == base64.b64decode(blob)
    assert b"session-abc" not in evidence.ciphertext
    assert b"emergency" not in evidence.ciphertext
    assert not hasattr(evidence, "decrypted_text")


def test_triage_metadata_is_lifted_from_the_verified_plaintext(client, session):
    client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=evidence_blob()),
        headers={"X-Incog-Key": API_KEY},
    )
    evidence = session.added[1]
    assert evidence.session_id == "session-abc"
    assert evidence.device_timestamp.year == 2023


def test_tampered_evidence_is_rejected(client):
    raw = bytearray(base64.b64decode(evidence_blob()))
    raw[20] ^= 0x01
    response = client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=base64.b64encode(bytes(raw)).decode()),
        headers={"X-Incog-Key": API_KEY},
    )
    assert response.status_code == 400
    assert "authentication" in response.json()["detail"].lower()


def test_evidence_rejection_tells_the_client_not_to_retry(client, session):
    """
    A 400 here means "evidence rejected", not "request failed". The signal is
    already committed and contacts already alerted, so a client that retried
    would file a duplicate signal and text every contact a second time.
    """
    raw = bytearray(base64.b64decode(evidence_blob()))
    raw[20] ^= 0x01
    response = client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=base64.b64encode(bytes(raw)).decode()),
        headers={"X-Incog-Key": API_KEY},
    )

    detail = response.json()["detail"].lower()
    assert "do not retry" in detail
    assert "signal 1" in detail
    # The signal really did survive the rejection.
    assert session.added[0].device_id == "demo-device-01"


def test_malformed_evidence_is_rejected(client):
    response = client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence="not base64 at all!!"),
        headers={"X-Incog-Key": API_KEY},
    )
    assert response.status_code == 400


def test_evidence_encrypted_with_the_wrong_key_is_rejected(client):
    blob = encrypt_evidence(b'{"sessionId":"x"}', bytes([b ^ 0xFF for b in EVIDENCE_KEY]))
    response = client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=blob),
        headers={"X-Incog-Key": API_KEY},
    )
    assert response.status_code == 400


def test_bad_evidence_does_not_lose_the_signal(client, session):
    """
    The location fix and the alert matter more than the evidence. A rejected
    blob must not roll back the signal that was already committed.
    """
    client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence="not base64 at all!!"),
        headers={"X-Incog-Key": API_KEY},
    )
    assert session.added[0].device_id == "demo-device-01"
    assert not session.rolled_back
    assert len(client.dispatched) == 1


def test_evidence_is_refused_when_no_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(main, "EVIDENCE_KEY", None)
    response = client.post(
        "/api/v1/sos",
        json=sos_body(encrypted_evidence=evidence_blob()),
        headers={"X-Incog-Key": API_KEY},
    )
    assert response.status_code == 503


def test_signals_without_evidence_work_when_no_key_is_configured(client, monkeypatch):
    """Losing the evidence key must not take the life-critical path down."""
    monkeypatch.setattr(main, "EVIDENCE_KEY", None)
    response = client.post(
        "/api/v1/sos", json=sos_body(), headers={"X-Incog-Key": API_KEY}
    )
    assert response.status_code == 200
    assert response.json()["evidence_stored"] is False


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def test_dashboard_is_served(client):
    response = client.get("/map")
    assert response.status_code == 200
    assert "Incog Safety Dashboard" in response.text


def test_dashboard_sends_the_api_key_as_a_header(client):
    """
    /api/v1/sos requires a key, so the page must send one, and never in the URL
    where it would land in history and access logs.
    """
    body = client.get("/map").text
    assert "'X-Incog-Key': apiKey()" in body
    assert "?key=" not in body


@pytest.mark.parametrize(
    "term",
    ["agent", "enemy", "compromised", "restricted", "stealth revoked", "c2 map"],
)
def test_dashboard_uses_safety_vocabulary(client, term):
    assert term not in client.get("/map").text.lower()


def test_dashboard_has_no_hardcoded_london_geofence(client):
    body = client.get("/map").text
    assert "51.50" not in body
    assert "dangerZone" not in body
