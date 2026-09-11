"""
Request/response schemas for the Incog safety backend.

Kept separate from main.py so validation rules can be unit-tested without
standing up Postgres/PostGIS.
"""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Device identifiers come from the Android client and end up in log lines and
# SMS bodies, so keep them to a conservative character set.
_ALLOWED_DEVICE_ID_EXTRA = {"-", "_"}

# E.164-ish: optional '+' then 7-15 digits, checked after separators are removed.
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")

# Humans type numbers with these; strip them rather than 422 a valid number.
_PHONE_SEPARATORS = " \t-()./"

# Nobody has more trusted contacts than this, and without a ceiling anyone
# holding the API key could post thousands of numbers and use the alert path
# as a free SMS relay.
MAX_TRUSTED_CONTACTS = 10


def _normalise_phone(value: str) -> str:
    """Strip human separators, then require '+' and 7-15 digits."""
    compact = value
    for separator in _PHONE_SEPARATORS:
        compact = compact.replace(separator, "")
    if not _PHONE_RE.match(compact):
        raise ValueError(
            "phone must be 7-15 digits, optionally prefixed with '+'"
        )
    return compact


def _blank_to_none(value):
    """Empty/whitespace strings mean "not configured", not "invalid"."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


class TrustedContact(BaseModel):
    """One person the owner chose to be alerted, from the app's setup screen."""

    name: Optional[str] = Field(None, max_length=100)
    phone: str = Field(..., max_length=20)

    # Whether the device's own SMS to this contact got through.
    # None = the device did not try; False = it tried and failed.
    sms_sent: Optional[bool] = None

    @field_validator("name", "sms_sent", mode="before")
    @classmethod
    def blank_is_absent(cls, v):
        return _blank_to_none(v)

    @field_validator("name")
    @classmethod
    def tidy_name(cls, v: Optional[str]) -> Optional[str]:
        return " ".join(v.split()) if v else None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _normalise_phone(v)


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

    # Did the device manage to SMS the contact itself, before uploading?
    # The app sends that SMS over the cellular network, which works where data
    # does not, so it is the primary path; this backend alert is the fallback
    # for when the phone is taken, broken, or out of credit. None means an
    # older client that does not report it.
    contact_sms_sent: Optional[bool] = None

    # The full list. Newer clients send every configured contact here and also
    # mirror the first into the three legacy fields above, so a backend that
    # only reads those still alerts somebody. When this is present it wins.
    contacts: Optional[List[TrustedContact]] = Field(
        None, max_length=MAX_TRUSTED_CONTACTS
    )

    def resolved_contacts(self) -> List[dict]:
        """
        The contacts to alert, from whichever form the client sent.

        Prefers the array; falls back to the legacy single fields so older
        APKs keep working unchanged. Deduplicated by phone number, preserving
        order, so the legacy mirror of contact #1 cannot cause a double alert.
        """
        if self.contacts:
            candidates = [
                {"name": c.name, "phone": c.phone, "sms_sent": c.sms_sent}
                for c in self.contacts
            ]
        elif self.contact_phone:
            candidates = [
                {
                    "name": self.contact_name,
                    "phone": self.contact_phone,
                    "sms_sent": self.contact_sms_sent,
                }
            ]
        else:
            return []

        seen, unique = set(), []
        for contact in candidates:
            if contact["phone"] not in seen:
                seen.add(contact["phone"])
                unique.append(contact)
        return unique

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        if not all(c.isalnum() or c in _ALLOWED_DEVICE_ID_EXTRA for c in v):
            raise ValueError(
                "device_id must contain only letters, digits, hyphens or underscores"
            )
        return v

    @field_validator("contact_name", "contact_phone", "contact_sms_sent", mode="before")
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
        return _blank_to_none(v)

    @field_validator("contact_name")
    @classmethod
    def tidy_contact_name(cls, v: Optional[str]) -> Optional[str]:
        # Collapse newlines/runs of whitespace: this goes into SMS and Discord
        # bodies, where a stray newline would break the message layout.
        return " ".join(v.split()) if v else None

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, v: Optional[str]) -> Optional[str]:
        # Normalised on the way through -- this is what gets handed to Twilio.
        return _normalise_phone(v) if v is not None else None


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
