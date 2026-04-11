"""Base client with auth, lifecycle, and __getattr__ delegation to OpenADRClient."""

from __future__ import annotations

import logging
import threading
from typing import Any

from openadr3.api import (
    OpenADRClient,
    create_bl_client,
    create_ven_client,
)
from openadr3.auth import fetch_token

from openadr3_client.discovery import DiscoveryMode, resolve_url

log = logging.getLogger(__name__)


class BaseClient:
    """Lifecycle-managed OpenADR 3 client with __getattr__ delegation.

    Any attribute not found on this class is forwarded to the underlying
    OpenADRClient, eliminating the need for explicit delegation methods.
    """

    _client_type: str = "ven"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        spec_version: str = "3.1.0",
        spec_path: str | None = None,
        validate: bool = False,
        discovery: str | DiscoveryMode = "never",
        discovery_timeout: float = 3.0,
    ) -> None:
        if not token and not (client_id and client_secret):
            raise ValueError("Provide either token or both client_id and client_secret")

        self.discovery_mode = DiscoveryMode(discovery)
        self.discovery_timeout = discovery_timeout

        if self.discovery_mode == DiscoveryMode.NEVER and not url:
            raise ValueError("url is required when discovery='never'")
        if self.discovery_mode == DiscoveryMode.LOCAL_WITH_FALLBACK and not url:
            raise ValueError("url is required when discovery='local_with_fallback'")

        self.url = url
        self.token = token
        self.client_id = client_id
        self.client_secret = client_secret
        self.spec_version = spec_version
        self.spec_path = spec_path
        self.validate = validate

        self._resolved_url: str | None = None
        self._api: OpenADRClient | None = None
        self._lock = threading.Lock()

    # -- Lifecycle --

    def start(self) -> BaseClient:
        """Start the client — creates the underlying OpenADRClient.

        Resolves the VTN URL via mDNS discovery (if configured), then
        fetches an auth token if needed, and creates the OpenADRClient.
        """
        if self._api:
            log.info(
                "%s already started: url=%s",
                type(self).__name__,
                self._resolved_url,
            )
            return self

        self._resolved_url = resolve_url(
            self.discovery_mode,
            self.url,
            self.discovery_timeout,
        )

        if not self.token:
            self.token = fetch_token(
                base_url=self._resolved_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            log.info("Token fetched via client credentials: client_id=%s", self.client_id)

        create_fn = create_ven_client if self._client_type == "ven" else create_bl_client
        self._api = create_fn(
            base_url=self._resolved_url,
            token=self.token,
            spec_path=self.spec_path,
            validate=self.validate,
        )
        log.info(
            "%s started: type=%s url=%s",
            type(self).__name__,
            self._client_type,
            self._resolved_url,
        )
        return self

    def stop(self) -> BaseClient:
        """Stop the client — close HTTP connection."""
        if self._api:
            self._api.close()
            self._api = None
        log.info("%s stopped", type(self).__name__)
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()

    @property
    def api(self) -> OpenADRClient:
        """The underlying OpenADRClient. Raises if not started."""
        if not self._api:
            raise RuntimeError(f"{type(self).__name__} not started. Call start() first.")
        return self._api

    # -- __getattr__ delegation --

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attributes to the underlying OpenADRClient."""
        # Only delegate if _api exists and is set (avoid recursion during __init__)
        api = self.__dict__.get("_api")
        if api is not None:
            try:
                return getattr(api, name)
            except AttributeError:
                pass
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
