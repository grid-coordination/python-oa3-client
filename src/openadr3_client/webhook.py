"""Webhook notification receiver for OpenADR 3 clients.

Runs a Flask HTTP server in a background thread to receive POST
callbacks from the VTN. Shares the same message collection interface
as MQTTConnection.

Requires the ``webhooks`` extra: ``pip install python-oa3-client[webhooks]``
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from openadr3.entities import coerce_notification, is_notification

log = logging.getLogger(__name__)


@dataclass
class WebhookMessage:
    """A received webhook notification."""

    path: str
    payload: Any
    time: float
    raw_payload: bytes


def _parse_webhook_payload(raw: bytes, path: str) -> Any:
    """Parse webhook body as JSON, coercing notifications."""
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
            parsed, {"openadr/channel": "webhook", "openadr/path": path}
        )
    return parsed


class WebhookReceiver:
    """HTTP server that receives VTN webhook notifications.

    Runs Flask in a daemon thread. The VTN POSTs notification JSON to
    the callback URL, optionally authenticated with a Bearer token.

    Usage::

        receiver = WebhookReceiver(port=9000, bearer_token="my-secret")
        receiver.start()
        # callbackUrl = "http://my-host:9000/notifications"
        # ... create subscription with VTN pointing to that URL ...
        msgs = receiver.await_messages(n=1, timeout=10.0)
        receiver.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9000,
        bearer_token: str | None = None,
        path: str = "/notifications",
        on_message: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.bearer_token = bearer_token
        self.path = path
        self.on_message_callback = on_message
        self._messages: list[WebhookMessage] = []
        self._lock = threading.Lock()
        self._server_thread: threading.Thread | None = None
        self._server: Any = None  # werkzeug Server instance

    @property
    def callback_url(self) -> str:
        """The URL the VTN should POST notifications to."""
        return f"http://{self.host}:{self.port}{self.path}"

    def start(self) -> None:
        """Start the webhook server in a background thread."""
        try:
            from flask import Flask, request, abort
        except ImportError:
            raise ImportError(
                "Flask is required for webhook support. "
                "Install it with: pip install python-oa3-client[webhooks]"
            )

        app = Flask(__name__)
        # Suppress Flask/werkzeug request logging
        flask_log = logging.getLogger("werkzeug")
        flask_log.setLevel(logging.WARNING)

        receiver = self  # capture for closure

        @app.route(self.path, methods=["POST"])
        def receive_notification():
            # Verify bearer token if configured
            if receiver.bearer_token:
                auth = request.headers.get("Authorization", "")
                if auth != f"Bearer {receiver.bearer_token}":
                    abort(403)

            raw = request.get_data()
            path = request.path
            parsed = _parse_webhook_payload(raw, path)

            msg = WebhookMessage(
                path=path,
                payload=parsed,
                time=time.time(),
                raw_payload=raw,
            )
            with receiver._lock:
                receiver._messages.append(msg)
            log.debug("Webhook received: path=%s", path)

            if receiver.on_message_callback:
                receiver.on_message_callback(path, parsed)

            return "", 200

        @app.route(self.path, methods=["GET"])
        def health():
            return {"status": "ok"}, 200

        from werkzeug.serving import make_server

        self._server = make_server(self.host, self.port, app)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._server_thread.start()
        log.info(
            "Webhook server started: host=%s port=%d path=%s",
            self.host, self.port, self.path,
        )

    def stop(self) -> None:
        """Stop the webhook server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._server_thread:
            self._server_thread.join(timeout=5.0)
            self._server_thread = None
        log.info("Webhook server stopped")

    @property
    def messages(self) -> list[WebhookMessage]:
        """All collected messages (snapshot)."""
        with self._lock:
            return list(self._messages)

    def messages_on_path(self, path: str) -> list[WebhookMessage]:
        """Messages received on a specific path."""
        with self._lock:
            return [m for m in self._messages if m.path == path]

    def clear_messages(self) -> None:
        """Clear collected messages."""
        with self._lock:
            self._messages.clear()

    def await_messages(self, n: int, timeout: float = 5.0) -> list[WebhookMessage]:
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

    def await_messages_on_path(
        self, path: str, n: int, timeout: float = 5.0
    ) -> list[WebhookMessage]:
        """Wait until at least n messages on a specific path, or timeout."""
        deadline = time.time() + timeout
        while True:
            msgs = self.messages_on_path(path)
            if len(msgs) >= n:
                return msgs
            if time.time() >= deadline:
                return msgs
            time.sleep(0.05)
