"""
Webhook payload shape.

Discord rejects a body without "content" and Slack rejects one without "text",
both with a 400 that the dispatcher only logs - so a broken payload looks
exactly like a webhook that silently never fires. These assertions are the
difference between that and a working fallback channel.
"""

import main


def capture_payload(monkeypatch, **kwargs):
    sent = {}
    dispatcher = main.AlertDispatcher()
    dispatcher.enable_webhook = True
    dispatcher.webhook_url = "https://example.invalid/hook"
    dispatcher.emergency_contacts = []
    dispatcher.enable_sms = False
    monkeypatch.setattr(
        dispatcher, "_send_webhook", lambda payload: sent.update(payload) or True
    )
    dispatcher.dispatch_alert(
        device_id=kwargs.get("device_id", "demo-device-01"),
        latitude=kwargs.get("latitude", 12.9412),
        longitude=kwargs.get("longitude", 77.5652),
        alert_type=kwargs.get("alert_type", "EMERGENCY"),
    )
    return sent


def test_payload_has_discord_content_field(monkeypatch):
    assert capture_payload(monkeypatch)["content"]


def test_payload_has_slack_text_field(monkeypatch):
    assert capture_payload(monkeypatch)["text"]


def test_discord_and_slack_fields_carry_the_full_alert(monkeypatch):
    payload = capture_payload(monkeypatch)
    for field in ("content", "text"):
        body = payload[field]
        assert "12.941200" in body
        assert "77.565200" in body
        assert "maps.google.com" in body
        assert "demo-device-01" in body


def test_structured_fields_are_still_present(monkeypatch):
    """Custom consumers should not have to parse the human-readable string."""
    payload = capture_payload(monkeypatch)
    assert payload["latitude"] == 12.9412
    assert payload["longitude"] == 77.5652
    assert payload["device_id"] == "demo-device-01"
    assert payload["alert_type"] == "EMERGENCY"
    assert payload["maps_url"].endswith("12.9412,77.5652")


def test_webhook_fires_even_with_no_sms_contacts(monkeypatch):
    """The webhook must work as a standalone channel when Twilio is unusable."""
    assert capture_payload(monkeypatch) != {}
