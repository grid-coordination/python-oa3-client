"""Tests for openadr3_client.bl — BlClient."""

from unittest.mock import MagicMock, patch

from openadr3_client.bl import BlClient


class TestBlClient:
    def test_client_type(self):
        assert BlClient._client_type == "bl"

    @patch("openadr3_client.base.create_bl_client")
    def test_start_uses_bl_factory(self, mock_create):
        mock_create.return_value = MagicMock()
        c = BlClient(url="http://test", token="tok")
        c.start()
        mock_create.assert_called_once()

    @patch("openadr3_client.base.create_bl_client")
    def test_context_manager(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        with BlClient(url="http://test", token="tok") as bl:
            assert bl._api is mock_api
        mock_api.close.assert_called_once()

    @patch("openadr3_client.base.create_bl_client")
    def test_delegates_create_program(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        with BlClient(url="http://test", token="tok") as bl:
            bl.create_program({"programName": "test"})
            mock_api.create_program.assert_called_once_with({"programName": "test"})

    @patch("openadr3_client.base.create_bl_client")
    def test_delegates_coerced_methods(self, mock_create):
        mock_api = MagicMock()
        mock_api.programs.return_value = ["p1"]
        mock_create.return_value = mock_api
        with BlClient(url="http://test", token="tok") as bl:
            assert bl.programs() == ["p1"]
