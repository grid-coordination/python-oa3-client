#!/usr/bin/env python3
"""Smoke test: mDNS discovery of a VTN-RI.

Advertises the already-running VTN-RI on mDNS, then uses VenClient
with discovery="require_local" to find and connect to it — no hardcoded
URL needed on the client side.

Requires:
  - VTN-RI running at http://localhost:8080/openadr3/3.1.0
  - pip install 'python-oa3-client[mdns]'

Auth:
  Same auto-detection as smoke_test.py. Override with VEN_TOKEN / BL_TOKEN.

Usage:
  python examples/smoke_test_mdns.py
"""

import base64
import os

from openadr3_client import (
    BlClient,
    VenClient,
    advertise_vtn,
    discover_vtns,
)
from openadr3.api import success, body

# VTN-RI location (used only for advertise_vtn, NOT by the VEN client)
VTN_HOST = os.environ.get("VTN_HOST", "127.0.0.1")
VTN_PORT = int(os.environ.get("VTN_PORT", "8080"))
VTN_BASE_PATH = os.environ.get("VTN_BASE_PATH", "/openadr3/3.1.0")
VTN_LOCAL_URL = f"http://{VTN_HOST}:{VTN_PORT}{VTN_BASE_PATH}"

# Credentials
_BL_CLIENT_ID = "bl_client"
_BL_SECRET = "1001"
_VEN_CLIENT_ID = "ven_client"
_VEN_SECRET = "999"


def _basic_token(client_id: str, secret: str) -> str:
    return base64.b64encode(f"{client_id}:{secret}".encode()).decode()


def _detect_auth_mode(vtn_url: str) -> tuple[str, str]:
    import httpx

    basic_bl = _basic_token(_BL_CLIENT_ID, _BL_SECRET)
    resp = httpx.get(
        f"{vtn_url}/programs",
        headers={"Authorization": f"Bearer {basic_bl}"},
    )
    if resp.status_code == 200:
        print("  Auth mode: basic")
        return basic_bl, _basic_token(_VEN_CLIENT_ID, _VEN_SECRET)

    resp = httpx.get(
        f"{vtn_url}/programs",
        headers={"Authorization": "Bearer bl_token"},
    )
    if resp.status_code == 200:
        print("  Auth mode: mock")
        return "bl_token", "ven_token"

    raise RuntimeError(f"Cannot authenticate with VTN at {vtn_url}")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    BL_TOKEN = os.environ.get("BL_TOKEN")
    VEN_TOKEN = os.environ.get("VEN_TOKEN")

    section("0. Auth detection")
    if BL_TOKEN and VEN_TOKEN:
        print("  Using tokens from environment")
    else:
        BL_TOKEN, VEN_TOKEN = _detect_auth_mode(VTN_LOCAL_URL)

    # -- 1. Advertise the VTN-RI on mDNS --
    section("1. Advertise VTN-RI on mDNS")
    with advertise_vtn(
        host=VTN_HOST,
        port=VTN_PORT,
        base_path=VTN_BASE_PATH,
        local_url=VTN_LOCAL_URL,
        version="3.1.0",
        program_names="",
        requires_auth="true",
        name="VTN-RI Smoke Test",
    ) as adv:
        print(f"  Registered: {adv._info.name}")

        # -- 2. Discover VTNs via mDNS --
        section("2. Discover VTNs via mDNS")
        vtns = discover_vtns(timeout=2.0)
        print(f"  Found {len(vtns)} VTN(s):")
        for v in vtns:
            print(f"    - {v.name}")
            print(f"      host={v.host} port={v.port}")
            print(f"      url={v.url}")
            print(f"      version={v.version} requires_auth={v.requires_auth}")

        assert len(vtns) >= 1, "Expected at least 1 VTN via mDNS"

        # -- 3. VenClient with discovery="require_local" --
        section("3. VenClient via mDNS discovery")
        with VenClient(
            token=VEN_TOKEN,
            discovery="require_local",
            discovery_timeout=2.0,
        ) as ven:
            print(f"  Connected to: {ven._resolved_url}")

            # Register VEN
            ven.register("mdns-smoke-ven")
            print(f"  VEN registered: id={ven.ven_id} name={ven.ven_name}")

            # List programs
            progs = ven.programs()
            print(f"  Programs: {len(progs)}")
            for p in progs:
                print(f"    - {p.program_name} (id={p.id})")

            # List events
            evts = ven.events()
            print(f"  Events: {len(evts)}")

        # -- 4. BlClient with discovery="prefer_local" --
        section("4. BlClient via mDNS discovery (prefer_local)")
        with BlClient(
            token=BL_TOKEN,
            discovery="prefer_local",
            discovery_timeout=2.0,
        ) as bl:
            print(f"  Connected to: {bl._resolved_url}")

            resp = bl.create_program({
                "programName": "mdns-smoke-program",
                "programLongName": "mDNS Smoke Test Program",
                "programType": "PRICING_TARIFF",
                "country": "US",
                "principalSubdivision": "CA",
                "intervalPeriod": {
                    "start": "2024-01-01T00:00:00Z",
                    "duration": "P1Y",
                },
            })
            assert success(resp), f"Create program failed: {resp.status_code}"
            program_id = body(resp)["id"]
            print(f"  Created program: {program_id}")

            # Clean up
            resp = bl.delete_program(program_id)
            print(f"  Deleted program: {resp.status_code}")

        # -- 5. Cleanup VEN --
        section("5. Cleanup")
        with VenClient(
            token=VEN_TOKEN,
            discovery="require_local",
            discovery_timeout=2.0,
        ) as ven:
            v = ven.find_ven_by_name("mdns-smoke-ven")
            if v:
                resp = ven.delete_ven(v["id"])
                print(f"  Deleted VEN: {resp.status_code}")

    # advertise_vtn context exited — service unregistered
    section("mDNS SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
