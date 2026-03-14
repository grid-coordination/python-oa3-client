"""Tests for openadr3_client.client."""

import json
from unittest.mock import patch, MagicMock, PropertyMock

import httpx
import pytest

from openadr3_client.client import OA3Client, extract_topics


def _make_response(status_code: int, json_data: dict) -> httpx.Response:
    """Create a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "http://test"),
    )
    return resp


class TestExtractTopics:
    def test_success(self):
        resp = _make_response(200, {"topics": {"a": "programs/create", "b": "programs/update"}})
        topics = extract_topics(resp)
        assert set(topics) == {"programs/create", "programs/update"}

    def test_empty_topics(self):
        resp = _make_response(200, {"topics": {}})
        assert extract_topics(resp) is None

    def test_error_response(self):
        resp = _make_response(401, {"error": "unauthorized"})
        assert extract_topics(resp) is None

    def test_no_topics_key(self):
        resp = _make_response(200, {"other": "data"})
        assert extract_topics(resp) is None


class TestOA3ClientLifecycle:
    def test_invalid_client_type(self):
        with pytest.raises(ValueError, match="client_type must be"):
            OA3Client(client_type="invalid", url="http://test", token="tok")

    @patch("openadr3_client.client.create_ven_client")
    def test_start_creates_client(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        result = c.start()
        assert result is c
        mock_create.assert_called_once()
        assert c._api is mock_api

    @patch("openadr3_client.client.create_ven_client")
    def test_start_idempotent(self, mock_create):
        mock_create.return_value = MagicMock()
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.start()  # Second call should be a no-op
        mock_create.assert_called_once()

    @patch("openadr3_client.client.create_bl_client")
    def test_bl_client_type(self, mock_create):
        mock_create.return_value = MagicMock()
        c = OA3Client(client_type="bl", url="http://test", token="tok")
        c.start()
        mock_create.assert_called_once()

    @patch("openadr3_client.client.create_ven_client")
    def test_stop(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.stop()
        mock_api.close.assert_called_once()
        assert c._api is None

    @patch("openadr3_client.client.create_ven_client")
    def test_context_manager(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        with OA3Client(client_type="ven", url="http://test", token="tok") as c:
            assert c._api is mock_api
        mock_api.close.assert_called_once()

    def test_api_not_started(self):
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        with pytest.raises(RuntimeError, match="not started"):
            _ = c.api


class TestOA3ClientVenRegistration:
    @patch("openadr3_client.client.create_ven_client")
    def test_register_existing_ven(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_ven_by_name.return_value = {"id": "ven-123", "venName": "my-ven"}
        mock_create.return_value = mock_api

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        result = c.register("my-ven")

        assert result is c
        assert c.ven_id == "ven-123"
        assert c.ven_name == "my-ven"
        mock_api.create_ven.assert_not_called()

    @patch("openadr3_client.client.create_ven_client")
    def test_register_new_ven(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_ven_by_name.return_value = None
        mock_resp = _make_response(201, {"id": "new-ven-456", "venName": "my-ven"})
        mock_api.create_ven.return_value = mock_resp
        mock_create.return_value = mock_api

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.register("my-ven")

        assert c.ven_id == "new-ven-456"
        mock_api.create_ven.assert_called_once_with({
            "objectType": "VEN_VEN_REQUEST",
            "venName": "my-ven",
        })

    def test_require_ven_id_not_registered(self):
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        with pytest.raises(RuntimeError, match="VEN not registered"):
            c._require_ven_id()


class TestOA3ClientMqttTopics:
    @patch("openadr3_client.client.create_ven_client")
    def test_ven_scoped_defaults_to_registered(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_ven_by_name.return_value = {"id": "ven-99", "venName": "v"}
        mock_create.return_value = mock_api

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.register("v")

        c.get_mqtt_topics_ven()
        mock_api.get_mqtt_topics_ven.assert_called_with("ven-99")

    @patch("openadr3_client.client.create_ven_client")
    def test_ven_scoped_explicit_id(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.get_mqtt_topics_ven("other-ven")
        mock_api.get_mqtt_topics_ven.assert_called_with("other-ven")

    @patch("openadr3_client.client.create_ven_client")
    def test_ven_scoped_not_registered(self, mock_create):
        mock_create.return_value = MagicMock()
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        with pytest.raises(RuntimeError, match="VEN not registered"):
            c.get_mqtt_topics_ven()


class TestOA3ClientApiDelegation:
    @patch("openadr3_client.client.create_ven_client")
    def test_delegates_programs(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.get_programs()
        mock_api.get_programs.assert_called_once()

    @patch("openadr3_client.client.create_ven_client")
    def test_delegates_coerced_programs(self, mock_create):
        mock_api = MagicMock()
        mock_api.programs.return_value = ["p1", "p2"]
        mock_create.return_value = mock_api
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        assert c.programs() == ["p1", "p2"]


class TestOA3ClientMqtt:
    @patch("openadr3_client.client.create_ven_client")
    @patch("openadr3_client.client.MQTTConnection")
    def test_connect_mqtt(self, mock_conn_cls, mock_create):
        mock_create.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        result = c.connect_mqtt("mqtt://broker:1883", client_id="test-id")

        assert result is c
        mock_conn_cls.assert_called_once_with(
            broker_url="mqtt://broker:1883",
            client_id="test-id",
            on_message=None,
        )
        mock_conn.connect.assert_called_once()

    def test_mqtt_not_connected(self):
        c = OA3Client(client_type="ven", url="http://test", token="tok")
        with pytest.raises(RuntimeError, match="MQTT not connected"):
            _ = c.mqtt

    @patch("openadr3_client.client.create_ven_client")
    @patch("openadr3_client.client.MQTTConnection")
    def test_disconnect_mqtt(self, mock_conn_cls, mock_create):
        mock_create.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.connect_mqtt("mqtt://broker:1883")
        c.disconnect_mqtt()

        mock_conn.disconnect.assert_called_once()
        assert c._mqtt is None

    @patch("openadr3_client.client.create_ven_client")
    @patch("openadr3_client.client.MQTTConnection")
    def test_subscribe_notifications(self, mock_conn_cls, mock_create):
        mock_api = MagicMock()
        mock_api.get_mqtt_topics_programs.return_value = _make_response(
            200, {"topics": {"a": "programs/create"}}
        )
        mock_create.return_value = mock_api
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        c = OA3Client(client_type="ven", url="http://test", token="tok")
        c.start()
        c.connect_mqtt("mqtt://broker:1883")
        c.subscribe_notifications(OA3Client.get_mqtt_topics_programs)

        mock_conn.subscribe.assert_called_once_with(["programs/create"])
