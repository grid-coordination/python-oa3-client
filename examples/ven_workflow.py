#!/usr/bin/env python3
"""VEN developer workflow example using VenClient.

Demonstrates:
  1. VEN registration
  2. Program discovery by name
  3. Notifier discovery and MQTT support check
  4. MQTT channel creation, subscription, and message collection
  5. Fallback to event polling
  6. Direct API access via __getattr__ delegation

Requires:
  - VTN-RI running at http://localhost:8080/openadr3/3.1.0
  - Mosquitto running at localhost:1883 (for MQTT path)

Usage:
  python examples/ven_workflow.py
"""

import os
import time

from openadr3_client import VenClient
from openadr3.api import success

VTN_URL = os.environ.get("VTN_URL", "http://localhost:8080/openadr3/3.1.0")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "mqtt://127.0.0.1:1883")
VEN_TOKEN = os.environ.get("VEN_TOKEN")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    if not VEN_TOKEN:
        print("Set VEN_TOKEN environment variable")
        return

    with VenClient(url=VTN_URL, token=VEN_TOKEN) as ven:

        # -- 1. Register VEN --
        section("1. Register VEN")
        ven.register("example-thermostat-ven")
        print(f"  VEN registered: id={ven.ven_id} name={ven.ven_name}")

        # -- 2. Discover programs --
        section("2. Discover programs")
        progs = ven.programs()  # __getattr__ → OpenADRClient.programs()
        print(f"  Programs available: {len(progs)}")
        for p in progs:
            print(f"    - {p.program_name} (id={p.id})")

        if not progs:
            print("  No programs found — create one with a BL client first")
            return

        # Find a specific program by name
        target_name = progs[0].program_name
        program = ven.find_program_by_name(target_name)
        if program:
            print(f"  Found program: {program.program_name} (id={program.id})")
        else:
            print(f"  Program '{target_name}' not found")
            return

        # -- 3. Check notification support --
        section("3. Notifier discovery")
        notifiers = ven.discover_notifiers()
        print(f"  Notifiers: {notifiers}")

        if ven.vtn_supports_mqtt():
            print("  VTN supports MQTT notifications")

            # -- 4a. MQTT path --
            section("4. MQTT notifications")
            mqtt = ven.add_mqtt(MQTT_BROKER, client_id="example-ven")
            mqtt.start()
            print(f"  Connected to MQTT broker")

            # Subscribe to program events
            topics = ven.subscribe(
                program_names=[target_name],
                objects=["EVENT"],
                operations=["CREATE", "UPDATE"],
                channel=mqtt,
            )
            print(f"  Subscribed to topics: {topics}")

            # Wait for messages
            msgs = mqtt.await_messages(1, timeout=5.0)
            print(f"  Messages received: {len(msgs)}")
            for m in msgs[:3]:
                print(f"    topic={m.topic} payload_type={type(m.payload).__name__}")

            mqtt.stop()
        else:
            print("  VTN does not support MQTT — falling back to polling")

            # -- 4b. Polling path --
            section("4. Poll events")
            events = ven.poll_events(program_name=target_name)
            print(f"  Events for '{target_name}': {len(events)}")
            for e in events[:5]:
                print(f"    - {e.event_name} (id={e.id})")

        # -- 5. Direct API access via __getattr__ --
        section("5. Direct API access")
        resp = ven.get_subscriptions()
        if success(resp):
            subs = resp.json()
            print(f"  Subscriptions: {len(subs)}")

        reports = ven.reports()
        print(f"  Reports: {len(reports)}")

    section("VEN WORKFLOW COMPLETE")


if __name__ == "__main__":
    main()
