# python-oa3-client

OpenADR 3 companion client with VEN/BL client framework, lifecycle management, and optional MQTT and webhook notification channels.

Built on top of [openadr3](https://github.com/grid-coordination/python-oa3) (Pydantic models, httpx HTTP client).

## Install

```bash
pip install python-oa3-client            # core: VEN/BL clients, API access
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

```
BaseClient          — auth, lifecycle, __getattr__ delegation to OpenADRClient
├── VenClient       — VEN registration, program lookup, notification subscribe
└── BlClient        — thin wrapper, client_type="bl", no VEN concepts
```

All `OpenADRClient` methods (raw HTTP, coerced entities, introspection) are available directly on both client types via `__getattr__` delegation — no explicit delegation methods needed.

## Authentication

Two auth modes:

**Direct token** — provide a Bearer token directly:
```python
ven = VenClient(url=vtn_url, token=my_token)
```

**OAuth2 client credentials** — token fetched automatically on `start()`:
```python
ven = VenClient(
    url=vtn_url,
    client_id="my_client",
    client_secret="my_secret",
)
```

For the **OpenADR 3 VTN Reference Implementation**, the default auth uses basic credentials encoded as `base64(client_id:secret)`:

```python
import base64
bl_token = base64.b64encode(b"bl_client:1001").decode()
ven_token = base64.b64encode(b"ven_client:999").decode()
```

## VEN Client

`VenClient` is the primary interface for VEN developers:

```python
from openadr3_client import VenClient

with VenClient(url="http://vtn:8080/openadr3/3.1.0", token=token) as ven:
    # Register VEN (idempotent — finds existing or creates new)
    ven.register("my-thermostat-ven")

    # Find a specific program
    pricing = ven.find_program_by_name("residential-pricing")

    # Check notification support
    if ven.vtn_supports_mqtt():
        mqtt = ven.add_mqtt("mqtts://broker:8883")
        mqtt.start()
        ven.subscribe(
            program_names=["residential-pricing"],
            objects=["EVENT"],
            operations=["CREATE", "UPDATE"],
            channel=mqtt,
        )
        msgs = mqtt.await_messages(1, timeout=30.0)
    else:
        events = ven.poll_events(program_name="residential-pricing")

    # All OpenADRClient methods work via __getattr__
    resp = ven.get_subscriptions()
    reports = ven.reports()
```

### VEN registration

```python
ven.register("my-ven")
print(ven.ven_id)    # "ven-abc-123"
print(ven.ven_name)  # "my-ven"
```

### Program lookup

```python
# Query by name (caches ID)
program = ven.find_program_by_name("residential-pricing")

# Cached name→ID resolution
pid = ven.resolve_program_id("residential-pricing")
```

### Notifier discovery

```python
notifiers = ven.discover_notifiers()
supports_mqtt = ven.vtn_supports_mqtt()
```

### VEN-scoped topic methods

Default to the registered `ven_id` when called without arguments:

```python
ven.register("my-ven")
resp = ven.get_mqtt_topics_ven()           # uses registered ven_id
resp = ven.get_mqtt_topics_ven_events()
resp = ven.get_mqtt_topics_ven("other-id") # explicit ven_id
```

## BL Client

For business logic (creating programs, events):

```python
from openadr3_client import BlClient

with BlClient(url=vtn_url, token=bl_token) as bl:
    bl.create_program({
        "programName": "tariff-program",
        "programType": "PRICING_TARIFF",
        "country": "US",
        "principalSubdivision": "CA",
        "intervalPeriod": {"start": "2024-01-01T00:00:00Z", "duration": "P1Y"},
    })
    bl.create_event({...})
```

## Notification Channels

### MqttChannel

Requires: `pip install python-oa3-client[mqtt]`

```python
mqtt = ven.add_mqtt("mqtt://broker:1883", client_id="my-ven-mqtt")
mqtt.start()

# Manual topic subscription
mqtt.subscribe_topics(["openadr3/#"])

# Or use ven.subscribe() for program-aware subscription
ven.subscribe(
    program_names=["residential-pricing"],
    objects=["EVENT"],
    operations=["CREATE", "UPDATE"],
    channel=mqtt,
)

msgs = mqtt.await_messages(n=1, timeout=10.0)
for msg in msgs:
    print(msg.topic, msg.payload)

mqtt.stop()
```

TLS connections: use `mqtts://` scheme (default port 8883).

### WebhookChannel

Requires: `pip install python-oa3-client[webhooks]`

```python
webhook = ven.add_webhook(
    port=0,                        # OS-assigned ephemeral port
    bearer_token="my-secret",
    callback_host="192.168.1.50",  # IP reachable from VTN
)
webhook.start()
print(webhook.callback_url)  # "http://192.168.1.50:54321/notifications"

# Subscribe creates VTN subscription with callback URL
ven.subscribe(
    program_names=["residential-pricing"],
    objects=["EVENT"],
    operations=["CREATE", "UPDATE"],
    channel=webhook,
)

msgs = webhook.await_messages(n=1, timeout=10.0)
webhook.stop()
```

### Channel lifecycle

Channels are created but not started automatically. You control the lifecycle:

```python
mqtt = ven.add_mqtt(broker_url)  # Created, not connected
mqtt.start()                      # Connected
# ... use ...
mqtt.stop()                       # Disconnected
```

When VenClient stops (via `stop()` or context manager exit), all channels are stopped automatically.

### Message types

**MQTTMessage:**

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | MQTT topic |
| `payload` | `Any` | Parsed JSON, or coerced `Notification` |
| `time` | `float` | Unix timestamp |
| `raw_payload` | `bytes` | Original bytes |

**WebhookMessage:**

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | URL path |
| `payload` | `Any` | Parsed JSON, or coerced `Notification` |
| `time` | `float` | Unix timestamp |
| `raw_payload` | `bytes` | Original request body |

## Direct API access

All `OpenADRClient` methods are available on both VenClient and BlClient via `__getattr__`:

```python
# Raw HTTP (returns httpx.Response)
resp = ven.get_programs(skip=0, limit=10)
resp = ven.create_subscription({...})

# Coerced entities (returns Pydantic models)
programs = ven.programs()
event = ven.event("evt-001")
reports = ven.reports()
subscriptions = ven.subscriptions()

# Introspection (requires spec_path)
routes = ven.all_routes()
scopes = ven.endpoint_scopes("/programs", "get")
```

## Low-level components

The standalone `MQTTConnection`, `WebhookReceiver`, `extract_topics`, `normalize_broker_uri`, and `detect_lan_ip` are still exported for direct use.

## Examples

- [`examples/smoke_test.py`](examples/smoke_test.py) — integration test against live VTN-RI and Mosquitto
- [`examples/ven_workflow.py`](examples/ven_workflow.py) — documented VEN developer workflow
- [`doc/ven-bl-client-guide.md`](doc/ven-bl-client-guide.md) — VEN & BL client use-case walkthrough

## Development

```bash
git clone https://github.com/grid-coordination/python-oa3-client
cd python-oa3-client
pip install -e ".[dev]"
pytest tests/ -v
```

## License

[MIT](LICENSE)
