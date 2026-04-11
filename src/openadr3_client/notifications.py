"""NotificationChannel protocol and channel implementations.

Provides a common interface for MqttChannel and WebhookChannel, wrapping
the lower-level MQTTConnection and WebhookReceiver.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from openadr3_client.mqtt import MQTTConnection, MQTTMessage
from openadr3_client.webhook import WebhookMessage, WebhookReceiver

log = logging.getLogger(__name__)

# Union of message types from either channel
ChannelMessage = MQTTMessage | WebhookMessage


@runtime_checkable
class NotificationChannel(Protocol):
    """Protocol for notification channels (MQTT, Webhook)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def subscribe_topics(self, topics: list[str]) -> None: ...

    @property
    def messages(self) -> list[ChannelMessage]: ...

    def await_messages(self, n: int, timeout: float = 5.0) -> list[ChannelMessage]: ...
    def clear_messages(self) -> None: ...


class MqttChannel:
    """MQTT notification channel wrapping MQTTConnection.

    Usage::

        ch = MqttChannel("mqtt://broker:1883")
        ch.start()
        ch.subscribe_topics(["openadr3/programs/create"])
        msgs = ch.await_messages(1, timeout=10.0)
        ch.stop()
    """

    def __init__(
        self,
        broker_url: str,
        client_id: str | None = None,
        on_message: Callable[[str, Any], None] | None = None,
        **kwargs: Any,
    ) -> None:
        self._conn = MQTTConnection(
            broker_url=broker_url,
            client_id=client_id,
            on_message=on_message,
        )

    def start(self) -> None:
        """Connect to the MQTT broker."""
        self._conn.connect()

    def stop(self) -> None:
        """Disconnect from the MQTT broker."""
        self._conn.disconnect()

    def subscribe_topics(self, topics: list[str]) -> None:
        """Subscribe to MQTT topics."""
        self._conn.subscribe(topics)

    @property
    def messages(self) -> list[MQTTMessage]:
        return self._conn.messages

    def messages_on_topic(self, topic: str) -> list[MQTTMessage]:
        return self._conn.messages_on_topic(topic)

    def await_messages(self, n: int, timeout: float = 5.0) -> list[MQTTMessage]:
        return self._conn.await_messages(n, timeout)

    def await_messages_on_topic(
        self, topic: str, n: int, timeout: float = 5.0
    ) -> list[MQTTMessage]:
        return self._conn.await_messages_on_topic(topic, n, timeout)

    def clear_messages(self) -> None:
        self._conn.clear_messages()

    @property
    def is_connected(self) -> bool:
        return self._conn.is_connected()


class WebhookChannel:
    """Webhook notification channel wrapping WebhookReceiver.

    Usage::

        ch = WebhookChannel(port=9000, bearer_token="secret")
        ch.start()
        print(ch.callback_url)  # Register with VTN
        msgs = ch.await_messages(1, timeout=10.0)
        ch.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 0,
        bearer_token: str | None = None,
        path: str = "/notifications",
        callback_host: str | None = None,
        on_message: Callable[[str, Any], None] | None = None,
        **kwargs: Any,
    ) -> None:
        self._receiver = WebhookReceiver(
            host=host,
            port=port,
            bearer_token=bearer_token,
            path=path,
            callback_host=callback_host,
            on_message=on_message,
        )

    def start(self) -> None:
        """Start the webhook HTTP server."""
        self._receiver.start()

    def stop(self) -> None:
        """Stop the webhook HTTP server."""
        self._receiver.stop()

    def subscribe_topics(self, topics: list[str]) -> None:
        """No-op for webhooks — topics are managed via VTN subscriptions."""
        pass

    @property
    def callback_url(self) -> str:
        return self._receiver.callback_url

    @property
    def messages(self) -> list[WebhookMessage]:
        return self._receiver.messages

    def messages_on_path(self, path: str) -> list[WebhookMessage]:
        return self._receiver.messages_on_path(path)

    def await_messages(self, n: int, timeout: float = 5.0) -> list[WebhookMessage]:
        return self._receiver.await_messages(n, timeout)

    def await_messages_on_path(
        self, path: str, n: int, timeout: float = 5.0
    ) -> list[WebhookMessage]:
        return self._receiver.await_messages_on_path(path, n, timeout)

    def clear_messages(self) -> None:
        self._receiver.clear_messages()
