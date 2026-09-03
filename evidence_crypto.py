"""
AES-256-GCM evidence decryption (Phase 11 backend side).

Wire format is produced by the Android security module, in
security-module/app/src/main/java/com/incog/incogsecuritycore/CryptoManager.kt::encrypt():

    [ 12-byte random IV ][ ciphertext || 16-byte GCM auth tag ]

...base64-encoded into SOSPayload.encrypted_evidence for transport.

Java's Cipher appends the GCM authentication tag to the ciphertext, which is
exactly the layout Python's AESGCM.decrypt() expects, so the two interoperate
byte-for-byte with no repacking. Neither side passes associated data, so AAD
is None here.

The plaintext is the UTF-8 JSON of EvidencePackage (see EvidencePackage.kt).

NOTE: this module is deliberately free of database and FastAPI imports so the
format can be unit-tested without a live Postgres.
"""

import base64
import json

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Must match CryptoManager.kt exactly.
GCM_IV_BYTES = 12
GCM_TAG_BYTES = 16
AES_256_KEY_BYTES = 32


class EvidenceError(Exception):
    """Base class for evidence decryption failures."""


class EvidenceFormatError(EvidenceError):
    """Blob was not valid base64, or was too short to be a real payload."""


class EvidenceAuthError(EvidenceError):
    """GCM tag did not verify: wrong key, or the payload was tampered with."""


def load_key(b64_key: str) -> bytes:
    """
    Decode the shared AES-256 key from its base64 representation.

    Raises ValueError (at startup, not per-request) if the key is unusable, so
    a misconfigured deploy fails loudly instead of silently rejecting evidence.
    """
    try:
        key = base64.b64decode(b64_key, validate=True)
    except Exception as exc:
        raise ValueError(f"EVIDENCE_AES_KEY is not valid base64: {exc}") from exc

    if len(key) != AES_256_KEY_BYTES:
        raise ValueError(
            f"EVIDENCE_AES_KEY must decode to {AES_256_KEY_BYTES} bytes "
            f"(AES-256), got {len(key)}"
        )
    return key


def decrypt_evidence(blob_b64: str, key: bytes) -> tuple[bytes, bytes]:
    """
    Verify and decrypt one evidence blob.

    Returns (raw_blob, plaintext). The raw blob is handed back so the caller can
    persist the *ciphertext* rather than the plaintext -- decryption here is for
    integrity verification and triage, not for storage.
    """
    try:
        raw = base64.b64decode(blob_b64, validate=True)
    except Exception as exc:
        raise EvidenceFormatError(f"evidence is not valid base64: {exc}") from exc

    # An empty-plaintext payload is still IV + tag, so anything at or below that
    # length cannot carry ciphertext and is malformed rather than merely invalid.
    if len(raw) <= GCM_IV_BYTES + GCM_TAG_BYTES:
        raise EvidenceFormatError(
            f"evidence blob too short: {len(raw)} bytes, need more than "
            f"{GCM_IV_BYTES + GCM_TAG_BYTES}"
        )

    iv = raw[:GCM_IV_BYTES]
    ciphertext_and_tag = raw[GCM_IV_BYTES:]

    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext_and_tag, None)
    except InvalidTag as exc:
        raise EvidenceAuthError(
            "evidence failed authentication: wrong key or tampered payload"
        ) from exc

    return raw, plaintext


def parse_evidence(plaintext: bytes) -> dict:
    """
    Decode the EvidencePackage JSON.

    Only ever called on plaintext that already passed GCM authentication, so a
    parse failure here means the two sides disagree on the payload schema.
    """
    try:
        decoded = plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceFormatError(f"evidence plaintext is not UTF-8: {exc}") from exc

    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise EvidenceFormatError(f"evidence plaintext is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise EvidenceFormatError(
            f"evidence JSON must be an object, got {type(parsed).__name__}"
        )
    return parsed


def encrypt_evidence(plaintext: bytes, key: bytes) -> str:
    """
    Produce a blob in CryptoManager.kt's format, base64-encoded.

    Used by tracker.py and the test-suite to simulate the Android client. The
    real evidence path is Kotlin-side; this exists so the format can be
    exercised end-to-end without an Android device in the loop.
    """
    import os as _os

    iv = _os.urandom(GCM_IV_BYTES)
    ciphertext_and_tag = AESGCM(key).encrypt(iv, plaintext, None)
    return base64.b64encode(iv + ciphertext_and_tag).decode("ascii")
