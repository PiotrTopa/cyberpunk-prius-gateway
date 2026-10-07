# Gateway v3 — RP2350 (C, pico-sdk)

From-scratch rewrite of the AVC-LAN / CAN / RS485 gateway for the
**Waveshare RP2350-Zero** (same pinout as the RP2040-Zero the v2.x MicroPython
firmware ran on; the RP2040 build is kept as a fallback target).

Design goals, in order:

1. **AVC-LAN frames reach the host the instant they end.** The PIO measures
   every dominant pulse and pushes it the moment the pulse ends; a per-bit
   decoder running in the PIO interrupt finishes the frame on its **last ACK
   slot** and hands it to the main loop, which writes the NDJSON line to USB
   and flushes it. No bus-silence timeout, no burst aggregation (`cnt` is
   gone), no GC pauses, nothing in the loop ever blocks. Bench figure from the
   cycle simulation: last-bit edge → word in the CPU ≈ 1.75 µs; end-to-end to
   the host is dominated by the USB poll (≤ 1 ms).
2. **CAN is solicited-only.** The controller sits in listen-only mode until a
   request or subscription needs it, hardware acceptance filters admit only
   the response ids of live queries, and a small non-blocking engine runs one
   request at a time with an inter-request gap. Passive CAN streaming is gone
   (that job now belongs to the panda).
3. **Same wire protocol.** The NDJSON envelope, device ids, `req`/`sub`/
   `unsub`/`subs`/`mode`/`tx` actions, `GATEWAY_READY`, `GW_HB`, `IDENT`,
   satellite tunnelling and error codes are unchanged, so the backend and the
   satellite tools keep working. Additions are listed below.

```
gateway-rp2350/
├── CMakeLists.txt, build.sh          build (Ninja, pico-sdk 2.2.0)
├── src/
│   ├── avclan.pio                    RX pulse-width capture, TX bit generator
│   ├── avclan_codec.[ch]             IEBus bit-stream decoder/encoder (pure C, unit-tested)
│   ├── avclan.[ch]                   PIO/IRQ/DMA glue, polarity detection, echo tagging
│   ├── mcp2515.[ch]                  SPI driver, acceptance filters
│   ├── can_sol.[ch]                  request/subscription engine, ISO-TP
│   ├── rs485.[ch]                    UART1 + DE, IRQ receive ring, non-blocking TX
│   ├── usb_cdc.c, usb_descriptors.c  TinyUSB CDC ("Prius Gateway", VID 2E8A PID 000A)
│   ├── commands.c                    NDJSON command dispatch, heartbeat, stats
│   ├── out.[ch]                      line output, seq counter
│   ├── led.c, ws2812.pio             on-board status LED
│   └── json_util.[ch], jsmn.h        tiny JSON helpers (jsmn, MIT)
├── test/run.sh, test_codec.c         host unit tests (codec + JSON helpers)
├── test/pio_sim.py                   cycle-level simulation of both PIO programs
└── tools/gwctl.py                    host CLI: monitor, whoami, raw pulses, avc/req/sub, bootsel
```

## Hardware

Pinout is identical to v2.x (see `../gateway/docs/wiring.md` and
`../gateway/docs/avclan-phy.md`):

| Function | GPIO |
|---|---|
| AVC-LAN RX (LM339 out, 4k7 to 3V3) | GP0 |
| AVC-LAN TX (→ 2k2 → BC547 base, HIGH = dominant) | GP1 |
| MCP2515 SCK / MOSI / MISO / CS / INT | GP2 / GP3 / GP4 / GP5 / GP6 |
| RS485 DE / TX / RX (UART1, 115200) | GP7 / GP8 / GP9 |
| WS2812 status LED (on the Zero boards) | GP16 |

CAN: 500 kbps, 8 MHz crystal, SPI 4 MHz — the CNF register values that were
verified on this module are transcribed unchanged (`mcp2515.c`, `set_bit_timing`).
Remember the 5 V MCP2515 module needs the MISO divider.

**RX polarity is detected at boot**: GP0 is sampled for ~60 ms and the
majority level is taken as idle; the opposite is dominant. With the LM339
front end from the PHY doc that yields idle-high/dominant-low, and the GPIO
input inverter is switched on so the PIO always sees dominant = high. The
result is reported as `avc_pol` in `GATEWAY_READY` (`"lo"` = dominant pulls
GP0 low) and can be forced with `avc_cfg`.

### Status LED

| Colour | Meaning |
|---|---|
| green breathing | idle, host port open |
| blue breathing | idle, no host |
| red breathing | MCP2515 did not initialise |
| cyan flash | AVC-LAN frame delivered |
| amber flash | CAN request/response |
| violet flash | RS485 traffic |

## Build & flash

Toolchain is expected under `~/.pico-sdk/` (installed 2026-09-16: ARM GCC
14.2.Rel1, pico-sdk 2.2.0, cmake+ninja in a venv) or on `$PATH`/`$PICO_SDK_PATH`.

```bash
./build.sh                                    # → build-waveshare_rp2350_zero/prius_gateway.uf2
PICO_BOARD=waveshare_rp2040_zero ./build.sh   # RP2040-Zero fallback
./test/run.sh                                 # host unit tests
python3 test/pio_sim.py                       # PIO timing simulation (needs a build)
```

Flash: hold BOOT while plugging in (or `tools/gwctl.py bootsel` on a running
v3 gateway — no need to reach the board in the dash), then copy the `.uf2`
to the mounted `RP2350` drive.

In the car the backend owns the port; use the maintenance-window procedure
from `../satellites/README.md` before running `gwctl.py`.

## First power-up in the car (bring-up checklist)

The v2.x receiver sampled bits at a point that does not match the IEBus bit
shape and never consumed ACK slots, and its transmitter emitted 20 µs
dominant pulses for both bit values. v3 implements the IEBus frame exactly
(broadcast bit, parity, ACK slots, 166/20/32 µs timing), so **the decoded
frames may differ from what v2.x reported for the same traffic** — notably
control values, and possibly byte alignment in frames the old decoder
accepted by chance. Host-side pattern matching that was fitted to v2.x
output (`avc_decoder.py`, `avc_state.py`) must be re-validated against a
fresh capture. Procedure:

1. `gwctl.py monitor --hb` — expect `GATEWAY_READY` with `"avc_pol"`, then
   `GW_HB` every second with `avc_lvl` (raw GP0 level; must be 1 when idle
   with the PHY doc wiring) and `avc` (frame counter) climbing when the car
   is awake.
2. If frames are not decoding: `gwctl.py raw --seconds 5 --csv pulses.csv`
   streams every dominant width (positive, µs) and gap (negative). A healthy
   bus shows clusters at ≈20, ≈32 and ≈166 µs. Retune with
   `{"id":0,"d":{"a":"avc_cfg","t1":26,"t0":100,"glitch":6}}` if the
   comparator shifts the widths; `{"a":"avc_err","on":true}` reports every
   parity/length failure with the field it died in.
3. Compare a minute of `id:2` lines with a v2.x recording
   (`cyberpank-prius-gen2-computer/assets/data/avc_lan_messages.ndjson`) and
   refit the host decoders where they differ.
4. TX: `gwctl.py avc 110 440 F 00 5E 29 60 01` (beep). The frame comes back
   on RX tagged `"echo":1`; `"nak":1` on it means no slave acknowledged.

## Protocol: what changed

Everything in `../PROTOCOL.md` and `../gateway/docs/protocol.md` still applies.
Differences and additions:

**AVC-LAN (id 2) frames** — emitted immediately, one line per frame.
`cnt` is no longer present (nothing is aggregated). New optional members:
`"b":1` broadcast frame, `"nak":1` individual frame with an unacknowledged
slot, `"echo":1` the frame is our own transmission seen back on the bus.
TX accepts an optional `"b":true` (default: broadcast when `s` is `FFF`).

**CAN (id 1)** — no passive frames. `req` timeout errors now carry the
expected response id: `{"a":"resp","err":"TIMEOUT","i":"0x7EA","req":"0x7E2"}`.
Subscription timeouts stay silent (counted in `subs`, which now includes
`ok`/`to`/`isotp`). ISO-TP flow control asks for STmin 5 ms, BS 0
(`can_cfg`). A one-shot request queue holds 8 entries; subscriptions are
polled round-robin, one job at a time, 5 ms apart.

Opt-in pass-through (3.1.0, off by default — nothing changes unless sent):
`{"id":1,"d":{"a":"sniff","on":true,"chg":false,"ids":["0x3C8"]}}` drops
subscriptions/queued requests, forces listen-only, accepts every id (or only
`ids`, max 32) and streams each frame as
`{"id":1,"ts":ms,"d":{"a":"sniff","t":µs,"i":"0x3C8","x":"0011…"}}`
(`"e":true` for extended ids). `chg:true` emits a standard-id frame only when
its payload changed. `req`/`sub`/`tx` answer `CAN_SNIFF_ACTIVE` while it is
on; `{"a":"sniff","on":false}` restores the normal filters. While on,
`can_diag` is followed by `{"can_sniff":{"rx","out","ovr"}}`.

**System (id 0)** — `GW_HB` gains `avc` (frames delivered), `avc_err`,
`avc_lvl`, `drop` (lines the host did not read). `GATEWAY_READY` gains
`fw`, `board`, `avc_pol`. New actions:

| Command | Effect |
|---|---|
| `{"a":"stats"}` | all counters (AVC, CAN, RS485, USB) |
| `{"a":"avc_raw","on":true}` | stream raw pulse widths |
| `{"a":"avc_err","on":true}` | report decode errors |
| `{"a":"avc_cfg","pol":"auto\|hi\|lo","t1":26,"t0":100,"tstart":400,"glitch":6}` | polarity / thresholds (µs) |
| `{"a":"can_cfg","stmin":5,"gap":5,"retries":1}` | ISO-TP and scheduler tuning |
| `{"a":"log_rx","on":true}` | v2.x-style `USB_RX` / `RS485_TX` log lines (off by default) |
| `{"a":"reset"}` | watchdog reboot |
| `{"a":"bootsel"}` | reboot into the UF2 bootloader |

Lines the host is not reading (port closed, or its buffer full) are dropped
rather than queued — stale events are worse than missing ones for touch
input — and counted in `drop`.

## Internals worth knowing

* **RX PIO** (4 MHz, 0.5 µs resolution): one word per edge; dominant words
  have bit 31 clear, gap words are the inverted gap count. Debounced ~1 µs.
  The µs conversion constants were calibrated against the simulator
  (`RX_DOM_TO_US`, `RX_GAP_TO_US`).
* **Decoder** (`avclan_codec.c`): symbols GLITCH < 6 µs < ONE < 26 µs < ZERO
  < 100 µs < START < 400 µs < STUCK. A start bit always resynchronises; a
  parity error drops the frame; a frame with no pulse for 600 µs is
  abandoned by the main loop.
* **TX PIO** (1 MHz): DMA-fed, exact 166/19 · 20/19 · 32/7 µs; waits for
  250 µs of bus silence before starting; up to 8 frames queued. ACK slots are
  sent as '1' and left for the slave to stretch.
* **Loop order**: AVC frames out → USB task/commands → CAN engine → RS485 →
  heartbeat/LED. Watchdog 8 s.
* Stack is 4 KB (SCRATCH_Y); every large line buffer is static and only
  touched from the main loop.
