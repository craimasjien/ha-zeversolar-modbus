# Decoding the Zeversolar / Eversolar protocol

This document explains, end to end, how a raw frame from the inverter is turned
into human-readable values like "295 W" and "20831.2 kWh". Everything here is
worked against a **real frame captured from a Zeversolar 2000s** on 2026-05-30.

> Note on the name: this is **not** Modbus. The Zeversolar 2000s speaks the
> proprietary **Eversolar** serial protocol (shared lineage with early Goodwe
> inverters). The Waveshare RS485→Ethernet bridge passes those serial bytes over
> TCP unchanged, so we parse the Eversolar framing ourselves.

The implementation lives in
[`custom_components/zeversolar/protocol.py`](../custom_components/zeversolar/protocol.py).

---

## 1. The captured frame

This is one complete `QueryNormalInfo` response, exactly as it arrived over the
socket (61 bytes):

```
aa 55 00 f1 01 00 11 82 32                                  <- 9-byte prefix
01 55 04 c9 09 59 00 00 00 0d 00 00 00 0d 08 de 13 84 01 27 \
ff ff 00 03 2d b8 00 00 a3 ea 00 01 00 00 00 00 ff ff 00 00  > 50-byte payload
00 00 00 00 00 00 ff 00 00 00                               /
0d 6b                                                       <- 2-byte checksum
```

## 2. Frame anatomy

Every Eversolar frame has the same shape:

```
AA 55 | SRC(2) | DST(2) | CC(1) FC(1) | LEN(1) | DATA(LEN) | CRC(2)
```

Mapping that onto the bytes above:

| Bytes        | Field      | Value     | Meaning |
|--------------|------------|-----------|---------|
| `aa 55`      | Header     | —         | Fixed start-of-frame marker. We scan for this to find frame boundaries. |
| `00 f1`      | SRC        | `0x00F1`  | Source address = the **inverter**. |
| `01 00`      | DST        | `0x0100`  | Destination = the **monitoring master** that asked for this data. |
| `11`         | CC         | `0x11`    | Control code = **Read**. |
| `82`         | FC         | `0x82`    | Function code. `0x82 = 0x02 | 0x80`: a **response** (`|0x80`) to **QueryNormalInfo** (`0x02`). |
| `32`         | LEN        | `50`      | Number of payload bytes that follow. |
| `01 55 … 00` | DATA       | 50 bytes  | The measurements (decoded in §4). |
| `0d 6b`      | CRC        | `0x0D6B`  | Checksum over everything before it (§3). |

Key points used by the parser:

- **Addresses are 2 bytes, big-endian.** Requests/responses are matched by
  `(CC, FC)`. Responses always have the high bit set on FC, so request `0x02`
  becomes response `0x82`.
- **`LEN` makes the frame self-describing.** We read 9 prefix bytes, then `LEN`
  payload bytes, then 2 checksum bytes — so we always know exactly where the
  frame ends, even when several frames arrive glued together in one TCP read.

## 3. The checksum

The checksum is a plain **16-bit additive sum** of every byte from the `AA`
header through the last DATA byte (i.e. the whole frame except the 2 CRC bytes),
kept to 16 bits and stored big-endian (high byte, low byte).

For the captured frame:

```
sum(all 59 bytes before the CRC) = 3435 = 0x0D6B
                       0x0D6B & 0xFFFF = 0x0D6B
        stored as two bytes, big-endian = 0d 6b   ✓ matches
```

In code:

```python
def checksum(payload: bytes) -> bytes:
    total = sum(payload) & 0xFFFF
    return bytes(((total >> 8) & 0xFF, total & 0xFF))
```

A frame whose recomputed checksum doesn't match the trailing two bytes is
rejected, and the parser re-syncs by scanning for the next `AA 55`. That's what
makes it robust to the line noise and partial frames we saw while dialling in
the serial settings.

## 4. Decoding the payload

The 50 DATA bytes are a packed structure of **fixed-point integers**. Each value
is a big-endian unsigned integer that you multiply by a scale factor to recover
the real-world number. Two extra wrinkles:

- **Cumulative counters are 32-bit** (4 bytes), because total energy and
  operating hours overflow a 16-bit value.
- **Temperature is signed** (it can go negative).

The layout is described declaratively by `FIELD_MAP`. Each entry is
`(key, offset, length, scale, signed)`:

```python
Field("power",        18, 2, 1.0)    # bytes 18-19, x1     -> watts
Field("ac_voltage",   14, 2, 0.1)    # bytes 14-15, x0.1   -> volts
Field("energy_total", 22, 4, 0.1)    # bytes 22-25, x0.1   -> kWh (32-bit)
Field("temperature",   0, 2, 0.1, signed=True)
...
```

Decoding is then uniform for every field:

```python
raw = int.from_bytes(data[offset : offset + length], "big", signed=field.signed)
value = raw * scale
```

### Worked decode of the captured payload

Payload (offsets shown for the bytes that matter):

```
off:  0     2     4     6     8     10    12    14    16    18    20
      0155  04c9  0959  0000  000d  0000  000d  08de  1384  0127  ffff
off:  22    24    26    28    30
      0003  2db8  0000  a3ea  0001  ...
```

| Field | Offset | Bytes | Raw int | Scale | Result |
|---|---|---|---|---|---|
| temperature | 0 (2) | `01 55` | 341 | ×0.1 | **34.1 °C** |
| energy_today | 2 (2) | `04 c9` | 1225 | ×0.01 | **12.25 kWh** |
| pv_voltage | 4 (2) | `09 59` | 2393 | ×0.1 | **239.3 V** |
| pv_current | 8 (2) | `00 0d` | 13 | ×0.1 | **1.3 A** |
| ac_current | 12 (2) | `00 0d` | 13 | ×0.1 | **1.3 A** |
| ac_voltage | 14 (2) | `08 de` | 2270 | ×0.1 | **227.0 V** |
| ac_frequency | 16 (2) | `13 84` | 4996 | ×0.01 | **49.96 Hz** |
| power | 18 (2) | `01 27` | 295 | ×1 | **295 W** |
| energy_total | 22 (4) | `00 03 2d b8` | 208312 | ×0.1 | **20831.2 kWh** |
| operating_hours | 26 (4) | `00 00 a3 ea` | 41962 | ×1 | **41962 h** |
| status | 30 (2) | `00 01` | 1 | ×1 | **1 (normal)** |

Bytes 6, 10, 20, and 32+ were constant/zero on this single-phase, single-MPPT
unit (unused phase/string slots and reserved fields), so they're left unmapped.

### How the offsets were trusted (not guessed)

The layout was confirmed two independent ways, both visible above:

1. **Ohm's law on the AC side:** `ac_current × ac_voltage = 1.3 × 227 ≈ 295 W`,
   which equals the `power` field exactly. Three separate offsets (12, 14, 18)
   all have to be right for that to hold.
2. **Plausible lifetime average:** `energy_total ÷ operating_hours =
   20831.2 kWh ÷ 41962 h ≈ 0.5 kW`, a sensible long-run average for a 2 kW
   inverter — which validates the 32-bit fields at offsets 22 and 26.

Comparing two consecutive frames also helped: the bytes that *changed* between
polls (power, AC volts/amps, PV volts, temperature) are exactly the live
measurements, while the ones that stayed fixed (energy totals, hours, frequency,
status) are the slow/cumulative ones.

## 5. Where the frame comes from (passive read)

We don't request this frame. The inverter's own monitoring master (`0x0100`)
polls the inverter (`0x00F1`) continuously, and the bridge mirrors all bus
traffic to our socket. The integration runs **passively**: it just watches the
stream, keeps the first frame matching `CC=0x11, FC=0x82`, decodes it with the
process above, and exposes the values as Home Assistant sensors. No transmitting,
no contention with the existing master.

See [`README.md`](../README.md) for configuration and the calibration/debug
tools (`tools/probe.py`, `tools/mock_inverter.py`).
