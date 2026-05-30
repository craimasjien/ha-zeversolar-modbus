#!/usr/bin/env python3
"""Standalone probe for the Zeversolar 2000s — talk to it WITHOUT Home Assistant.

Connects to the Waveshare RS485->Ethernet bridge (raw TCP server), runs the
Eversolar handshake, polls runtime data, and prints:

  * every TX/TX frame as hex (the actual bytes on the wire),
  * the decoded values using the current FIELD_MAP,
  * a labelled offset table of the raw data payload to help you calibrate
    FIELD_MAP in custom_components/zeversolar/protocol.py.

This imports and exercises the SAME client code Home Assistant runs.

Examples
--------
    python3 tools/probe.py 192.168.2.200
    python3 tools/probe.py 192.168.2.200 --port 4196 --address 10
    python3 tools/probe.py 192.168.2.200 --interval 10      # poll forever

Run it during DAYLIGHT — the inverter is offline/dark at night and will not
answer (you will see a connect, then a timeout waiting for the serial-number
frame).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Import the real package without needing Home Assistant installed.
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components")
)
from zeversolar import protocol  # noqa: E402
from zeversolar.client import ZeversolarClient  # noqa: E402


def print_offset_table(payload: bytes) -> None:
    """Dump the payload as offset / hex-pair / candidate-scalings for calibration."""
    print("\n  raw payload (look for power in W, today & total in kWh):")
    print(f"  {'off':>3}  {'hex':<5}  {'uint16':>6}  {'/10':>9}  {'/100':>9}")
    print(f"  {'-'*3}  {'-'*5}  {'-'*6}  {'-'*9}  {'-'*9}")
    for off in range(0, len(payload) - 1, 2):
        pair = payload[off : off + 2]
        val = int.from_bytes(pair, "big")
        print(
            f"  {off:>3}  {pair.hex(' '):<5}  {val:>6}  {val / 10:>9.2f}  {val / 100:>9.2f}"
        )
    if len(payload) >= 4:
        last4 = int.from_bytes(payload[-4:], "big")
        print(
            f"\n  last 4 bytes as uint32 (often E-Total): {last4}  "
            f"(/10 = {last4 / 10:.1f} kWh, /100 = {last4 / 100:.2f} kWh)"
        )


async def sniff(args: argparse.Namespace) -> int:
    """Low-level diagnostic: send the offline query and dump ALL raw bytes.

    Bypasses frame validation so we can tell apart:
      * nothing back        -> wiring (A/B swap), bus owned by another master,
                               wrong baud such that the inverter hears garbage,
                               or the bridge isn't forwarding;
      * garbage bytes back  -> baud/parity mismatch or swapped A/B lines;
      * a valid frame       -> parser/offset issue, not the link.
    """
    print(f"[sniff] connecting to {args.host}:{args.port} ...")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(args.host, args.port), 10
        )
    except (OSError, asyncio.TimeoutError, TimeoutError) as err:
        print(f"[sniff] connect failed: {type(err).__name__}: {err}")
        return 1
    print("[sniff] connected")

    query = protocol.build_frame(
        protocol.ADDR_HOST,
        protocol.ADDR_BROADCAST,
        protocol.CC_REGISTER,
        protocol.FC_OFFLINE_QUERY,
    )
    buffer = b""
    total = 0
    all_raw = bytearray()
    valid_frames = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + args.sniff
    next_send = 0.0
    try:
        while True:
            now = loop.time()
            remaining = deadline - now
            if remaining <= 0:
                break
            if now >= next_send:
                print(f"[sniff] TX offline query: {query.hex(' ')}")
                writer.write(query)
                await writer.drain()
                next_send = now + 2.0
            try:
                chunk = await asyncio.wait_for(
                    reader.read(256), timeout=min(2.0, remaining)
                )
            except (asyncio.TimeoutError, TimeoutError):
                continue
            if not chunk:
                print("[sniff] peer closed the connection")
                break
            total += len(chunk)
            all_raw += chunk
            buffer += chunk
            print(f"[sniff] RX {len(chunk)} bytes: {chunk.hex(' ')}")
            frames, buffer = protocol.parse_frames(buffer)
            for f in frames:
                valid_frames += 1
                print(
                    f"[sniff]   -> VALID FRAME cc=0x{f.cc:02x} fc=0x{f.fc:02x} "
                    f"data={f.data.hex(' ')}"
                )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    header_at = all_raw.find(protocol.HEADER)
    print(f"\n[sniff] done — {total} bytes received total.")
    print(
        f"[sniff] VERDICT: {valid_frames} valid frame(s); "
        f"'aa 55' header {'SEEN' if header_at != -1 else 'NOT seen'} in raw stream."
    )
    if total and header_at == -1:
        print(
            "[sniff] No 'aa 55' anywhere => serial settings still wrong. Keep\n"
            "        sweeping baud (target is the run where 'aa 55' appears):\n"
            "          9600  -> 19200 -> 38400 -> 4800 -> 2400 -> 57600 -> 115200\n"
            "        Keep parity=None, data=8, stop=1. 9600 8N1 is the usual answer."
        )
    elif header_at != -1 and valid_frames == 0:
        print(
            "[sniff] 'aa 55' appears but no frame passed the checksum => baud is\n"
            "        close/right but parity or stop bits are off (set 8/None/1),\n"
            "        or there is light corruption. Very near now."
        )
    if total == 0:
        print(
            "[sniff] Nothing came back. The TCP link to the Waveshare is fine, so\n"
            "        suspect the RS485 side:\n"
            "          * A/B (D+/D-) lines swapped — the single most common cause;\n"
            "          * wrong baud rate on the bridge (Zeversolar is usually 9600 8N1);\n"
            "          * the RS485 bus is already owned by the Zeversolar Wi-Fi/monitor\n"
            "            dongle — unplug it and retry;\n"
            "          * the bridge isn't in transparent/raw mode."
        )
    else:
        print(
            "[sniff] Bytes came back. If no VALID FRAME was found above, the link is\n"
            "        live but the serial settings are off (baud/parity) or A/B are\n"
            "        swapped, corrupting the framing. If a VALID FRAME WAS found, the\n"
            "        link is good and this is a parsing/offset matter."
        )
    return 0


async def run(args: argparse.Namespace) -> int:
    client = ZeversolarClient(
        host=args.host,
        port=args.port,
        inverter_address=args.address,
        log_raw_frames=True,  # always show the wire bytes in the probe
    )
    try:
        while True:
            try:
                data = await client.async_update()
            except (
                OSError,
                asyncio.TimeoutError,
                TimeoutError,
                ConnectionError,
            ) as err:
                print(f"\n[poll failed] {type(err).__name__}: {err}")
                if not args.interval:
                    return 1
            else:
                print(f"\n[serial] {data.get('serial')}")
                print("[decoded via current FIELD_MAP]")
                for key, value in data.items():
                    if key != "serial":
                        print(f"    {key:<14} = {value}")
                if client.last_runtime_raw is not None:
                    print_offset_table(client.last_runtime_raw)
            if not args.interval:
                return 0
            await asyncio.sleep(args.interval)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", help="Waveshare bridge IP, e.g. 192.168.2.200")
    parser.add_argument(
        "--port", type=int, default=502, help="raw TCP port (default 502; also 4196)"
    )
    parser.add_argument(
        "--address",
        type=int,
        default=10,
        help="address to assign the inverter (1..254, default 10)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0,
        help="seconds between polls; 0 = poll once and exit (default)",
    )
    parser.add_argument(
        "--sniff",
        type=float,
        default=0,
        metavar="SECONDS",
        help="diagnostic mode: send the offline query and hex-dump ALL raw bytes "
        "for this many seconds (e.g. --sniff 15). Use this when polls time out.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG, format="%(levelname)-7s %(message)s", stream=sys.stdout
    )

    try:
        return asyncio.run(sniff(args) if args.sniff > 0 else run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
