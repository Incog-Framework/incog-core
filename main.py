import os
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, func, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from geoalchemy2 import Geometry
from cryptography.fernet import Fernet

# Load the secrets from the .env file
load_dotenv()

# Setup Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("CRITICAL: DATABASE_URL not found in .env file!")

# Setup Encryption Engine
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
cipher_suite = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

# Initialize SQLAlchemy Engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Models
class EmergencySignal(Base):
    __tablename__ = "emergency_signals"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_stealth_active = Column(Boolean, default=True)
    # PostGIS Point storage
    location = Column(Geometry(geometry_type='POINT', srid=4326))

class Evidence(Base):
    __tablename__ = "evidence_vault"
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("emergency_signals.id"))
    decrypted_text = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

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
    device_id: str
    latitude: float
    longitude: float
    is_stealth_active: bool
    encrypted_evidence: Optional[str] = None  # New field for secret payloads

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
api_key_header = APIKeyHeader(name="X-Agent-Key", auto_error=True)

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != SECRET_AGENT_KEY:
        raise HTTPException(status_code=403, detail="ACCESS DENIED: Invalid Agent Key")
    return api_key

app = FastAPI(title="Incog C2 Server")

@app.post("/api/v1/sos", response_model=SOSResponse)
def trigger_sos(payload: SOSPayload, db: Session = Depends(get_db), api_key: str = Depends(verify_api_key)):
    try:
        # 1. GEOFENCING: Define Restricted Enemy Zone
        RESTRICTED_ZONE_WKT = "POLYGON((-0.1260 51.5050, -0.1200 51.5050, -0.1200 51.5100, -0.1260 51.5100, -0.1260 51.5050))"
        point_wkt = f"POINT({payload.longitude} {payload.latitude})"
        
        # Check if agent is inside the restricted polygon
        is_in_zone = db.query(
            func.ST_Contains(
                func.ST_GeomFromText(RESTRICTED_ZONE_WKT, 4326), 
                func.ST_GeomFromText(point_wkt, 4326)
            )
        ).scalar()

        # If they wander into the zone, dynamically revoke stealth
        if is_in_zone:
            payload.is_stealth_active = False
            print(f"⚠️ [GEOFENCE BREACH] {payload.device_id} entered the Restricted Zone!")

        # 2. SAVE GPS DOT
        db_point = f"SRID=4326;{point_wkt}"
        new_signal = EmergencySignal(
            device_id=payload.device_id,
            is_stealth_active=payload.is_stealth_active,
            location=db_point
        )
        db.add(new_signal)
        db.commit()
        db.refresh(new_signal)
        
        # 3. DECRYPTION MODULE: Extract secret evidence if attached
        if payload.encrypted_evidence and cipher_suite:
            try:
                decrypted_bytes = cipher_suite.decrypt(payload.encrypted_evidence.encode())
                decrypted_string = decrypted_bytes.decode()
                
                new_evidence = Evidence(
                    signal_id=new_signal.id,
                    decrypted_text=decrypted_string
                )
                db.add(new_evidence)
                db.commit()
                print(f"🔓 DECRYPTION SUCCESS: Secret evidence saved -> '{decrypted_string}'")
            except Exception as e:
                print(f"❌ DECRYPTION FAILED: {e}")

        return {"status": "success", "message": "Logged.", "signal_id": new_signal.id}
    except Exception as e:
        db.rollback() 
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/sos", response_model=list[SignalRecord])
def get_all_signals(db: Session = Depends(get_db)):
    try:
        # OPTIMIZATION: Pull only the single most recent coordinate per agent
        signals = db.query(
            EmergencySignal.id,
            EmergencySignal.device_id,
            EmergencySignal.timestamp,
            EmergencySignal.is_stealth_active,
            func.ST_Y(EmergencySignal.location).label('latitude'),
            func.ST_X(EmergencySignal.location).label('longitude')
        ).distinct(EmergencySignal.device_id).order_by(
            EmergencySignal.device_id, 
            EmergencySignal.timestamp.desc()
        ).all()
        
        return signals
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

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

            setInterval(fetchLocations, 2000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)