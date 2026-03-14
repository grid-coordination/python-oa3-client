"""Tests for openadr3_client.discovery — mDNS/DNS-SD VTN discovery."""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from openadr3_client.discovery import (
    DiscoveredVTN,
    DiscoveryMode,
    SERVICE_TYPE,
    _parse_txt_properties,
    discover_vtns,
    resolve_url,
    advertise_vtn,
)


# -- _parse_txt_properties --


class TestParseTxtProperties:
    def test_bytes_keys_and_values(self):
        props = {b"version": b"3.1.0", b"base_path": b"/openadr3"}
        result = _parse_txt_properties(props)
        assert result == {"version": "3.1.0", "base_path": "/openadr3"}

    def test_string_keys_and_values(self):
        props = {"version": "3.1.0", "base_path": "/openadr3"}
        result = _parse_txt_properties(props)
        assert result == {"version": "3.1.0", "base_path": "/openadr3"}

    def test_none_value(self):
        props = {b"flag": None}
        result = _parse_txt_properties(props)
        assert result == {"flag": ""}

    def test_mixed(self):
        props = {b"version": b"3.1.0", "local_url": "http://vtn.local:8080"}
        result = _parse_txt_properties(props)
        assert result["version"] == "3.1.0"
        assert result["local_url"] == "http://vtn.local:8080"

    def test_empty(self):
        assert _parse_txt_properties({}) == {}


# -- DiscoveredVTN --


class TestDiscoveredVTN:
    def test_url_from_local_url(self):
        vtn = DiscoveredVTN(
            name="test", host="vtn.local", port=8080,
            local_url="http://vtn.local:8080/openadr3",
        )
        assert vtn.url == "http://vtn.local:8080/openadr3"

    def test_url_strips_trailing_slash(self):
        vtn = DiscoveredVTN(
            name="test", host="vtn.local", port=8080,
            local_url="http://vtn.local:8080/openadr3/",
        )
        assert vtn.url == "http://vtn.local:8080/openadr3"

    def test_url_constructed_from_host_port(self):
        vtn = DiscoveredVTN(name="test", host="vtn.local", port=8080)
        assert vtn.url == "http://vtn.local:8080"

    def test_url_constructed_with_base_path(self):
        vtn = DiscoveredVTN(
            name="test", host="vtn.local", port=8080,
            base_path="/openadr3",
        )
        assert vtn.url == "http://vtn.local:8080/openadr3"

    def test_url_https_on_443(self):
        vtn = DiscoveredVTN(name="test", host="vtn.local", port=443)
        assert vtn.url == "https://vtn.local:443"

    def test_from_service_info(self):
        info = MagicMock()
        info.name = "My VTN._openadr3._tcp.local."
        info.server = "myvtn.local."
        info.port = 8080
        info.properties = {
            b"version": b"3.1.0",
            b"base_path": b"/openadr3",
            b"local_url": b"http://myvtn.local:8080/openadr3",
            b"program_names": b"prog1,prog2",
            b"requires_auth": b"true",
        }
        info.parsed_addresses.return_value = ["192.168.1.100"]

        vtn = DiscoveredVTN.from_service_info(info)
        assert vtn.name == "My VTN._openadr3._tcp.local."
        assert vtn.host == "myvtn.local"  # trailing dot stripped
        assert vtn.port == 8080
        assert vtn.base_path == "/openadr3"
        assert vtn.version == "3.1.0"
        assert vtn.local_url == "http://myvtn.local:8080/openadr3"
        assert vtn.program_names == "prog1,prog2"
        assert vtn.requires_auth == "true"

    def test_from_service_info_no_server(self):
        info = MagicMock()
        info.name = "test"
        info.server = None
        info.port = 8080
        info.properties = {}
        info.parsed_addresses.return_value = ["10.0.0.1"]

        vtn = DiscoveredVTN.from_service_info(info)
        assert vtn.host == "10.0.0.1"

    def test_frozen(self):
        vtn = DiscoveredVTN(name="test", host="h", port=80)
        with pytest.raises(AttributeError):
            vtn.name = "changed"


# -- discover_vtns --


class TestDiscoverVtns:
    @patch("openadr3_client.discovery._import_zeroconf")
    def test_discovers_services(self, mock_import):
        mock_zc_mod = MagicMock()
        mock_import.return_value = mock_zc_mod

        mock_zc_instance = MagicMock()
        mock_zc_mod.Zeroconf.return_value = mock_zc_instance

        # Set up ServiceInfo that get_service_info returns
        mock_info = MagicMock()
        mock_info.name = "TestVTN._openadr3._tcp.local."
        mock_info.server = "testvtn.local."
        mock_info.port = 8080
        mock_info.properties = {b"version": b"3.1.0", b"base_path": b"/"}
        mock_info.parsed_addresses.return_value = ["127.0.0.1"]
        mock_zc_instance.get_service_info.return_value = mock_info

        # Capture the listener passed to ServiceBrowser and call add_service
        def capture_browser(zc, stype, listener):
            listener.add_service(zc, stype, "TestVTN._openadr3._tcp.local.")
            return MagicMock()

        mock_zc_mod.ServiceBrowser.side_effect = capture_browser

        vtns = discover_vtns(timeout=0.01)
        assert len(vtns) == 1
        assert vtns[0].host == "testvtn.local"
        assert vtns[0].port == 8080
        mock_zc_instance.close.assert_called_once()

    @patch("openadr3_client.discovery._import_zeroconf")
    def test_no_services_found(self, mock_import):
        mock_zc_mod = MagicMock()
        mock_import.return_value = mock_zc_mod
        mock_zc_instance = MagicMock()
        mock_zc_mod.Zeroconf.return_value = mock_zc_instance

        # ServiceBrowser does nothing (no services)
        mock_zc_mod.ServiceBrowser.return_value = MagicMock()

        vtns = discover_vtns(timeout=0.01)
        assert vtns == []
        mock_zc_instance.close.assert_called_once()

    @patch("openadr3_client.discovery._import_zeroconf")
    def test_service_info_none_skipped(self, mock_import):
        mock_zc_mod = MagicMock()
        mock_import.return_value = mock_zc_mod
        mock_zc_instance = MagicMock()
        mock_zc_mod.Zeroconf.return_value = mock_zc_instance
        mock_zc_instance.get_service_info.return_value = None

        def capture_browser(zc, stype, listener):
            listener.add_service(zc, stype, "ghost._openadr3._tcp.local.")
            return MagicMock()

        mock_zc_mod.ServiceBrowser.side_effect = capture_browser

        vtns = discover_vtns(timeout=0.01)
        assert vtns == []


# -- resolve_url --


class TestResolveUrl:
    def test_never_returns_configured(self):
        assert resolve_url("never", "http://vtn.example.com") == "http://vtn.example.com"

    def test_never_no_url_raises(self):
        with pytest.raises(ValueError, match="url is required"):
            resolve_url("never", None)

    @patch("openadr3_client.discovery.discover_vtns")
    def test_require_local_found(self, mock_discover):
        vtn = DiscoveredVTN(name="v", host="vtn.local", port=8080,
                            local_url="http://vtn.local:8080")
        mock_discover.return_value = [vtn]
        assert resolve_url("require_local", None) == "http://vtn.local:8080"

    @patch("openadr3_client.discovery.discover_vtns")
    def test_require_local_not_found(self, mock_discover):
        mock_discover.return_value = []
        with pytest.raises(RuntimeError, match="no VTN found"):
            resolve_url("require_local", None)

    @patch("openadr3_client.discovery.discover_vtns")
    def test_prefer_local_found(self, mock_discover):
        vtn = DiscoveredVTN(name="v", host="vtn.local", port=8080,
                            local_url="http://vtn.local:8080")
        mock_discover.return_value = [vtn]
        assert resolve_url("prefer_local", "http://cloud.vtn.com") == "http://vtn.local:8080"

    @patch("openadr3_client.discovery.discover_vtns")
    def test_prefer_local_fallback_to_configured(self, mock_discover):
        mock_discover.return_value = []
        assert resolve_url("prefer_local", "http://cloud.vtn.com") == "http://cloud.vtn.com"

    @patch("openadr3_client.discovery.discover_vtns")
    def test_prefer_local_no_fallback_raises(self, mock_discover):
        mock_discover.return_value = []
        with pytest.raises(RuntimeError, match="no VTN found.*no url configured"):
            resolve_url("prefer_local", None)

    @patch("openadr3_client.discovery.discover_vtns")
    def test_local_with_fallback_found(self, mock_discover):
        vtn = DiscoveredVTN(name="v", host="vtn.local", port=8080,
                            local_url="http://vtn.local:8080")
        mock_discover.return_value = [vtn]
        assert resolve_url("local_with_fallback", "http://cloud.vtn.com") == "http://vtn.local:8080"

    @patch("openadr3_client.discovery.discover_vtns")
    def test_local_with_fallback_not_found(self, mock_discover):
        mock_discover.return_value = []
        assert resolve_url("local_with_fallback", "http://cloud.vtn.com") == "http://cloud.vtn.com"

    def test_enum_values(self):
        assert resolve_url(DiscoveryMode.NEVER, "http://x") == "http://x"


# -- advertise_vtn --


class TestAdvertiseVtn:
    @patch("openadr3_client.discovery._import_zeroconf")
    def test_registers_and_closes(self, mock_import):
        mock_zc_mod = MagicMock()
        mock_import.return_value = mock_zc_mod
        mock_zc_instance = MagicMock()
        mock_zc_mod.Zeroconf.return_value = mock_zc_instance

        adv = advertise_vtn("127.0.0.1", 8080, base_path="/openadr3")
        mock_zc_instance.register_service.assert_called_once()
        info = mock_zc_instance.register_service.call_args[0][0]
        assert info is adv._info

        adv.close()
        mock_zc_instance.unregister_service.assert_called_once()
        mock_zc_instance.close.assert_called_once()

    @patch("openadr3_client.discovery._import_zeroconf")
    def test_context_manager(self, mock_import):
        mock_zc_mod = MagicMock()
        mock_import.return_value = mock_zc_mod
        mock_zc_instance = MagicMock()
        mock_zc_mod.Zeroconf.return_value = mock_zc_instance

        with advertise_vtn("127.0.0.1", 8080) as adv:
            mock_zc_instance.register_service.assert_called_once()
        mock_zc_instance.unregister_service.assert_called_once()
        mock_zc_instance.close.assert_called_once()

    @patch("openadr3_client.discovery._import_zeroconf")
    def test_service_info_properties(self, mock_import):
        mock_zc_mod = MagicMock()
        mock_import.return_value = mock_zc_mod
        mock_zc_instance = MagicMock()
        mock_zc_mod.Zeroconf.return_value = mock_zc_instance

        advertise_vtn(
            "127.0.0.1", 8080,
            base_path="/openadr3",
            version="3.1.0",
            program_names="prog1,prog2",
        )

        call_args = mock_zc_mod.ServiceInfo.call_args
        assert call_args[0][0] == SERVICE_TYPE
        props = call_args[1]["properties"]
        assert props["version"] == "3.1.0"
        assert props["base_path"] == "/openadr3"
        assert props["program_names"] == "prog1,prog2"


# -- BaseClient integration --


class TestBaseClientDiscovery:
    def test_default_discovery_never_requires_url(self):
        from openadr3_client.base import BaseClient
        with pytest.raises(ValueError, match="url is required"):
            BaseClient(token="tok")

    def test_local_with_fallback_requires_url(self):
        from openadr3_client.base import BaseClient
        with pytest.raises(ValueError, match="url is required.*local_with_fallback"):
            BaseClient(token="tok", discovery="local_with_fallback")

    def test_require_local_no_url_ok(self):
        from openadr3_client.base import BaseClient
        c = BaseClient(token="tok", discovery="require_local")
        assert c.url is None
        assert c.discovery_mode == DiscoveryMode.REQUIRE_LOCAL

    def test_prefer_local_no_url_ok(self):
        from openadr3_client.base import BaseClient
        c = BaseClient(token="tok", discovery="prefer_local")
        assert c.url is None

    @patch("openadr3_client.base.resolve_url", return_value="http://discovered:8080")
    @patch("openadr3_client.base.create_ven_client")
    def test_start_uses_resolved_url(self, mock_create, mock_resolve):
        from openadr3_client.base import BaseClient
        mock_create.return_value = MagicMock()

        c = BaseClient(token="tok", discovery="require_local")
        c.start()

        mock_resolve.assert_called_once_with(
            DiscoveryMode.REQUIRE_LOCAL, None, 3.0,
        )
        mock_create.assert_called_once()
        assert mock_create.call_args[1]["base_url"] == "http://discovered:8080"
        assert c._resolved_url == "http://discovered:8080"

    @patch("openadr3_client.base.resolve_url", return_value="http://test")
    @patch("openadr3_client.base.create_ven_client")
    def test_start_never_mode_passes_url(self, mock_create, mock_resolve):
        from openadr3_client.base import BaseClient
        mock_create.return_value = MagicMock()

        c = BaseClient(url="http://test", token="tok")
        c.start()

        mock_resolve.assert_called_once_with(
            DiscoveryMode.NEVER, "http://test", 3.0,
        )
