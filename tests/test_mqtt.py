"""Tests for openadr3_client.mqtt."""

import json
from unittest.mock import MagicMock, patch

import pytest

from openadr3_client.mqtt import (
    MQTTConnection,
    _parse_payload,
    normalize_broker_uri,
)


class TestNormalizeBrokerUri:
    def test_mqtt_default_port(self):
        assert normalize_broker_uri("mqtt://broker.local") == ("broker.local", 1883, False)

    def test_mqtt_custom_port(self):
        assert normalize_broker_uri("mqtt://broker.local:9883") == ("broker.local", 9883, False)

    def test_mqtts_default_port(self):
        assert normalize_broker_uri("mqtts://broker.local") == ("broker.local", 8883, True)

    def test_mqtts_custom_port(self):
        assert normalize_broker_uri("mqtts://broker.local:9883") == ("broker.local", 9883, True)

    def test_tcp_scheme(self):
        assert normalize_broker_uri("tcp://127.0.0.1") == ("127.0.0.1", 1883, False)

    def test_ssl_scheme(self):
        assert normalize_broker_uri("ssl://broker.local") == ("broker.local", 8883, True)


class TestParsePayload:
    def test_json_object(self):
        raw = json.dumps({"key": "value"}).encode()
        result = _parse_payload(raw, "test/topic")
        assert result == {"key": "value"}

    def test_plain_string(self):
        raw = b"not json"
        result = _parse_payload(raw, "test/topic")
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
        result = _parse_payload(raw, "programs/create")
        # Should be coerced into a Notification model
        assert hasattr(result, "operation")
        assert result.operation == "POST"

    def test_binary_payload(self):
        raw = bytes([0xFF, 0xFE, 0x00, 0x80])
        result = _parse_payload(raw, "binary/topic")
        assert result == raw


@pytest.fixture
def mock_mqtt_client():
    """Mock ebus_mqtt_client.MqttClient to prevent real connections."""
    with patch("ebus_mqtt_client.MqttClient") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_cls.return_value = mock_instance
        yield {"cls": mock_cls, "instance": mock_instance}


class TestMQTTConnection:
    def test_connect(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local:1883", client_id="test")
        conn.connect()
        mock_mqtt_client["cls"].assert_called_once_with(
            client_id="test",
            endpoint="broker.local",
            port=1883,
            use_tls=False,
            tls_insecure=True,
        )
        mock_mqtt_client["instance"].start.assert_called_once()

    def test_connect_tls(self, mock_mqtt_client):
        conn = MQTTConnection("mqtts://secure.broker:8883")
        conn.connect()
        call_kwargs = mock_mqtt_client["cls"].call_args[1]
        assert call_kwargs["use_tls"] is True
        assert call_kwargs["port"] == 8883

    def test_disconnect(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        conn.disconnect()
        mock_mqtt_client["instance"].stop.assert_called_once()
        assert conn._client is None

    def test_is_connected(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        assert conn.is_connected() is False
        conn.connect()
        assert conn.is_connected() is True

    def test_subscribe(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        conn.subscribe(["topic/a", "topic/b"])
        assert mock_mqtt_client["instance"].subscribe.call_count == 2

    def test_subscribe_single_string(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        conn.subscribe("topic/a")
        mock_mqtt_client["instance"].subscribe.assert_called_once()

    def test_subscribe_not_connected(self):
        conn = MQTTConnection("mqtt://broker.local")
        with pytest.raises(RuntimeError, match="Not connected"):
            conn.subscribe("topic/a")

    def test_message_collection(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()

        # Simulate receiving a message
        conn._handle_message("test/topic", b'{"key": "value"}')

        msgs = conn.messages
        assert len(msgs) == 1
        assert msgs[0].topic == "test/topic"
        assert msgs[0].payload == {"key": "value"}
        assert isinstance(msgs[0].time, float)

    def test_messages_on_topic(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()

        conn._handle_message("topic/a", b'"msg1"')
        conn._handle_message("topic/b", b'"msg2"')
        conn._handle_message("topic/a", b'"msg3"')

        a_msgs = conn.messages_on_topic("topic/a")
        assert len(a_msgs) == 2

    def test_clear_messages(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        conn._handle_message("topic", b'"data"')
        assert len(conn.messages) == 1
        conn.clear_messages()
        assert len(conn.messages) == 0

    def test_on_message_callback(self, mock_mqtt_client):
        callback = MagicMock()
        conn = MQTTConnection("mqtt://broker.local", on_message=callback)
        conn.connect()
        conn._handle_message("topic/x", b'{"a": 1}')
        callback.assert_called_once_with("topic/x", {"a": 1})

    def test_await_messages_immediate(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        conn._handle_message("t", b'"a"')
        conn._handle_message("t", b'"b"')
        msgs = conn.await_messages(2, timeout=0.1)
        assert len(msgs) == 2

    def test_await_messages_timeout(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        msgs = conn.await_messages(5, timeout=0.1)
        assert len(msgs) == 0

    def test_messages_snapshot_is_copy(self, mock_mqtt_client):
        conn = MQTTConnection("mqtt://broker.local")
        conn.connect()
        conn._handle_message("t", b'"a"')
        snapshot = conn.messages
        conn._handle_message("t", b'"b"')
        assert len(snapshot) == 1  # Original snapshot unchanged
        assert len(conn.messages) == 2
