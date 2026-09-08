"""
Per-signal trusted contact: the contact the owner configured in the app.

The signal carries it, so it is additional to the server-configured
EMERGENCY_CONTACTS rather than a replacement, and it is PII belonging to
someone who never installed the app -- so it must stay out of the logs.
"""

import pytest
from pydantic import ValidationError

import main
from main import redact_phone
from schemas import SOSPayload


def payload(**overrides):
    body = {
        "device_id": "demo-device-01",
        "latitude": 12.9412,
        "longitude": 77.5652,
        "is_stealth_active": True,
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def test_contact_fields_are_optional():
    """Older clients omit them entirely; the signal must still be accepted."""
    parsed = SOSPayload(**payload())
    assert parsed.contact_name is None
    assert parsed.contact_phone is None


def test_valid_contact_is_accepted():
    parsed = SOSPayload(
        **payload(contact_name="Amma", contact_phone="+918618065357")
    )
    assert parsed.contact_name == "Amma"
    assert parsed.contact_phone == "+918618065357"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+91 86180 65357", "+918618065357"),
        ("+91-86180-65357", "+918618065357"),
        ("(415) 523-8886", "4155238886"),
        ("  +918618065357  ", "+918618065357"),
        ("8618065357", "8618065357"),
    ],
)
def test_human_typed_numbers_are_normalised(raw, expected):
    """
    A number typed with spaces or dashes is valid input from a setup screen.
    Rejecting it would block the user's own emergency contact over formatting.
    """
    assert SOSPayload(**payload(contact_phone=raw)).contact_phone == expected


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_blank_contact_is_treated_as_absent_not_invalid(blank):
    """
    IncogConfig defaults these to "", so a user who skipped setup would send
    contact_phone="". Rejecting that would drop their emergency signal entirely
    -- the worst possible failure for a safety app.
    """
    parsed = SOSPayload(**payload(contact_phone=blank, contact_name=blank))
    assert parsed.contact_phone is None
    assert parsed.contact_name is None


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-phone",
        "+91861806535712345",   # too many digits
        "12345",                # too few
        "+",
        "555-CALL-NOW",
        "<script>alert(1)</script>",
    ],
)
def test_invalid_contact_phone_is_rejected(bad):
    with pytest.raises(ValidationError):
        SOSPayload(**payload(contact_phone=bad))


def test_contact_name_newlines_are_collapsed():
    """The name lands in SMS and Discord bodies; a newline would break layout."""
    parsed = SOSPayload(**payload(contact_name="Amma\nInjected: line"))
    assert "\n" not in parsed.contact_name
    assert parsed.contact_name == "Amma Injected: line"


def test_overlong_contact_fields_are_rejected():
    with pytest.raises(ValidationError):
        SOSPayload(**payload(contact_name="a" * 101))
    with pytest.raises(ValidationError):
        SOSPayload(**payload(contact_phone="1" * 21))


# --------------------------------------------------------------------------
# Log redaction
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phone,expected",
    [
        ("+918618065357", "**********357"),
        ("8618065357", "*******357"),
        ("123", "123"),
        (None, "(none)"),
        ("", "(none)"),
    ],
)
def test_redact_phone_keeps_only_the_last_three_digits(phone, expected):
    assert redact_phone(phone) == expected


def test_redaction_hides_the_subscriber_digits():
    redacted = redact_phone("+918618065357")
    assert "8618065" not in redacted
    assert redacted.endswith("357")


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
class FakeTwilio:
    """Records sends, and can be told to fail for one specific number."""

    def __init__(self, fail_for=None):
        self.sent = []
        self.fail_for = fail_for
        self.messages = self

    def create(self, body, from_, to):
        if self.fail_for and self.fail_for in to:
            raise RuntimeError("twilio rejected this number")
        self.sent.append({"to": to, "body": body})


def build_dispatcher(monkeypatch, contacts="", webhook=False, fail_for=None):
    monkeypatch.setenv("EMERGENCY_CONTACTS", contacts)
    monkeypatch.setenv("TWILIO_CHANNEL", "sms")
    dispatcher = main.AlertDispatcher()
    dispatcher.enable_sms = True
    dispatcher.twilio_phone = "+14155238886"
    dispatcher.twilio_client = FakeTwilio(fail_for=fail_for)
    dispatcher.enable_webhook = webhook
    dispatcher.webhook_url = "https://example.invalid/hook" if webhook else None
    return dispatcher


def recipients_of(dispatcher):
    return [m["to"] for m in dispatcher.twilio_client.sent]


def test_user_contact_is_alerted_in_addition_to_server_contacts(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="+911111111111")
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_name="Amma",
        contact_phone="+918618065357",
    )
    assert recipients_of(d) == ["+911111111111", "+918618065357"]


def test_server_contacts_still_alerted_when_no_user_contact(monkeypatch):
    """Behaviour for older clients must be unchanged."""
    d = build_dispatcher(monkeypatch, contacts="+911111111111")
    d.dispatch_alert(
        device_id="demo-device-01", latitude=12.9412, longitude=77.5652
    )
    assert recipients_of(d) == ["+911111111111"]


def test_duplicate_contact_is_not_texted_twice(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="+918618065357")
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_phone="+918618065357",
    )
    assert recipients_of(d) == ["+918618065357"]


def test_alert_is_sent_when_only_the_signal_carries_a_contact(monkeypatch):
    """No server contacts and no webhook must not mean the alert is dropped."""
    d = build_dispatcher(monkeypatch, contacts="", webhook=False)
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_phone="+918618065357",
    )
    assert recipients_of(d) == ["+918618065357"]


def test_message_names_the_trusted_contact(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="+911111111111")
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_name="Amma",
        contact_phone="+918618065357",
    )
    body = d.twilio_client.sent[0]["body"]
    assert "Trusted contact: Amma +918618065357" in body
    assert "maps.google.com" in body


def test_unnamed_contact_still_appears(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="+911111111111")
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_phone="+918618065357",
    )
    assert "Trusted contact: unnamed +918618065357" in d.twilio_client.sent[0]["body"]


def test_no_contact_line_when_none_supplied(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="+911111111111")
    d.dispatch_alert(
        device_id="demo-device-01", latitude=12.9412, longitude=77.5652
    )
    assert "Trusted contact" not in d.twilio_client.sent[0]["body"]


def test_webhook_payload_carries_the_contact(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="", webhook=True)
    captured = {}
    monkeypatch.setattr(d, "_send_webhook", lambda p: captured.update(p) or True)
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_name="Amma",
        contact_phone="+918618065357",
    )
    assert captured["contact_name"] == "Amma"
    assert captured["contact_phone"] == "+918618065357"
    # Whoever monitors the channel needs the real number to call.
    assert "Trusted contact: Amma +918618065357" in captured["content"]


def test_failing_to_reach_the_user_contact_does_not_block_the_others(monkeypatch):
    """
    A bad number from a user's setup screen must not cost the server contacts
    their alert, nor the webhook.
    """
    d = build_dispatcher(
        monkeypatch, contacts="+911111111111", webhook=True, fail_for="+918618065357"
    )
    webhook_fired = []
    monkeypatch.setattr(d, "_send_webhook", lambda p: webhook_fired.append(p) or True)

    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_phone="+918618065357",
    )

    assert recipients_of(d) == ["+911111111111"]  # server contact still got it
    assert len(webhook_fired) == 1                # webhook still fired


def test_dispatch_thread_swallows_failures(monkeypatch):
    """A crash in the dispatch thread must never surface to the request."""
    d = build_dispatcher(monkeypatch, contacts="+911111111111")

    def boom(**_):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(d, "dispatch_alert", boom)
    d.dispatch_alert_async(device_id="x", latitude=0.0, longitude=0.0)  # must not raise


# --------------------------------------------------------------------------
# Did the device's own SMS get through? (hybrid dispatch)
# --------------------------------------------------------------------------
def test_contact_sms_sent_is_optional():
    """Older clients do not report it; that must read as 'unknown', not False."""
    assert SOSPayload(**payload()).contact_sms_sent is None


@pytest.mark.parametrize("value", ["", "  "])
def test_blank_contact_sms_sent_is_absent(value):
    assert SOSPayload(**payload(contact_sms_sent=value)).contact_sms_sent is None


@pytest.mark.parametrize("raw,expected", [(True, True), (False, False)])
def test_contact_sms_sent_round_trips(raw, expected):
    assert SOSPayload(**payload(contact_sms_sent=raw)).contact_sms_sent is expected


def alert_body(monkeypatch, **kwargs):
    d = build_dispatcher(monkeypatch, contacts="+911111111111")
    d.dispatch_alert(
        device_id="demo-device-01", latitude=12.9412, longitude=77.5652, **kwargs
    )
    return d.twilio_client.sent[0]["body"]


def test_alert_says_the_device_already_texted_them(monkeypatch):
    body = alert_body(
        monkeypatch, contact_phone="+918618065357", contact_sms_sent=True
    )
    assert "device already texted them" in body


def test_alert_shouts_when_the_device_could_not_text_them(monkeypatch):
    """
    This is the case a responder must act on: the primary path failed, so
    somebody has to phone the contact themselves.
    """
    body = alert_body(
        monkeypatch, contact_phone="+918618065357", contact_sms_sent=False
    )
    assert "DEVICE COULD NOT TEXT THEM - CALL THEM" in body


def test_alert_says_unknown_for_older_clients(monkeypatch):
    body = alert_body(monkeypatch, contact_phone="+918618065357")
    assert "unknown whether the device texted them" in body


def test_no_delivery_note_without_a_contact(monkeypatch):
    body = alert_body(monkeypatch, contact_sms_sent=True)
    assert "texted them" not in body
    assert "Trusted contact" not in body


def test_webhook_payload_reports_device_sms_status(monkeypatch):
    d = build_dispatcher(monkeypatch, contacts="", webhook=True)
    captured = {}
    monkeypatch.setattr(d, "_send_webhook", lambda p: captured.update(p) or True)
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_phone="+918618065357",
        contact_sms_sent=False,
    )
    assert captured["contact_sms_sent"] is False


def test_backend_still_alerts_the_contact_even_if_the_device_already_did(monkeypatch):
    """
    Redundancy is the point: a duplicate message is a trivial cost next to a
    missed one, so the backend does not skip its own send.
    """
    d = build_dispatcher(monkeypatch, contacts="")
    d.dispatch_alert(
        device_id="demo-device-01",
        latitude=12.9412,
        longitude=77.5652,
        contact_phone="+918618065357",
        contact_sms_sent=True,
    )
    assert recipients_of(d) == ["+918618065357"]
