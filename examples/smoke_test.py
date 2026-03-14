#!/usr/bin/env python3
"""Smoke test: run VenClient/BlClient against a live VTN-RI + Mosquitto.

Requires:
  - VTN-RI running at http://localhost:8080/openadr3/3.1.0
  - Mosquitto running at localhost:1883

Auth modes:
  The VTN-RI supports multiple auth providers. This script auto-detects
  which one is active:

  - Basic auth (default on main): tokens are base64(client_id:secret)
  - Mock auth (older branches): tokens are plain strings like "bl_token"

  Override with environment variables:
    BL_TOKEN=... VEN_TOKEN=... python examples/smoke_test.py
"""

import base64
import os
import time

from openadr3_client import VenClient, BlClient, extract_topics
from openadr3.api import success, body

VTN_URL = os.environ.get("VTN_URL", "http://localhost:8080/openadr3/3.1.0")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "mqtt://127.0.0.1:1883")

# VTN-RI default credentials (from config.py)
_BL_CLIENT_ID = "bl_client"
_BL_SECRET = "1001"
_VEN_CLIENT_ID = "ven_client"
_VEN_SECRET = "999"


def _basic_token(client_id: str, secret: str) -> str:
    """Encode credentials as a basic auth token (base64 client_id:secret)."""
    return base64.b64encode(f"{client_id}:{secret}".encode()).decode()


def _detect_auth_mode(vtn_url: str) -> tuple[str, str]:
    """Auto-detect VTN auth mode and return (bl_token, ven_token)."""
    import httpx

    # Try basic auth first (VTN-RI main default)
    basic_bl = _basic_token(_BL_CLIENT_ID, _BL_SECRET)
    resp = httpx.get(
        f"{vtn_url}/programs",
        headers={"Authorization": f"Bearer {basic_bl}"},
    )
    if resp.status_code == 200:
        basic_ven = _basic_token(_VEN_CLIENT_ID, _VEN_SECRET)
        print("  Auth mode: basic (base64 client_id:secret)")
        return basic_bl, basic_ven

    # Fall back to mock auth
    resp = httpx.get(
        f"{vtn_url}/programs",
        headers={"Authorization": "Bearer bl_token"},
    )
    if resp.status_code == 200:
        print("  Auth mode: mock (plain string tokens)")
        return "bl_token", "ven_token"

    raise RuntimeError(f"Cannot authenticate with VTN at {vtn_url}")


# Allow env var override, otherwise auto-detect
BL_TOKEN = os.environ.get("BL_TOKEN")
VEN_TOKEN = os.environ.get("VEN_TOKEN")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    global BL_TOKEN, VEN_TOKEN

    section("0. Auth detection")
    if BL_TOKEN and VEN_TOKEN:
        print(f"  Using tokens from environment")
    else:
        BL_TOKEN, VEN_TOKEN = _detect_auth_mode(VTN_URL)

    # -- BL client: create a program --
    section("1. BL Client — create a program")
    with BlClient(url=VTN_URL, token=BL_TOKEN) as bl:
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

    # -- VEN client: register, list programs, MQTT --
    section("2. VEN Client — register and list programs")
    with VenClient(url=VTN_URL, token=VEN_TOKEN) as ven:
        # Register VEN
        ven.register("smoke-test-ven")
        print(f"  VEN registered: id={ven.ven_id} name={ven.ven_name}")

        # List programs (coerced entities via __getattr__)
        progs = ven.programs()
        print(f"  Programs found: {len(progs)}")
        for p in progs:
            print(f"    - {p.program_name} (id={p.id})")

        # Find program by name
        found = ven.find_program_by_name("smoke-test-program")
        print(f"  Found by name: {found['programName'] if found else 'NOT FOUND'}")

        # List events
        evts = ven.events()
        print(f"  Events found: {len(evts)}")

        # -- MQTT topic discovery --
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

        # -- MQTT channel --
        section("4. MQTT channel — connect and collect messages")
        mqtt = ven.add_mqtt(MQTT_BROKER, client_id="smoke-test-ven")
        mqtt.start()
        print(f"  Connected to MQTT broker")

        mqtt.subscribe_topics(["openadr3/#"])
        print(f"  Subscribed to openadr3/#")

        time.sleep(1)
        msgs = mqtt.messages
        print(f"  Messages received: {len(msgs)}")
        for m in msgs[:5]:
            print(f"    topic={m.topic} payload={m.payload}")

        mqtt.stop()
        print(f"  MQTT disconnected")

        # -- Webhook channel --
        section("5. Webhook channel")
        WEBHOOK_TOKEN = "smoke-test-webhook-token"
        webhook = ven.add_webhook(port=9876, bearer_token=WEBHOOK_TOKEN)
        webhook.start()
        print(f"  Webhook server started at {webhook.callback_url}")

        # Create a subscription pointing to our webhook
        sub_resp = ven.create_subscription({
            "clientName": "smoke-test-ven",
            "programID": program_id,
            "objectOperations": [{
                "objects": ["PROGRAM"],
                "operations": ["CREATE", "UPDATE", "DELETE"],
                "callbackUrl": f"http://127.0.0.1:9876/notifications",
                "bearerToken": WEBHOOK_TOKEN,
            }],
        })
        if success(sub_resp):
            sub = body(sub_resp)
            sub_id = sub.get("id")
            print(f"  Subscription created: {sub_id}")
        else:
            sub_id = None
            print(f"  Subscription creation: {sub_resp.status_code} (VTN-RI may not callback)")

        # Trigger a notification by updating the program
        with BlClient(url=VTN_URL, token=BL_TOKEN) as bl2:
            bl2.update_program(program_id, {
                "programName": "smoke-test-program-updated",
                "programLongName": "Smoke Test Program Updated",
                "programType": "PRICING_TARIFF",
                "country": "US",
                "principalSubdivision": "CA",
                "intervalPeriod": {
                    "start": "2024-01-01T00:00:00Z",
                    "duration": "P1Y",
                },
            })
            print(f"  Program updated to trigger webhook")

        webhook_msgs = webhook.await_messages(1, timeout=3.0)
        print(f"  Webhook messages received: {len(webhook_msgs)}")
        for m in webhook_msgs[:5]:
            print(f"    path={m.path} payload_type={type(m.payload).__name__}")

        webhook.stop()
        print(f"  Webhook server stopped")

        # Clean up subscription
        if sub_id:
            del_resp = ven.delete_subscription(sub_id)
            print(f"  Delete subscription {sub_id}: {del_resp.status_code}")

        # -- VEN-scoped topic methods --
        section("6. VEN-scoped endpoints (default to registered ven_id)")
        for method_name in [
            "get_mqtt_topics_ven",
            "get_mqtt_topics_ven_events",
            "get_mqtt_topics_ven_programs",
            "get_mqtt_topics_ven_resources",
        ]:
            method = getattr(ven, method_name)
            resp = method()
            print(f"  {method_name}(): {resp.status_code}")

        # -- Introspection (via __getattr__) --
        section("7. Introspection")
        routes = ven.all_routes()
        print(f"  Routes in spec: {len(routes)}")

    # -- BL cleanup --
    section("8. Cleanup")
    with BlClient(url=VTN_URL, token=BL_TOKEN) as bl:
        resp = bl.delete_program(program_id)
        print(f"  Delete program {program_id}: {resp.status_code}")

    # Delete the VEN
    with VenClient(url=VTN_URL, token=VEN_TOKEN) as ven:
        v = ven.find_ven_by_name("smoke-test-ven")
        if v:
            resp = ven.delete_ven(v["id"])
            print(f"  Delete VEN {v['id']}: {resp.status_code}")

    section("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
