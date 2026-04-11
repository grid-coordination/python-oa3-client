"""Tests for openadr3_client.ven — VenClient registration, program lookup, subscribe."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from openadr3.entities.models import Program

from openadr3_client.ven import VenClient, extract_topics


def _make_response(status_code: int, json_data) -> httpx.Response:
    """Create a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "http://test"),
    )


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


class TestVenClientRegistration:
    @patch("openadr3_client.base.create_ven_client")
    def test_register_existing_ven(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_ven_by_name.return_value = {"id": "ven-123", "venName": "my-ven"}
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            result = ven.register("my-ven")
            assert result is ven
            assert ven.ven_id == "ven-123"
            assert ven.ven_name == "my-ven"
            mock_api.create_ven.assert_not_called()

    @patch("openadr3_client.base.create_ven_client")
    def test_register_new_ven(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_ven_by_name.return_value = None
        mock_api.create_ven.return_value = _make_response(
            201, {"id": "new-ven-456", "venName": "my-ven"}
        )
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            ven.register("my-ven")
            assert ven.ven_id == "new-ven-456"
            mock_api.create_ven.assert_called_once_with(
                {
                    "objectType": "VEN_VEN_REQUEST",
                    "venName": "my-ven",
                }
            )

    def test_require_ven_id_not_registered(self):
        ven = VenClient(url="http://test", token="tok")
        with pytest.raises(RuntimeError, match="VEN not registered"):
            ven._require_ven_id()


class TestVenClientProgramLookup:
    @patch("openadr3_client.base.create_ven_client")
    def test_find_program_by_name(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_program_by_name.return_value = {
            "objectType": "PROGRAM",
            "id": "prog-1",
            "programName": "pricing",
        }
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            result = ven.find_program_by_name("pricing")
            assert isinstance(result, Program)
            assert result.id == "prog-1"
            assert result.program_name == "pricing"
            assert ven._program_cache["pricing"] == "prog-1"

    @patch("openadr3_client.base.create_ven_client")
    def test_find_program_not_found(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_program_by_name.return_value = None
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            result = ven.find_program_by_name("nonexistent")
            assert result is None
            assert "nonexistent" not in ven._program_cache

    @patch("openadr3_client.base.create_ven_client")
    def test_resolve_program_id_cached(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            ven._program_cache["pricing"] = "prog-1"
            result = ven.resolve_program_id("pricing")
            assert result == "prog-1"
            mock_api.find_program_by_name.assert_not_called()

    @patch("openadr3_client.base.create_ven_client")
    def test_resolve_program_id_queries(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_program_by_name.return_value = {
            "objectType": "PROGRAM",
            "id": "prog-2",
            "programName": "dr-program",
        }
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            result = ven.resolve_program_id("dr-program")
            assert result == "prog-2"

    @patch("openadr3_client.base.create_ven_client")
    def test_resolve_program_id_not_found(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_program_by_name.return_value = None
        mock_create.return_value = mock_api

        with (
            VenClient(url="http://test", token="tok") as ven,
            pytest.raises(KeyError, match="Program not found"),
        ):
            ven.resolve_program_id("missing")


class TestVenClientNotifiers:
    @patch("openadr3_client.base.create_ven_client")
    def test_discover_notifiers(self, mock_create):
        mock_api = MagicMock()
        mock_api.get_notifiers.return_value = _make_response(
            200,
            [
                {"transport": "MQTT", "url": "mqtt://broker:1883"},
            ],
        )
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            result = ven.discover_notifiers()
            assert isinstance(result, list)
            assert result[0]["transport"] == "MQTT"

    @patch("openadr3_client.base.create_ven_client")
    def test_vtn_supports_mqtt_true(self, mock_create):
        mock_api = MagicMock()
        mock_api.get_notifiers.return_value = _make_response(
            200,
            [
                {"transport": "MQTT", "url": "mqtt://broker:1883"},
            ],
        )
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            assert ven.vtn_supports_mqtt() is True

    @patch("openadr3_client.base.create_ven_client")
    def test_vtn_supports_mqtt_false(self, mock_create):
        mock_api = MagicMock()
        mock_api.get_notifiers.return_value = _make_response(
            200,
            [
                {"transport": "HTTP", "url": "http://example.com"},
            ],
        )
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            assert ven.vtn_supports_mqtt() is False

    @patch("openadr3_client.base.create_ven_client")
    def test_vtn_supports_mqtt_error(self, mock_create):
        mock_api = MagicMock()
        mock_api.get_notifiers.return_value = _make_response(500, {})
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            assert ven.vtn_supports_mqtt() is False


class TestVenClientMqttTopics:
    @patch("openadr3_client.base.create_ven_client")
    def test_ven_scoped_defaults_to_registered(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_ven_by_name.return_value = {"id": "ven-99", "venName": "v"}
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            ven.register("v")
            ven.get_mqtt_topics_ven()
            mock_api.get_mqtt_topics_ven.assert_called_with("ven-99")

    @patch("openadr3_client.base.create_ven_client")
    def test_ven_scoped_explicit_id(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            ven.get_mqtt_topics_ven("other-ven")
            mock_api.get_mqtt_topics_ven.assert_called_with("other-ven")

    @patch("openadr3_client.base.create_ven_client")
    def test_ven_scoped_not_registered(self, mock_create):
        mock_create.return_value = MagicMock()
        with (
            VenClient(url="http://test", token="tok") as ven,
            pytest.raises(RuntimeError, match="VEN not registered"),
        ):
            ven.get_mqtt_topics_ven()


class TestVenClientGetattr:
    @patch("openadr3_client.base.create_ven_client")
    def test_delegates_programs(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        with VenClient(url="http://test", token="tok") as ven:
            ven.get_programs()
            mock_api.get_programs.assert_called_once()

    @patch("openadr3_client.base.create_ven_client")
    def test_delegates_coerced_programs(self, mock_create):
        mock_api = MagicMock()
        mock_api.programs.return_value = ["p1", "p2"]
        mock_create.return_value = mock_api
        with VenClient(url="http://test", token="tok") as ven:
            assert ven.programs() == ["p1", "p2"]


class TestVenClientSubscribe:
    @patch("openadr3_client.base.create_ven_client")
    def test_subscribe_mqtt(self, mock_create):
        mock_api = MagicMock()
        mock_api.find_program_by_name.return_value = {
            "objectType": "PROGRAM",
            "id": "prog-1",
            "programName": "pricing",
        }
        mock_api.get_mqtt_topics_program_events.return_value = _make_response(
            200, {"topics": {"a": "openadr3/programs/prog-1/events"}}
        )
        mock_create.return_value = mock_api

        with VenClient(url="http://test", token="tok") as ven:
            from unittest.mock import patch as p

            from openadr3_client.notifications import MqttChannel

            with p.object(MqttChannel, "subscribe_topics") as mock_sub:
                ch = MqttChannel.__new__(MqttChannel)
                ch._conn = MagicMock()
                topics = ven.subscribe(
                    program_names=["pricing"],
                    objects=["EVENT"],
                    operations=["CREATE"],
                    channel=ch,
                )
                assert "openadr3/programs/prog-1/events" in topics
                mock_sub.assert_called_once()


class TestVenClientChannelLifecycle:
    @patch("openadr3_client.base.create_ven_client")
    def test_stop_stops_channels(self, mock_create):
        mock_create.return_value = MagicMock()
        ven = VenClient(url="http://test", token="tok")
        ven.start()

        mock_ch = MagicMock()
        ven._channels.append(mock_ch)

        ven.stop()
        mock_ch.stop.assert_called_once()
        assert len(ven._channels) == 0
