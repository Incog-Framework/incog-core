import os
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, func, ForeignKey, Index
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from geoalchemy2 import Geometry
from cryptography.fernet import Fernet, InvalidToken
import requests
from twilio.rest import Client as TwilioClient

# Configure structured logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load the secrets from the .env file
load_dotenv()

# Setup Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("CRITICAL: DATABASE_URL not found in .env file!")

# Validate and setup Encryption Engine
def validate_fernet_key(key_str: str) -> Fernet:
    try:
        return Fernet(key_str.encode())
    except Exception as e:
        raise ValueError(f"CRITICAL: Invalid ENCRYPTION_KEY - must be valid Fernet key. Error: {e}")

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError("CRITICAL: ENCRYPTION_KEY not found in .env file!")
cipher_suite = validate_fernet_key(ENCRYPTION_KEY)

# Initialize SQLAlchemy Engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================
# SOS DISPATCHER MODULE
# ============================================
class SOSDispatcher:
    def __init__(self):
        self.enable_sms = os.getenv("ENABLE_SMS_DISPATCH", "true").lower() == "true"
        self.enable_webhook = os.getenv("ENABLE_WEBHOOK_DISPATCH", "false").lower() == "true"
        self.webhook_url = os.getenv("DISPATCH_WEBHOOK_URL")

        self.twilio_client = None
        self.twilio_phone = None

        if self.enable_sms:
            account_sid = os.getenv("TWILIO_ACCOUNT_SID")
            auth_token = os.getenv("TWILIO_AUTH_TOKEN")
            self.twilio_phone = os.getenv("TWILIO_PHONE_NUMBER")

            if not all([account_sid, auth_token, self.twilio_phone]):
                logger.warning("SMS dispatch enabled but missing Twilio credentials")
                self.enable_sms = False
            else:
                try:
                    self.twilio_client = TwilioClient(account_sid, auth_token)
                    logger.info("Twilio SMS dispatcher initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize Twilio: {e}")
                    self.enable_sms = False

        self.emergency_contacts = [
            c.strip() for c in os.getenv("EMERGENCY_CONTACTS", "").split(",")
            if c.strip()
        ]

    def _send_sms(self, phone_number: str, message: str) -> bool:
        if not self.enable_sms or not self.twilio_client:
            return False

        try:
            self.twilio_client.messages.create(
                body=message,
                from_=self.twilio_phone,
                to=phone_number
            )
            logger.info(f"SMS sent to {phone_number}")
            return True
        except Exception as e:
            logger.error(f"SMS send failed to {phone_number}: {e}")
            return False

    def _send_webhook(self, payload: dict) -> bool:
        if not self.enable_webhook or not self.webhook_url:
            return False

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code >= 400:
                logger.error(f"Webhook failed with status {response.status_code}: {response.text}")
                return False
            logger.info(f"Webhook dispatched successfully")
            return True
        except Exception as e:
            logger.error(f"Webhook dispatch failed: {e}")
            return False

    def dispatch_alert(
        self,
        device_id: str,
        latitude: float,
        longitude: float,
        is_stealth_active: bool,
        alert_type: str = "SOS",
        message: str = None
    ):
        if not self.emergency_contacts and not self.enable_webhook:
            logger.info("No dispatch channels configured")
            return

        timestamp = datetime.utcnow().isoformat()
        status = "STEALTH ACTIVE" if is_stealth_active else "COMPROMISED"

        default_message = f"🚨 {alert_type} ALERT [{timestamp}]\nAgent: {device_id}\nStatus: {status}\nLocation: ({latitude:.6f}, {longitude:.6f})\nGoogle Maps: https://maps.google.com/?q={latitude},{longitude}"

        alert_message = message or default_message

        webhook_payload = {
            "alert_type": alert_type,
            "device_id": device_id,
            "timestamp": timestamp,
            "latitude": latitude,
            "longitude": longitude,
            "is_stealth_active": is_stealth_active,
            "status": status,
            "maps_url": f"https://maps.google.com/?q={latitude},{longitude}",
            "message": alert_message
        }

        if self.emergency_contacts:
            for contact in self.emergency_contacts:
                self._send_sms(contact, alert_message)

        if self.enable_webhook:
            self._send_webhook(webhook_payload)

    def dispatch_alert_async(self, **kwargs):
        thread = threading.Thread(target=self.dispatch_alert, kwargs=kwargs, daemon=True)
        thread.start()

dispatcher = SOSDispatcher()

# Database Models
class EmergencySignal(Base):
    __tablename__ = "emergency_signals"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    is_stealth_active = Column(Boolean, default=True)
    location = Column(Geometry(geometry_type='POINT', srid=4326))

    __table_args__ = (
        Index('idx_device_timestamp', 'device_id', 'timestamp'),
        Index('idx_location_spatial', 'location', postgresql_using='gist'),
    )

class Evidence(Base):
    __tablename__ = "evidence_vault"
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("emergency_signals.id"), index=True)
    decrypted_text = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic Schemas for data validation
class SOSPayload(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=50)
    latitude: float = Field(..., ge=-90, le=90, description="Valid latitude range: -90 to 90")
    longitude: float = Field(..., ge=-180, le=180, description="Valid longitude range: -180 to 180")
    is_stealth_active: bool
    encrypted_evidence: Optional[str] = None

    @validator('device_id')
    def validate_device_id(cls, v):
        if not all(c.isalnum() or c in '-_' for c in v):
            raise ValueError('device_id must be alphanumeric with hyphens or underscores only')
        return v

class SOSResponse(BaseModel):
    status: str
    message: str
    signal_id: int

class SignalRecord(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    is_stealth_active: bool
    latitude: float
    longitude: float

# API Key Security
SECRET_AGENT_KEY = os.getenv("AGENT_SECRET_KEY")
if not SECRET_AGENT_KEY:
    raise ValueError("CRITICAL: AGENT_SECRET_KEY not found in .env file!")
if len(SECRET_AGENT_KEY) < 16:
    logger.warning("SECURITY WARNING: AGENT_SECRET_KEY is less than 16 characters - consider using a stronger key")

api_key_header = APIKeyHeader(name="X-Agent-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != SECRET_AGENT_KEY:
        logger.warning(f"Failed authentication attempt with invalid key")
        raise HTTPException(status_code=403, detail="ACCESS DENIED: Invalid Agent Key")
    return api_key

app = FastAPI(title="Incog C2 Server")

RESTRICTED_ZONE_WKT = "POLYGON((-0.1260 51.5050, -0.1200 51.5050, -0.1200 51.5100, -0.1260 51.5100, -0.1260 51.5050))"

@app.post("/api/v1/sos", response_model=SOSResponse)
def trigger_sos(payload: SOSPayload, db: Session = Depends(get_db), api_key: str = Depends(verify_api_key)):
    try:
        # 1. GEOFENCING: Check if agent is inside the restricted polygon
        point_wkt = f"POINT({payload.longitude} {payload.latitude})"
        is_in_zone = db.query(
            func.ST_Contains(
                func.ST_GeomFromText(RESTRICTED_ZONE_WKT, 4326),
                func.ST_GeomFromText(point_wkt, 4326)
            )
        ).scalar()

        stealth_status = payload.is_stealth_active
        geofence_breach = False

        if is_in_zone:
            stealth_status = False
            geofence_breach = True
            logger.warning(f"GEOFENCE BREACH: {payload.device_id} entered Restricted Zone at ({payload.latitude}, {payload.longitude})")

        # 2. SAVE GPS DOT
        db_point = f"SRID=4326;{point_wkt}"
        new_signal = EmergencySignal(
            device_id=payload.device_id,
            is_stealth_active=stealth_status,
            location=db_point
        )
        db.add(new_signal)
        db.commit()
        db.refresh(new_signal)
        logger.info(f"Signal recorded", extra={"device_id": payload.device_id, "signal_id": new_signal.id, "stealth": stealth_status})

        # 2.5. DISPATCH ALERTS (async to avoid blocking response)
        if geofence_breach:
            dispatcher.dispatch_alert_async(
                device_id=payload.device_id,
                latitude=payload.latitude,
                longitude=payload.longitude,
                is_stealth_active=stealth_status,
                alert_type="GEOFENCE BREACH",
                message=f"🚨 GEOFENCE BREACH DETECTED\nAgent: {payload.device_id}\nLocation: ({payload.latitude:.6f}, {payload.longitude:.6f})\nStatus: STEALTH REVOKED\nMaps: https://maps.google.com/?q={payload.latitude},{payload.longitude}"
            )
        else:
            dispatcher.dispatch_alert_async(
                device_id=payload.device_id,
                latitude=payload.latitude,
                longitude=payload.longitude,
                is_stealth_active=stealth_status,
                alert_type="SOS SIGNAL"
            )

        # 3. DECRYPTION MODULE: Extract secret evidence if attached
        if payload.encrypted_evidence:
            try:
                decrypted_bytes = cipher_suite.decrypt(payload.encrypted_evidence.encode())
                decrypted_string = decrypted_bytes.decode('utf-8')

                new_evidence = Evidence(
                    signal_id=new_signal.id,
                    decrypted_text=decrypted_string
                )
                db.add(new_evidence)
                db.commit()
                logger.info(f"Evidence decrypted successfully", extra={"signal_id": new_signal.id, "preview": decrypted_string[:50]})
            except InvalidToken:
                logger.error(f"Decryption failed: Invalid or tampered evidence for signal {new_signal.id}")
                raise HTTPException(status_code=400, detail="Decryption failed: Invalid or tampered evidence")
            except UnicodeDecodeError:
                logger.error(f"Decryption failed: Invalid UTF-8 encoding for signal {new_signal.id}")
                raise HTTPException(status_code=400, detail="Decryption failed: Invalid character encoding")
            except Exception as e:
                logger.error(f"Decryption failed: {str(e)}", extra={"signal_id": new_signal.id})
                raise HTTPException(status_code=400, detail=f"Decryption failed: {str(e)}")

        return {"status": "success", "message": "Logged.", "signal_id": new_signal.id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error in trigger_sos: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/v1/sos", response_model=list[SignalRecord])
def get_all_signals(db: Session = Depends(get_db), api_key: str = Depends(verify_api_key)):
    try:
        from sqlalchemy.sql import text

        # Use window function to get latest signal per device (deterministic)
        subquery = db.query(
            EmergencySignal.id,
            EmergencySignal.device_id,
            EmergencySignal.timestamp,
            EmergencySignal.is_stealth_active,
            func.ST_Y(EmergencySignal.location).label('latitude'),
            func.ST_X(EmergencySignal.location).label('longitude'),
            func.row_number().over(
                partition_by=EmergencySignal.device_id,
                order_by=EmergencySignal.timestamp.desc()
            ).label('rn')
        ).subquery()

        signals = db.query(
            subquery.c.id,
            subquery.c.device_id,
            subquery.c.timestamp,
            subquery.c.is_stealth_active,
            subquery.c.latitude,
            subquery.c.longitude
        ).filter(subquery.c.rn == 1).all()

        logger.info(f"Retrieved {len(signals)} active signals")
        return signals
    except Exception as e:
        logger.error(f"Database error in get_all_signals: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve signals")

@app.get("/map", response_class=HTMLResponse)
def get_map_dashboard():
    # A simple built-in HTML dashboard for quick testing
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>C2 Map Dashboard</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>body { margin: 0; } #map { height: 100vh; width: 100vw; background-color: #1a1a1a; }</style>
    </head>
    <body>
        <div id="map"></div>
        <script>
            var map = L.map('map').setView([51.5074, -0.1278], 14);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { attribution: '© OpenStreetMap' }).addTo(map);
            
            // Draw Danger Zone
            var dangerZone = L.polygon([
                [51.5050, -0.1260],
                [51.5050, -0.1200],
                [51.5100, -0.1200],
                [51.5100, -0.1260]
            ], { color: 'red', fillColor: '#f03', fillOpacity: 0.2 }).addTo(map);
            dangerZone.bindPopup("RESTRICTED ENEMY ZONE");

            var markers = {};

            function fetchLocations() {
                fetch('/api/v1/sos')
                    .then(response => response.json())
                    .then(data => {
                        // Clear old markers
                        for (let id in markers) { map.removeLayer(markers[id]); }
                        markers = {};

                        let isAlarmActive = false;

                        data.forEach(agent => {
                            let color = agent.is_stealth_active ? 'green' : 'red';
                            if (!agent.is_stealth_active) { isAlarmActive = true; }
                            
                            let marker = L.circleMarker([agent.latitude, agent.longitude], {
                                color: color,
                                radius: 8,
                                fillOpacity: 0.8
                            }).addTo(map).bindPopup(agent.device_id);
                            
                            markers[agent.device_id] = marker;
                        });

                        // Flash map red if an agent is compromised
                        document.getElementById('map').style.boxShadow = isAlarmActive ? 'inset 0 0 100px red' : 'none';
                    });
            }

            setInterval(fetchLocations, 5000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/v1/dispatch/test")
def test_dispatch(
    device_id: str = "TEST-AGENT",
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Test endpoint to verify dispatcher configuration and send test alerts.
    Useful for validating Twilio/webhook setup.
    """
    try:
        test_lat, test_lon = 51.5074, -0.1278
        dispatcher.dispatch_alert(
            device_id=device_id,
            latitude=test_lat,
            longitude=test_lon,
            is_stealth_active=False,
            alert_type="TEST ALERT",
            message=f"✅ Dispatcher Test Alert\nDevice: {device_id}\nSMS Enabled: {dispatcher.enable_sms}\nWebhook Enabled: {dispatcher.enable_webhook}\nContacts Configured: {len(dispatcher.emergency_contacts)}"
        )
        logger.info(f"Test dispatch sent for {device_id}")
        return {
            "status": "success",
            "message": "Test alert dispatched",
            "sms_enabled": dispatcher.enable_sms,
            "webhook_enabled": dispatcher.enable_webhook,
            "contacts_count": len(dispatcher.emergency_contacts)
        }
    except Exception as e:
        logger.error(f"Test dispatch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/dispatch/status")
def dispatch_status(api_key: str = Depends(verify_api_key)):
    """
    Get dispatcher configuration status without sending alerts.
    """
    return {
        "sms_enabled": dispatcher.enable_sms,
        "webhook_enabled": dispatcher.enable_webhook,
        "twilio_configured": dispatcher.twilio_client is not None,
        "emergency_contacts": len(dispatcher.emergency_contacts),
        "webhook_url": dispatcher.webhook_url if dispatcher.enable_webhook else None
    }

@app.on_event("shutdown")
def shutdown_event():
    engine.dispose()
    logger.info("Database connections closed")