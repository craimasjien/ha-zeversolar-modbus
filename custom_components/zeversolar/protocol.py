"""Eversolar (Zeversolar) serial protocol: framing, checksums and decoding.

The Zeversolar 2000s does NOT speak Modbus RTU. It uses the proprietary
"Eversolar" serial protocol (shared lineage with early Goodwe inverters).
The Waveshare RS485->Ethernet bridge is configured as a transparent TCP
server, so it passes these raw serial frames over the socket verbatim.

Frame format
------------
    AA 55 | SRC(2) | DST(2) | CC(1) FC(1) | LEN(1) | DATA(LEN) | CRC(2, BE)

* ``AA 55``  - fixed header.
* ``SRC``    - source address (2 bytes, big-endian).
* ``DST``    - destination address (2 bytes, big-endian).
* ``CC``,``FC`` - control code + function code.
* ``LEN``    - number of DATA bytes.
* ``DATA``   - payload (LEN bytes).
* ``CRC``    - 16-bit sum of every byte from AA through the last DATA byte,
               big-endian (high byte, low byte).

Handshake
---------
1. Offline query (CC=0x10 FC=0x00, broadcast)  -> resp FC=0x80, DATA=serial.
2. Assign address (CC=0x10 FC=0x01, DATA=serial+addr) -> resp FC=0x81, ACK.
3. Poll runtime data (CC=0x11 FC=0x02, to addr) -> resp FC=0x82, DATA=values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

HEADER = b"\xaa\x55"

# Minimum bytes before DATA: header(2)+src(2)+dst(2)+cc(1)+fc(1)+len(1).
_PREFIX_LEN = 9
_CRC_LEN = 2

# Addresses (2 bytes, big-endian on the wire).
ADDR_HOST = 0x0000  # us (the master / data logger)
ADDR_BROADCAST = 0x0000  # destination used for discovery / offline query

# Control codes.
CC_REGISTER = 0x10
CC_READ = 0x11

# Register (CC_REGISTER) function codes.
FC_OFFLINE_QUERY = 0x00
FC_SEND_ADDRESS = 0x01
FC_REMOVE_REGISTER = 0x02
FC_RECONNECT = 0x04

# Read (CC_READ) function codes.
FC_QUERY_PARAMETER = 0x00
FC_QUERY_ID = 0x01
FC_QUERY_NORMAL_INFO = 0x02

# Inverter responses set the high bit of the request function code.
RESPONSE_BIT = 0x80


def checksum(payload: bytes) -> bytes:
    """Return the 16-bit big-endian sum checksum of ``payload``."""
    total = sum(payload) & 0xFFFF
    return bytes(((total >> 8) & 0xFF, total & 0xFF))


def build_frame(src: int, dst: int, cc: int, fc: int, data: bytes = b"") -> bytes:
    """Assemble a complete, checksummed protocol frame."""
    body = bytearray(HEADER)
    body += src.to_bytes(2, "big")
    body += dst.to_bytes(2, "big")
    body.append(cc)
    body.append(fc)
    body.append(len(data))
    body += data
    return bytes(body) + checksum(bytes(body))


@dataclass(frozen=True)
class Frame:
    """A decoded, checksum-validated protocol frame."""

    src: int
    dst: int
    cc: int
    fc: int
    data: bytes
    raw: bytes


def parse_frames(buffer: bytes) -> tuple[list[Frame], bytes]:
    """Extract every complete, checksum-valid frame from ``buffer``.

    Returns ``(frames, leftover)`` where ``leftover`` is the unconsumed tail
    (a partial frame, or a single trailing byte that may begin a header).
    Re-syncs on the ``AA 55`` header so line noise or a bad checksum cannot
    wedge the stream.
    """
    frames: list[Frame] = []
    n = len(buffer)
    i = 0
    while True:
        idx = buffer.find(HEADER, i)
        if idx == -1:
            # No header found; keep a trailing byte that could start one.
            return frames, buffer[max(i, n - 1):] if n else b""
        if idx + _PREFIX_LEN > n:
            return frames, buffer[idx:]  # header but not enough for prefix yet
        length = buffer[idx + 8]
        end = idx + _PREFIX_LEN + length + _CRC_LEN
        if end > n:
            return frames, buffer[idx:]  # complete frame not yet received
        candidate = buffer[idx:end]
        if checksum(candidate[:-_CRC_LEN]) == candidate[-_CRC_LEN:]:
            frames.append(
                Frame(
                    src=int.from_bytes(candidate[2:4], "big"),
                    dst=int.from_bytes(candidate[4:6], "big"),
                    cc=candidate[6],
                    fc=candidate[7],
                    data=candidate[_PREFIX_LEN : _PREFIX_LEN + length],
                    raw=candidate,
                )
            )
            i = end
        else:
            _LOGGER.debug("Bad checksum, resyncing past header at %d", idx)
            i = idx + 2  # skip this AA 55 and keep looking


# ---------------------------------------------------------------------------
# Runtime data decoding
#
# CALIBRATED against real QueryNormalInfo (cc=0x11 fc=0x82) responses captured
# from a Zeversolar 2000s on 2026-05-30 (50-byte payload). Verified two ways:
#   * AC current x AC voltage == reported power (offsets 12,14,18);
#   * E-total / operating-hours gives a believable ~0.5 kW average (offsets
#     22,26).
# Bytes 6, 10, 20, 32+ were constant/unused on this single-phase, single-MPPT
# unit and are intentionally left unmapped. If your unit reports differently,
# enable ``log_raw_frames`` and re-check the offsets against the LCD.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One decoded value: where it lives in the payload and how to scale it."""

    key: str
    offset: int
    length: int  # bytes (2 or 4)
    scale: float  # raw integer is multiplied by this
    signed: bool = False


FIELD_MAP: tuple[Field, ...] = (
    Field("temperature", 0, 2, 0.1, signed=True),  # degC
    Field("energy_today", 2, 2, 0.01),  # kWh
    Field("pv_voltage", 4, 2, 0.1),  # V
    Field("pv_current", 8, 2, 0.1),  # A
    Field("ac_current", 12, 2, 0.1),  # A
    Field("ac_voltage", 14, 2, 0.1),  # V
    Field("ac_frequency", 16, 2, 0.01),  # Hz
    Field("power", 18, 2, 1.0),  # W
    Field("energy_total", 22, 4, 0.1),  # kWh
    Field("operating_hours", 26, 4, 1.0),  # h
    Field("status", 30, 2, 1.0),  # 1 = normal / grid-connected
)


def decode_runtime(data: bytes) -> dict[str, float]:
    """Decode a QueryNormalInfo payload into named values using FIELD_MAP."""
    result: dict[str, float] = {}
    for field in FIELD_MAP:
        if field.offset + field.length > len(data):
            continue  # payload shorter than this model exposes; skip safely
        raw = int.from_bytes(
            data[field.offset : field.offset + field.length],
            "big",
            signed=field.signed,
        )
        result[field.key] = round(raw * field.scale, 3)
    return result
