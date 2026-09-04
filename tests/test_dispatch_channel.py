"""
Twilio channel selection (SMS vs WhatsApp sandbox).

Twilio trial accounts reject free-form SMS bodies with error 572006 - trial SMS
must use a predefined template, which has nowhere to put coordinates or a Maps
link. The WhatsApp sandbox accepts arbitrary text, so the alert survives intact.
The only wire difference is a 'whatsapp:' prefix on both addresses, and getting
that wrong fails silently at Twilio rather than locally.
"""

import pytest

import main


def dispatcher_with(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return main.AlertDispatcher()


def test_defaults_to_sms(monkeypatch):
    monkeypatch.delenv("TWILIO_CHANNEL", raising=False)
    assert dispatcher_with(monkeypatch).channel == "sms"


def test_sms_addresses_are_bare(monkeypatch):
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="sms")
    assert d._address("+918618065357") == "+918618065357"


def test_whatsapp_addresses_are_prefixed(monkeypatch):
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="whatsapp")
    assert d._address("+918618065357") == "whatsapp:+918618065357"


def test_whatsapp_prefix_is_not_doubled(monkeypatch):
    """A contact already written as 'whatsapp:+91...' must not become 'whatsapp:whatsapp:+91...'."""
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="whatsapp")
    assert d._address("whatsapp:+918618065357") == "whatsapp:+918618065357"


def test_sms_strips_a_stray_whatsapp_prefix(monkeypatch):
    """Switching back to SMS must not leave a prefix that Twilio would reject."""
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="sms")
    assert d._address("whatsapp:+918618065357") == "+918618065357"


def test_surrounding_whitespace_is_tolerated(monkeypatch):
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="whatsapp")
    assert d._address("  +918618065357  ") == "whatsapp:+918618065357"


@pytest.mark.parametrize("value", ["WhatsApp", "WHATSAPP", " whatsapp "])
def test_channel_is_case_and_space_insensitive(monkeypatch, value):
    assert dispatcher_with(monkeypatch, TWILIO_CHANNEL=value).channel == "whatsapp"


def test_unknown_channel_falls_back_to_sms(monkeypatch):
    """A typo must not silently produce unroutable addresses."""
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="telegram")
    assert d.channel == "sms"
    assert d._address("+918618065357") == "+918618065357"


def test_both_endpoints_of_a_whatsapp_message_are_prefixed(monkeypatch):
    """Twilio requires the prefix on 'from' as well as 'to'."""
    d = dispatcher_with(monkeypatch, TWILIO_CHANNEL="whatsapp")
    d.twilio_phone = "+14155238886"  # Twilio's shared sandbox sender

    sent = {}

    class FakeMessages:
        def create(self, body, from_, to):
            sent.update(body=body, from_=from_, to=to)

    d.enable_sms = True
    d.twilio_client = type("C", (), {"messages": FakeMessages()})()

    assert d._send_message("+918618065357", "emergency at 12.94, 77.56") is True
    assert sent["from_"] == "whatsapp:+14155238886"
    assert sent["to"] == "whatsapp:+918618065357"
    # Free-form body survives - the whole reason for using WhatsApp on trial.
    assert "12.94" in sent["body"]
