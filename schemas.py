"""
Request/response schemas for the Incog safety backend.

Kept separate from main.py so validation rules can be unit-tested without
standing up Postgres/PostGIS.
"""

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Device identifiers come from the Android client and end up in log lines and
# SMS bodies, so keep them to a conservative character set.
_ALLOWED_DEVICE_ID_EXTRA = {"-", "_"}

# E.164-ish: optional '+' then 7-15 digits, checked after separators are removed.
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")

# Humans type numbers with these; strip them rather than 422 a valid number.
_PHONE_SEPARATORS = " \t-()./"


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

    # The owner's own trusted contact, configured in the app's setup screen.
    # Both optional: older clients omit them, and a user may skip setup, so a
    # signal without a contact must still be accepted.
    contact_name: Optional[str] = Field(None, max_length=100)
    contact_phone: Optional[str] = Field(None, max_length=20)

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        if not all(c.isalnum() or c in _ALLOWED_DEVICE_ID_EXTRA for c in v):
            raise ValueError(
                "device_id must contain only letters, digits, hyphens or underscores"
            )
        return v

    @field_validator("contact_name", "contact_phone", mode="before")
    @classmethod
    def blank_contact_is_absent(cls, v):
        """
        Treat "" and whitespace as "not configured" rather than invalid.

        The Android client stores these as empty strings by default, so a user
        who skipped setup would otherwise send contact_phone="" and have every
        SOS rejected with a 422. Silently dropping the emergency signal of
        someone who never filled in the setup screen is the worst possible
        failure mode here.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("contact_name")
    @classmethod
    def tidy_contact_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        # Collapse newlines/runs of whitespace: this goes into SMS and Discord
        # bodies, where a stray newline would break the message layout.
        return " ".join(v.split())

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        compact = v
        for separator in _PHONE_SEPARATORS:
            compact = compact.replace(separator, "")
        if not _PHONE_RE.match(compact):
            raise ValueError(
                "contact_phone must be 7-15 digits, optionally prefixed with '+'"
            )
        # Store the normalised form -- it is what gets handed to Twilio.
        return compact


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
