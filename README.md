# python-oa3-client

OpenADR 3 companion client with VEN registration, lifecycle management, and optional MQTT and webhook notification support.

Built on top of [openadr3](https://github.com/grid-coordination/python-oa3) (Pydantic models, httpx HTTP client).

## Install

```bash
pip install python-oa3-client            # core: VEN registration, API access
pip install python-oa3-client[mqtt]      # + MQTT notifications
pip install python-oa3-client[webhooks]  # + webhook receiver
pip install python-oa3-client[all]       # everything
```

The core package depends only on `openadr3`. Notification channels are optional extras:

| Extra | Adds | Dependency |
|-------|------|------------|
| `mqtt` | MQTT broker connection, topic discovery, message collection | [ebus-mqtt-client](https://github.com/electrification-bus/ebus-mqtt-client) (paho-mqtt v2) |
| `webhooks` | HTTP webhook receiver for VTN callbacks | [Flask](https://flask.palletsprojects.com/) |
| `all` | Both of the above | — |

## Architecture

`OA3Client` wraps `OpenADRClient` (from openadr3) with:

- **Lifecycle management** — `start()` / `stop()` / context manager
- **VEN registration** — find-or-create by name, stores `ven_id` in client state
- **MQTT notifications** (optional) — connect to broker, subscribe to VTN topics, collect messages
- **Webhook notifications** (optional) — receive VTN callbacks via HTTP
- **Thread-safe state** — VEN registration and message buffers guarded by locks
- **Full API delegation** — all `OpenADRClient` methods available through `OA3Client`

## Authentication

The client sends the `token` as a `Bearer` token in every HTTP request. The
token format depends on the VTN's auth configuration — the client itself is
auth-agnostic.

When using the **OpenADR 3 VTN Reference Implementation**, the default auth
provider (as of mid-2026) uses basic credentials encoded as
`base64(client_id:secret)`:

```python
import base64

# VTN-RI default credentials (from config.py)
bl_token = base64.b64encode(b"bl_client:1001").decode()
ven_token = base64.b64encode(b"ven_client:999").decode()

bl = OA3Client(client_type="bl", url=vtn_url, token=bl_token)
ven = OA3Client(client_type="ven", url=vtn_url, token=ven_token)
```

For production VTNs, obtain tokens via the VTN's OAuth2 / token endpoint.

## Quick start

```python
from openadr3_client import OA3Client

client = OA3Client(
    client_type="ven",
    url="http://localhost:8080/openadr3/3.1.0",
    token="my-token",  # Bearer token — format depends on VTN auth config
)
client.start()

# Register VEN (idempotent — finds existing by name or creates new)
client.register("my-ven")
print(client.ven_id)   # => "42"
print(client.ven_name) # => "my-ven"

# Query the VTN
programs = client.programs()    # coerced Pydantic models
events = client.events()
vens = client.vens()

# Raw HTTP access (returns httpx.Response)
resp = client.get_programs(skip=0, limit=10)

client.stop()
```

### Context manager

```python
with OA3Client(client_type="ven", url=url, token=token) as client:
    client.register("my-ven")
    programs = client.programs()
# automatically stopped — notifications disconnected, HTTP closed
```

### BL (Business Logic) client

```python
with OA3Client(client_type="bl", url=url, token=bl_token) as bl:
    resp = bl.create_program({
        "programName": "tariff-program",
        "programType": "PRICING_TARIFF",
        "country": "US",
        "principalSubdivision": "CA",
        "intervalPeriod": {"start": "2024-01-01T00:00:00Z", "duration": "P1Y"},
    })
    resp = bl.create_event({...})
```

## MQTT notifications

Requires: `pip install python-oa3-client[mqtt]`

Connect to an MQTT broker, discover topics from the VTN, and collect notification messages.

### Manual subscription

```python
client.connect_mqtt("mqtt://broker:1883", client_id="my-ven-mqtt")
client.subscribe_mqtt("openadr3/#")

# Wait for messages
messages = client.await_mqtt_messages(n=1, timeout=10.0)
for msg in messages:
    print(msg.topic, msg.payload)

client.disconnect_mqtt()
```

### Auto-subscribe via VTN topic discovery

The VTN publishes which MQTT topics it uses. `subscribe_notifications()` queries the VTN for topics and subscribes in one call:

```python
client.register("my-ven")
client.connect_mqtt("mqtt://broker:1883")

# Subscribe to all topics for this VEN (uses registered ven_id)
client.subscribe_notifications(OA3Client.get_mqtt_topics_ven)

# Or subscribe to program topics
client.subscribe_notifications(OA3Client.get_mqtt_topics_programs)
```

### Message inspection

```python
# All messages
msgs = client.mqtt_messages

# Filter by topic
msgs = client.mqtt_messages_on_topic("programs/create")

# Wait for N messages (with timeout)
msgs = client.await_mqtt_messages(n=3, timeout=5.0)
msgs = client.await_mqtt_messages_on_topic("events/create", n=1, timeout=5.0)

# Clear collected messages
client.clear_mqtt_messages()
```

### MQTTMessage fields

Each collected message is an `MQTTMessage` dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | MQTT topic the message arrived on |
| `payload` | `Any` | Parsed JSON, or coerced `Notification` if applicable |
| `time` | `float` | Unix timestamp when received |
| `raw_payload` | `bytes` | Original bytes from the broker |

Payloads that look like OpenADR notifications are automatically coerced into `Notification` models with the inner object parsed as a Pydantic entity (Program, Event, etc.).

### TLS connections

```python
client.connect_mqtt("mqtts://secure-broker:8883")
```

The `MQTTConnection` translates URI schemes automatically:
- `mqtt://` → plaintext, default port 1883
- `mqtts://` → TLS, default port 8883

## Webhook notifications

Requires: `pip install python-oa3-client[webhooks]`

Receive VTN notifications via HTTP callbacks. The client starts a Flask HTTP server
in a background thread to receive POST requests from the VTN.

### Basic usage

```python
# Start a webhook server (port=0 lets the OS assign a free port)
client.start_webhook_server(
    bearer_token="my-secret",
    callback_host="192.168.1.50",  # IP/hostname the VTN can reach
)
print(client.webhook_callback_url)
# => "http://192.168.1.50:54321/notifications"

# Create a VTN subscription pointing to the webhook
client.create_subscription({
    "clientName": "my-ven",
    "programID": program_id,
    "objectOperations": [{
        "objects": ["PROGRAM"],
        "operations": ["CREATE", "UPDATE", "DELETE"],
        "callbackUrl": client.webhook_callback_url,
        "bearerToken": "my-secret",
    }],
})

# Wait for notifications
msgs = client.await_webhook_messages(n=1, timeout=10.0)
for msg in msgs:
    print(msg.path, msg.payload)

client.stop_webhook_server()
```

### Callback URL and network reachability

The VTN sends notifications by POSTing to the `callbackUrl` you provide in the
subscription. This URL must be **reachable from the VTN**, which means:

- **`callback_host`** must be set to an IP address or hostname that the VTN can
  route to. The default `127.0.0.1` only works when VTN and client run on the
  same host.
- **`port=0`** (the default) lets the OS assign an ephemeral port, which is
  safe for running multiple clients on the same host. The actual port is
  available via `webhook_callback_url` after `start()`.

Webhooks work well in two common scenarios:

- **Same subnet** (home LAN, on-prem) — use `detect_lan_ip()` to auto-discover
  the client's LAN address
- **Cloud-to-cloud** — provide the client's known public hostname or load
  balancer URL

Webhooks behind NATing firewalls are uncommon — MQTT is usually a better fit for
those environments.

```python
# Same host as VTN (testing/development)
client.start_webhook_server()  # callback_host defaults to 127.0.0.1

# Same subnet — auto-detect LAN IP
from openadr3_client import detect_lan_ip
client.start_webhook_server(callback_host=detect_lan_ip())
# => callback_url: http://192.168.1.50:54321/notifications

# Cloud — user provides their known public hostname
client.start_webhook_server(callback_host="ven42.example.com")

# Multiple clients on the same host (each gets a unique port)
client1.start_webhook_server(callback_host=detect_lan_ip())
client2.start_webhook_server(callback_host=detect_lan_ip())
print(client1.webhook_callback_url)  # http://192.168.1.50:52341/notifications
print(client2.webhook_callback_url)  # http://192.168.1.50:52342/notifications
```

### Standalone WebhookReceiver

```python
from openadr3_client import WebhookReceiver

receiver = WebhookReceiver(
    port=9000,
    bearer_token="secret",
    path="/callbacks",
    callback_host="10.0.1.42",
)
receiver.start()

# Use receiver.callback_url in your VTN subscription
# ... VTN sends POST to http://10.0.1.42:9000/callbacks ...

msgs = receiver.await_messages(n=1, timeout=5.0)
receiver.stop()
```

### WebhookMessage fields

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | URL path the notification arrived on |
| `payload` | `Any` | Parsed JSON, or coerced `Notification` if applicable |
| `time` | `float` | Unix timestamp when received |
| `raw_payload` | `bytes` | Original request body bytes |

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `"0.0.0.0"` | Bind address (listen on all interfaces) |
| `port` | `0` | Listen port (0 = OS-assigned ephemeral) |
| `bearer_token` | `None` | Expected Bearer token from VTN (no auth if None) |
| `path` | `"/notifications"` | URL path to receive POSTs on |
| `callback_host` | `"127.0.0.1"` | Hostname/IP used in `callback_url` — must be reachable from the VTN |
| `on_message` | `None` | Callback `(path, payload) -> None` |

## MQTT topic endpoints

VEN-scoped methods default to the registered `ven_id` when called without arguments:

```python
client.register("my-ven")

# These use the registered ven_id automatically
resp = client.get_mqtt_topics_ven()
resp = client.get_mqtt_topics_ven_events()
resp = client.get_mqtt_topics_ven_programs()
resp = client.get_mqtt_topics_ven_resources()

# Or pass an explicit ven_id
resp = client.get_mqtt_topics_ven("other-ven-id")
```

Non-VEN-scoped topic endpoints:

```python
client.get_mqtt_topics_programs()
client.get_mqtt_topics_program(program_id)
client.get_mqtt_topics_program_events(program_id)
client.get_mqtt_topics_events()
client.get_mqtt_topics_reports()
client.get_mqtt_topics_subscriptions()
client.get_mqtt_topics_vens()
client.get_mqtt_topics_resources()
```

## API reference

### OA3Client

#### Constructor

```python
OA3Client(
    client_type: str,        # "ven" or "bl"
    url: str,                # VTN base URL
    token: str,              # Bearer auth token
    spec_version: str = "3.1.0",
    spec_path: str = None,   # Path to OpenAPI spec YAML (optional)
    validate: bool = False,  # Enable request/response validation
)
```

#### Lifecycle

| Method | Returns | Description |
|--------|---------|-------------|
| `start()` | `OA3Client` | Create HTTP client, connect to VTN |
| `stop()` | `OA3Client` | Stop MQTT, webhook server, close HTTP |
| `__enter__` / `__exit__` | — | Context manager (calls start/stop) |

#### VEN registration

| Method / Property | Returns | Description |
|-------------------|---------|-------------|
| `register(ven_name)` | `OA3Client` | Find-or-create VEN, store ven_id |
| `ven_id` | `str \| None` | Registered VEN ID |
| `ven_name` | `str \| None` | Registered VEN name |

#### Coerced entity access

Returns Pydantic models (from openadr3):

| Method | Returns |
|--------|---------|
| `programs(**params)` | `list[Program]` |
| `program(id)` | `Program` |
| `events(**params)` | `list[Event]` |
| `event(id)` | `Event` |
| `vens(**params)` | `list[Ven]` |
| `ven(id)` | `Ven` |
| `resources(**params)` | `list[Resource]` |
| `resource(id)` | `Resource` |
| `reports(**params)` | `list[Report]` |
| `report(id)` | `Report` |
| `subscriptions(**params)` | `list[Subscription]` |
| `subscription(id)` | `Subscription` |

#### Raw HTTP methods

All return `httpx.Response`. Full CRUD for programs, events, vens, resources, reports, subscriptions. See source for complete list.

#### MQTT (requires `[mqtt]` extra)

| Method | Returns | Description |
|--------|---------|-------------|
| `connect_mqtt(broker_url, client_id?, on_message?)` | `OA3Client` | Connect to broker |
| `subscribe_mqtt(topics)` | `OA3Client` | Subscribe to topic(s) |
| `subscribe_notifications(topic_fn)` | `OA3Client` | Query VTN + subscribe |
| `mqtt_messages` | `list[MQTTMessage]` | All collected messages |
| `mqtt_messages_on_topic(topic)` | `list[MQTTMessage]` | Filter by topic |
| `await_mqtt_messages(n, timeout=5.0)` | `list[MQTTMessage]` | Wait for N messages |
| `await_mqtt_messages_on_topic(topic, n, timeout=5.0)` | `list[MQTTMessage]` | Wait for N on topic |
| `clear_mqtt_messages()` | `OA3Client` | Clear message buffer |
| `disconnect_mqtt()` | `OA3Client` | Disconnect from broker |

#### Webhook (requires `[webhooks]` extra)

| Method | Returns | Description |
|--------|---------|-------------|
| `start_webhook_server(host?, port?, bearer_token?, path?, callback_host?, on_message?)` | `OA3Client` | Start receiver |
| `webhook_callback_url` | `str` | URL for VTN subscription (uses callback_host + actual port) |
| `webhook_messages` | `list[WebhookMessage]` | All collected messages |
| `webhook_messages_on_path(path)` | `list[WebhookMessage]` | Filter by path |
| `await_webhook_messages(n, timeout=5.0)` | `list[WebhookMessage]` | Wait for N messages |
| `await_webhook_messages_on_path(path, n, timeout=5.0)` | `list[WebhookMessage]` | Wait for N on path |
| `clear_webhook_messages()` | `OA3Client` | Clear message buffer |
| `stop_webhook_server()` | `OA3Client` | Stop receiver |

### Helper functions

```python
from openadr3_client import extract_topics, normalize_broker_uri, detect_lan_ip

# Extract topic strings from a VTN MQTT topics response
topics = extract_topics(resp)  # => ["programs/create", "programs/update"]

# Parse broker URI into (host, port, use_tls)
host, port, tls = normalize_broker_uri("mqtts://broker:8883")
# => ("broker", 8883, True)

# Detect this machine's LAN IP (for webhook callback_host)
ip = detect_lan_ip()  # => "192.168.1.50"
```

## Examples

See [`examples/smoke_test.py`](examples/smoke_test.py) for a complete integration test against a live VTN-RI and Mosquitto broker.

## Development

```bash
git clone https://github.com/grid-coordination/python-oa3-client
cd python-oa3-client
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
