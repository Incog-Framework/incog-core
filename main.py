"""
Incog safety backend (Phases 11-12).

Receives emergency signals from the Android client, stores them with their
PostGIS location, verifies any attached AES-256-GCM evidence blob, and
dispatches alerts to the user's emergency contacts.
"""

import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import HTMLResponse
from fastapi.security.api_key import APIKeyHeader
from geoalchemy2 import Geometry
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Boolean,
    create_engine,
    func,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from twilio.rest import Client as TwilioClient

from evidence_crypto import (
    EvidenceAuthError,
    EvidenceError,
    EvidenceFormatError,
    decrypt_evidence,
    load_key,
    parse_evidence,
)
from schemas import SignalRecord, SOSPayload, SOSResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


def _utcnow() -> datetime:
    """
    Naive UTC timestamp.

    The DateTime columns are timezone-naive, so strip the tzinfo rather than
    using the deprecated datetime.utcnow().
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("CRITICAL: DATABASE_URL is not set")

# INCOG_API_KEY is the current name; AGENT_SECRET_KEY is accepted so the live
# Render deploy keeps working until the rotated key is in place.
API_KEY = os.getenv("INCOG_API_KEY") or os.getenv("AGENT_SECRET_KEY")
if not API_KEY:
    raise ValueError("CRITICAL: INCOG_API_KEY is not set")
if os.getenv("INCOG_API_KEY") is None:
    logger.warning(
        "Using deprecated AGENT_SECRET_KEY; rename it to INCOG_API_KEY when rotating."
    )
if len(API_KEY) < 16:
    logger.warning("INCOG_API_KEY is shorter than 16 characters - use a stronger key.")

# Shared AES-256 key for evidence, base64 of 32 raw bytes. Optional: if it is
# absent the location/alerting path (the life-critical one) still runs, and only
# evidence ingestion is refused. Failing startup here would take SOS down too.
EVIDENCE_KEY: Optional[bytes] = None
_evidence_key_b64 = os.getenv("EVIDENCE_AES_KEY")
if _evidence_key_b64:
    EVIDENCE_KEY = load_key(_evidence_key_b64)
    logger.info("Evidence decryption enabled (AES-256-GCM).")
else:
    logger.warning(
        "EVIDENCE_AES_KEY is not set - evidence ingestion disabled. "
        "SOS signals and alerts are unaffected."
    )

# Dashboard fallback centre, used only until a signal arrives. Defaults to
# BMSCE, Bangalore rather than a hardcoded foreign city.
MAP_DEFAULT_LAT = os.getenv("MAP_DEFAULT_LAT", "12.9412")
MAP_DEFAULT_LON = os.getenv("MAP_DEFAULT_LON", "77.5652")

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --------------------------------------------------------------------------
# Alert dispatch
# --------------------------------------------------------------------------
WHATSAPP_PREFIX = "whatsapp:"


class AlertDispatcher:
    """Fans an emergency out over Twilio (SMS or WhatsApp) and/or a webhook."""

    def __init__(self):
        self.enable_sms = os.getenv("ENABLE_SMS_DISPATCH", "true").lower() == "true"
        self.enable_webhook = (
            os.getenv("ENABLE_WEBHOOK_DISPATCH", "false").lower() == "true"
        )
        self.webhook_url = os.getenv("DISPATCH_WEBHOOK_URL")

        # "sms" or "whatsapp". Twilio trial accounts reject free-form SMS bodies
        # (error 572006 - trial SMS must use a predefined template), but the
        # WhatsApp sandbox accepts arbitrary text, so it carries the coordinates
        # and Maps link that make the alert worth sending.
        self.channel = os.getenv("TWILIO_CHANNEL", "sms").strip().lower()
        if self.channel not in ("sms", "whatsapp"):
            logger.warning(
                f"TWILIO_CHANNEL={self.channel!r} is not 'sms' or 'whatsapp'; "
                "falling back to sms"
            )
            self.channel = "sms"

        self.twilio_client = None
        self.twilio_phone = None

        if self.enable_sms:
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            self.twilio_phone = os.getenv("TWILIO_PHONE_NUMBER")

            if not all([account_sid, auth_token, self.twilio_phone]):
                logger.warning(
                    "Twilio dispatch enabled but credentials are missing"
                )
                self.enable_sms = False
            else:
                try:
                    self.twilio_client = TwilioClient(account_sid, auth_token)
                    logger.info(f"Twilio dispatch initialized (channel={self.channel})")
                except Exception as exc:
                    logger.error(f"Failed to initialize Twilio: {exc}")
                    self.enable_sms = False

        self.emergency_contacts = [
            c.strip() for c in os.getenv("EMERGENCY_CONTACTS", "").split(",") if c.strip()
        ]

    def _address(self, number: str) -> str:
        """
        Render a phone number as Twilio expects for the active channel.

        WhatsApp addresses are prefixed 'whatsapp:'; SMS addresses must not be.
        Tolerates a number that already carries the prefix either way, so a
        stray prefix in EMERGENCY_CONTACTS cannot silently break delivery.
        """
        bare = number.strip()
        if bare.startswith(WHATSAPP_PREFIX):
            bare = bare[len(WHATSAPP_PREFIX):].strip()
        return f"{WHATSAPP_PREFIX}{bare}" if self.channel == "whatsapp" else bare

    def _send_message(self, phone_number: str, message: str) -> bool:
        if not self.enable_sms or not self.twilio_client:
            return False
        try:
            self.twilio_client.messages.create(
                body=message,
                from_=self._address(self.twilio_phone),
                to=self._address(phone_number),
            )
            logger.info(f"Alert {self.channel} sent to {phone_number}")
            return True
        except Exception as exc:
            logger.error(f"Alert {self.channel} to {phone_number} failed: {exc}")
            return False

    def _send_webhook(self, payload: dict) -> bool:
        if not self.enable_webhook or not self.webhook_url:
            return False
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code >= 400:
                logger.error(
                    f"Alert webhook failed with status {response.status_code}: "
                    f"{response.text}"
                )
                return False
            logger.info("Alert webhook delivered")
            return True
        except Exception as exc:
            logger.error(f"Alert webhook failed: {exc}")
            return False

    def dispatch_alert(
        self,
        device_id: str,
        latitude: float,
        longitude: float,
        alert_type: str = "EMERGENCY",
        message: Optional[str] = None,
    ):
        if not self.emergency_contacts and not self.enable_webhook:
            logger.info("No dispatch channels configured; alert not sent")
            return

        timestamp = _utcnow().isoformat()
        maps_url = f"https://maps.google.com/?q={latitude},{longitude}"

        alert_message = message or (
            f"[Incog] {alert_type}\n"
            f"User: {device_id}\n"
            f"Time: {timestamp} UTC\n"
            f"Location: {latitude:.6f}, {longitude:.6f}\n"
            f"Map: {maps_url}"
        )

        webhook_payload = {
            "alert_type": alert_type,
            "device_id": device_id,
            "timestamp": timestamp,
            "latitude": latitude,
            "longitude": longitude,
            "maps_url": maps_url,
            "message": alert_message,
        }

        for contact in self.emergency_contacts:
            self._send_message(contact, alert_message)

        if self.enable_webhook:
            self._send_webhook(webhook_payload)

    def dispatch_alert_async(self, **kwargs):
        """Dispatch off the request path so alerting never delays the response."""
        threading.Thread(
            target=self.dispatch_alert, kwargs=kwargs, daemon=True
        ).start()


dispatcher = AlertDispatcher()


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class EmergencySignal(Base):
    __tablename__ = "emergency_signals"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    timestamp = Column(DateTime, default=_utcnow, index=True)
    is_stealth_active = Column(Boolean, default=True)
    location = Column(Geometry(geometry_type="POINT", srid=4326))

    __table_args__ = (
        Index("idx_device_timestamp", "device_id", "timestamp"),
        Index("idx_location_spatial", "location", postgresql_using="gist"),
    )


class Evidence(Base):
    """
    Encrypted evidence at rest.

    Only the ciphertext is persisted -- exactly the bytes the device sent. The
    backend decrypts in memory to verify the GCM tag and read a little triage
    metadata, and the plaintext is then discarded.
    """

    __tablename__ = "evidence_vault"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("emergency_signals.id"), index=True)

    # [12-byte IV][ciphertext||16-byte GCM tag], as received.
    ciphertext = Column(LargeBinary, nullable=False)

    # Non-sensitive identifiers lifted from the verified plaintext for lookup.
    session_id = Column(String, index=True, nullable=True)
    device_timestamp = Column(DateTime, nullable=True)

    timestamp = Column(DateTime, default=_utcnow, index=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
_key_header = APIKeyHeader(name="X-Incog-Key", auto_error=False)
_legacy_key_header = APIKeyHeader(name="X-Agent-Key", auto_error=False)


def verify_api_key(
    supplied: Optional[str] = Security(_key_header),
    legacy: Optional[str] = Security(_legacy_key_header),
) -> str:
    """
    Accepts X-Incog-Key, falling back to the deprecated X-Agent-Key so existing
    clients keep working through the rename.
    """
    key = supplied or legacy
    if not key:
        raise HTTPException(status_code=403, detail="Missing API key")
    # Constant-time, so a wrong key cannot be recovered by timing the response.
    if not secrets.compare_digest(key, API_KEY):
        logger.warning("Rejected request with an invalid API key")
        raise HTTPException(status_code=403, detail="Invalid API key")
    if supplied is None:
        logger.warning("Request used the deprecated X-Agent-Key header")
    return key


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema creation is deferred out of import so the module can be imported
    # (and tested) without a reachable database.
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema verified")
    yield
    engine.dispose()
    logger.info("Database connections closed")


app = FastAPI(title="Incog Safety Backend", lifespan=lifespan)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.post("/api/v1/sos", response_model=SOSResponse)
def trigger_sos(
    payload: SOSPayload,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key),
):
    """
    Record an emergency signal, alert the user's contacts, and store any
    attached evidence in encrypted form.
    """
    try:
        point_wkt = f"POINT({payload.longitude} {payload.latitude})"
        new_signal = EmergencySignal(
            device_id=payload.device_id,
            is_stealth_active=payload.is_stealth_active,
            location=f"SRID=4326;{point_wkt}",
        )
        db.add(new_signal)
        db.commit()
        db.refresh(new_signal)
        logger.info(
            "Emergency signal recorded",
            extra={"device_id": payload.device_id, "signal_id": new_signal.id},
        )

        # Alerting happens off-thread: a slow Twilio call must never hold up the
        # acknowledgement to a user in danger.
        dispatcher.dispatch_alert_async(
            device_id=payload.device_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            alert_type="EMERGENCY",
        )

        evidence_stored = False
        if payload.encrypted_evidence:
            evidence_stored = _store_evidence(
                db, new_signal.id, payload.encrypted_evidence
            )

        return {
            "status": "success",
            "message": "Emergency signal recorded.",
            "signal_id": new_signal.id,
            "evidence_stored": evidence_stored,
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error(f"Unexpected error handling SOS: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


def _store_evidence(db: Session, signal_id: int, blob_b64: str) -> bool:
    """
    Verify an evidence blob and persist it as ciphertext.

    The signal itself is already committed by this point, so a bad blob costs
    the evidence but never the location fix or the alert.

    Rejections are reported as 4xx/5xx, but the signal survives. Every message
    says so explicitly: a client that retried on this status would file a
    duplicate signal and text every emergency contact a second time.
    """
    # Appended to each rejection so the caller cannot mistake it for "the whole
    # request failed, send it again".
    recorded = (
        f" Signal {signal_id} was recorded and contacts were alerted; do not retry it."
    )

    if EVIDENCE_KEY is None:
        logger.error("Evidence supplied but EVIDENCE_AES_KEY is not configured")
        raise HTTPException(
            status_code=503,
            detail="Evidence ingestion is not configured." + recorded,
        )

    try:
        raw_blob, plaintext = decrypt_evidence(blob_b64, EVIDENCE_KEY)
        parsed = parse_evidence(plaintext)
    except EvidenceAuthError as exc:
        logger.error(f"Evidence authentication failed for signal {signal_id}: {exc}")
        raise HTTPException(
            status_code=400, detail="Evidence failed authentication." + recorded
        )
    except EvidenceFormatError as exc:
        logger.error(f"Malformed evidence for signal {signal_id}: {exc}")
        raise HTTPException(
            status_code=400, detail="Malformed evidence payload." + recorded
        )
    except EvidenceError as exc:
        logger.error(f"Evidence rejected for signal {signal_id}: {exc}")
        raise HTTPException(status_code=400, detail="Evidence rejected." + recorded)

    device_timestamp = None
    raw_ts = parsed.get("timestamp")
    if isinstance(raw_ts, (int, float)):
        try:
            # EvidencePackage.timestamp is epoch milliseconds.
            device_timestamp = datetime.fromtimestamp(
                raw_ts / 1000, tz=timezone.utc
            ).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            logger.warning(f"Evidence for signal {signal_id} had an unusable timestamp")

    session_id = parsed.get("sessionId")
    if session_id is not None and not isinstance(session_id, str):
        session_id = str(session_id)

    db.add(
        Evidence(
            signal_id=signal_id,
            ciphertext=raw_blob,
            session_id=session_id,
            device_timestamp=device_timestamp,
        )
    )
    db.commit()
    logger.info(
        "Evidence verified and stored encrypted",
        extra={"signal_id": signal_id, "session_id": session_id},
    )
    return True


@app.get("/api/v1/sos", response_model=list[SignalRecord])
def get_all_signals(
    db: Session = Depends(get_db), api_key: str = Depends(verify_api_key)
):
    """Latest known position for every device."""
    try:
        ranked = db.query(
            EmergencySignal.id,
            EmergencySignal.device_id,
            EmergencySignal.timestamp,
            EmergencySignal.is_stealth_active,
            func.ST_Y(EmergencySignal.location).label("latitude"),
            func.ST_X(EmergencySignal.location).label("longitude"),
            func.row_number()
            .over(
                partition_by=EmergencySignal.device_id,
                order_by=EmergencySignal.timestamp.desc(),
            )
            .label("rn"),
        ).subquery()

        signals = (
            db.query(
                ranked.c.id,
                ranked.c.device_id,
                ranked.c.timestamp,
                ranked.c.is_stealth_active,
                ranked.c.latitude,
                ranked.c.longitude,
            )
            .filter(ranked.c.rn == 1)
            .all()
        )

        logger.info(f"Returned {len(signals)} device positions")
        return signals
    except Exception as exc:
        logger.error(f"Database error listing signals: {exc}")
        raise HTTPException(status_code=500, detail="Failed to retrieve signals")


@app.post("/api/v1/dispatch/test")
def test_dispatch(
    device_id: str = "test-device",
    api_key: str = Depends(verify_api_key),
):
    """Send a test alert, to check Twilio/webhook configuration."""
    try:
        dispatcher.dispatch_alert(
            device_id=device_id,
            latitude=float(MAP_DEFAULT_LAT),
            longitude=float(MAP_DEFAULT_LON),
            alert_type="TEST",
            message=(
                f"[Incog] Test alert\n"
                f"Device: {device_id}\n"
                f"SMS enabled: {dispatcher.enable_sms}\n"
                f"Webhook enabled: {dispatcher.enable_webhook}\n"
                f"Contacts configured: {len(dispatcher.emergency_contacts)}"
            ),
        )
        return {
            "status": "success",
            "message": "Test alert dispatched",
            "sms_enabled": dispatcher.enable_sms,
            "webhook_enabled": dispatcher.enable_webhook,
            "contacts_count": len(dispatcher.emergency_contacts),
        }
    except Exception as exc:
        logger.error(f"Test dispatch failed: {exc}")
        raise HTTPException(status_code=500, detail="Test dispatch failed")


@app.get("/api/v1/dispatch/status")
def dispatch_status(api_key: str = Depends(verify_api_key)):
    """Report dispatcher configuration without sending anything."""
    return {
        "sms_enabled": dispatcher.enable_sms,
        "channel": dispatcher.channel,
        "webhook_enabled": dispatcher.enable_webhook,
        "twilio_configured": dispatcher.twilio_client is not None,
        "emergency_contacts": len(dispatcher.emergency_contacts),
        "webhook_url": dispatcher.webhook_url if dispatcher.enable_webhook else None,
        "evidence_decryption_enabled": EVIDENCE_KEY is not None,
    }


# --------------------------------------------------------------------------
# Responder dashboard
# --------------------------------------------------------------------------
# /api/v1/sos requires a key, so the page asks for one and sends it as a header.
# The key is held in sessionStorage only -- never in the URL, where it would end
# up in browser history and server logs.
_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Incog Safety Dashboard</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { margin: 0; font-family: system-ui, sans-serif; }
        #map { height: 100vh; width: 100vw; background: #1a1a1a; }
        #gate {
            position: fixed; inset: 0; z-index: 1000; display: flex;
            align-items: center; justify-content: center; background: #12141a;
        }
        #gate form {
            background: #1e2230; padding: 24px; border-radius: 10px;
            display: flex; flex-direction: column; gap: 12px; min-width: 300px;
            color: #e7e9ee;
        }
        #gate input {
            padding: 10px; border-radius: 6px; border: 1px solid #39405a;
            background: #12141a; color: #e7e9ee;
        }
        #gate button {
            padding: 10px; border-radius: 6px; border: 0;
            background: #4f7cff; color: #fff; cursor: pointer;
        }
        #err { color: #ff8080; font-size: 13px; min-height: 16px; }
        #banner {
            position: fixed; top: 0; left: 0; right: 0; z-index: 900;
            background: #b3261e; color: #fff; padding: 8px 12px;
            font-size: 14px; display: none;
        }
    </style>
</head>
<body>
    <div id="banner"></div>
    <div id="map"></div>

    <div id="gate">
        <form id="gate-form">
            <strong>Incog Safety Dashboard</strong>
            <label for="key">Responder API key</label>
            <input id="key" type="password" autocomplete="current-password" required>
            <div id="err"></div>
            <button type="submit">Open dashboard</button>
        </form>
    </div>

    <script>
        var map = L.map('map').setView([__MAP_LAT__, __MAP_LON__], 13);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }).addTo(map);

        var markers = {};
        var timer = null;
        var hasFitBounds = false;

        function apiKey() { return sessionStorage.getItem('incogKey'); }

        function showGate(message) {
            if (timer) { clearInterval(timer); timer = null; }
            sessionStorage.removeItem('incogKey');
            document.getElementById('err').textContent = message || '';
            document.getElementById('gate').style.display = 'flex';
        }

        function setBanner(text) {
            var el = document.getElementById('banner');
            if (text) { el.textContent = text; el.style.display = 'block'; }
            else { el.style.display = 'none'; }
        }

        function fetchLocations() {
            fetch('/api/v1/sos', { headers: { 'X-Incog-Key': apiKey() } })
                .then(function (response) {
                    if (response.status === 403) {
                        showGate('That key was rejected.');
                        return null;
                    }
                    if (!response.ok) { throw new Error('HTTP ' + response.status); }
                    return response.json();
                })
                .then(function (data) {
                    if (!data) { return; }
                    setBanner(null);

                    for (var id in markers) { map.removeLayer(markers[id]); }
                    markers = {};

                    var points = [];
                    data.forEach(function (device) {
                        var marker = L.circleMarker(
                            [device.latitude, device.longitude],
                            { color: '#4f7cff', radius: 8, fillOpacity: 0.85 }
                        ).addTo(map);
                        marker.bindPopup(
                            '<strong>' + device.device_id + '</strong><br>' +
                            'Last seen: ' + device.timestamp + ' UTC'
                        );
                        markers[device.device_id] = marker;
                        points.push([device.latitude, device.longitude]);
                    });

                    // Frame the actual data rather than assuming a fixed city.
                    if (points.length && !hasFitBounds) {
                        map.fitBounds(points, { maxZoom: 15, padding: [40, 40] });
                        hasFitBounds = true;
                    }
                })
                .catch(function (err) {
                    setBanner('Connection problem: ' + err.message);
                });
        }

        function start() {
            document.getElementById('gate').style.display = 'none';
            fetchLocations();
            timer = setInterval(fetchLocations, 5000);
        }

        document.getElementById('gate-form').addEventListener('submit', function (e) {
            e.preventDefault();
            var value = document.getElementById('key').value.trim();
            if (!value) { return; }
            sessionStorage.setItem('incogKey', value);
            document.getElementById('key').value = '';
            start();
        });

        if (apiKey()) { start(); }
    </script>
</body>
</html>
"""


@app.get("/map", response_class=HTMLResponse)
def get_map_dashboard():
    html = _DASHBOARD_HTML.replace("__MAP_LAT__", MAP_DEFAULT_LAT).replace(
        "__MAP_LON__", MAP_DEFAULT_LON
    )
    return HTMLResponse(content=html)
