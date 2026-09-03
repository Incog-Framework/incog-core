"""
Request/response schemas for the Incog safety backend.

Kept separate from main.py so validation rules can be unit-tested without
standing up Postgres/PostGIS.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Device identifiers come from the Android client and end up in log lines and
# SMS bodies, so keep them to a conservative character set.
_ALLOWED_DEVICE_ID_EXTRA = {"-", "_"}


class SOSPayload(BaseModel):
    """One emergency signal from a user's device."""

    device_id: str = Field(..., min_length=1, max_length=50)
    latitude: float = Field(..., ge=-90, le=90, description="WGS84 latitude, -90..90")
    longitude: float = Field(..., ge=-180, le=180, description="WGS84 longitude, -180..180")

    # Whether the app is currently running in its disguised ("ghost") mode.
    # Reported by the client only -- the backend never changes it.
    is_stealth_active: bool

    # Base64 of [12-byte IV][ciphertext||16-byte GCM tag]; see evidence_crypto.
    encrypted_evidence: Optional[str] = None

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        if not all(c.isalnum() or c in _ALLOWED_DEVICE_ID_EXTRA for c in v):
            raise ValueError(
                "device_id must contain only letters, digits, hyphens or underscores"
            )
        return v


class SOSResponse(BaseModel):
    status: str
    message: str
    signal_id: int
    # True when an evidence blob was attached, authenticated and stored.
    evidence_stored: bool = False


class SignalRecord(BaseModel):
    """Latest known position for one device."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: str
    timestamp: datetime
    is_stealth_active: bool
    latitude: float
    longitude: float
