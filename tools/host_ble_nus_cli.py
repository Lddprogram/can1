#!/usr/bin/env python3
"""
BLE NUS host tool (Route B): monitor + control in one process.

Features:
- Scan/connect by name (default: Limb_Assistant)
- Subscribe NUS TX notify and parse frames (G/M/S/A)
- Optionally send START/STOP/STATUS to NUS RX
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

from host_frame_monitor import Monitor

try:
    from bleak import BleakClient, BleakScanner
except Exception:
    BleakClient = None
    BleakScanner = None

NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # write
NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notify


async def find_device(name: str, timeout: float):
    assert BleakScanner is not None
    print(f"[scan] looking for '{name}' ({timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    for d in devices:
        if (d.name or "") == name:
            return d
    return None


async def run(args) -> int:
    if BleakClient is None or BleakScanner is None:
        print("ERROR: bleak not installed. Run: pip install bleak", file=sys.stderr)
        return 2

    mon = Monitor(quiet=args.quiet)

    dev = await find_device(args.name, args.scan_timeout)
    if dev is None:
        print(f"ERROR: device '{args.name}' not found", file=sys.stderr)
        return 3

    print(f"[connect] {dev.address} {dev.name}")

    done = asyncio.Event()

    def on_tx(_: int, data: bytearray):
        text = bytes(data).decode(errors="ignore")
        for line in text.splitlines():
            mon.feed_line(line)

    async with BleakClient(dev.address) as client:
        # Bleak compatibility:
        # - old versions: await client.get_services()
        # - newer versions: services available via client.services after connect
        if hasattr(client, "get_services"):
            svcs = await client.get_services()
            svc_uuids = {s.uuid.lower() for s in svcs}
        else:
            svc_uuids = {s.uuid.lower() for s in client.services}

        if NUS_SERVICE_UUID.lower() not in svc_uuids:
            print("ERROR: NUS service not found", file=sys.stderr)
            return 4

        await client.start_notify(NUS_TX_UUID, on_tx)
        print("[notify] subscribed NUS TX")

        if args.cmd:
            payload = (args.cmd.strip().upper() + "\n").encode("ascii", errors="ignore")
            print(f"[write] {payload!r}")
            await client.write_gatt_char(NUS_RX_UUID, payload, response=True)
            # Give firmware a brief window to enqueue ACK/STATUS before heavy stream dominates output.
            await asyncio.sleep(0.2)

        if args.duration > 0:
            await asyncio.sleep(args.duration)
            done.set()
        else:
            print("[run] press Ctrl+C to stop")
            try:
                while not done.is_set():
                    await asyncio.sleep(0.2)
            except KeyboardInterrupt:
                done.set()

        await client.stop_notify(NUS_TX_UUID)

    print(mon.summary())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BLE NUS monitor/control for Progress A/B")
    ap.add_argument("--name", default="Limb_Assistant", help="BLE device name")
    ap.add_argument("--scan-timeout", type=float, default=8.0)
    ap.add_argument("--duration", type=float, default=10.0, help="Monitor seconds, 0=until Ctrl+C")
    ap.add_argument("--cmd", choices=["START", "STOP", "STATUS"], help="Optional one-shot command")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
