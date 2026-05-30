"""Standalone tests for the Eversolar protocol module.

Run directly (no Home Assistant needed):  python3 tests/test_protocol.py
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "zeversolar")
)

import protocol  # noqa: E402


def test_checksum_known_value():
    # 0xAA+0x55+0x10 = 271 = 0x010F -> high 0x01, low 0x0F
    frame = protocol.build_frame(0x0000, 0x0000, 0x10, 0x00)
    assert frame[-2:] == bytes((0x01, 0x0F)), frame.hex(" ")
    assert frame == bytes.fromhex("aa5500000000100000010f")


def test_roundtrip_single_frame():
    data = bytes(range(20))
    frame = protocol.build_frame(0x0000, 0x000A, 0x11, 0x82, data)
    frames, leftover = protocol.parse_frames(frame)
    assert leftover == b""
    assert len(frames) == 1
    f = frames[0]
    assert (f.src, f.dst, f.cc, f.fc) == (0x0000, 0x000A, 0x11, 0x82)
    assert f.data == data


def test_two_frames_with_leading_garbage():
    a = protocol.build_frame(0x0000, 0x0000, 0x10, 0x00)
    b = protocol.build_frame(0x0000, 0x000A, 0x11, 0x82, b"\x01\x02\x03")
    stream = b"\x99\x99" + a + b"\x00" + b
    frames, leftover = protocol.parse_frames(stream)
    assert len(frames) == 2
    assert frames[0].fc == 0x00 and frames[1].fc == 0x82
    assert leftover == b""


def test_partial_frame_is_buffered():
    full = protocol.build_frame(0x0000, 0x000A, 0x11, 0x82, b"\xde\xad\xbe\xef")
    head, tail = full[:7], full[7:]
    frames, leftover = protocol.parse_frames(head)
    assert frames == [] and leftover == head
    frames, leftover = protocol.parse_frames(leftover + tail)
    assert len(frames) == 1 and leftover == b""


def test_bad_checksum_resyncs_to_next_frame():
    good = protocol.build_frame(0x0000, 0x000A, 0x11, 0x82, b"\x01\x02")
    corrupt = bytearray(protocol.build_frame(0x0000, 0x000A, 0x11, 0x82, b"\x09\x09"))
    corrupt[-1] ^= 0xFF  # break the checksum
    frames, _ = protocol.parse_frames(bytes(corrupt) + good)
    assert len(frames) == 1
    assert frames[0].data == b"\x01\x02"


def test_decode_runtime_uses_field_map():
    # Build a payload that exercises key fields at their calibrated offsets.
    payload = bytearray(32)
    payload[0:2] = (250).to_bytes(2, "big")  # temperature 25.0
    payload[18:20] = (1500).to_bytes(2, "big")  # power 1500 W
    payload[22:26] = (123456).to_bytes(4, "big")  # energy_total 12345.6 kWh
    decoded = protocol.decode_runtime(bytes(payload))
    assert decoded["temperature"] == 25.0
    assert decoded["power"] == 1500.0
    assert decoded["energy_total"] == 12345.6


def test_decode_runtime_handles_short_payload():
    # A payload too short for energy_total must not raise.
    decoded = protocol.decode_runtime(bytes(8))
    assert "energy_total" not in decoded
    assert decoded["temperature"] == 0.0


def test_decode_real_captured_frame():
    # Real cc=0x11 fc=0x82 frame captured from a Zeversolar 2000s (2026-05-30).
    raw = bytes.fromhex(
        "aa5500f1010011823201"
        "5504c90959000000 0d0000000d08de138401"
        "27ffff00032db80000a3ea00010000"
        "0000ffff0000000000000000ff000000"
        "0d6b".replace(" ", "")
    )
    frames, leftover = protocol.parse_frames(raw)
    assert leftover == b"" and len(frames) == 1
    f = frames[0]
    assert (f.cc, f.fc) == (protocol.CC_READ, protocol.FC_QUERY_NORMAL_INFO | 0x80)
    d = protocol.decode_runtime(f.data)
    assert d["power"] == 295.0
    assert d["ac_voltage"] == 227.0
    assert d["ac_current"] == 1.3
    assert d["ac_frequency"] == 49.96
    assert d["temperature"] == 34.1
    assert d["energy_today"] == 12.25
    assert d["energy_total"] == 20831.2
    assert d["operating_hours"] == 41962
    assert d["status"] == 1
    # The decoded AC power must match current x voltage.
    assert round(d["ac_current"] * d["ac_voltage"]) == d["power"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
