# Backend Architecture - Incog C2 Server

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     INCOG C2 BACKEND SYSTEM                      │
└─────────────────────────────────────────────────────────────────┘

                            ┌─────────────┐
                            │   CLIENT    │
                            │  (Tracker)  │
                            └──────┬──────┘
                                   │
                  ┌────────────────┼────────────────┐
                  │                │                │
                  ▼                ▼                ▼
         ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
         │ SOS Signal   │  │  Encrypted   │  │     API      │
         │  (GPS Data)  │  │   Evidence   │  │   Key Auth   │
         └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                │                 │                 │
                └─────────────────┼─────────────────┘
                                  │
                        ┌─────────▼────────────┐
                        │   FastAPI Router    │
                        │ (/api/v1/sos)       │
                        └─────────┬────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
            ┌──────────────┐ ┌───────────┐ ┌──────────────┐
            │  Database    │ │ Geofence  │ │  Dispatcher  │
            │  (PostgreSQL)│ │  Check    │ │   Pipeline   │
            │   + PostGIS  │ │ (ST_Cont) │ │   (Async)    │
            └──────┬───────┘ └─────┬─────┘ └──────┬───────┘
                   │               │              │
         ┌─────────▼────────┐      │     ┌────────▼─────────┐
         │ Store Signal     │      │     │  Alert Dispatch  │
         │ Store Evidence   │      │     └────────┬─────────┘
         │ Index by Device  │      │              │
         └──────────────────┘      │     ┌────────┴────────┐
                                   │     │                 │
                    ┌──────────────┘     │                 │
                    │                    ▼                 ▼
                    ▼             ┌─────────────┐  ┌──────────────┐
            ┌──────────────┐      │   Twilio    │  │    Webhook   │
            │ Revoke/Keep  │      │    SMS      │  │ (External    │
            │  Stealth     │      │             │  │  Systems)    │
            └──────────────┘      └─────────────┘  └──────────────┘
                                         │                │
                                         ▼                ▼
                                  ┌─────────────┐  ┌──────────────┐
                                  │ Emergency   │  │ SIEM / Slack │
                                  │  Contacts   │  │ / PagerDuty  │
                                  └─────────────┘  └──────────────┘
```

## Component Details

### 1. FastAPI REST API Layer
**File:** `main.py` (Lines 89-100+)

```
Endpoint: POST /api/v1/sos
├─ Authentication: API Key via X-Agent-Key header
├─ Validation: Pydantic SOSPayload model
│  ├─ device_id: 1-50 alphanumeric chars
│  ├─ latitude: -90 to +90 (bounded)
│  ├─ longitude: -180 to +180 (bounded)
│  ├─ is_stealth_active: Boolean
│  └─ encrypted_evidence: Optional Fernet-encrypted data
└─ Response: SOSResponse with signal_id
```

### 2. Database Layer (PostgreSQL + PostGIS)

#### Schema
```sql
emergency_signals
├─ id (PK, indexed)
├─ device_id (indexed)
├─ timestamp (indexed)
├─ is_stealth_active (boolean)
└─ location (geometry POINT, SRID=4326)
   └─ Spatial index (GiST)

evidence_vault
├─ id (PK)
├─ signal_id (FK, indexed)
├─ decrypted_text (string)
└─ timestamp (indexed)
```

#### Indexes
- `idx_device_timestamp` - Composite index on (device_id, timestamp)
- `idx_location_spatial` - GiST spatial index on PostGIS geometry
- Default indexes on all primary/foreign keys

#### Connection Management
```python
engine = create_engine(
    pool_size=20,           # Maintain 20 connections
    max_overflow=40,        # Allow up to 40 overflow connections
    pool_recycle=3600,      # Recycle connections after 1 hour
    pool_pre_ping=True      # Verify connection before use
)
```

### 3. Geofencing Module
**Location:** `main.py` (Lines 243-256)

```
Restricted Zone (Hardcoded)
└─ POLYGON (London, UK coordinates)
   ├─ Lat: 51.5050 to 51.5100
   └─ Lon: -0.1260 to -0.1200

Logic
├─ ST_Contains(zone_polygon, agent_point) → boolean
├─ If true: Stealth revoked → COMPROMISED status
└─ Alert dispatched with GEOFENCE BREACH type
```

### 4. Encryption Module
**File:** `main.py` (Lines 27-37)

```
Fernet Symmetric Encryption (AES-128)
├─ Key: ENCRYPTION_KEY environment variable
├─ Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
├─ Validation: On startup (raises ValueError if invalid)
│
Decryption Process
├─ Input: Base64-encoded ciphertext from client
├─ Process:
│  ├─ Decode from Base64
│  ├─ Decrypt with Fernet
│  ├─ Validate authenticity (built-in)
│  └─ Decode UTF-8
├─ Error Handling:
│  ├─ InvalidToken → Tampered data
│  ├─ UnicodeDecodeError → Invalid encoding
│  └─ Other → Log and return error
└─ Storage: Plaintext in evidence_vault table
```

### 5. SOS Dispatcher Pipeline
**File:** `main.py` (Lines 54-160)

#### Architecture
```
SOSDispatcher Class
├─ __init__()
│  ├─ Load Twilio credentials from env
│  ├─ Initialize TwilioClient
│  ├─ Parse emergency contacts
│  └─ Load webhook URL
│
├─ _send_sms(phone, message) → bool
│  ├─ Validate SMS enabled
│  ├─ Call twilio.messages.create()
│  └─ Log result
│
├─ _send_webhook(payload) → bool
│  ├─ Validate webhook enabled
│  ├─ POST to webhook_url
│  ├─ Check 2xx response
│  └─ Log result
│
├─ dispatch_alert(...) → None
│  ├─ Build formatted message
│  ├─ Create webhook payload
│  ├─ Send SMS to all contacts
│  └─ Send webhook (if enabled)
│
└─ dispatch_alert_async(...) → None
   └─ Spawn daemon thread → dispatch_alert()
```

#### Alert Types & Messages

**SOS Signal Alert**
```
Alert Type: "SOS SIGNAL"
Channels: SMS + Webhook
Content: Standard format with coordinates & maps link
```

**Geofence Breach Alert**
```
Alert Type: "GEOFENCE BREACH"
Channels: SMS + Webhook
Triggers: dispatch_alert_async() in trigger_sos()
Content: Urgent breach notification + stealth revocation notice
```

#### Configuration Matrix

| Setting | SMS | Webhook | Behavior |
|---------|-----|---------|----------|
| ✅ ✅ | Enabled | Enabled | Both channels active |
| ✅ ❌ | Enabled | Disabled | SMS only |
| ❌ ✅ | Disabled | Enabled | Webhook only |
| ❌ ❌ | Disabled | Disabled | No alerts (silent mode) |

#### Error Handling
```
Twilio SMS
├─ Auth Error → Disable SMS, log warning
├─ Invalid Phone → Log error, continue
└─ Network Error → Log error, continue (async doesn't block)

Webhook
├─ 4xx/5xx Response → Log error, continue
├─ Timeout → Log error, continue
└─ Network Error → Log error, continue
```

### 6. Query Optimization

#### Problem: Non-Deterministic Results
**Original Query (v1.0)**
```python
.distinct(EmergencySignal.device_id)  # ❌ Undefined which row per device
```

**Solution: Window Function (v2.0)**
```python
func.row_number().over(
    partition_by=EmergencySignal.device_id,
    order_by=EmergencySignal.timestamp.desc()
).label('rn')
# Filter: rn == 1  ✅ Guaranteed latest per device
```

#### Performance Impact
- **Before:** Non-deterministic query results
- **After:** Deterministic + indexed lookups
- **Cost:** Minimal (standard SQL operation)

### 7. API Endpoints Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/v1/sos` | POST | ✅ | SOS signal ingestion |
| `/api/v1/sos` | GET | ✅ | Fetch latest signals |
| `/api/v1/dispatch/test` | POST | ✅ | Test alert dispatch |
| `/api/v1/dispatch/status` | GET | ✅ | Check dispatcher config |
| `/map` | GET | ❌ | Map dashboard (public) |

## Data Flow: Complete SOS Signal Journey

```
1. CLIENT SENDS SOS
   └─ POST /api/v1/sos with GPS coordinates + API key

2. FASTAPI VALIDATION
   └─ Pydantic validates payload (lat/lon bounds, device_id format)

3. AUTHENTICATION
   └─ API key verification via verify_api_key() dependency

4. GEOFENCE CHECK
   ├─ ST_Contains(restricted_zone, agent_point)
   └─ If true: Set is_stealth_active = false

5. DATABASE SAVE
   ├─ Insert EmergencySignal record
   ├─ Commit transaction
   └─ Refresh to get signal_id

6. EVIDENCE PROCESSING (If encrypted_evidence in payload)
   ├─ Decrypt using Fernet cipher_suite
   ├─ Catch InvalidToken / UnicodeDecodeError
   ├─ Insert Evidence record
   └─ Log success/failure

7. ALERT DISPATCH (Async)
   ├─ Spawn background thread
   ├─ Check alert type (SOS vs GEOFENCE)
   ├─ Build appropriate message
   ├─ Send SMS to all emergency contacts
   ├─ Send webhook (if enabled)
   └─ Log results (no blocking)

8. RESPONSE TO CLIENT
   ├─ Return immediately: {"status": "success", "signal_id": 123}
   └─ Dispatch still happening in background
```

## Performance Characteristics

### Latency Targets
```
POST /api/v1/sos Request
├─ Network → API: ~50ms (network)
├─ Validation: ~1ms (pydantic)
├─ Geofence check: ~5ms (ST_Contains)
├─ Database save: ~10ms (PostgreSQL)
├─ Evidence decrypt: ~2ms (Fernet)
├─ Evidence save: ~5ms (PostgreSQL)
├─ Spawn dispatch thread: <1ms
└─ Return response: ~75ms total
    └─ Plus SMS delivery: 1-10s (Twilio)
       Plus Webhook delivery: <1s (HTTP)
```

### Scalability
```
Connection Pool
├─ Steady state: 20 connections
├─ Peak traffic: Up to 60 connections
├─ Recycled every: 3600 seconds

Concurrent Signals
├─ 10 signals/second: No issue (20 pool)
├─ 50 signals/second: Minimal queuing
├─ 100+ signals/second: Needs load balancing

Index Performance
├─ device_id lookup: O(log N) via B-tree index
├─ Geofence check: O(log N) via GiST index
└─ Latest per device: O(N log N) with window function, O(1) filter
```

## Security Architecture

### Authentication
```
Header-based API Key
├─ Header: X-Agent-Key
├─ Validation: Constant-time comparison
├─ Failure: 403 Forbidden response
└─ Logging: Failed attempts logged
```

### Data Encryption
```
Transit (Client → Server)
├─ HTTPS/TLS (enforced in production)
└─ Fernet encrypted evidence payload (optional extra layer)

At Rest (PostgreSQL)
├─ Plaintext storage (encrypted evidence decrypted server-side)
├─ Future: Column-level encryption if needed
└─ Access: Credentials in environment variables
```

### Secrets Management
```
Environment Variables
├─ DATABASE_URL
├─ ENCRYPTION_KEY (Fernet base64)
├─ AGENT_SECRET_KEY
├─ TWILIO_ACCOUNT_SID
├─ TWILIO_AUTH_TOKEN
├─ TWILIO_PHONE_NUMBER
└─ Stored in: .env (local) or secrets manager (production)
```

## Deployment Architecture

### Current (Render.com)
```
Render Web Service
├─ Runtime: Python 3.11+
├─ Entrypoint: uvicorn main:app --host 0.0.0.0 --port $PORT
├─ Environment: .env via secrets
└─ Auto-restart on crash
```

### Production Recommended
```
Load Balancer (Nginx/ALB)
├─ HTTPS termination
├─ Rate limiting
└─ Routing to 2-3 instances

Application Servers (3x)
├─ Uvicorn workers per server
├─ Auto-scaling based on CPU/memory
└─ Health checks

PostgreSQL RDS
├─ Primary + standby (high availability)
├─ Automated backups
├─ Read replicas for reporting
└─ VPC-private access

Message Queue (Optional)
├─ Redis or RabbitMQ
├─ For alert delivery reliability
└─ Retry mechanism for failed alerts
```

## Monitoring & Observability

### Key Metrics
```
Application Health
├─ Request rate (requests/sec)
├─ Response latency (p50, p95, p99)
├─ Error rate (4xx, 5xx)
└─ Database connections in use

Alert Dispatch
├─ SMS success rate
├─ Webhook success rate
├─ Average delivery time
└─ Cost per alert

Database
├─ Connection pool utilization
├─ Query latency (especially ST_Contains)
├─ Index hit rate
└─ Table sizes
```

### Logging Strategy
```
Structured Logging
├─ Format: JSON with timestamp, level, message
├─ Fields: device_id, signal_id, stealth_status, error_message
├─ Levels: INFO (normal ops), WARNING (config issues), ERROR (failures)
└─ Aggregation: CloudWatch / ELK / Splunk
```

---

## Technology Stack Summary

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Framework** | FastAPI | 0.139.0 | REST API routing |
| **Server** | Uvicorn | 0.50.2 | ASGI server |
| **Database** | PostgreSQL | 12+ | Signal/evidence storage |
| **Spatial** | PostGIS | 3.x | Geofencing queries |
| **ORM** | SQLAlchemy | 2.0.51 | Database abstraction |
| **Validation** | Pydantic | 2.13.4 | Request validation |
| **Encryption** | Cryptography | 50.0.0 | Fernet cipher |
| **SMS** | Twilio | 9.11.0 | Alert dispatch |
| **Config** | python-dotenv | 1.2.2 | Environment management |
| **HTTP** | Requests | 2.34.2 | Webhook dispatch |

---

**Architecture Design:** Backend Lead - CHIRAG8643  
**Last Updated:** 2026-08-31  
**Status:** Production Ready ✅
