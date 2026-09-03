"""
Tests for the AES-256-GCM evidence format.

The point of this suite is interoperability: the backend must accept exactly
what CryptoManager.kt produces, and reject everything else. The layout
assertions below are what would catch a silent drift between the two sides.
"""

import base64
import json

import pytest

from evidence_crypto import (
    AES_256_KEY_BYTES,
    GCM_IV_BYTES,
    GCM_TAG_BYTES,
    EvidenceAuthError,
    EvidenceFormatError,
    decrypt_evidence,
    encrypt_evidence,
    load_key,
    parse_evidence,
)

# Fixed vector, generated with key = bytes(range(32)) and IV = bytes(range(12)).
# AES-GCM is deterministic for a fixed key/IV/plaintext, so this pins the wire
# format: if the IV placement, tag length or tag position ever changes, this
# fails. Kotlin's CryptoManager.encrypt() produces the identical layout.
KAT_KEY_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
KAT_BLOB_B64 = (
    "AAECAwQFBgcICQoLPCClfraWq3TjCPOpi8sTDPf7twTBWXNeTA6I4G4dYd9xMpTNmPEiqESU"
    "T924txgIk7x4XWmgIMVDLbiycJXIuWA="
)
KAT_PLAINTEXT = b'{"sessionId":"kat-001","timestamp":1700000000000}'


@pytest.fixture
def key() -> bytes:
    return bytes(range(AES_256_KEY_BYTES))


# --------------------------------------------------------------------------
# Key loading
# --------------------------------------------------------------------------
def test_load_key_accepts_valid_256_bit_key(key):
    assert load_key(base64.b64encode(key).decode()) == key


def test_load_key_rejects_wrong_length():
    short = base64.b64encode(b"\x00" * 16).decode()
    with pytest.raises(ValueError, match="32 bytes"):
        load_key(short)


def test_load_key_rejects_invalid_base64():
    with pytest.raises(ValueError, match="base64"):
        load_key("not!valid!base64!")


# --------------------------------------------------------------------------
# Wire format
# --------------------------------------------------------------------------
def test_known_answer_vector_decrypts(key):
    """Pins the exact byte layout shared with CryptoManager.kt."""
    assert load_key(KAT_KEY_B64) == key
    _, plaintext = decrypt_evidence(KAT_BLOB_B64, key)
    assert plaintext == KAT_PLAINTEXT


def test_blob_overhead_is_iv_plus_tag(key):
    """
    A GCM blob is IV + ciphertext + tag, and ciphertext is the same length as
    the plaintext. Java appends the tag to the ciphertext, which is what Python
    expects, so the total overhead must be exactly 28 bytes.
    """
    plaintext = b"x" * 100
    raw = base64.b64decode(encrypt_evidence(plaintext, key))
    assert len(raw) == GCM_IV_BYTES + len(plaintext) + GCM_TAG_BYTES


def test_round_trip(key):
    plaintext = json.dumps({"sessionId": "abc", "timestamp": 1}).encode()
    _, decrypted = decrypt_evidence(encrypt_evidence(plaintext, key), key)
    assert decrypted == plaintext


def test_decrypt_returns_original_ciphertext_for_storage(key):
    """The raw blob is handed back so the caller can store ciphertext, not plaintext."""
    blob_b64 = encrypt_evidence(b"secret", key)
    raw, plaintext = decrypt_evidence(blob_b64, key)
    assert raw == base64.b64decode(blob_b64)
    assert plaintext not in raw  # plaintext is not recoverable from what we persist


def test_each_encryption_uses_a_fresh_iv(key):
    """Reusing an IV under one key would be catastrophic for GCM."""
    blobs = {encrypt_evidence(b"same plaintext", key)[:16] for _ in range(50)}
    assert len(blobs) == 50


# --------------------------------------------------------------------------
# Rejection paths
# --------------------------------------------------------------------------
def test_wrong_key_fails_authentication(key):
    blob = encrypt_evidence(b"sensitive", key)
    other_key = bytes([b ^ 0xFF for b in key])
    with pytest.raises(EvidenceAuthError):
        decrypt_evidence(blob, other_key)


def test_tampered_ciphertext_fails_authentication(key):
    raw = bytearray(base64.b64decode(encrypt_evidence(b"sensitive payload", key)))
    raw[GCM_IV_BYTES + 2] ^= 0x01  # flip one bit of ciphertext
    with pytest.raises(EvidenceAuthError):
        decrypt_evidence(base64.b64encode(bytes(raw)).decode(), key)


def test_tampered_iv_fails_authentication(key):
    raw = bytearray(base64.b64decode(encrypt_evidence(b"sensitive payload", key)))
    raw[0] ^= 0x01
    with pytest.raises(EvidenceAuthError):
        decrypt_evidence(base64.b64encode(bytes(raw)).decode(), key)


def test_truncated_tag_fails_authentication(key):
    raw = base64.b64decode(encrypt_evidence(b"sensitive payload", key))[:-1]
    with pytest.raises(EvidenceAuthError):
        decrypt_evidence(base64.b64encode(raw).decode(), key)


def test_blob_of_only_iv_and_tag_is_malformed(key):
    raw = b"\x00" * (GCM_IV_BYTES + GCM_TAG_BYTES)
    with pytest.raises(EvidenceFormatError, match="too short"):
        decrypt_evidence(base64.b64encode(raw).decode(), key)


def test_short_blob_is_malformed(key):
    with pytest.raises(EvidenceFormatError, match="too short"):
        decrypt_evidence(base64.b64encode(b"tiny").decode(), key)


def test_empty_blob_is_malformed(key):
    with pytest.raises(EvidenceFormatError):
        decrypt_evidence("", key)


def test_non_base64_blob_is_malformed(key):
    with pytest.raises(EvidenceFormatError, match="base64"):
        decrypt_evidence("this is definitely not base64!!", key)


# --------------------------------------------------------------------------
# Plaintext parsing
# --------------------------------------------------------------------------
def test_parse_evidence_package_shape():
    """Mirrors EvidencePackage.kt, including the AIResult PascalCase keys."""
    package = {
        "sessionId": "session-1",
        "timestamp": 1700000000000,
        "gps": {"lat": 12.9412, "lng": 77.5652},
        "audioBase64": "",
        "featureVector": {
            "peakAcceleration": 18.2,
            "motionVariance": 3.1,
            "audioEnergy": 0.8,
            "gpsVelocity": 1.2,
            "possibleFall": True,
        },
        "aiResult": {
            "SessionID": "session-1",
            "Prediction": "emergency",
            "Confidence": 0.93,
            "EmergencyStatus": True,
            "DecisionThreshold": 0.75,
            "SHAP": {"audioEnergy": 0.41},
            "LIME": {"audioEnergy": 0.38},
        },
    }
    parsed = parse_evidence(json.dumps(package).encode())
    assert parsed["sessionId"] == "session-1"
    assert parsed["timestamp"] == 1700000000000
    assert parsed["aiResult"]["EmergencyStatus"] is True


def test_parse_evidence_rejects_non_json():
    with pytest.raises(EvidenceFormatError, match="JSON"):
        parse_evidence(b"plain text, not json")


def test_parse_evidence_rejects_json_array():
    with pytest.raises(EvidenceFormatError, match="object"):
        parse_evidence(b'["not", "an", "object"]')


def test_parse_evidence_rejects_invalid_utf8():
    with pytest.raises(EvidenceFormatError, match="UTF-8"):
        parse_evidence(b"\xff\xfe\x00invalid")
