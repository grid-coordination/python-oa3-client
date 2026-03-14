# python-oa3-client

OpenADR 3 companion client with VEN registration, MQTT notifications, and lifecycle management.

Built on top of [openadr3](https://github.com/grid-coordination/python-oa3) (Pydantic models, httpx client) and [ebus-mqtt-client](https://github.com/electrification-bus/ebus-mqtt-client) (paho-mqtt v2 wrapper).

## Install

```bash
pip install python-oa3-client
```

This pulls in `openadr3` and `ebus-mqtt-client` automatically.

## Architecture

```
python-oa3-client
├── openadr3         # Base library: Pydantic models, httpx HTTP client
└── ebus-mqtt-client # MQTT client: paho-mqtt v2, TLS, reconnection
```

`OA3Client` wraps `OpenADRClient` (from openadr3) with:

- **Lifecycle management** — `start()` / `stop()` / context manager
- **VEN registration** — find-or-create by name, stores `ven_id` in client state
- **MQTT notifications** — connect to broker, subscribe to VTN topics, collect messages
- **Thread-safe state** — VEN registration and MQTT messages guarded by locks
- **Full API delegation** — all `OpenADRClient` methods available through `OA3Client`

## Quick start

```python
from openadr3_client import OA3Client

client = OA3Client(
    client_type="ven",
    url="http://localhost:8080/openadr3/3.1.0",
    token="my-token",
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
# automatically stopped — MQTT disconnected, HTTP closed
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
| `stop()` | `OA3Client` | Disconnect MQTT, close HTTP |
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

#### MQTT

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

### Helper functions

```python
from openadr3_client import extract_topics, normalize_broker_uri

# Extract topic strings from a VTN MQTT topics response
topics = extract_topics(resp)  # => ["programs/create", "programs/update"]

# Parse broker URI into (host, port, use_tls)
host, port, tls = normalize_broker_uri("mqtts://broker:8883")
# => ("broker", 8883, True)
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
