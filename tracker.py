"""
Local simulator for the Incog backend.

Stands in for the Android client during development: walks a fake device around
a starting point, posts emergency signals, and occasionally attaches an
AES-256-GCM evidence blob in the same wire format the security module produces.

This is a development tool, not part of the deployed service.
"""

import json
import logging
import os
import random
import time
import uuid

import requests
from dotenv import load_dotenv

from evidence_crypto import encrypt_evidence, load_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tracker")

load_dotenv()

URL = os.getenv("C2_SERVER_URL", "http://localhost:8000/api/v1/sos")

API_KEY = os.getenv("INCOG_API_KEY") or os.getenv("AGENT_SECRET_KEY")
if not API_KEY:
    logger.error("INCOG_API_KEY is not set in .env")
    raise SystemExit(1)

# Evidence is optional: without a key the simulator still exercises the
# location and alerting path, which is the part that matters most.
EVIDENCE_KEY = None
_evidence_key_b64 = os.getenv("EVIDENCE_AES_KEY")
if _evidence_key_b64:
    try:
        EVIDENCE_KEY = load_key(_evidence_key_b64)
    except ValueError as exc:
        logger.error(f"{exc}")
        raise SystemExit(1)
else:
    logger.warning("EVIDENCE_AES_KEY not set - sending location signals only.")

DEVICE_ID = os.getenv("DEVICE_ID", "demo-device-01")

# Defaults to BMSCE, Bangalore.
current_lat = float(os.getenv("SIM_START_LAT", "12.9412"))
current_lon = float(os.getenv("SIM_START_LON", "77.5652"))

POLL_INTERVAL = 3
MAX_CONSECUTIVE_FAILURES = 10
MAX_BACKOFF = 300
EVIDENCE_CHANCE_IN = 10  # roughly one signal in ten carries evidence


def build_evidence_package() -> bytes:
    """
    Build a payload shaped like the security module's EvidencePackage.

    Mirrors EvidencePackage.kt / AIResult.kt so the backend's parsing and
    triage-metadata extraction get exercised for real.
    """
    session_id = str(uuid.uuid4())
    now_ms = int(time.time() * 1000)

    package = {
        "sessionId": session_id,
        "timestamp": now_ms,
        "gps": {"lat": current_lat, "lng": current_lon},
        # The real client attaches a compressed audio buffer here.
        "audioBase64": "",
        "featureVector": {
            "peakAcceleration": round(random.uniform(12.0, 30.0), 3),
            "motionVariance": round(random.uniform(0.5, 6.0), 3),
            "audioEnergy": round(random.uniform(0.2, 0.95), 3),
            "gpsVelocity": round(random.uniform(0.0, 4.0), 3),
            "possibleFall": random.random() < 0.3,
        },
        "aiResult": {
            "SessionID": session_id,
            "TimestampMs": now_ms,
            "Prediction": "emergency",
            "Confidence": round(random.uniform(0.76, 0.99), 4),
            "EmergencyStatus": True,
            "DecisionThreshold": 0.75,
            "SHAP": {"audioEnergy": 0.41, "peakAcceleration": 0.33, "gpsVelocity": -0.12},
            "LIME": {"audioEnergy": 0.38, "peakAcceleration": 0.29, "gpsVelocity": -0.09},
        },
    }
    return json.dumps(package).encode("utf-8")


logger.info("Incog tracker simulator")
logger.info(f"Device: {DEVICE_ID}")
logger.info(f"Target: {URL}")
logger.info("Ctrl+C to stop.")

consecutive_failures = 0

try:
    while True:
        # Wander a little, simulating someone walking.
        current_lat += random.uniform(-0.002, 0.002)
        current_lon += random.uniform(-0.002, 0.002)
        current_lat = max(-90.0, min(90.0, current_lat))
        current_lon = max(-180.0, min(180.0, current_lon))

        payload = {
            "device_id": DEVICE_ID,
            "latitude": current_lat,
            "longitude": current_lon,
            "is_stealth_active": True,
        }

        if EVIDENCE_KEY and random.randint(1, EVIDENCE_CHANCE_IN) == 1:
            payload["encrypted_evidence"] = encrypt_evidence(
                build_evidence_package(), EVIDENCE_KEY
            )
            logger.info("Attaching encrypted evidence to this signal")

        headers = {"X-Incog-Key": API_KEY, "Content-Type": "application/json"}

        try:
            response = requests.post(URL, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                body = response.json()
                suffix = " (evidence stored)" if body.get("evidence_stored") else ""
                logger.info(
                    f"Signal accepted: ({current_lat:.4f}, {current_lon:.4f}){suffix}"
                )
                consecutive_failures = 0
            elif response.status_code == 403:
                logger.error("Rejected: invalid or missing API key")
                consecutive_failures += 1
            elif response.status_code == 503:
                logger.error(f"Server cannot accept evidence: {response.text}")
                consecutive_failures += 1
            else:
                logger.error(f"Server returned {response.status_code}: {response.text}")
                consecutive_failures += 1

        except requests.exceptions.Timeout:
            logger.warning("Request timed out")
            consecutive_failures += 1
        except requests.exceptions.ConnectionError:
            logger.warning("Connection failed - is the server running?")
            consecutive_failures += 1
        except Exception as exc:
            logger.error(f"Unexpected error: {exc}")
            consecutive_failures += 1

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            backoff = min(
                2 ** (consecutive_failures - MAX_CONSECUTIVE_FAILURES), MAX_BACKOFF
            )
            logger.critical(
                f"{consecutive_failures} consecutive failures; backing off {backoff}s"
            )
            time.sleep(backoff)
        else:
            time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    logger.info("Tracker stopped.")
