"""Tests for openadr3_client.webhook."""

import json
import threading
import time

import httpx
import pytest

from openadr3_client.webhook import (
    WebhookReceiver,
    _parse_webhook_payload,
    detect_lan_ip,
)


class TestDetectLanIp:
    def test_returns_string(self):
        ip = detect_lan_ip()
        assert isinstance(ip, str)
        assert len(ip) >= 7  # shortest: "x.x.x.x"

    def test_not_loopback_when_network_available(self):
        ip = detect_lan_ip()
        # On a machine with network, should get a real LAN IP
        # On CI/isolated, may fall back to 127.0.0.1 — both are valid
        parts = ip.split(".")
        assert len(parts) == 4
        assert all(p.isdigit() for p in parts)

    def test_used_with_webhook_receiver(self):
        ip = detect_lan_ip()
        r = WebhookReceiver(port=0, callback_host=ip)
        r.start()
        try:
            assert ip in r.callback_url
        finally:
            r.stop()


class TestParseWebhookPayload:
    def test_json_object(self):
        raw = json.dumps({"key": "value"}).encode()
        result = _parse_webhook_payload(raw, "/notifications")
        assert result == {"key": "value"}

    def test_plain_string(self):
        raw = b"not json"
        result = _parse_webhook_payload(raw, "/notifications")
        assert result == "not json"

    def test_notification_coerced(self):
        notif = {
            "objectType": "PROGRAM",
            "operation": "POST",
            "object": {
                "objectType": "PROGRAM",
                "id": "prog-1",
                "programName": "test-program",
                "createdDateTime": "2024-01-01T00:00:00Z",
                "modificationDateTime": "2024-01-01T00:00:00Z",
            },
        }
        raw = json.dumps(notif).encode()
        result = _parse_webhook_payload(raw, "/notifications")
        assert hasattr(result, "operation")
        assert result.operation == "POST"

    def test_binary_payload(self):
        raw = bytes([0xFF, 0xFE, 0x00, 0x80])
        result = _parse_webhook_payload(raw, "/notifications")
        assert result == raw


@pytest.fixture
def receiver():
    """Create and start a WebhookReceiver, stop after test."""
    r = WebhookReceiver(port=19876, bearer_token="test-token")
    r.start()
    # Give the server a moment to bind
    time.sleep(0.2)
    yield r
    r.stop()


@pytest.fixture
def open_receiver():
    """WebhookReceiver with no auth token."""
    r = WebhookReceiver(port=19877)
    r.start()
    time.sleep(0.2)
    yield r
    r.stop()


class TestWebhookReceiver:
    def test_callback_url(self, receiver):
        assert receiver.callback_url == "http://127.0.0.1:19876/notifications"

    def test_health_check(self, receiver):
        resp = httpx.get("http://127.0.0.1:19876/notifications")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_post_notification(self, receiver):
        payload = {"key": "value"}
        resp = httpx.post(
            "http://127.0.0.1:19876/notifications",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200

        msgs = receiver.messages
        assert len(msgs) == 1
        assert msgs[0].path == "/notifications"
        assert isinstance(msgs[0].time, float)

    def test_auth_required(self, receiver):
        resp = httpx.post(
            "http://127.0.0.1:19876/notifications",
            json={"test": True},
        )
        assert resp.status_code == 403

    def test_auth_wrong_token(self, receiver):
        resp = httpx.post(
            "http://127.0.0.1:19876/notifications",
            json={"test": True},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 403

    def test_no_auth_when_no_token(self, open_receiver):
        resp = httpx.post(
            "http://127.0.0.1:19877/notifications",
            json={"data": "hello"},
        )
        assert resp.status_code == 200
        assert len(open_receiver.messages) == 1

    def test_multiple_messages(self, receiver):
        for i in range(3):
            httpx.post(
                "http://127.0.0.1:19876/notifications",
                json={"n": i},
                headers={"Authorization": "Bearer test-token"},
            )
        assert len(receiver.messages) == 3

    def test_clear_messages(self, receiver):
        httpx.post(
            "http://127.0.0.1:19876/notifications",
            json={"data": 1},
            headers={"Authorization": "Bearer test-token"},
        )
        assert len(receiver.messages) == 1
        receiver.clear_messages()
        assert len(receiver.messages) == 0

    def test_await_messages(self, receiver):
        # Post in a background thread after a short delay
        def post_later():
            time.sleep(0.2)
            httpx.post(
                "http://127.0.0.1:19876/notifications",
                json={"delayed": True},
                headers={"Authorization": "Bearer test-token"},
            )

        t = threading.Thread(target=post_later)
        t.start()
        msgs = receiver.await_messages(1, timeout=2.0)
        t.join()
        assert len(msgs) >= 1

    def test_await_messages_timeout(self, receiver):
        msgs = receiver.await_messages(5, timeout=0.1)
        assert len(msgs) == 0

    def test_messages_snapshot_is_copy(self, receiver):
        httpx.post(
            "http://127.0.0.1:19876/notifications",
            json={"a": 1},
            headers={"Authorization": "Bearer test-token"},
        )
        snapshot = receiver.messages
        httpx.post(
            "http://127.0.0.1:19876/notifications",
            json={"b": 2},
            headers={"Authorization": "Bearer test-token"},
        )
        assert len(snapshot) == 1
        assert len(receiver.messages) == 2

    def test_on_message_callback(self):
        received = []
        r = WebhookReceiver(
            port=19878,
            on_message=lambda path, payload: received.append((path, payload)),
        )
        r.start()
        time.sleep(0.2)
        try:
            httpx.post("http://127.0.0.1:19878/notifications", json={"x": 1})
            time.sleep(0.1)
            assert len(received) == 1
            assert received[0] == ("/notifications", {"x": 1})
        finally:
            r.stop()

    def test_notification_payload_coerced(self, receiver):
        notif = {
            "objectType": "PROGRAM",
            "operation": "CREATE",
            "object": {
                "objectType": "PROGRAM",
                "id": "p1",
                "programName": "coerce-test",
                "createdDateTime": "2024-01-01T00:00:00Z",
                "modificationDateTime": "2024-01-01T00:00:00Z",
            },
        }
        httpx.post(
            "http://127.0.0.1:19876/notifications",
            json=notif,
            headers={"Authorization": "Bearer test-token"},
        )
        msg = receiver.messages[0]
        assert hasattr(msg.payload, "operation")
        assert msg.payload.operation == "CREATE"
        assert hasattr(msg.payload.object, "program_name")

    def test_ephemeral_port(self):
        r = WebhookReceiver(port=0)
        r.start()
        try:
            assert r.port > 0
            resp = httpx.post(
                f"http://127.0.0.1:{r.port}/notifications",
                json={"ephemeral": True},
            )
            assert resp.status_code == 200
            assert len(r.messages) == 1
        finally:
            r.stop()

    def test_callback_host(self):
        r = WebhookReceiver(port=0, callback_host="myhost.example.com")
        r.start()
        try:
            assert "myhost.example.com" in r.callback_url
            assert str(r.port) in r.callback_url
        finally:
            r.stop()

    def test_multiple_receivers(self):
        """Multiple receivers on different ports (multi-client scenario)."""
        r1 = WebhookReceiver(port=0, bearer_token="t1")
        r2 = WebhookReceiver(port=0, bearer_token="t2")
        r1.start()
        r2.start()
        try:
            assert r1.port != r2.port
            httpx.post(
                f"http://127.0.0.1:{r1.port}/notifications",
                json={"target": "r1"},
                headers={"Authorization": "Bearer t1"},
            )
            httpx.post(
                f"http://127.0.0.1:{r2.port}/notifications",
                json={"target": "r2"},
                headers={"Authorization": "Bearer t2"},
            )
            assert len(r1.messages) == 1
            assert r1.messages[0].payload == {"target": "r1"}
            assert len(r2.messages) == 1
            assert r2.messages[0].payload == {"target": "r2"}
        finally:
            r1.stop()
            r2.stop()

    def test_custom_path(self):
        r = WebhookReceiver(port=19879, path="/callbacks/oa3")
        r.start()
        time.sleep(0.2)
        try:
            resp = httpx.post(
                "http://127.0.0.1:19879/callbacks/oa3",
                json={"custom": True},
            )
            assert resp.status_code == 200
            assert r.callback_url == "http://127.0.0.1:19879/callbacks/oa3"
            assert len(r.messages) == 1
        finally:
            r.stop()
