# python-oa3-client

OpenADR 3 companion client with VEN registration, MQTT notifications, and lifecycle management.

Python equivalent of [clj-oa3-client](https://github.com/grid-sw/clj-oa3-client).

## Install

```bash
pip install python-oa3-client
```

## Quick start

```python
from openadr3_client import OA3Client

# Create and start
client = OA3Client(client_type="ven", url="http://localhost:8080/openadr3/3.1.0", token="my-token")
client.start()

# Register VEN (find-or-create by name)
client.register("my-ven")
print(client.ven_id)  # => "abc-123"

# Use the API
programs = client.programs()
events = client.events()

# MQTT notifications
client.connect_mqtt("mqtt://broker:1883")
client.subscribe_notifications(OA3Client.get_mqtt_topics_ven)
messages = client.await_mqtt_messages(1, timeout=10.0)

# Clean up
client.stop()
```

### Context manager

```python
with OA3Client(client_type="ven", url=url, token=token) as client:
    client.register("my-ven")
    # ... use client
# automatically stopped
```

## License

MIT
