"""MQTT notification support for OpenADR 3 clients.

Connects to an MQTT broker via ebus-mqtt-client and collects messages
in a thread-safe list. Payloads that look like OpenADR notifications
are automatically coerced into Notification models.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from openadr3.entities import coerce_notification, is_notification

if TYPE_CHECKING:
    from ebus_mqtt_client import MqttClient

log = logging.getLogger(__name__)


_KNOWN_MQTT_SCHEMES = frozenset({"mqtt", "mqtts", "tcp", "ssl"})
_TLS_MQTT_SCHEMES = frozenset({"mqtts", "ssl"})


def normalize_broker_uri(uri: str) -> tuple[str, int, bool]:
    """Translate an MQTT URI into (host, port, use_tls).

    Liberal in what is accepted (Postel's Law):

    - Recognized schemes: ``mqtt://`` and ``tcp://`` (plain, default 1883),
      ``mqtts://`` and ``ssl://`` (TLS, default 8883). Case-insensitive.
    - Bare or unknown-scheme inputs (``broker.example.com``,
      ``broker.example.com:1883``) are interpreted as plain MQTT.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if scheme not in _KNOWN_MQTT_SCHEMES:
        # Unknown or missing scheme — strip any "<scheme>://" prefix and
        # re-parse as plain MQTT. Be liberal in what we accept.
        rest = uri.split("://", 1)[1] if "://" in uri else uri
        parsed = urlparse(f"mqtt://{rest}")
        scheme = "mqtt"

    host = parsed.hostname or "127.0.0.1"
    use_tls = scheme in _TLS_MQTT_SCHEMES
    port = parsed.port or (8883 if use_tls else 1883)
    return host, port, use_tls


def extract_mqtt_broker_uris(notifiers: Any) -> list[str]:
    """Extract MQTT broker URIs from a ``/notifiers`` response.

    Accepts both response shapes seen in the wild:

    - **Spec shape** (`notifiersResponse`): ``{"WEBHOOK": true, "MQTT": {"URIS": [...], ...}}``
    - **VTN-RI shape**: ``[{"transport": "MQTT", "url": "..."}, ...]``

    Returns an empty list if no MQTT URI is advertised. Schemes are returned
    as-is (callers should pass them through :func:`normalize_broker_uri`).
    """
    if not notifiers:
        return []

    if isinstance(notifiers, dict):
        mqtt = notifiers.get("MQTT") or notifiers.get("mqtt")
        if not isinstance(mqtt, dict):
            return []
        uris = mqtt.get("URIS") or mqtt.get("uris")
        if isinstance(uris, list):
            return [u for u in uris if isinstance(u, str)]
        single = mqtt.get("URI") or mqtt.get("uri") or mqtt.get("url") or mqtt.get("broker")
        return [single] if isinstance(single, str) else []

    if isinstance(notifiers, list):
        result: list[str] = []
        for item in notifiers:
            if not isinstance(item, dict):
                continue
            transport = (item.get("transport") or item.get("Transport") or "").upper()
            if transport and transport != "MQTT":
                continue
            uri = (
                item.get("url")
                or item.get("uri")
                or item.get("URI")
                or item.get("URL")
                or item.get("broker")
                or item.get("endpoint")
            )
            if isinstance(uri, str):
                result.append(uri)
            uris = item.get("URIS") or item.get("uris")
            if isinstance(uris, list):
                result.extend(u for u in uris if isinstance(u, str))
        return result

    return []


def _parse_payload(raw: bytes, topic: str) -> Any:
    """Parse MQTT payload bytes as JSON, coercing notifications."""
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw

    try:
        parsed = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s

    if isinstance(parsed, dict) and is_notification(parsed):
        return coerce_notification(parsed, {"openadr/channel": "mqtt", "openadr/topic": topic})
    return parsed


@dataclass
class MQTTMessage:
    """A received MQTT message."""

    topic: str
    payload: Any
    time: float
    raw_payload: bytes


class MQTTConnection:
    """MQTT connection with thread-safe message collection.

    Wraps ebus-mqtt-client's MqttClient, adding:
    - Message collection in a thread-safe list
    - Notification payload coercion
    - Await helpers for testing
    """

    def __init__(
        self,
        broker_url: str,
        client_id: str | None = None,
        on_message: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.broker_url = broker_url
        self.client_id = client_id or f"oa3-{id(self):x}"
        self.on_message_callback = on_message
        self._messages: list[MQTTMessage] = []
        self._lock = threading.Lock()
        self._client: MqttClient | None = None

    def connect(self) -> None:
        """Connect to the MQTT broker."""
        try:
            from ebus_mqtt_client import MqttClient
        except ImportError as err:
            raise ImportError(
                "ebus-mqtt-client is required for MQTT support. "
                "Install it with: pip install python-oa3-client[mqtt]"
            ) from err

        host, port, use_tls = normalize_broker_uri(self.broker_url)
        self._client = MqttClient(
            client_id=self.client_id,
            endpoint=host,
            port=port,
            use_tls=use_tls,
            tls_insecure=True,
        )
        self._client.start()
        log.info("MQTT connected: broker=%s client_id=%s", self.broker_url, self.client_id)

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._client:
            self._client.stop()
            log.info("MQTT disconnected: broker=%s", self.broker_url)
            self._client = None

    def is_connected(self) -> bool:
        return self._client.is_connected() if self._client else False

    def subscribe(self, topics: list[str] | str) -> None:
        """Subscribe to one or more MQTT topics."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        if isinstance(topics, str):
            topics = [topics]
        for topic in topics:
            self._client.subscribe(topic, self._handle_message)
        log.info("MQTT subscribed: topics=%s", topics)

    def _handle_message(self, topic: str, payload: bytes) -> None:
        """Internal callback — parse, collect, and dispatch."""
        parsed = _parse_payload(payload, topic)
        msg = MQTTMessage(
            topic=topic,
            payload=parsed,
            time=time.time(),
            raw_payload=payload,
        )
        with self._lock:
            self._messages.append(msg)
        log.debug("MQTT message: topic=%s", topic)
        if self.on_message_callback:
            self.on_message_callback(topic, parsed)

    @property
    def messages(self) -> list[MQTTMessage]:
        """All collected messages (snapshot)."""
        with self._lock:
            return list(self._messages)

    def messages_on_topic(self, topic: str) -> list[MQTTMessage]:
        """Messages received on a specific topic."""
        with self._lock:
            return [m for m in self._messages if m.topic == topic]

    def clear_messages(self) -> None:
        """Clear collected messages."""
        with self._lock:
            self._messages.clear()

    def await_messages(self, n: int, timeout: float = 5.0) -> list[MQTTMessage]:
        """Wait until at least n messages collected, or timeout."""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if len(self._messages) >= n:
                    return list(self._messages)
            if time.time() >= deadline:
                with self._lock:
                    return list(self._messages)
            time.sleep(0.05)

    def await_messages_on_topic(
        self, topic: str, n: int, timeout: float = 5.0
    ) -> list[MQTTMessage]:
        """Wait until at least n messages on a specific topic, or timeout."""
        deadline = time.time() + timeout
        while True:
            msgs = self.messages_on_topic(topic)
            if len(msgs) >= n:
                return msgs
            if time.time() >= deadline:
                return msgs
            time.sleep(0.05)
