"""Tests for openadr3_client.base — lifecycle, __getattr__, auth."""

from unittest.mock import MagicMock, patch

import pytest

from openadr3_client.base import BaseClient


class TestBaseClientLifecycle:
    def test_no_token_no_credentials(self):
        with pytest.raises(ValueError, match="Provide either token"):
            BaseClient(url="http://test")

    @patch("openadr3_client.base.create_ven_client")
    def test_start_creates_client(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = BaseClient(url="http://test", token="tok")
        result = c.start()
        assert result is c
        mock_create.assert_called_once()
        assert c._api is mock_api

    @patch("openadr3_client.base.create_ven_client")
    def test_start_idempotent(self, mock_create):
        mock_create.return_value = MagicMock()
        c = BaseClient(url="http://test", token="tok")
        c.start()
        c.start()
        mock_create.assert_called_once()

    @patch("openadr3_client.base.create_ven_client")
    def test_stop(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = BaseClient(url="http://test", token="tok")
        c.start()
        c.stop()
        mock_api.close.assert_called_once()
        assert c._api is None

    @patch("openadr3_client.base.create_ven_client")
    def test_context_manager(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        with BaseClient(url="http://test", token="tok") as c:
            assert c._api is mock_api
        mock_api.close.assert_called_once()

    def test_api_not_started(self):
        c = BaseClient(url="http://test", token="tok")
        with pytest.raises(RuntimeError, match="not started"):
            _ = c.api

    @patch("openadr3_client.base.create_ven_client")
    @patch("openadr3_client.base.fetch_token")
    def test_client_credentials_auth(self, mock_fetch, mock_create):
        mock_fetch.return_value = "fetched-token"
        mock_create.return_value = MagicMock()
        c = BaseClient(
            url="http://test",
            client_id="my_client",
            client_secret="my_secret",
        )
        c.start()
        mock_fetch.assert_called_once_with(
            base_url="http://test",
            client_id="my_client",
            client_secret="my_secret",
        )
        assert c.token == "fetched-token"

    @patch("openadr3_client.base.create_ven_client")
    def test_token_skips_fetch(self, mock_create):
        mock_create.return_value = MagicMock()
        c = BaseClient(url="http://test", token="direct-token")
        c.start()
        assert c.token == "direct-token"


class TestBaseClientGetattr:
    @patch("openadr3_client.base.create_ven_client")
    def test_delegates_to_api(self, mock_create):
        mock_api = MagicMock()
        mock_api.programs.return_value = ["p1", "p2"]
        mock_create.return_value = mock_api
        c = BaseClient(url="http://test", token="tok")
        c.start()
        assert c.programs() == ["p1", "p2"]
        mock_api.programs.assert_called_once()

    @patch("openadr3_client.base.create_ven_client")
    def test_delegates_raw_methods(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = BaseClient(url="http://test", token="tok")
        c.start()
        c.get_programs()
        mock_api.get_programs.assert_called_once()

    @patch("openadr3_client.base.create_ven_client")
    def test_delegates_with_args(self, mock_create):
        mock_api = MagicMock()
        mock_create.return_value = mock_api
        c = BaseClient(url="http://test", token="tok")
        c.start()
        c.get_program_by_id("prog-123")
        mock_api.get_program_by_id.assert_called_once_with("prog-123")

    def test_raises_attribute_error_not_started(self):
        c = BaseClient(url="http://test", token="tok")
        with pytest.raises(AttributeError):
            c.nonexistent_method()

    @patch("openadr3_client.base.create_ven_client")
    def test_raises_attribute_error_unknown(self, mock_create):
        mock_api = MagicMock(spec=["programs", "close"])
        mock_create.return_value = mock_api
        c = BaseClient(url="http://test", token="tok")
        c.start()
        with pytest.raises(AttributeError):
            c.totally_fake_method()
