# SOS Dispatcher - Quick Start Guide

## 5-Minute Setup

### Step 1: Configure Environment Variables
```bash
# Copy template
cp .env.example .env

# Edit .env and fill in:
# - TWILIO_ACCOUNT_SID (from Twilio Console)
# - TWILIO_AUTH_TOKEN (from Twilio Console)
# - TWILIO_PHONE_NUMBER (your Twilio number, e.g., +1-800-EMERGENCY)
# - EMERGENCY_CONTACTS (+1-555-0100,+1-555-0101,...)
```

### Step 2: Verify Installation
```bash
# Twilio SDK is already in requirements.txt
pip install -r requirements.txt

# Start the server
uvicorn main:app --reload
```

### Step 3: Test Dispatcher
```bash
# Test endpoint (curl or Postman)
curl -X POST http://localhost:8000/api/v1/dispatch/test \
  -H "X-Agent-Key: your-secret-agent-key"

# Response should show configuration
{
  "status": "success",
  "sms_enabled": true,
  "webhook_enabled": false,
  "contacts_count": 3
}
```

### Step 4: Check Status
```bash
curl http://localhost:8000/api/v1/dispatch/status \
  -H "X-Agent-Key: your-secret-agent-key"
```

## How It Works

### Automatic Alert Dispatch
When an SOS signal is received:

1. **Regular SOS** → Sends SMS to all emergency contacts
2. **Geofence Breach** → Sends urgent breach alert + revokes stealth

### No Manual Configuration Needed
- Dispatcher auto-initializes when app starts
- Gracefully disables SMS if Twilio credentials missing
- Webhook dispatch is optional

### Alert Flow
```
SOS Signal Received
    ↓
[Save to Database]
    ↓
[Check Geofence]
    ↓
[Dispatch Alert] (Async - doesn't block response)
    ├→ SMS (if enabled)
    └→ Webhook (if enabled)
    ↓
[Immediate Response to Client]
```

## Alert Message Examples

### SOS Signal Alert
```
🚨 SOS SIGNAL ALERT [2026-08-31T12:34:56]
Agent: Agent-X-Delta
Status: STEALTH ACTIVE
Location: (51.506740, -0.127800)
Google Maps: https://maps.google.com/?q=51.5074,-0.1278
```

### Geofence Breach Alert
```
🚨 GEOFENCE BREACH DETECTED
Agent: Agent-X-Delta
Location: (51.505200, -0.125000)
Status: STEALTH REVOKED
Maps: https://maps.google.com/?q=51.5052,-0.125
```

## Configuration Examples

### SMS Only (Default)
```bash
# .env
ENABLE_SMS_DISPATCH=true
TWILIO_ACCOUNT_SID=ACxxxxxx
TWILIO_AUTH_TOKEN=xxxxxx
TWILIO_PHONE_NUMBER=+1-800-EMERGENCY
EMERGENCY_CONTACTS=+1-555-0100,+1-555-0101
```

### Webhook Only
```bash
# .env
ENABLE_SMS_DISPATCH=false
ENABLE_WEBHOOK_DISPATCH=true
DISPATCH_WEBHOOK_URL=https://your-siem.example.com/alerts
```

### Both SMS + Webhook
```bash
# .env
ENABLE_SMS_DISPATCH=true
ENABLE_WEBHOOK_DISPATCH=true
TWILIO_ACCOUNT_SID=ACxxxxxx
TWILIO_AUTH_TOKEN=xxxxxx
TWILIO_PHONE_NUMBER=+1-800-EMERGENCY
EMERGENCY_CONTACTS=+1-555-0100
DISPATCH_WEBHOOK_URL=https://your-siem.example.com/alerts
```

### Disable Dispatcher
```bash
# .env
ENABLE_SMS_DISPATCH=false
ENABLE_WEBHOOK_DISPATCH=false
```

## API Reference

### Trigger SOS (Auto-Dispatches Alert)
```bash
POST /api/v1/sos
X-Agent-Key: <key>
Content-Type: application/json

{
  "device_id": "Agent-X",
  "latitude": 51.5074,
  "longitude": -0.1278,
  "is_stealth_active": true
}
```

### Test Dispatcher
```bash
POST /api/v1/dispatch/test
X-Agent-Key: <key>

# Optional query params
?device_id=CUSTOM-AGENT
```

### Get Status
```bash
GET /api/v1/dispatch/status
X-Agent-Key: <key>
```

## Troubleshooting

### Alerts Not Sending?

**Check 1: Verify Configuration**
```bash
curl http://localhost:8000/api/v1/dispatch/status \
  -H "X-Agent-Key: key"
```

**Check 2: Test Dispatcher**
```bash
curl -X POST http://localhost:8000/api/v1/dispatch/test \
  -H "X-Agent-Key: key"
```

**Check 3: Review Server Logs**
```
Look for:
- "Twilio SMS dispatcher initialized" → SMS ready
- "SMS send failed" → Invalid phone number or account issue
- "No dispatch channels configured" → Enable SMS or webhook
```

### Twilio Issues?

| Error | Solution |
|-------|----------|
| `Failed to initialize Twilio` | Check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN |
| `SMS send failed: Invalid phone number` | Verify EMERGENCY_CONTACTS format: +1-555-0000 |
| `SMS send failed: Permission denied` | Twilio account not in active state (check Twilio Console) |

### Webhook Issues?

| Error | Solution |
|-------|----------|
| `Webhook failed with status 4xx/5xx` | Check webhook URL is correct and responding |
| `Connection timeout` | Webhook server may be offline, check firewall |
| `JSON decode error` | Webhook server rejecting JSON format |

## Common Use Cases

### Emergency Response Team Integration
```bash
# Webhook to Slack
DISPATCH_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### SIEM Integration
```bash
# Webhook to Splunk/ELK
DISPATCH_WEBHOOK_URL=https://splunk.yourcompany.com/api/events
```

### Multiple Contact Groups
```bash
# Field response
EMERGENCY_CONTACTS=+1-555-0100
ENABLE_WEBHOOK_DISPATCH=true
DISPATCH_WEBHOOK_URL=https://dispatch-service.example.com/field-ops

# Admin escalation via separate webhook
# Can add custom endpoint for admin alerts
```

## Performance Notes

- **Alert Latency:** <100ms (async dispatch doesn't block SOS response)
- **SMS Delivery:** 1-10 seconds (Twilio latency)
- **Webhook Delivery:** <1 second (HTTP timeout: 10s)
- **Thread Overhead:** Minimal (one thread per alert, cleans up automatically)

## Security Considerations

✅ **What's Secure:**
- API key required for all dispatcher endpoints
- Credentials loaded from environment (not hardcoded)
- No credentials logged or exposed
- Webhook errors don't reveal sensitive data

⚠️ **What to Watch:**
- Protect your TWILIO_AUTH_TOKEN in version control
- Validate webhook URLs point to trusted servers
- Monitor alert volume to detect abuse

---

**Need Help?** Check [DISPATCHER_SETUP.md](./DISPATCHER_SETUP.md) for detailed configuration guide.
