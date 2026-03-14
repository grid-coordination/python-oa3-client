"""MQTT notification support for OpenADR 3 clients.

Connects to an MQTT broker via ebus-mqtt-client and collects messages
in a thread-safe list. Payloads that look like OpenADR notifications
are automatically coerced into Notification models.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from ebus_mqtt_client import MqttClient
from openadr3.entities import coerce_notification, is_notification

log = logging.getLogger(__name__)


def normalize_broker_uri(uri: str) -> tuple[str, int, bool]:
    """Translate an MQTT URI into (host, port, use_tls).

    Supports mqtt://, mqtts://, tcp://, ssl:// schemes.
    Adds default ports (1883 for plain, 8883 for TLS) when omitted.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or "127.0.0.1"

    if scheme in ("mqtts", "ssl"):
        use_tls = True
        port = parsed.port or 8883
    else:
        use_tls = False
        port = parsed.port or 1883

    return host, port, use_tls


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
        return coerce_notification(
            parsed, {"openadr/channel": "mqtt", "openadr/topic": topic}
        )
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
