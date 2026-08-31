import requests
import time
import random
import os
import base64
import logging
from dotenv import load_dotenv
from cryptography.fernet import Fernet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load the secrets
load_dotenv()

# Configuration from environment
URL = os.getenv("C2_SERVER_URL", "https://incog-c2-backend.onrender.com/api/v1/sos")
AGENT_SECRET_KEY = os.getenv("AGENT_SECRET_KEY")
if not AGENT_SECRET_KEY:
    logger.error("CRITICAL: AGENT_SECRET_KEY not found in .env!")
    exit(1)

# Setup Encryption with validation
def validate_fernet_key(key_str: str) -> Fernet:
    try:
        return Fernet(key_str.encode())
    except Exception as e:
        raise ValueError(f"CRITICAL: Invalid ENCRYPTION_KEY - must be valid Fernet key. Error: {e}")

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    logger.error("CRITICAL: ENCRYPTION_KEY not found in .env!")
    exit(1)

try:
    cipher_suite = validate_fernet_key(ENCRYPTION_KEY)
except ValueError as e:
    logger.error(str(e))
    exit(1)

DEVICE_ID = "Agent-X-Delta"

# Starting coordinates (Central London)
current_lat = 51.5074
current_lon = -0.1278

logger.info("=" * 50)
logger.info(f"📡 ACTIVATING SECURE TRACKER FOR: {DEVICE_ID}")
logger.info(f"Target URL: {URL}")
logger.info("=" * 50)

consecutive_failures = 0
MAX_CONSECUTIVE_FAILURES = 10
POLL_INTERVAL = 3
MAX_BACKOFF = 300

try:
    while True:
        # Move the agent randomly simulating walking
        current_lat += random.uniform(-0.002, 0.002)
        current_lon += random.uniform(-0.002, 0.002)

        # Clamp to valid coordinates
        current_lat = max(-90, min(90, current_lat))
        current_lon = max(-180, min(180, current_lon))

        # Package the standard GPS data
        payload = {
            "device_id": DEVICE_ID,
            "latitude": current_lat,
            "longitude": current_lon,
            "is_stealth_active": True
        }

        # 10% chance to send an encrypted secret message
        if random.randint(1, 10) == 1:
            secret_message = f"Intercepted intel at {time.strftime('%H:%M:%S')} - Awaiting extraction."
            encrypted_bytes = cipher_suite.encrypt(secret_message.encode('utf-8'))
            payload["encrypted_evidence"] = base64.b64encode(encrypted_bytes).decode('utf-8')
            logger.info(f"🔒 Encrypted payload attached: '{secret_message}'")

        # Package the secret API key into headers
        headers = {
            "X-Agent-Key": AGENT_SECRET_KEY,
            "Content-Type": "application/json"
        }

        try:
            logger.info(f"[{time.strftime('%H:%M:%S')}] 📤 Sending packet to {URL}...")
            response = requests.post(URL, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                logger.info(f"[{time.strftime('%H:%M:%S')}] ✅ Target updated: ({current_lat:.4f}, {current_lon:.4f})")
                consecutive_failures = 0
            elif response.status_code == 403:
                logger.error(f"[{time.strftime('%H:%M:%S')}] 🚨 ACCESS DENIED: Invalid API Key")
                consecutive_failures += 1
            elif response.status_code == 400:
                logger.error(f"[{time.strftime('%H:%M:%S')}] ❌ Bad Request: {response.text}")
                consecutive_failures += 1
            else:
                logger.error(f"[{time.strftime('%H:%M:%S')}] ❌ Server error {response.status_code}: {response.text}")
                consecutive_failures += 1

        except requests.exceptions.Timeout:
            logger.warning(f"[{time.strftime('%H:%M:%S')}] ⏳ Connection timeout")
            consecutive_failures += 1
        except requests.exceptions.ConnectionError:
            logger.warning(f"[{time.strftime('%H:%M:%S')}] 🌐 Connection error - server may be offline")
            consecutive_failures += 1
        except Exception as e:
            logger.error(f"[{time.strftime('%H:%M:%S')}] ❌ Unexpected error: {e}")
            consecutive_failures += 1

        # Exponential backoff on consecutive failures
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            backoff = min(2 ** (consecutive_failures - MAX_CONSECUTIVE_FAILURES), MAX_BACKOFF)
            logger.critical(f"❌ {consecutive_failures} consecutive failures. Backing off for {backoff}s")
            time.sleep(backoff)
        else:
            time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    logger.info("\n🛑 Tracker deactivated.")