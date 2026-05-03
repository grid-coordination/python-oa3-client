"""Tests for openadr3_client.mqtt."""

import json
from unittest.mock import MagicMock, patch

import pytest

from openadr3_client.mqtt import (
    MQTTConnection,
    _parse_payload,
    extract_mqtt_broker_uris,
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

    def test_uppercase_scheme(self):
        assert normalize_broker_uri("MQTTS://broker.local") == ("broker.local", 8883, True)

    def test_bare_host(self):
        assert normalize_broker_uri("broker.example.com") == ("broker.example.com", 1883, False)

    def test_bare_host_with_port(self):
        assert normalize_broker_uri("broker.example.com:9883") == (
            "broker.example.com",
            9883,
            False,
        )

    def test_bare_ip_with_port(self):
        assert normalize_broker_uri("127.0.0.1:1883") == ("127.0.0.1", 1883, False)

    def test_unknown_scheme_treated_as_plain(self):
        # An unrecognized scheme falls back to mqtt:// — be liberal in what we accept.
        assert normalize_broker_uri("foo://broker.local:1234") == ("broker.local", 1234, False)


class TestExtractMqttBrokerUris:
    def test_spec_dict_shape(self):
        notifiers = {
            "WEBHOOK": True,
            "MQTT": {
                "URIS": ["mqtts://broker.vtn.example.com", "mqtt://broker.vtn.example.com:1883"],
                "serialization": "JSON",
                "authentication": {},
            },
        }
        assert extract_mqtt_broker_uris(notifiers) == [
            "mqtts://broker.vtn.example.com",
            "mqtt://broker.vtn.example.com:1883",
        ]

    def test_spec_dict_shape_lowercase_keys(self):
        notifiers = {"mqtt": {"uris": ["mqtt://broker:1883"]}}
        assert extract_mqtt_broker_uris(notifiers) == ["mqtt://broker:1883"]

    def test_spec_dict_shape_no_mqtt(self):
        assert extract_mqtt_broker_uris({"WEBHOOK": True}) == []

    def test_spec_dict_shape_single_uri_field(self):
        notifiers = {"MQTT": {"uri": "mqtt://broker:1883"}}
        assert extract_mqtt_broker_uris(notifiers) == ["mqtt://broker:1883"]

    def test_vtn_ri_list_shape(self):
        notifiers = [
            {"transport": "MQTT", "url": "mqtt://broker:1883"},
            {"transport": "WEBHOOK", "url": "https://example.com"},
        ]
        assert extract_mqtt_broker_uris(notifiers) == ["mqtt://broker:1883"]

    def test_vtn_ri_list_uri_field_variants(self):
        # Different VTNs may use different field names for the broker URI.
        for field in ("url", "uri", "URI", "URL", "broker", "endpoint"):
            notifiers = [{"transport": "MQTT", field: "mqtt://broker:1883"}]
            assert extract_mqtt_broker_uris(notifiers) == ["mqtt://broker:1883"], field

    def test_vtn_ri_list_with_uris_array_in_item(self):
        notifiers = [
            {"transport": "MQTT", "URIS": ["mqtts://b1:8883", "tcp://b2:1883"]},
        ]
        assert extract_mqtt_broker_uris(notifiers) == ["mqtts://b1:8883", "tcp://b2:1883"]

    def test_empty_inputs(self):
        assert extract_mqtt_broker_uris(None) == []
        assert extract_mqtt_broker_uris({}) == []
        assert extract_mqtt_broker_uris([]) == []

    def test_normalizable_tcp_scheme_round_trip(self):
        # The whole point: VTN advertises tcp://, we accept it through to normalization.
        uris = extract_mqtt_broker_uris([{"transport": "MQTT", "url": "tcp://broker:1883"}])
        assert uris == ["tcp://broker:1883"]
        assert normalize_broker_uri(uris[0]) == ("broker", 1883, False)


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
