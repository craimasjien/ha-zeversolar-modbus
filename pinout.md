# Zeversolar Zeverlution 2000S — RJ45 RS485 pinout & zero-export findings

## Interface definition

| Property        | Value                                                       |
|-----------------|-------------------------------------------------------------|
| Connector type  | RJ45 (8P8C)                                                 |
| Protocol        | Eversolar serial (often mislabelled Modbus)                 |
| Physical layer  | **RS422 / 4-wire RS485 — full-duplex** (two separate pairs) |
| Wiring standard | T568B reference                                             |

This port is **full-duplex**: it has two *independent* differential pairs — one
the inverter transmits on, one it receives on. They are **not** interchangeable
and must **never be joined together** (see [why](#never-combine-the-tx-and-rx-pairs)).

## Pinout mapping

Signal names are from the **inverter's** point of view (`TX` = the inverter
transmits; `RX` = the inverter receives).

| Pin | Signal      | Pair / role                  | T568B wire color | Connect to…                          |
|-----|-------------|------------------------------|------------------|--------------------------------------|
| 1   | `TX_RS485A` | **TX pair** (inverter → you) | Orange/White     | Adapter **RX A+** (to read)          |
| 2   | `TX_RS485B` | **TX pair** (inverter → you) | Orange           | Adapter **RX B−** (to read)          |
| 3   | `RX_RS485A` | **RX pair** (you → inverter) | Green/White      | Adapter **TX A+** (to write)         |
| 6   | `RX_RS485B` | **RX pair** (you → inverter) | Green            | Adapter **TX B−** (to write)         |
| 4   | `GND`       | Signal ground                | Blue             | Adapter **GND**                      |
| 5   | `GND`       | Signal ground                | Blue/White       | Adapter **GND** (same net as pin 4)  |
| 7   | `+7V`       | VCC (power)                  | Brown/White      | **DO NOT CONNECT** — cut & insulate  |
| 8   | `+7V`       | VCC (power)                  | Brown            | **DO NOT CONNECT** — cut & insulate  |

- **TX pair (1/2)** carries the inverter's *responses* — listening here is
  **read-only**. This is what the Waveshare uses today.
- **RX pair (3/6)** is the line the bus master *drives* to send commands —
  driving here is the **only way to write** to the inverter.
- **GND (4/5)** are the same ground net; use either one, or join both. Joining
  the two ground pins is the *only* permitted combining of wires on this port.
- **+7 V (7/8)** is for proprietary Zeversolar accessories only and will damage a
  standard RS485 adapter. Always cut back and insulate.

---

## Wiring configurations

There are exactly two valid ways to wire this port. Which one you use depends on
whether you only want to **read** the inverter or also **write** to it. Both keep
the TX and RX pairs strictly separate.

### A. Read-only tap (passive monitoring) — current setup

Use a 2-wire RS485 adapter on the **TX pair only**:

```
[Inverter RJ45]                 [RS485 adapter — receive only]
Pin 1 (Orange/White) ─────────▶ A (+)
Pin 2 (Orange)       ─────────▶ B (−)
Pin 4 (Blue)         ─────────▶ GND
```

> Pins 3, 6 left unconnected. Pins 7, 8 cut and insulated.
> This can only listen to the inverter's replies; it cannot command it.

### B. Read + write (full-duplex, 4-wire RS422) — required to command the inverter

Use an adapter in **4-wire / RS422 mode**, crossing each pair to the matching
adapter direction:

```
[Inverter RJ45]                 [RS485/RS422 adapter — 4-wire mode]
Pin 1 (Orange/White) ─────────▶ RX A (+)     (inverter TX → adapter RX)
Pin 2 (Orange)       ─────────▶ RX B (−)
Pin 3 (Green/White)  ◀───────── TX A (+)     (adapter TX → inverter RX)
Pin 6 (Green)        ◀───────── TX B (−)
Pin 4 (Blue)         ─────────▶ GND
```

> Pins 7, 8 cut and insulated.
> If your adapter is 2-wire only, you cannot do this with a single adapter —
> either use a true 4-wire/RS422 adapter, or a second 2-wire adapter dedicated to
> the 3/6 pair.

### Never combine the TX and RX pairs

Some community pinouts show a "bridged" wiring that joins **pin 1 + pin 3** into
one A line and **pin 2 + pin 6** into one B line. **Do not do this.** On a
full-duplex port that shorts the inverter's own transmitter (TX, 1/2) onto its
own receiver (RX, 3/6) and onto your adapter — guaranteed bus contention and a
risk of damaging the line drivers. The TX and RX pairs are always wired
separately, as in configurations A and B above. (Joining the two **GND** pins,
4 and 5, is fine — that is the only legitimate combining.)

---

## Safety — grid-tied inverter, mains + high DC present

Before touching the RJ45, the wiring, or any board:

1. Switch off **AC** at the breaker **and** the **DC/PV isolator**.
2. **Wait several minutes** for the bus capacitors to discharge.
3. Confirm pins **7 and 8** are cut back and insulated before connecting any
   adapter — they carry +7 V.

Never rewire live.

---

## Goal: zero-export by commanding the inverter from Home Assistant

**Target:** feed the inverter an active-power limit derived from a P1 grid
reading so it throttles to ~zero export — replacing the role a ComBox +
Eastron-meter combo would play.

**Why "emulate an Eastron meter" is *not* possible on this unit:**

- Zero-export normally is:
  `Eastron meter ──Modbus──▶ data logger (ComBox) ──Eversolar──▶ inverter`.
  The data logger reads the meter, computes the limit, and commands the inverter.
  **The inverter never reads a meter itself.**
- This ComBox is a **WiFi/Ethernet monitoring logger only**: it talks to the
  inverter over the internal board-to-board header and has **no 2-wire RS485
  meter terminal**. There is nowhere to attach an emulated meter.

Therefore the only route is: **HA becomes the RS485 master on the RX pair (3/6)
and sends the inverter a "set active power" command itself** (wiring
configuration B).

**Unknown to solve:** the exact "set active power" frame (control/function code +
value encoding) is **not** in the current codebase and is **not** publicly
documented. Only the read/register side is known (see
[`docs/PROTOCOL.md`](docs/PROTOCOL.md)). We must capture it.

---

## Plan — capture first, then write

Everything up to Step 3 is **read-only and reversible**. Step 2's capture removes
the need to guess the command, avoiding blind writes to a grid-tied inverter.

### Step 0 — verify directionality (non-invasive)

Move the Waveshare (or a second adapter) onto the **RX pair (3/6)**, listen, and
run the sniffer (`tools/probe.py --sniff`). If 3/6 is the master→inverter pair
you will now see the ComBox's **requests** (`cc=0x11 fc=0x02`) that never appear
on the TX pair (1/2). This confirms the pinout before anything is driven.

### Step 1 — capture the limit command (ComBox still connected & active)

The ComBox can apply a **fixed active-power reduction with no meter**, via its
power-management / EEG "70%" setting (ZeverManager / web UI). Changing that
setting makes the ComBox **emit the "set active power" command** on the RX pair
(3/6). With the listener on 3/6, toggle the limit (e.g. 100% → 70% → 50% → 0%)
and record the frames.

### Step 2 — decode

Diff the captured frames across limit values to isolate the control code,
function code, and the value field (percent vs watts). That **is** the command.
Add it to `protocol.py` (a `build_limit_frame()`) mirroring `build_frame()`.

### Step 3 — write (ComBox now isolated — see below)

Wire configuration **B** (4-wire), make HA the sole master, switch the client
from passive to active master mode, poll for data **and** send the limit frame
with a value computed from the live P1 reading. Closes the zero-export loop.

---

## Isolating the ComBox (only needed for Step 3 / write mode)

**Why:** a single-master RS485 bus cannot have both the ComBox and HA driving the
RX pair (3/6). Once isolated the ComBox also stops monitoring (a master that
can't transmit can't poll) — expected, HA replaces it. **The inverter itself runs
fine with no logger;** the ComBox is not part of its control/safety loop.

**How** — the ComBox is a daughterboard stacked on the comm board, tied to the
bus via a **board-to-board header**, *not* via either RJ45 jack:

1. **Preferred:** power down, then **unstack** the ComBox off its mating header.
   Removes its RS485 driver from the bus completely. Fully reversible.
2. If it mates via a removable connector/short cable: **unplug that connector**.
3. **Avoid:** lifting only the RS485-TX pins — fiddly and pointless (it can't
   monitor once muted anyway).

> **Do not isolate during Step 1** — the ComBox is what generates the command you
> are capturing. Isolate only when flipping HA to sole-master write mode (and
> observe the [safety](#safety--grid-tied-inverter-mains--high-dc-present) steps
> before opening the unit).
