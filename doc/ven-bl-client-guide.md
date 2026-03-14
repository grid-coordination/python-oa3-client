# VEN & BL Client Guide

## Overview

`VenClient` is the primary interface for VEN (Virtual End Node) developers integrating with an OpenADR 3 VTN. It handles the common VEN workflow: authenticate, register, discover programs, subscribe to notifications, and process events.

## Quick Start

```python
from openadr3_client import VenClient

with VenClient(
    url="http://vtn.example.com/openadr3/3.1.0",
    client_id="my_ven_client",
    client_secret="my_secret",
) as ven:
    ven.register("my-thermostat-ven")
    programs = ven.programs()
    events = ven.events()
```

## VEN Workflow

### 1. Authentication

VenClient supports two auth modes:

**Direct token:**
```python
ven = VenClient(url=VTN_URL, token="my-bearer-token")
```

**OAuth2 client credentials** (token fetched automatically on `start()`):
```python
ven = VenClient(
    url=VTN_URL,
    client_id="my_client",
    client_secret="my_secret",
)
```

### 2. Register VEN

```python
ven.register("my-thermostat-ven")
print(ven.ven_id)    # "ven-abc-123"
print(ven.ven_name)  # "my-thermostat-ven"
```

Registration is idempotent — if a VEN with that name already exists, VenClient reuses it.

### 3. Discover Programs

```python
# List all programs (coerced Pydantic models)
programs = ven.programs()

# Find a specific program by name
program = ven.find_program_by_name("residential-pricing")
program_id = program["id"]

# Cached name→ID lookup (queries VTN on first call)
pid = ven.resolve_program_id("residential-pricing")
```

### 4. Choose Notification Strategy

Check what the VTN supports:

```python
notifiers = ven.discover_notifiers()

if ven.vtn_supports_mqtt():
    # Use MQTT notifications (real-time)
    ...
else:
    # Fall back to polling
    ...
```

### 5a. MQTT Notifications

```python
# Create channel (not connected yet)
mqtt = ven.add_mqtt("mqtts://broker.example.com:8883")

# Connect
mqtt.start()

# Subscribe to program events
ven.subscribe(
    program_names=["residential-pricing"],
    objects=["EVENT"],
    operations=["CREATE", "UPDATE"],
    channel=mqtt,
)

# Wait for messages
msgs = mqtt.await_messages(1, timeout=30.0)
for m in msgs:
    print(m.topic, m.payload)

# Clean up
mqtt.stop()
```

### 5b. Webhook Notifications

```python
# Create channel
webhook = ven.add_webhook(port=9000, bearer_token="my-secret")

# Start HTTP server
webhook.start()
print(webhook.callback_url)  # "http://127.0.0.1:9000/notifications"

# Subscribe (creates VTN subscription with callback URL)
ven.subscribe(
    program_names=["residential-pricing"],
    objects=["EVENT"],
    operations=["CREATE", "UPDATE"],
    channel=webhook,
)

# Wait for notifications
msgs = webhook.await_messages(1, timeout=30.0)

webhook.stop()
```

### 5c. Polling

```python
events = ven.poll_events(program_name="residential-pricing")
for event in events:
    print(event.event_name, event.intervals)
```

### 6. Direct API Access

All `OpenADRClient` methods are available directly via `__getattr__` delegation:

```python
# Raw HTTP responses
resp = ven.get_subscriptions()
resp = ven.get_events(programID="prog-001")

# Coerced entity models
reports = ven.reports()
subs = ven.subscriptions()

# Introspection (requires spec_path)
routes = ven.all_routes()
```

## Channel Lifecycle

Channels are created separately from VenClient, giving you control:

```python
mqtt = ven.add_mqtt("mqtt://broker:1883")  # Created, not connected
mqtt.start()                                # Now connected
mqtt.subscribe_topics(["openadr3/#"])       # Manual topic subscription
# ... use ...
mqtt.stop()                                 # Disconnected
```

When VenClient stops (via `stop()` or context manager exit), all channels are stopped automatically.

## BL Client

For business logic (creating programs, events):

```python
from openadr3_client import BlClient

with BlClient(url=VTN_URL, token=BL_TOKEN) as bl:
    bl.create_program({
        "programName": "my-dr-program",
        "programType": "PRICING_TARIFF",
    })
    bl.create_event({
        "programID": program_id,
        "eventName": "peak-event",
    })
```

BlClient has no VEN registration or notification concepts. All `OpenADRClient` methods are available via `__getattr__`.

## Class Hierarchy

```
BaseClient          — auth, lifecycle, __getattr__ delegation
├── VenClient       — registration, program lookup, notifications
└── BlClient        — thin wrapper, client_type="bl"
```

## Installation

```bash
# Core only
pip install python-oa3-client

# With MQTT support
pip install python-oa3-client[mqtt]

# With webhook support
pip install python-oa3-client[webhooks]

# Everything
pip install python-oa3-client[all]
```
