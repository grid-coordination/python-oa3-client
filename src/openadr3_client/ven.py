"""VenClient — VEN registration, program lookup, notification subscribe."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
from openadr3.api import success
from openadr3.entities.models import Event, Program

from openadr3_client.base import BaseClient
from openadr3_client.mqtt import extract_mqtt_broker_uris
from openadr3_client.notifications import (
    MqttChannel,
    NotificationChannel,
    WebhookChannel,
)

log = logging.getLogger(__name__)


def extract_topics(resp: httpx.Response) -> list[str] | None:
    """Extract topic strings from a VTN MQTT topics response."""
    if not success(resp):
        return None
    data = resp.json()
    if not isinstance(data, dict):
        return None
    topics = data.get("topics", {})
    return list(topics.values()) if topics else None


class VenClient(BaseClient):
    """OpenADR 3 VEN client with registration, program lookup, and notifications.

    Extends BaseClient with VEN-specific capabilities:
    - VEN registration (find-or-create by name)
    - Program name→ID resolution with caching
    - Notifier discovery and MQTT support detection
    - Notification channel management (MQTT, webhook)
    - subscribe() for topic-based notification subscription
    - VEN-scoped topic methods that default to the registered ven_id
    """

    _client_type = "ven"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ven_id: str | None = None
        self._ven_name: str | None = None
        self._program_cache: dict[str, str] = {}  # name → id
        self._channels: list[NotificationChannel] = []

    # -- Lifecycle --

    def stop(self) -> BaseClient:
        """Stop all channels, then stop the base client."""
        for ch in self._channels:
            ch.stop()
        self._channels.clear()
        return super().stop()

    # -- VEN registration --

    @property
    def ven_id(self) -> str | None:
        return self._ven_id

    @property
    def ven_name(self) -> str | None:
        return self._ven_name

    def _require_ven_id(self) -> str:
        if not self._ven_id:
            raise RuntimeError("VEN not registered. Call register() first.")
        return self._ven_id

    def register(self, ven_name: str) -> VenClient:
        """Register this VEN with the VTN. Idempotent — finds existing or creates new."""
        with self._lock:
            existing = self.api.find_ven_by_name(ven_name)
            if existing:
                vid = existing.id
                log.info("VEN found, reusing: name=%s id=%s", ven_name, vid)
            else:
                resp = self.api.create_ven(
                    {
                        "objectType": "VEN_VEN_REQUEST",
                        "venName": ven_name,
                    }
                )
                resp.raise_for_status()
                vid = resp.json().get("id")
                if not vid:
                    raise RuntimeError(f"VEN registration failed: {resp.status_code} {resp.text}")
                log.info("VEN registered: name=%s id=%s", ven_name, vid)
            self._ven_id = vid
            self._ven_name = ven_name
        return self

    # -- Program lookup --

    def find_program_by_name(self, name: str) -> Program | None:
        """Query VTN for a program by programName. Caches the ID on success."""
        program = self.api.find_program_by_name(name)
        if program and program.id:
            self._program_cache[name] = program.id
        return program

    def resolve_program_id(self, name: str) -> str:
        """Cached name→ID lookup. Queries VTN if not cached.

        Raises KeyError if program not found.
        """
        if name in self._program_cache:
            return self._program_cache[name]
        result = self.find_program_by_name(name)
        if not result:
            raise KeyError(f"Program not found: {name!r}")
        return self._program_cache[name]

    # -- Notifier discovery --

    def discover_notifiers(self) -> dict[str, Any] | None:
        """GET /notifiers — discover VTN notification capabilities."""
        resp = self.api.get_notifiers()
        if success(resp):
            return resp.json()
        return None

    def vtn_supports_mqtt(self) -> bool:
        """Check if the VTN advertises MQTT notification support.

        Handles both the spec ``notifiersResponse`` dict (presence of an
        ``MQTT`` key with a non-null binding object) and the VTN-RI list
        shape (``[{"transport": "MQTT", ...}, ...]``).
        """
        notifiers = self.discover_notifiers()
        if not notifiers:
            return False
        if isinstance(notifiers, dict):
            mqtt = notifiers.get("MQTT") or notifiers.get("mqtt")
            return bool(mqtt)
        if isinstance(notifiers, list):
            return any(
                isinstance(n, dict) and (n.get("transport") or "").upper() == "MQTT"
                for n in notifiers
            )
        return False

    def get_mqtt_broker_uris(self) -> list[str]:
        """Return MQTT broker URIs the VTN advertises via ``/notifiers``.

        Empty if MQTT is not advertised. Use :func:`normalize_broker_uri`
        before passing to a connection if you need (host, port, use_tls).
        """
        return extract_mqtt_broker_uris(self.discover_notifiers())

    # -- Channel management --

    def add_mqtt(
        self,
        broker_url: str,
        client_id: str | None = None,
        on_message: Callable[[str, Any], None] | None = None,
        **kwargs: Any,
    ) -> MqttChannel:
        """Create an MqttChannel (not started yet)."""
        ch = MqttChannel(
            broker_url=broker_url,
            client_id=client_id,
            on_message=on_message,
            **kwargs,
        )
        self._channels.append(ch)
        return ch

    def add_webhook(
        self,
        host: str = "0.0.0.0",
        port: int = 0,
        bearer_token: str | None = None,
        path: str = "/notifications",
        callback_host: str | None = None,
        on_message: Callable[[str, Any], None] | None = None,
        **kwargs: Any,
    ) -> WebhookChannel:
        """Create a WebhookChannel (not started yet)."""
        ch = WebhookChannel(
            host=host,
            port=port,
            bearer_token=bearer_token,
            path=path,
            callback_host=callback_host,
            on_message=on_message,
            **kwargs,
        )
        self._channels.append(ch)
        return ch

    # -- Subscribe --

    def subscribe(
        self,
        program_names: list[str],
        objects: list[str],
        operations: list[str],
        channel: NotificationChannel,
    ) -> list[str]:
        """Resolve program names to IDs, discover MQTT topics, and subscribe.

        For MQTT channels: queries VTN for topics for each program and subscribes.
        For webhook channels: creates VTN subscriptions with callback URLs.

        Returns the list of topics subscribed to.
        """
        all_topics = []

        for name in program_names:
            program_id = self.resolve_program_id(name)

            if isinstance(channel, MqttChannel):
                # Query VTN for MQTT topics for this program's events
                resp = self.api.get_mqtt_topics_program_events(program_id)
                topics = extract_topics(resp)
                if topics:
                    channel.subscribe_topics(topics)
                    all_topics.extend(topics)
            elif isinstance(channel, WebhookChannel):
                # Create a VTN subscription pointing to the webhook
                self.api.create_subscription(
                    {
                        "clientName": self._ven_name or "ven-client",
                        "programID": program_id,
                        "objectOperations": [
                            {
                                "objects": objects,
                                "operations": operations,
                                "callbackUrl": channel.callback_url,
                                "bearerToken": channel._receiver.bearer_token,
                            }
                        ],
                    }
                )

        return all_topics

    # -- Poll events --

    def poll_events(self, program_name: str) -> list[Event]:
        """GET events filtered by program name. Returns coerced Event models."""
        program_id = self.resolve_program_id(program_name)
        return self.api.events(programID=program_id)

    # -- VEN-scoped topic methods (default ven_id to registered) --

    def get_mqtt_topics_ven(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven(ven_id or self._require_ven_id())

    def get_mqtt_topics_ven_events(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven_events(ven_id or self._require_ven_id())

    def get_mqtt_topics_ven_programs(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven_programs(ven_id or self._require_ven_id())

    def get_mqtt_topics_ven_resources(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven_resources(ven_id or self._require_ven_id())
