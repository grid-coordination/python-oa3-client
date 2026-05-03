"""Regression tests for pendulum.DateTime propagation through notification channels.

The client itself does no datetime parsing — it forwards payloads to
``openadr3.entities.coerce_notification`` (from python-oa3). These tests
lock in that behavior so a regression upstream or in our parse glue would
be caught here.

The OpenADR 3 wire-offset rule: the wire string's offset is preserved
end-to-end and is NOT normalized. ``Z``, ``+00:00``, ``-07:00``, ``+05:30``
all round-trip exactly.
"""

import json

import pendulum

from openadr3_client.mqtt import _parse_payload
from openadr3_client.webhook import _parse_webhook_payload


def _notification_with_offset(offset: str) -> bytes:
    return json.dumps(
        {
            "objectType": "PROGRAM",
            "operation": "POST",
            "object": {
                "objectType": "PROGRAM",
                "id": "p1",
                "programName": "test",
                "createdDateTime": f"2024-06-15T10:30:00{offset}",
                "modificationDateTime": f"2024-06-15T10:30:00{offset}",
            },
        }
    ).encode()


class TestPendulumDateTimePropagation:
    """Wire-offset preservation across MQTT and webhook coercion paths."""

    def test_mqtt_payload_yields_pendulum_datetime(self):
        msg = _parse_payload(_notification_with_offset("Z"), "programs/create")
        assert isinstance(msg.object.created, pendulum.DateTime)
        assert isinstance(msg.object.modified, pendulum.DateTime)

    def test_webhook_payload_yields_pendulum_datetime(self):
        msg = _parse_webhook_payload(_notification_with_offset("Z"), "/notifications")
        assert isinstance(msg.object.created, pendulum.DateTime)

    def test_mqtt_negative_offset_preserved(self):
        msg = _parse_payload(_notification_with_offset("-07:00"), "programs/create")
        assert msg.object.created.utcoffset().total_seconds() == -7 * 3600

    def test_webhook_half_hour_offset_preserved(self):
        msg = _parse_webhook_payload(_notification_with_offset("+05:30"), "/notifications")
        assert msg.object.created.utcoffset().total_seconds() == 5.5 * 3600

    def test_mqtt_z_not_normalized_to_plus_zero(self):
        # Z and +00:00 are distinct wire forms; the parser must preserve which
        # one came in. Round-trip the parsed DateTime back to ISO 8601 and
        # confirm it ends with "Z".
        msg = _parse_payload(_notification_with_offset("Z"), "programs/create")
        assert msg.object.created.to_iso8601_string().endswith("Z")

    def test_webhook_plus_zero_not_normalized_to_z(self):
        msg = _parse_webhook_payload(_notification_with_offset("+00:00"), "/notifications")
        assert msg.object.created.to_iso8601_string().endswith("+00:00")
