import requests
import time
import random
import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

# Load the secrets
load_dotenv()

URL = "https://incog-c2-backend.onrender.com/api/v1/sos"
AGENT_SECRET_KEY = os.getenv("AGENT_SECRET_KEY")

# Setup Encryption
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    print("❌ ERROR: ENCRYPTION_KEY not found in .env!")
    exit(1)
    
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

DEVICE_ID = "Agent-X-Delta"

# Starting coordinates (Central London)
current_lat = 51.5074
current_lon = -0.1278

print("========================================")
print(f"📡 ACTIVATING SECURE TRACKER FOR: {DEVICE_ID}")
print("========================================")
print("Sending encrypted GPS coordinates... Press Ctrl+C to stop.")

try:
    while True:
        # Move the agent randomly simulating walking
        current_lat += random.uniform(-0.002, 0.002)
        current_lon += random.uniform(-0.002, 0.002)
        
        # Package the standard GPS data
        payload = {
            "device_id": DEVICE_ID,
            "latitude": current_lat,
            "longitude": current_lon,
            "is_stealth_active": True
        }
        
        # 10% chance to send an encrypted secret message on this ping
        if random.randint(1, 10) == 1:
            secret_message = f"Intercepted intel at {time.strftime('%H:%M:%S')} - Awaiting extraction."
            # Encrypt the text into garbled bytes, then convert to string for JSON transmission
            encrypted_bytes = cipher_suite.encrypt(secret_message.encode())
            payload["encrypted_evidence"] = encrypted_bytes.decode()
            print(f"\n🔒 ENCRYPTION PAYLOAD: '{secret_message}'")
            print("📤 Attaching to signal...")

        # Package the secret API key into the HTTP Headers
        headers = {
            "X-Agent-Key": AGENT_SECRET_KEY
        }
        
        try:
            print(f"[{time.strftime('%H:%M:%S' )}] 📤 Sending packet to cloud...")
            response = requests.post(URL, json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                print(f"[{time.strftime('%H:%M:%S')}] ✅ Target updated: {current_lat:.4f}, {current_lon:.4f}")
            elif response.status_code == 403:
                print(f"[{time.strftime('%H:%M:%S')}] 🚨 ACCESS DENIED: Incorrect Secret Key!")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] ❌ Server rejected the data: {response.status_code} - {response.text}")
                
        except requests.exceptions.Timeout:
            print(f"[{time.strftime('%H:%M:%S')}] ⏳ Connection timed out. Render free tier may be waking up...")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Connection failed: {e}")
            
        # Wait 3 seconds before moving the agent again
        time.sleep(3)

except KeyboardInterrupt:
    print("\n🛑 Tracker deactivated.")