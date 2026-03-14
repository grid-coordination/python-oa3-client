"""OpenADR 3 companion client with lifecycle, VEN registration, and MQTT."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

import httpx

from openadr3.api import (
    OpenADRClient,
    create_bl_client,
    create_ven_client,
    success,
    body,
)
from openadr3.entities.models import (
    Event,
    Program,
    Report,
    Resource,
    Subscription,
    Ven,
)

from openadr3_client.mqtt import MQTTConnection, MQTTMessage

log = logging.getLogger(__name__)


def extract_topics(resp: httpx.Response) -> list[str] | None:
    """Extract topic strings from a VTN MQTT topics response."""
    if not success(resp):
        return None
    data = resp.json()
    topics = data.get("topics", {})
    return list(topics.values()) if topics else None


class OA3Client:
    """Lifecycle-managed OpenADR 3 client with VEN registration and MQTT.

    Mirrors the Clojure clj-oa3-client OA3Client component. Wraps
    OpenADRClient with mutable state for VEN registration and MQTT
    connection, all guarded by threading locks.
    """

    def __init__(
        self,
        client_type: str,
        url: str,
        token: str,
        spec_version: str = "3.1.0",
        spec_path: str | None = None,
        validate: bool = False,
    ) -> None:
        if client_type not in ("ven", "bl"):
            raise ValueError(f"client_type must be 'ven' or 'bl', got {client_type!r}")

        self.client_type = client_type
        self.url = url
        self.token = token
        self.spec_version = spec_version
        self.spec_path = spec_path
        self.validate = validate

        self._api: OpenADRClient | None = None
        self._lock = threading.Lock()
        self._ven_id: str | None = None
        self._ven_name: str | None = None
        self._mqtt: MQTTConnection | None = None

    # -- Lifecycle --

    def start(self) -> OA3Client:
        """Start the client — creates the underlying OpenADRClient."""
        if self._api:
            log.info("OA3Client already started: type=%s url=%s", self.client_type, self.url)
            return self

        create_fn = create_ven_client if self.client_type == "ven" else create_bl_client
        self._api = create_fn(
            base_url=self.url,
            token=self.token,
            spec_path=self.spec_path,
            validate=self.validate,
        )
        log.info(
            "OA3Client started: type=%s url=%s spec=%s",
            self.client_type, self.url, self.spec_version,
        )
        return self

    def stop(self) -> OA3Client:
        """Stop the client — disconnect MQTT and close HTTP."""
        if self._mqtt:
            self._mqtt.disconnect()
            self._mqtt = None
        if self._api:
            self._api.close()
            self._api = None
        log.info("OA3Client stopped: type=%s", self.client_type)
        return self

    def __enter__(self) -> OA3Client:
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()

    @property
    def api(self) -> OpenADRClient:
        """The underlying OpenADRClient. Raises if not started."""
        if not self._api:
            raise RuntimeError("OA3Client not started. Call start() first.")
        return self._api

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

    def register(self, ven_name: str) -> OA3Client:
        """Register this VEN with the VTN. Idempotent — finds existing or creates new."""
        with self._lock:
            existing = self.api.find_ven_by_name(ven_name)
            if existing:
                vid = existing["id"]
                log.info("VEN found, reusing: name=%s id=%s", ven_name, vid)
            else:
                resp = self.api.create_ven({"venName": ven_name})
                resp.raise_for_status()
                vid = resp.json().get("id")
                if not vid:
                    raise RuntimeError(
                        f"VEN registration failed: {resp.status_code} {resp.text}"
                    )
                log.info("VEN registered: name=%s id=%s", ven_name, vid)
            self._ven_id = vid
            self._ven_name = ven_name
        return self

    # -- Raw API delegation --

    def get_programs(self, **params: Any) -> httpx.Response:
        return self.api.get_programs(**params)

    def get_program_by_id(self, program_id: str) -> httpx.Response:
        return self.api.get_program_by_id(program_id)

    def create_program(self, data: dict[str, Any]) -> httpx.Response:
        return self.api.create_program(data)

    def update_program(self, program_id: str, data: dict[str, Any]) -> httpx.Response:
        return self.api.update_program(program_id, data)

    def delete_program(self, program_id: str) -> httpx.Response:
        return self.api.delete_program(program_id)

    def get_events(self, **params: Any) -> httpx.Response:
        return self.api.get_events(**params)

    def get_event_by_id(self, event_id: str) -> httpx.Response:
        return self.api.get_event_by_id(event_id)

    def create_event(self, data: dict[str, Any]) -> httpx.Response:
        return self.api.create_event(data)

    def update_event(self, event_id: str, data: dict[str, Any]) -> httpx.Response:
        return self.api.update_event(event_id, data)

    def delete_event(self, event_id: str) -> httpx.Response:
        return self.api.delete_event(event_id)

    def get_vens(self, **params: Any) -> httpx.Response:
        return self.api.get_vens(**params)

    def get_ven_by_id(self, ven_id: str) -> httpx.Response:
        return self.api.get_ven_by_id(ven_id)

    def create_ven(self, data: dict[str, Any]) -> httpx.Response:
        return self.api.create_ven(data)

    def update_ven(self, ven_id: str, data: dict[str, Any]) -> httpx.Response:
        return self.api.update_ven(ven_id, data)

    def delete_ven(self, ven_id: str) -> httpx.Response:
        return self.api.delete_ven(ven_id)

    def find_ven_by_name(self, name: str) -> dict[str, Any] | None:
        return self.api.find_ven_by_name(name)

    def get_resources(self, **params: Any) -> httpx.Response:
        return self.api.get_resources(**params)

    def get_resource_by_id(self, resource_id: str) -> httpx.Response:
        return self.api.get_resource_by_id(resource_id)

    def create_resource(self, data: dict[str, Any]) -> httpx.Response:
        return self.api.create_resource(data)

    def update_resource(self, resource_id: str, data: dict[str, Any]) -> httpx.Response:
        return self.api.update_resource(resource_id, data)

    def delete_resource(self, resource_id: str) -> httpx.Response:
        return self.api.delete_resource(resource_id)

    def get_reports(self, **params: Any) -> httpx.Response:
        return self.api.get_reports(**params)

    def get_report_by_id(self, report_id: str) -> httpx.Response:
        return self.api.get_report_by_id(report_id)

    def create_report(self, data: dict[str, Any]) -> httpx.Response:
        return self.api.create_report(data)

    def update_report(self, report_id: str, data: dict[str, Any]) -> httpx.Response:
        return self.api.update_report(report_id, data)

    def delete_report(self, report_id: str) -> httpx.Response:
        return self.api.delete_report(report_id)

    def get_subscriptions(self, **params: Any) -> httpx.Response:
        return self.api.get_subscriptions(**params)

    def get_subscription_by_id(self, subscription_id: str) -> httpx.Response:
        return self.api.get_subscription_by_id(subscription_id)

    def create_subscription(self, data: dict[str, Any]) -> httpx.Response:
        return self.api.create_subscription(data)

    def update_subscription(self, subscription_id: str, data: dict[str, Any]) -> httpx.Response:
        return self.api.update_subscription(subscription_id, data)

    def delete_subscription(self, subscription_id: str) -> httpx.Response:
        return self.api.delete_subscription(subscription_id)

    def get_notifiers(self) -> httpx.Response:
        return self.api.get_notifiers()

    # -- Coerced entity access --

    def programs(self, **params: Any) -> list[Program]:
        return self.api.programs(**params)

    def program(self, program_id: str) -> Program:
        return self.api.program(program_id)

    def events(self, **params: Any) -> list[Event]:
        return self.api.events(**params)

    def event(self, event_id: str) -> Event:
        return self.api.event(event_id)

    def vens(self, **params: Any) -> list[Ven]:
        return self.api.vens(**params)

    def ven(self, ven_id: str) -> Ven:
        return self.api.ven(ven_id)

    def resources(self, **params: Any) -> list[Resource]:
        return self.api.resources(**params)

    def resource(self, resource_id: str) -> Resource:
        return self.api.resource(resource_id)

    def reports(self, **params: Any) -> list[Report]:
        return self.api.reports(**params)

    def report(self, report_id: str) -> Report:
        return self.api.report(report_id)

    def subscriptions(self, **params: Any) -> list[Subscription]:
        return self.api.subscriptions(**params)

    def subscription(self, subscription_id: str) -> Subscription:
        return self.api.subscription(subscription_id)

    # -- MQTT topic endpoints (VEN-scoped versions default to registered ven_id) --

    def get_mqtt_topics_programs(self) -> httpx.Response:
        return self.api.get_mqtt_topics_programs()

    def get_mqtt_topics_program(self, program_id: str) -> httpx.Response:
        return self.api.get_mqtt_topics_program(program_id)

    def get_mqtt_topics_program_events(self, program_id: str) -> httpx.Response:
        return self.api.get_mqtt_topics_program_events(program_id)

    def get_mqtt_topics_events(self) -> httpx.Response:
        return self.api.get_mqtt_topics_events()

    def get_mqtt_topics_reports(self) -> httpx.Response:
        return self.api.get_mqtt_topics_reports()

    def get_mqtt_topics_subscriptions(self) -> httpx.Response:
        return self.api.get_mqtt_topics_subscriptions()

    def get_mqtt_topics_vens(self) -> httpx.Response:
        return self.api.get_mqtt_topics_vens()

    def get_mqtt_topics_ven(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven(ven_id or self._require_ven_id())

    def get_mqtt_topics_ven_events(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven_events(ven_id or self._require_ven_id())

    def get_mqtt_topics_ven_programs(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven_programs(ven_id or self._require_ven_id())

    def get_mqtt_topics_ven_resources(self, ven_id: str | None = None) -> httpx.Response:
        return self.api.get_mqtt_topics_ven_resources(ven_id or self._require_ven_id())

    def get_mqtt_topics_resources(self) -> httpx.Response:
        return self.api.get_mqtt_topics_resources()

    # -- Introspection --

    def all_routes(self) -> list[str]:
        return self.api.all_routes()

    def endpoint_scopes(self, path: str, method: str = "get") -> list[str]:
        return self.api.endpoint_scopes(path, method)

    def authorized(self, path: str, method: str = "get") -> bool:
        return self.api.authorized(path, method)

    # -- MQTT notifications --

    def connect_mqtt(
        self,
        broker_url: str,
        client_id: str | None = None,
        on_message: Callable[[str, Any], None] | None = None,
    ) -> OA3Client:
        """Connect to an MQTT broker for notifications."""
        self._mqtt = MQTTConnection(
            broker_url=broker_url,
            client_id=client_id,
            on_message=on_message,
        )
        self._mqtt.connect()
        return self

    @property
    def mqtt(self) -> MQTTConnection:
        """The MQTT connection. Raises if not connected."""
        if not self._mqtt:
            raise RuntimeError("MQTT not connected. Call connect_mqtt() first.")
        return self._mqtt

    def subscribe_mqtt(self, topics: list[str] | str) -> OA3Client:
        """Subscribe to MQTT topics."""
        self.mqtt.subscribe(topics)
        return self

    def subscribe_notifications(
        self, topic_fn: Callable[[OA3Client], httpx.Response]
    ) -> OA3Client:
        """Query VTN for MQTT topics via topic_fn and subscribe to them."""
        resp = topic_fn(self)
        topics = extract_topics(resp)
        if topics:
            self.subscribe_mqtt(topics)
        return self

    @property
    def mqtt_messages(self) -> list[MQTTMessage]:
        return self.mqtt.messages

    def mqtt_messages_on_topic(self, topic: str) -> list[MQTTMessage]:
        return self.mqtt.messages_on_topic(topic)

    def await_mqtt_messages(self, n: int, timeout: float = 5.0) -> list[MQTTMessage]:
        return self.mqtt.await_messages(n, timeout)

    def await_mqtt_messages_on_topic(
        self, topic: str, n: int, timeout: float = 5.0
    ) -> list[MQTTMessage]:
        return self.mqtt.await_messages_on_topic(topic, n, timeout)

    def clear_mqtt_messages(self) -> OA3Client:
        self.mqtt.clear_messages()
        return self

    def disconnect_mqtt(self) -> OA3Client:
        """Disconnect from the MQTT broker."""
        if self._mqtt:
            self._mqtt.disconnect()
            self._mqtt = None
        return self
