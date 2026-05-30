#!/usr/bin/env python3
"""A fake Zeversolar inverter for offline testing — no hardware required.

Listens on a TCP port and answers the Eversolar handshake exactly like the real
inverter (offline query -> serial, assign address -> ACK, poll -> runtime data),
so you can exercise tools/probe.py and the client end-to-end on localhost.

    python3 tools/mock_inverter.py --port 5020 &
    python3 tools/probe.py 127.0.0.1 --port 5020

The runtime payload below is laid out to match the DEFAULT FIELD_MAP in
protocol.py (temperature 25.0 C, today 12.34 kWh, power 1500 W,
total 12345.6 kWh), so a correct decode is easy to recognise.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components")
)
from zeversolar import protocol  # noqa: E402

SERIAL = b"AB1234567890XYZ"
MOCK_ADDR = 0x000A  # src we report once "registered"


def _runtime_payload() -> bytes:
    """A 20-byte payload matching the default FIELD_MAP offsets/scales."""
    p = bytearray(20)
    p[0:2] = (250).to_bytes(2, "big")  # temperature 25.0 C
    p[2:4] = (1234).to_bytes(2, "big")  # energy_today 12.34 kWh
    p[4:6] = (3200).to_bytes(2, "big")  # pv_voltage 320.0 V
    p[6:8] = (65).to_bytes(2, "big")  # ac_current 6.5 A
    p[8:10] = (2300).to_bytes(2, "big")  # ac_voltage 230.0 V
    p[10:12] = (5000).to_bytes(2, "big")  # ac_frequency 50.00 Hz
    p[12:14] = (1500).to_bytes(2, "big")  # power 1500 W
    p[16:20] = (123456).to_bytes(4, "big")  # energy_total 12345.6 kWh
    return bytes(p)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    print(f"[mock] client connected: {peer}")
    buffer = b""
    try:
        while True:
            chunk = await reader.read(256)
            if not chunk:
                break
            buffer += chunk
            frames, buffer = protocol.parse_frames(buffer)
            for f in frames:
                resp = _respond(f)
                if resp is not None:
                    print(f"[mock] RX cc=0x{f.cc:02x} fc=0x{f.fc:02x} -> reply")
                    writer.write(resp)
                    await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        print(f"[mock] client disconnected: {peer}")
        writer.close()


def _respond(f: protocol.Frame) -> bytes | None:
    rb = protocol.RESPONSE_BIT
    if f.cc == protocol.CC_REGISTER and f.fc == protocol.FC_OFFLINE_QUERY:
        return protocol.build_frame(
            MOCK_ADDR, protocol.ADDR_HOST, f.cc, f.fc | rb, SERIAL
        )
    if f.cc == protocol.CC_REGISTER and f.fc == protocol.FC_SEND_ADDRESS:
        return protocol.build_frame(
            MOCK_ADDR, protocol.ADDR_HOST, f.cc, f.fc | rb, b"\x06"
        )
    if f.cc == protocol.CC_READ and f.fc == protocol.FC_QUERY_NORMAL_INFO:
        return protocol.build_frame(
            MOCK_ADDR, protocol.ADDR_HOST, f.cc, f.fc | rb, _runtime_payload()
        )
    return None


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5020)
    args = parser.parse_args()

    server = await asyncio.start_server(handle, args.host, args.port)
    addr = server.sockets[0].getsockname()
    print(f"[mock] Zeversolar mock inverter listening on {addr[0]}:{addr[1]}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
