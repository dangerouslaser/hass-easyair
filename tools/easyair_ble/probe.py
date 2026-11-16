"""Connect to a Bosch IDS outdoor unit over BLE and dump live data.

Requires: pip install bleak

  1. Open the outdoor unit's access panel, hold the gateway "Connect" button for
     4 seconds until the blue Bluetooth LED blinks.
  2. python3 -m easyair_ble.probe            (run from the tools/ directory)
  3. macOS: enter the PIN in the system prompt. Linux: pass --pin 123456.

Raw packets are written to ble_capture.jsonl so the decoding can be verified.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from bleak import BleakClient, BleakScanner

from .decoder import (
    NAME_PREFIXES,
    NOTIFY_CHAR_UUID,
    TRIGGER_CHAR_UUID,
    decode_packet,
    describe,
    guess_table,
)


async def main(args):
    print("Scanning for BOSCH_HP_* / HP_* devices...")
    devices = await BleakScanner.discover(timeout=args.scan, return_adv=True)
    found = [
        (d, adv) for d, adv in devices.values()
        if (d.name or adv.local_name or "").startswith(NAME_PREFIXES)
    ]
    if args.name:
        found = [(d, a) for d, a in found if (d.name or a.local_name) == args.name]
    if not found:
        print("No unit found. Is the blue LED blinking? Nearby named devices:")
        for d, adv in devices.values():
            if d.name or adv.local_name:
                print(f"  {d.name or adv.local_name}  rssi={adv.rssi}  {d.address}")
        return
    dev, adv = found[0]
    print(f"Found {dev.name or adv.local_name} rssi={adv.rssi} services={adv.service_uuids}")

    packets: list[bytes] = []
    log = open(args.out, "a")

    def on_notify(_sender, data: bytearray):
        data = bytes(data)
        packets.append(data)
        log.write(json.dumps({"t": time.time(), "hex": data.hex()}) + "\n")
        log.flush()
        print(f"<- {data.hex(' ')}")

    agent = None
    if args.pin and sys.platform.startswith("linux"):
        from .bluez_agent import PasskeyAgent

        agent = PasskeyAgent(args.pin, dev.address)
        await agent.__aenter__()
        print("Registered BlueZ passkey agent")

    try:
        await _session(dev, args, on_notify)
    finally:
        if agent:
            await agent.__aexit__(None, None, None)
    log.close()
    _summary(packets, args)


async def _session(dev, args, on_notify):
    async with BleakClient(dev, timeout=30) as client:
        print("Connected. Services:")
        for s in client.services:
            print(f"  {s.uuid}")
            for c in s.characteristics:
                print(f"    {c.uuid} {','.join(c.properties)}")
        if args.pin and sys.platform.startswith("linux"):
            try:
                print(f"pair(): {await client.pair()}")
            except Exception as e:  # noqa: BLE001
                print(f"pair() failed: {e!r}")
        await client.start_notify(NOTIFY_CHAR_UUID, on_notify)
        trigger = os.urandom(3)  # app writes base64-decoded 4 random chars = 3 bytes
        await client.write_gatt_char(TRIGGER_CHAR_UUID, trigger, response=True)
        print(f"-> wrote trigger {trigger.hex()}; listening {args.listen}s ...")
        await asyncio.sleep(args.listen)
        await client.stop_notify(NOTIFY_CHAR_UUID)


def _summary(packets, args):
    if not packets:
        print("No notifications received.")
        return
    table = args.table or guess_table({p[0] for p in packets})
    merged: dict[int, object] = {}
    for p in packets:
        merged.update(decode_packet(p, table))
    print(f"\nDecoded with table '{table}' from {len(packets)} packets:")
    print("\n".join(describe(merged)))
    print(f"\nRaw packets appended to {args.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="exact BLE name, e.g. BOSCH_HP_ABC123")
    ap.add_argument("--scan", type=float, default=15)
    ap.add_argument("--listen", type=float, default=30)
    ap.add_argument("--table", choices=["v22", "new"])
    ap.add_argument("--pin", help="6-digit Bluetooth PIN (Linux: answered via a BlueZ agent)")
    ap.add_argument("--out", default="ble_capture.jsonl")
    asyncio.run(main(ap.parse_args()))
