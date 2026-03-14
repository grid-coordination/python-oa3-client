"""mDNS/DNS-SD discovery for OpenADR 3 VTNs.

Browses for ``_openadr3._tcp.local.`` services via zeroconf and parses
TXT records defined in the OpenADR 3.1.0 specification (section 4.1).

The ``zeroconf`` package is lazily imported so that the core library
works without it installed — add the ``[mdns]`` extra to pull it in.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)

SERVICE_TYPE = "_openadr3._tcp.local."


class DiscoveryMode(str, Enum):
    """How the client should discover a VTN."""

    NEVER = "never"
    PREFER_LOCAL = "prefer_local"
    LOCAL_WITH_FALLBACK = "local_with_fallback"
    REQUIRE_LOCAL = "require_local"


def _parse_txt_properties(properties: dict[bytes | str, bytes | str | None]) -> dict[str, str]:
    """Convert zeroconf TXT record properties to ``{str: str}``."""
    result: dict[str, str] = {}
    for k, v in properties.items():
        key = k.decode("utf-8") if isinstance(k, bytes) else k
        if v is None:
            result[key] = ""
        elif isinstance(v, bytes):
            result[key] = v.decode("utf-8")
        else:
            result[key] = str(v)
    return result


@dataclass(frozen=True)
class DiscoveredVTN:
    """A VTN discovered via mDNS/DNS-SD."""

    name: str
    host: str
    port: int
    base_path: str = "/"
    version: str = ""
    local_url: str = ""
    program_names: str = ""
    requires_auth: str = ""
    openapi_url: str = ""

    @property
    def url(self) -> str:
        """Resolved URL: ``local_url`` if set, else constructed from host/port/base_path."""
        if self.local_url:
            return self.local_url.rstrip("/")
        scheme = "https" if self.port == 443 else "http"
        base = self.base_path.rstrip("/") if self.base_path != "/" else ""
        return f"{scheme}://{self.host}:{self.port}{base}"

    @classmethod
    def from_service_info(cls, info: Any) -> DiscoveredVTN:
        """Build from a ``zeroconf.ServiceInfo`` object."""
        props = _parse_txt_properties(info.properties or {})
        # Prefer .server (the .local hostname) over parsed addresses
        host = info.server.rstrip(".") if info.server else (
            info.parsed_addresses()[0] if info.parsed_addresses() else "localhost"
        )
        return cls(
            name=info.name,
            host=host,
            port=info.port,
            base_path=props.get("base_path", "/"),
            version=props.get("version", ""),
            local_url=props.get("local_url", ""),
            program_names=props.get("program_names", ""),
            requires_auth=props.get("requires_auth", ""),
            openapi_url=props.get("openapi_url", ""),
        )


def _import_zeroconf():
    """Lazy-import zeroconf with a helpful error message."""
    try:
        import zeroconf  # noqa: F811
        return zeroconf
    except ImportError:
        raise ImportError(
            "zeroconf is required for mDNS discovery. "
            "Install it with: pip install 'python-oa3-client[mdns]'"
        ) from None


def discover_vtns(timeout: float = 3.0) -> list[DiscoveredVTN]:
    """Browse for OpenADR 3 VTNs via mDNS.

    Blocks for *timeout* seconds while collecting service announcements,
    then returns all discovered VTNs.
    """
    zc_mod = _import_zeroconf()
    Zeroconf = zc_mod.Zeroconf
    ServiceBrowser = zc_mod.ServiceBrowser

    found: list[DiscoveredVTN] = []
    event = threading.Event()

    class Listener:
        def add_service(self, zc: Any, type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name)
            if info:
                vtn = DiscoveredVTN.from_service_info(info)
                found.append(vtn)
                log.info("Discovered VTN: %s at %s", vtn.name, vtn.url)

        def remove_service(self, zc: Any, type_: str, name: str) -> None:
            pass

        def update_service(self, zc: Any, type_: str, name: str) -> None:
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE_TYPE, Listener())
        event.wait(timeout)
    finally:
        zc.close()

    return found


def resolve_url(
    mode: DiscoveryMode | str,
    configured_url: str | None,
    timeout: float = 3.0,
) -> str:
    """Resolve the VTN URL based on discovery mode.

    Called by ``BaseClient.start()`` to determine the final URL.
    """
    mode = DiscoveryMode(mode)

    if mode == DiscoveryMode.NEVER:
        if not configured_url:
            raise ValueError("url is required when discovery='never'")
        return configured_url

    vtns = discover_vtns(timeout=timeout)
    discovered_url = vtns[0].url if vtns else None

    if mode == DiscoveryMode.REQUIRE_LOCAL:
        if not discovered_url:
            raise RuntimeError(
                "discovery='require_local' but no VTN found via mDNS"
            )
        return discovered_url

    if mode == DiscoveryMode.PREFER_LOCAL:
        if discovered_url:
            return discovered_url
        if configured_url:
            return configured_url
        raise RuntimeError(
            "discovery='prefer_local': no VTN found via mDNS and no url configured"
        )

    # LOCAL_WITH_FALLBACK
    if discovered_url:
        return discovered_url
    # configured_url is guaranteed non-None by __init__ validation
    return configured_url  # type: ignore[return-value]


class _VTNAdvertiser:
    """Context manager that registers an mDNS service for a VTN."""

    def __init__(self, info: Any, zc: Any) -> None:
        self._info = info
        self._zc = zc

    def close(self) -> None:
        """Unregister the service and shut down zeroconf."""
        self._zc.unregister_service(self._info)
        self._zc.close()
        log.info("mDNS service unregistered: %s", self._info.name)

    def __enter__(self) -> _VTNAdvertiser:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def advertise_vtn(
    host: str,
    port: int,
    base_path: str = "/",
    version: str = "3.1.0",
    local_url: str = "",
    program_names: str = "",
    requires_auth: str = "false",
    openapi_url: str = "",
    name: str = "OpenADR3 VTN",
) -> _VTNAdvertiser:
    """Register an mDNS service advertising a VTN.

    Returns a context manager / object with ``.close()`` to unregister.

    Useful for testing discovery against a running VTN-RI without
    modifying VTN-RI itself.
    """
    zc_mod = _import_zeroconf()
    import socket

    Zeroconf = zc_mod.Zeroconf
    ServiceInfo = zc_mod.ServiceInfo

    properties = {
        "version": version,
        "base_path": base_path,
    }
    if local_url:
        properties["local_url"] = local_url
    if program_names:
        properties["program_names"] = program_names
    if requires_auth:
        properties["requires_auth"] = requires_auth
    if openapi_url:
        properties["openapi_url"] = openapi_url

    info = ServiceInfo(
        SERVICE_TYPE,
        f"{name}.{SERVICE_TYPE}",
        server=f"{host}.",
        port=port,
        properties=properties,
        addresses=[socket.inet_aton(
            "127.0.0.1" if host in ("localhost", "127.0.0.1") else host
        )],
    )

    zc = Zeroconf()
    zc.register_service(info)
    log.info("mDNS service registered: %s on %s:%d", name, host, port)

    return _VTNAdvertiser(info, zc)
