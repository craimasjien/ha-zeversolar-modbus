# Zeversolar Zeverlution 2000S — RJ45 RS485 pinout & zero-export findings

## Interface definition

| Property        | Value                                      |
|-----------------|--------------------------------------------|
| Connector type  | RJ45 (8P8C)                                |
| Protocol        | Eversolar serial (often mislabelled Modbus)|
| Physical layer  | RS485, derived from an internal RS422 layout (full-duplex) |
| Wiring standard | T568B reference                            |

## Pinout mapping

| Pin | Signal name | RS485 function | T568B wire color | Connection note   |
|-----|-------------|----------------|------------------|-------------------|
| 1   | `TX_RS485A` | Data + (A)     | Orange/White     | Required          |
| 2   | `TX_RS485B` | Data − (B)     | Orange           | Required          |
| 3   | `RX_RS485A` | Data + (A)     | Green/White      | Optional (loop)   |
| 4   | `GND`       | Signal ground  | Blue             | Recommended (GND) |
| 5   | `GND`       | Signal ground  | Blue/White       | Recommended (GND) |
| 6   | `RX_RS485B` | Data − (B)     | Green            | Optional (loop)   |
| 7   | `+7V`       | VCC (power)    | Brown/White      | **DO NOT CONNECT**|
| 8   | `+7V`       | VCC (power)    | Brown            | **DO NOT CONNECT**|

## Wiring configuration schematics

### Method 1 — standard RS485 connection (simplified)

```
[RJ45 connector]                              [Modbus reader / controller]
Pin 1 (Orange/White) ───────────────────────▶ Data A (+)
Pin 2 (Orange)       ───────────────────────▶ Data B (−)
Pin 4 (Blue)      ╲
                   ╲── (combined/joined) ────▶ GND / signal ground
Pin 5 (Blue/White)╱
```

> Pins 3, 6, 7, 8 left disconnected. Isolate pins 7 and 8.

### Method 2 — looped/bridged connection

```
[RJ45 connector]                              [Modbus reader / controller]
Pin 1 (Orange/White)╲
                     ╲── (combined/joined) ──▶ Data A (+)
Pin 3 (Green/White) ╱

Pin 2 (Orange)      ╲
                     ╲── (combined/joined) ──▶ Data B (−)
Pin 6 (Green)       ╱

Pin 4 (Blue)        ╲
                     ╲── (combined/joined) ──▶ GND / signal ground
Pin 5 (Blue/White)  ╱
```

> Pins 7 and 8 left disconnected. Isolate pins 7 and 8.
>
> **Do not use Method 2 on this port** — see [directionality](#read-vs-write--directionality-of-the-four-wire-port) below. It is full-duplex, and bridging 1+3 / 2+6 ties the inverter's own transmitter onto its own receiver.

## Critical safety & operational parameters

1. **Voltage warning.** Pins 7 and 8 carry an active **+7 V DC** supply intended solely for proprietary Zeversolar accessories (ZeverCom/ZeverManager). Connecting them to a standard RS485 adapter will cause hardware damage. Cut them back and insulate them.
2. **Grounding.** Combining pins 4 and 5 into a single GND terminal is permissible and recommended; a single wire (pin 4 only) is also acceptable.

---

## Read vs write — directionality of the four-wire port

This port is **full-duplex (RS422-style)**: two independent differential pairs, named from the **inverter's** point of view. This is the key to whether you can only listen or can also command the inverter.

| Pair       | Pins            | Direction & meaning                                                                                  |
|------------|-----------------|------------------------------------------------------------------------------------------------------|
| TX (1 / 2) | 1 = A+, 2 = B−  | **Inverter → master.** Carries the inverter's *responses* (`QueryNormalInfo`, `cc=0x11 fc=0x82`). Listen here = **read-only**. |
| RX (3 / 6) | 3 = A+, 6 = B−  | **Master → inverter.** The pair the bus master *drives* to send commands/polls. Drive here = the only way to **write**. |

**Consequences:**

- The Waveshare wired to pins 1/2 is **receive-only by construction**. It sees the inverter's replies (that's why passive monitoring works) but never the master's requests, and it **cannot** command the inverter.
- To write (e.g. an active-power-limit command) you must drive **pins 3/6**.
- Because it is full-duplex, **do not use Method 2** (bridging 1+3 / 2+6). Use a Waveshare/adapter in **4-wire / RS422 mode** instead:

  ```
  inverter TX (1/2) ──▶ adapter RX
  inverter RX (3/6) ◀── adapter TX
  ```

  (Or use a second 2-wire adapter dedicated to the 3/6 pair.)
- Pins 7/8 (+7 V) remain **cut and insulated** in all of the below.

> **Provenance:** this pinout was community/LLM-sourced. Confirm the TX/RX directionality empirically before driving anything — see [Step 0](#plan--capture-first-then-write) of the plan.

---

## Goal: zero-export by commanding the inverter from Home Assistant

**Target:** feed the inverter an active-power limit derived from a P1 grid reading so it throttles to ~zero export — replacing the role a ComBox + Eastron-meter combo would play.

**Why "emulate an Eastron meter" is *not* possible on this unit:**

- Zero-export normally is: `Eastron meter ──Modbus──▶ data logger (ComBox) ──Eversolar──▶ inverter`. The data logger reads the meter, computes the limit, and commands the inverter. **The inverter never reads a meter itself.**
- This ComBox is a **WiFi/Ethernet monitoring logger only**: it talks to the inverter over the internal board-to-board header and has **no 2-wire RS485 meter terminal**. There is nowhere to attach an emulated meter.

Therefore the only route is: **HA becomes the RS485 master on pins 3/6 and sends the inverter a "set active power" command itself.**

**Unknown to solve:** the exact "set active power" frame (control/function code + value encoding) is **not** in the current codebase and is **not** publicly documented. Only the read/register side is known (see [`docs/PROTOCOL.md`](docs/PROTOCOL.md)). We must capture it.

---

## Plan — capture first, then write

Everything up to Step 3 is **read-only and reversible**. Step 2's capture removes the need to guess the command, avoiding blind writes to a grid-tied inverter.

### Step 0 — verify directionality (non-invasive)

Move the Waveshare (or a second adapter) onto pins 3/6, listen, and run the sniffer (`tools/probe.py --sniff`). If 3/6 is the master→inverter pair you will now see the ComBox's **requests** (`cc=0x11 fc=0x02`) that never appear on 1/2. This confirms the [directionality table](#read-vs-write--directionality-of-the-four-wire-port) before anything is driven.

### Step 1 — capture the limit command (ComBox still connected & active)

The ComBox can apply a **fixed active-power reduction with no meter**, via its power-management / EEG "70%" setting (ZeverManager / web UI). Changing that setting makes the ComBox **emit the "set active power" command** on pins 3/6. With the listener on 3/6, toggle the limit (e.g. 100% → 70% → 50% → 0%) and record the frames.

### Step 2 — decode

Diff the captured frames across limit values to isolate the control code, function code, and the value field (percent vs watts). That **is** the command. Add it to `protocol.py` (a `build_limit_frame()`) mirroring `build_frame()`.

### Step 3 — write (ComBox now isolated — see below)

Make HA sole master on pins 3/6 (4-wire/RS422), switch the client from passive to active master mode, poll for data **and** send the limit frame with a value computed from the live P1 reading. Closes the zero-export loop.

---

## Isolating the ComBox (only needed for Step 3 / write mode)

**Why:** a single-master RS485 bus cannot have both the ComBox and HA driving pins 3/6. Once isolated the ComBox also stops monitoring (a master that can't transmit can't poll) — expected, HA replaces it. **The inverter itself runs fine with no logger;** the ComBox is not part of its control/safety loop.

**How** — the ComBox is a daughterboard stacked on the comm board, tied to the bus via a **board-to-board header**, *not* via either RJ45 jack:

1. **Preferred:** power down, then **unstack** the ComBox off its mating header. Removes its RS485 driver from the bus completely. Fully reversible.
2. If it mates via a removable connector/short cable: **unplug that connector**.
3. **Avoid:** lifting only the RS485-TX pins — fiddly and pointless (it can't monitor once muted anyway).

> **Do not isolate during Step 1** — the ComBox is what generates the command you are capturing. Isolate only when flipping HA to sole-master write mode.

### ⚠️ Safety: grid-tied inverter — mains + high DC present

Before touching boards: switch off **AC** at the breaker **and** the **DC/PV isolator**, then **wait several minutes** for the bus capacitors to discharge. Never unstack or rewire live.
