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
- Bridge reachable at e.g. `192.168.2.200`, port `502` (or `4196`).

### Verified serial / wiring settings (confirmed on real hardware)

| Setting | Value |
|---|---|
| Baud | **9600** |
| Framing | **8 / None / 1** |
| RS485 A/B (D+/D−) | **may be swapped** vs. the obvious labelling — see troubleshooting |

If you see only garbage and never an `aa 55` header, fix these first — the
component can't do anything until the bridge delivers clean frames. The
[Troubleshooting](#troubleshooting-connects-but-times-out) section walks through
finding them with the probe.

## Install

This is a **custom component** (domain `zeversolar`). It is configured in
YAML — there is no UI config-flow — so installation is two parts: get the files
into Home Assistant, then add the [configuration](#configure-configurationyaml)
and restart.

### 1. Locate your Home Assistant `config` directory

This is the folder that contains `configuration.yaml`. Where it lives depends on
your install type:

| Install type | `config` directory |
|---|---|
| Home Assistant OS / Supervised | `/config` (via the **File editor**, **Samba**, or **SSH/Terminal** add-on) |
| Home Assistant Container (Docker) | the host folder you bind-mounted to `/config` |
| Home Assistant Core (venv) | typically `~/.homeassistant/` |

### 2. Copy the integration in

Create the `custom_components/zeversolar/` folder under `config` and copy the
**contents of [`custom_components/zeversolar/`](custom_components/zeversolar/)**
from this repo into it. The result must look exactly like:

```
<config>/
├── configuration.yaml
└── custom_components/
    └── zeversolar/
        ├── __init__.py
        ├── manifest.json
        ├── const.py
        ├── protocol.py
        ├── client.py
        ├── coordinator.py
        └── sensor.py
```

Pick whichever transfer method matches your setup:

- **Samba add-on** — browse to the `\\<ha-host>\config` share and drag the
  folder in.
- **SSH / Terminal add-on** (or Container host):

  ```bash
  cd /config
  mkdir -p custom_components
  git clone https://github.com/erwin/ha-zeversolar-modbus /tmp/zeversolar
  cp -r /tmp/zeversolar/custom_components/zeversolar custom_components/
  ```

- **File editor / Studio Code Server add-on** — create the files and paste the
  contents manually.

> **HACS (optional):** HACS → ⋮ → *Custom repositories* → add
> `https://github.com/erwin/ha-zeversolar-modbus` as category **Integration**,
> then install it. HACS just copies the same files into
> `custom_components/zeversolar/` for you.

### 3. Configure and restart

Add the sensor platform to `configuration.yaml` (see
[Configure](#configure-configurationyaml) below), then restart Home Assistant
(**Developer Tools → YAML → Restart**, or **Settings → System → Restart**).

### 4. Verify it loaded

After the restart:

- The `zeversolar` entities (e.g. **Zeversolar Current Power**) appear under
  **Settings → Devices & Services → Entities**.
- **Settings → System → Logs** shows `custom_components.zeversolar` lines and no
  import errors.

If entities are missing or show *unavailable*, it's almost always the bus link,
not the install — work through [Troubleshooting](#troubleshooting-connects-but-times-out)
and confirm the wiring/serial settings first.

## Configure (`configuration.yaml`)

```yaml
sensor:
  - platform: zeversolar
    host: 192.168.2.200
    port: 502              # or 4196 — whatever the Waveshare raw socket uses
    name: Zeversolar
    passive: true          # listen to the existing bus master (recommended)
    scan_interval: 30      # seconds
    # inverter_address: 10 # only used when passive: false (we become master)
    # log_raw_frames: true # dump every frame to the log (calibration/debug)
```

Restart Home Assistant after editing.

### Passive vs. active mode

Most Zeversolar installs keep the **monitoring module (ComBox / Wi-Fi /
Ethernet) as the RS485 bus master**, continuously polling the inverter. Two
masters on one bus collide, so this integration defaults to **`passive: true`**:
it transmits nothing and simply decodes the `QueryNormalInfo` responses the
existing master already solicits. No registration, no contention, and your
existing monitoring keeps working untouched.

Set **`passive: false`** only if there is *no* other master on the bus (e.g. you
removed the monitoring module). In active mode the component performs the
discovery → assign-address → poll handshake itself, using `inverter_address`.

### Entities created

| Entity                     | Unit | Enabled by default |
|----------------------------|------|--------------------|
| `Zeversolar Current Power` | W    | ✅ |
| `Zeversolar Energy Today`  | kWh  | ✅ |
| `Zeversolar Energy Total`  | kWh  | ✅ |
| PV Voltage / PV Current / AC Voltage / AC Current / AC Frequency / Temperature / Operating Hours | V·A·Hz·°C·h | disabled (enable in UI) |

`Energy Today` / `Energy Total` use `state_class: total_increasing`, so they
plug straight into the HA **Energy dashboard**.

## Data offsets — calibrated, but model-dependent

The payload offsets in `FIELD_MAP` ([`protocol.py`](custom_components/zeversolar/protocol.py))
are **calibrated against real `QueryNormalInfo` frames captured from a Zeversolar
2000s** and cross-checked (AC volts × amps = reported watts; energy ÷ hours =
believable average). For an identical 2000s they should be correct out of the box.

The Eversolar payload layout can still vary by model/firmware, so if any value
looks wrong, re-verify against your inverter's LCD:

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

The byte *character* tells you which way to turn the baud: streams saturated
with `0xff` mean the bridge baud is **too high** (oversampling a slower signal);
sparse, mostly-`0x00` streams mean it's **too low**. As you approach the right
rate the bytes look less like filler and more like varied data.

**What worked on the reference unit:** the data was garbled at every baud until
the **A/B wires were swapped** at the Waveshare; with A/B swapped and **9600 8N1**
the `aa 55` frames came through cleanly. The capture also revealed an existing
bus master — hence `passive: true` is the default (see above).

## Tests

```
python3 tests/test_protocol.py
```

Covers checksum, frame round-trip, multi-frame + garbage resync, partial-frame
buffering, bad-checksum recovery, and `FIELD_MAP` decoding.

## Protocol reference

For a full, worked walk-through of how a raw frame becomes human-readable values
(frame anatomy, checksum arithmetic, and a byte-by-byte decode of a real
capture), see **[docs/PROTOCOL.md](docs/PROTOCOL.md)**.

```
AA 55 | SRC(2) | DST(2) | CC(1) FC(1) | LEN(1) | DATA(LEN) | CRC(2, big-endian)
CRC = 16-bit sum of every byte from AA through the last DATA byte.

Handshake:
  Offline query   CC=0x10 FC=0x00 (broadcast)        -> FC=0x80, DATA=serial
  Assign address  CC=0x10 FC=0x01 (DATA=serial+addr) -> FC=0x81, ACK
  Poll data       CC=0x11 FC=0x02 (to addr)          -> FC=0x82, DATA=values
Responses set the high bit (0x80) of the request function code.
```
