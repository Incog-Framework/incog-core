import base64
import os
import sys
from pathlib import Path

# The modules under test live one level up; add that to the path so the suite
# runs without needing the backend installed as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Configure the app before main.py is imported. These are set (not
# setdefault) so a developer's real .env can never point the suite at the
# live database or fire real SMS -- load_dotenv() does not override values
# already present in the environment.
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/incog_test"
os.environ["INCOG_API_KEY"] = "test-key-0123456789abcdef"
os.environ["EVIDENCE_AES_KEY"] = base64.b64encode(bytes(range(32))).decode()
os.environ["ENABLE_SMS_DISPATCH"] = "false"
os.environ["ENABLE_WEBHOOK_DISPATCH"] = "false"
os.environ["EMERGENCY_CONTACTS"] = ""
