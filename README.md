# Zeversolar 2000s — Home Assistant custom component (Eversolar protocol)

Reads real-time data from a **Zeversolar 2000s** (Zeverlution series) inverter
over a **raw TCP socket** and exposes it as Home Assistant sensors.

The 2000s does **not** speak Modbus RTU on its RS485 port — it uses the
proprietary **Eversolar** serial protocol (shared lineage with early Goodwe
inverters). A Waveshare RS485→Ethernet bridge, configured as a *transparent TCP
server*, forwards these raw serial frames over the network. This component
talks that protocol directly with `asyncio` (no `pymodbus`, no Modbus
translation on the bridge).

## Hardware assumptions

- Inverter: Zeversolar 2000s, RS485 wired to a Waveshare RS485→Ethernet bridge.
- Bridge mode: **TCP Server**, *transparent / raw* (no Modbus TCP↔RTU).
- Serial settings on the bridge must match the inverter (typically
  **9600 baud, 8N1**).
- Bridge reachable at e.g. `192.168.2.200`, port `502` (or `4196`).

## Install

Copy the integration into your Home Assistant config directory:

```
<config>/custom_components/zeversolar/
```

Restart Home Assistant.

## Configure (`configuration.yaml`)

```yaml
sensor:
  - platform: zeversolar
    host: 192.168.2.200
    port: 502              # or 4196 — whatever the Waveshare raw socket uses
    name: Zeversolar
    inverter_address: 10   # address we assign during registration (1..254)
    scan_interval: 30      # seconds
    log_raw_frames: true   # SEE CALIBRATION BELOW — turn off once verified
```

Restart Home Assistant after editing.

### Entities created

| Entity                     | Unit | Enabled by default |
|----------------------------|------|--------------------|
| `Zeversolar Current Power` | W    | ✅ |
| `Zeversolar Energy Today`  | kWh  | ✅ |
| `Zeversolar Energy Total`  | kWh  | ✅ |
| PV Voltage / AC Voltage / AC Current / AC Frequency / Temperature | V·A·Hz·°C | disabled (enable in UI) |

`Energy Today` / `Energy Total` use `state_class: total_increasing`, so they
plug straight into the HA **Energy dashboard**.

## ⚠️ Calibration — required before you trust the numbers

The framing, checksum, and registration handshake are fully implemented and
unit-tested. **The byte offsets of the data payload are a best-guess**: in the
Eversolar protocol the data layout is negotiated per inverter model, and this
build assumes the common single-phase / single-MPPT (Goodwe-style) layout. Your
2000s may differ.

To lock the offsets to your hardware:

1. Keep `log_raw_frames: true` (the default) and add to `configuration.yaml`:

   ```yaml
   logger:
     default: warning
     logs:
       custom_components.zeversolar: warning
   ```

2. Let it poll **during daylight** (the inverter is offline/dark at night and
   won't respond). Watch **Settings → System → Logs** for lines like:

   ```
   Zeversolar TX: aa 55 00 00 00 0a 11 02 00 ...
   Zeversolar RX: cc=0x11 fc=0x82 len=24 data=00 fa 01 2c 09 1e ...
   ```

   The `cc=0x11 fc=0x82` line is the runtime-data response. Copy its `data=`
   hex.

3. Compare against the inverter's LCD (current power in W, today's kWh, total
   kWh) and map which byte pair holds each value. Then edit `FIELD_MAP` in
   [`protocol.py`](custom_components/zeversolar/protocol.py):

   ```python
   FIELD_MAP = (
       Field("power", <offset>, 2, 1.0),
       Field("energy_today", <offset>, 2, 0.01),
       Field("energy_total", <offset>, 4, 0.1),
       ...
   )
   ```

   Each `Field` is `(key, byte_offset, length, scale, signed=False)`; values are
   big-endian. Restart HA and confirm the sensors match the LCD.

4. Once correct, set `log_raw_frames: false` to quiet the log.

If you capture a real `data=` frame and paste it back, I can finish the byte
mapping for you.

## How it works

- [`protocol.py`](custom_components/zeversolar/protocol.py) — pure functions:
  `build_frame`, `checksum`, a resync-safe streaming `parse_frames`, and the
  `FIELD_MAP`-driven `decode_runtime`.
- [`coordinator.py`](custom_components/zeversolar/coordinator.py) —
  `ZeversolarClient` owns the `asyncio` socket and the discovery → assign-address
  → poll handshake; on any socket/timeout error it drops the connection and
  re-registers on the next cycle. `ZeversolarCoordinator` is the
  `DataUpdateCoordinator`.
- [`sensor.py`](custom_components/zeversolar/sensor.py) — YAML platform setup and
  the `CoordinatorEntity` sensor definitions.

## Test against the inverter WITHOUT Home Assistant

Before touching HA, talk to the inverter directly with the standalone probe. It
runs the exact same client code HA uses, prints every frame on the wire, decodes
with the current `FIELD_MAP`, and dumps a labelled offset table to calibrate
from. **Run it during daylight** — the inverter is dark at night and won't answer.

```
python3 tools/probe.py 192.168.2.200            # poll once
python3 tools/probe.py 192.168.2.200 --port 4196 --address 10
python3 tools/probe.py 192.168.2.200 --interval 10   # poll forever
```

The offset table shows each byte pair as a `uint16` plus `/10` and `/100`
candidates, so you can eyeball which offset holds power (W), today (kWh) and
total (kWh) against the inverter's LCD, then edit `FIELD_MAP` in
[`protocol.py`](custom_components/zeversolar/protocol.py).

No hardware handy? A mock inverter answers the full handshake on localhost:

```
python3 tools/mock_inverter.py --port 5020 &
python3 tools/probe.py 127.0.0.1 --port 5020
```

### Troubleshooting: connects but times out

If the probe connects but the poll times out (`No frame cc=0x10 fc=0x80 ...`),
the TCP link to the Waveshare is fine but the inverter isn't answering over
RS485. Run the low-level sniffer, which re-sends the query and hex-dumps **every**
byte that comes back, valid frame or not:

```
python3 tools/probe.py 192.168.2.200 --port 502 --sniff 15
```

- **Nothing back** → RS485 problem: A/B (D+/D−) lines swapped (most common),
  wrong baud (Zeversolar is usually 9600 8N1), the bus is owned by the
  Zeversolar Wi-Fi/monitoring dongle (unplug it), or the bridge isn't in
  transparent/raw mode.
- **Garbage back, no valid frame** → link is live but serial settings (baud/
  parity) are off, or A/B are swapped — framing is corrupted.
- **A valid frame** → the link is good; it's a parsing/offset matter.

## Tests

```
python3 tests/test_protocol.py
```

Covers checksum, frame round-trip, multi-frame + garbage resync, partial-frame
buffering, bad-checksum recovery, and `FIELD_MAP` decoding.

## Protocol reference

```
AA 55 | SRC(2) | DST(2) | CC(1) FC(1) | LEN(1) | DATA(LEN) | CRC(2, big-endian)
CRC = 16-bit sum of every byte from AA through the last DATA byte.

Handshake:
  Offline query   CC=0x10 FC=0x00 (broadcast)        -> FC=0x80, DATA=serial
  Assign address  CC=0x10 FC=0x01 (DATA=serial+addr) -> FC=0x81, ACK
  Poll data       CC=0x11 FC=0x02 (to addr)          -> FC=0x82, DATA=values
Responses set the high bit (0x80) of the request function code.
```
