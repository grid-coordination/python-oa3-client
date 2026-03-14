#!/usr/bin/env python3
"""Smoke test: run OA3Client against a live VTN-RI + Mosquitto.

Requires:
  - VTN-RI running at http://localhost:8080/openadr3/3.1.0
  - Mosquitto running at localhost:1883
"""

import time

from openadr3_client import OA3Client, extract_topics
from openadr3.api import success, body

VTN_URL = "http://localhost:8080/openadr3/3.1.0"
BL_TOKEN = "bl_token"
VEN_TOKEN = "ven_token"
MQTT_BROKER = "mqtt://127.0.0.1:1883"


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    # ── BL client: create a program ──────────────────────────────
    section("1. BL Client — create a program")
    with OA3Client(client_type="bl", url=VTN_URL, token=BL_TOKEN) as bl:
        resp = bl.create_program({
            "programName": "smoke-test-program",
            "programLongName": "Smoke Test Program",
            "programType": "PRICING_TARIFF",
            "country": "US",
            "principalSubdivision": "CA",
            "intervalPeriod": {
                "start": "2024-01-01T00:00:00Z",
                "duration": "P1Y",
            },
        })
        assert success(resp), f"Create program failed: {resp.status_code} {resp.text}"
        program = body(resp)
        program_id = program["id"]
        print(f"  Created program: {program_id}")
        print(f"  Name: {program['programName']}")

    # ── VEN client: register, list programs, MQTT ────────────────
    section("2. VEN Client — register and list programs")
    with OA3Client(client_type="ven", url=VTN_URL, token=VEN_TOKEN) as ven:
        # Register VEN
        ven.register("smoke-test-ven")
        print(f"  VEN registered: id={ven.ven_id} name={ven.ven_name}")

        # List programs (coerced entities)
        progs = ven.programs()
        print(f"  Programs found: {len(progs)}")
        for p in progs:
            print(f"    - {p.program_name} (id={p.id})")

        # List events
        evts = ven.events()
        print(f"  Events found: {len(evts)}")

        # ── MQTT topic discovery ─────────────────────────────────
        section("3. MQTT topic discovery")
        resp = ven.get_mqtt_topics_ven()
        print(f"  VEN topics response: {resp.status_code}")
        if success(resp):
            topics = extract_topics(resp)
            print(f"  Topics: {topics}")
        else:
            print(f"  (VTN-RI may not support MQTT topics endpoint)")

        resp2 = ven.get_mqtt_topics_programs()
        print(f"  Program topics response: {resp2.status_code}")
        if success(resp2):
            topics2 = extract_topics(resp2)
            print(f"  Topics: {topics2}")

        # ── MQTT connection ──────────────────────────────────────
        section("4. MQTT connection and message collection")
        ven.connect_mqtt(MQTT_BROKER, client_id="smoke-test-ven")
        print(f"  Connected to MQTT broker")

        # Subscribe to a topic
        ven.subscribe_mqtt("openadr3/#")
        print(f"  Subscribed to openadr3/#")

        # Wait briefly for any messages
        time.sleep(1)
        msgs = ven.mqtt_messages
        print(f"  Messages received: {len(msgs)}")
        for m in msgs[:5]:
            print(f"    topic={m.topic} payload={m.payload}")

        ven.disconnect_mqtt()
        print(f"  MQTT disconnected")

        # ── VEN-scoped topic methods ─────────────────────────────
        section("5. VEN-scoped endpoints (default to registered ven_id)")
        for method_name in [
            "get_mqtt_topics_ven",
            "get_mqtt_topics_ven_events",
            "get_mqtt_topics_ven_programs",
            "get_mqtt_topics_ven_resources",
        ]:
            method = getattr(ven, method_name)
            resp = method()  # No ven_id arg — defaults to registered
            print(f"  {method_name}(): {resp.status_code}")

        # ── Introspection ────────────────────────────────────────
        section("6. Introspection")
        routes = ven.all_routes()
        print(f"  Routes in spec: {len(routes)}")

    # ── BL cleanup ───────────────────────────────────────────────
    section("7. Cleanup")
    with OA3Client(client_type="bl", url=VTN_URL, token=BL_TOKEN) as bl:
        # Delete program
        resp = bl.delete_program(program_id)
        print(f"  Delete program {program_id}: {resp.status_code}")

    # Delete the VEN (need ven token)
    with OA3Client(client_type="ven", url=VTN_URL, token=VEN_TOKEN) as ven:
        # Find the ven we created
        v = ven.find_ven_by_name("smoke-test-ven")
        if v:
            resp = ven.delete_ven(v["id"])
            print(f"  Delete VEN {v['id']}: {resp.status_code}")

    section("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
