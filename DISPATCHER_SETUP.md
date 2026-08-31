# SOS Dispatcher Pipeline - Setup & Integration Guide

## Overview

The SOS Dispatcher is an automated notification system that sends real-time emergency alerts when agents trigger SOS signals or geofence breaches. It supports multiple delivery channels:

- **SMS (Twilio)** - Text message alerts to emergency contacts
- **Webhooks** - HTTP POST payloads to external emergency systems (SIEM, incident management, etc.)

## Architecture

```
trigger_sos() endpoint
    ↓
[Save Signal to DB]
    ↓
[Check Geofence]
    ↓
[Dispatch Alert] (async thread)
    ├→ SMS Channel (Twilio)
    └→ Webhook Channel (HTTP POST)
    
[Return Response to Client]
```

The dispatcher runs **asynchronously** in a background thread to prevent blocking the main SOS response.

## Configuration

### SMS Notifications (Twilio)

#### Prerequisites
1. Create a Twilio account at https://www.twilio.com
2. Obtain your Account SID and Auth Token from the Twilio Console
3. Purchase or provision a Twilio phone number

#### Environment Variables
```bash
ENABLE_SMS_DISPATCH=true
TWILIO_ACCOUNT_SID=AC_EXAMPLE_SID_ABC123
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+1-800-EMERGENCY
EMERGENCY_CONTACTS=+1-555-0100,+1-555-0101,+1-555-0102
```

**Note:** Phone numbers should include country code (+1 for US).

#### Cost Estimation
- Twilio outbound SMS: ~$0.0075 per message
- 1 SOS with 3 contacts = $0.0225 per incident
- For 100 incidents/month = ~$2.25

### Webhook Notifications

#### Configuration
```bash
ENABLE_WEBHOOK_DISPATCH=true
DISPATCH_WEBHOOK_URL=https://your-siem.example.com/api/emergency-alerts
```

#### Webhook Payload Format
```json
{
  "alert_type": "GEOFENCE BREACH",
  "device_id": "Agent-X-Delta",
  "timestamp": "2026-08-31T12:34:56.789123",
  "latitude": 51.5074,
  "longitude": -0.1278,
  "is_stealth_active": false,
  "status": "COMPROMISED",
  "maps_url": "https://maps.google.com/?q=51.5074,-0.1278",
  "message": "🚨 GEOFENCE BREACH DETECTED\nAgent: Agent-X-Delta\n..."
}
```

#### Expected Response
- **2xx** - Success (alert processed)
- **4xx/5xx** - Failure (logged and retried if needed)

## API Endpoints

### 1. Trigger SOS Signal
```bash
POST /api/v1/sos
Authorization: X-Agent-Key: <AGENT_SECRET_KEY>
Content-Type: application/json

{
  "device_id": "Agent-X-Delta",
  "latitude": 51.5074,
  "longitude": -0.1278,
  "is_stealth_active": true,
  "encrypted_evidence": "optional_encrypted_data"
}
```

**Behavior:**
- Saves signal to database
- Checks geofence (revokes stealth if breached)
- Dispatches alerts asynchronously
- Returns signal ID immediately

### 2. Test Dispatcher (Validation)
```bash
POST /api/v1/dispatch/test
Authorization: X-Agent-Key: <AGENT_SECRET_KEY>
```

**Response:**
```json
{
  "status": "success",
  "message": "Test alert dispatched",
  "sms_enabled": true,
  "webhook_enabled": false,
  "contacts_count": 3
}
```

**Use Case:** Verify Twilio and webhook configuration without triggering a real alert.

### 3. Get Dispatcher Status
```bash
GET /api/v1/dispatch/status
Authorization: X-Agent-Key: <AGENT_SECRET_KEY>
```

**Response:**
```json
{
  "sms_enabled": true,
  "webhook_enabled": false,
  "twilio_configured": true,
  "emergency_contacts": 3,
  "webhook_url": null
}
```

## Alert Types

### SOS Signal Alert
Sent for every regular SOS signal. Format:
```
🚨 SOS SIGNAL ALERT [2026-08-31T12:34:56]
Agent: Agent-X-Delta
Status: STEALTH ACTIVE
Location: (51.506740, -0.127800)
Google Maps: https://maps.google.com/?q=51.5074,-0.1278
```

### Geofence Breach Alert
Sent when agent enters restricted zone. Format:
```
🚨 GEOFENCE BREACH DETECTED
Agent: Agent-X-Delta
Location: (51.505200, -0.125000)
Status: STEALTH REVOKED
Maps: https://maps.google.com/?q=51.5052,-0.125
```

## Error Handling & Reliability

### Graceful Degradation
- **SMS disabled** if Twilio credentials are invalid
- **Webhook disabled** if URL is not configured
- **Missing contacts** disables SMS dispatch
- **Alert failures don't block SOS response** (async dispatch)

### Logging
All dispatch events are logged:
```
INFO: SMS sent to +1-555-0100
ERROR: SMS send failed to +1-555-0101: Invalid phone number
INFO: Webhook dispatched successfully
WARNING: SMS dispatch enabled but missing Twilio credentials
```

### Retry Logic
Currently implemented with exponential backoff in the **tracker.py** client.
Server-side dispatcher does NOT retry on failure (fires once per alert).

For production, consider:
- Message queuing (Redis, RabbitMQ)
- Retry policy with max attempts
- Dead letter queue for failed messages

## Testing & Deployment

### 1. Local Testing
```bash
# Copy and configure .env
cp .env.example .env
# Edit .env with your Twilio credentials

# Start server
uvicorn main:app --reload

# Test dispatcher (curl or Postman)
curl -X POST http://localhost:8000/api/v1/dispatch/test \
  -H "X-Agent-Key: your-secret-key"
```

### 2. Validate Configuration
```bash
# Check status
curl http://localhost:8000/api/v1/dispatch/status \
  -H "X-Agent-Key: your-secret-key"
```

### 3. Mock Webhook Testing
Use RequestBin or Webhook.cool to inspect webhook payloads:
```bash
# Generate temporary webhook URL
# https://webhook.cool/unique-id

# Set in .env
DISPATCH_WEBHOOK_URL=https://webhook.cool/unique-id
ENABLE_WEBHOOK_DISPATCH=true

# Trigger test alert and inspect payload
curl -X POST http://localhost:8000/api/v1/dispatch/test \
  -H "X-Agent-Key: your-secret-key"
```

## Production Checklist

- [ ] Twilio account funded and verified
- [ ] Emergency contact numbers validated (format: +1-555-0000)
- [ ] Webhook URL tested and responding with 2xx
- [ ] Dispatcher status endpoint confirms configuration
- [ ] Test alert successfully sent to all contacts
- [ ] Error logging configured in application monitoring
- [ ] Incident response team trained on alert formats
- [ ] Geofence coordinates validated and tested

## Future Enhancements

1. **Message Queuing** - Redis/RabbitMQ for reliable delivery
2. **Alert History** - Store dispatch events in database for audit trail
3. **Alert Escalation** - Retry failed contacts with exponential backoff
4. **Templating** - Customizable alert message templates
5. **Rate Limiting** - Prevent alert spam from same agent
6. **Multi-channel Fallback** - Switch to SMS if webhook fails, and vice versa
7. **Email Alerts** - SendGrid/AWS SES integration
8. **Slack Integration** - Direct to incident response channel

## Troubleshooting

### SMS not sending
```
❌ Check logs for:
- "missing Twilio credentials"
- "Failed to initialize Twilio: ..."
- "SMS send failed: Invalid phone number"

✅ Solution:
- Verify TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
- Validate phone number format: +1-555-0000
- Check Twilio account balance
- Test with /api/v1/dispatch/test
```

### Webhook not firing
```
❌ Check logs for:
- "Webhook failed with status 4xx/5xx"
- "Webhook dispatch failed: Connection timeout"

✅ Solution:
- Verify DISPATCH_WEBHOOK_URL is accessible
- Check webhook server logs for incoming requests
- Test with curl/Postman
- Verify JSON payload format
```

### Dispatcher not initialized
```
❌ Check logs for:
- "No dispatch channels configured"

✅ Solution:
- Set ENABLE_SMS_DISPATCH=true OR ENABLE_WEBHOOK_DISPATCH=true
- Configure required credentials for chosen channel
- Restart application
```

## Code Integration Reference

### Dispatch in trigger_sos Endpoint
```python
if geofence_breach:
    dispatcher.dispatch_alert_async(
        device_id=payload.device_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_stealth_active=stealth_status,
        alert_type="GEOFENCE BREACH",
        message="Custom message..."
    )
```

### Direct Dispatch Call (Blocking)
```python
dispatcher.dispatch_alert(
    device_id="Agent-X",
    latitude=51.5074,
    longitude=-0.1278,
    is_stealth_active=False,
    alert_type="CUSTOM"
)
```

### Async Dispatch Call (Recommended)
```python
dispatcher.dispatch_alert_async(
    device_id="Agent-X",
    latitude=51.5074,
    longitude=-0.1278,
    is_stealth_active=False,
    alert_type="CUSTOM"
)
```

---

**Last Updated:** 2026-08-31  
**Backend Lead:** CHIRAG8643  
**Status:** Production Ready ✅
