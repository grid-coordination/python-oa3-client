#!/usr/bin/env python3
"""VEN client that discovers its VTN via mDNS.

Demonstrates the zero-configuration VEN workflow: no URL needed.
The VEN browses for ``_openadr3._tcp.local.`` on the local network,
connects to the first VTN it finds, registers, and polls for events.

Requires:
  - A VTN advertising itself on mDNS (see advertise_vtn or a
    spec-compliant VTN with built-in mDNS support)
  - pip install 'python-oa3-client[mdns]'

Usage:
  VEN_TOKEN=... python examples/ven_mdns.py
  VEN_TOKEN=... python examples/ven_mdns.py --name my-thermostat
  VEN_TOKEN=... python examples/ven_mdns.py --discovery prefer_local --url http://fallback:8080/openadr3/3.1.0
"""

import argparse
import os
import time

from openadr3_client import VenClient, discover_vtns


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="VEN client with mDNS discovery")
    parser.add_argument("--name", default="mdns-ven", help="VEN name for registration")
    parser.add_argument(
        "--discovery", default="require_local",
        choices=["require_local", "prefer_local", "local_with_fallback"],
        help="Discovery mode (default: require_local)",
    )
    parser.add_argument("--url", default=None, help="Fallback VTN URL (for prefer_local / local_with_fallback)")
    parser.add_argument("--timeout", type=float, default=5.0, help="mDNS discovery timeout in seconds")
    parser.add_argument("--poll-interval", type=float, default=10.0, help="Event poll interval in seconds")
    args = parser.parse_args()

    token = os.environ.get("VEN_TOKEN")
    if not token:
        print("Set VEN_TOKEN environment variable")
        return

    # -- 1. Show what's on the network --
    section("1. Scanning for VTNs on the local network")
    vtns = discover_vtns(timeout=args.timeout)
    if vtns:
        print(f"  Found {len(vtns)} VTN(s):")
        for v in vtns:
            print(f"    - {v.name}")
            print(f"      url={v.url}  version={v.version}")
            if v.program_names:
                print(f"      programs={v.program_names}")
            if v.requires_auth:
                print(f"      requires_auth={v.requires_auth}")
    else:
        print("  No VTNs found on the local network")
        if args.discovery == "require_local":
            print("  Exiting (discovery=require_local)")
            return

    # -- 2. Connect via discovery --
    section("2. Connecting to VTN")
    with VenClient(
        url=args.url,
        token=token,
        discovery=args.discovery,
        discovery_timeout=args.timeout,
    ) as ven:
        print(f"  Connected to: {ven._resolved_url}")

        # -- 3. Register --
        section("3. Register VEN")
        ven.register(args.name)
        print(f"  Registered: id={ven.ven_id} name={ven.ven_name}")

        # -- 4. Discover programs --
        section("4. Programs")
        progs = ven.programs()
        print(f"  Available programs: {len(progs)}")
        for p in progs:
            print(f"    - {p.program_name} (id={p.id})")

        # -- 5. Poll events --
        section("5. Polling events (Ctrl-C to stop)")
        try:
            while True:
                events = ven.events()
                if events:
                    print(f"  [{time.strftime('%H:%M:%S')}] {len(events)} event(s):")
                    for e in events[:5]:
                        print(f"    - {e.event_name} (id={e.id})")
                else:
                    print(f"  [{time.strftime('%H:%M:%S')}] No events")
                time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            print("\n  Stopped polling")

    print("\nDone.")


if __name__ == "__main__":
    main()
