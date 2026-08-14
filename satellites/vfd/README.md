# Satellite: VFD Display

**Device ID:** `110`
**MCU:** RP2040 (MicroPython)
**Role:** 256×48 GP1294AI VFD renderer — energy dashboard + free-form canvas.

Combines the light-satellite RS485 stack with the GP1294AI driver from
[rp2040-05-fluorite-vfd-controller](https://github.com/PiotrTopa/rp2040-05-fluorite-vfd-controller).
The dashboard rendering is a MicroPython port of the pygame `vfd_satellite`
simulator from `cyberpank-prius-gen2-computer`.

---

## Hardware Overview

| Subsystem | IC / Module | Notes |
|:----------|:------------|:------|
| Display | GP1294AI VFD, 256×48 px | SPI Mode 3, LSB-first (bit-reversed in SW) |
| Communication | MAX485 | Half-duplex RS485, UART1 — same wiring as light satellite |

### Pin Map

| Pin | Direction | Function | Logic |
|:----|:----------|:---------|:------|
| GP0 | OUT | VFD FIL_EN (filament enable) | Active High |
| GP1 | OUT | VFD CS# | Active Low |
| GP2 | OUT | VFD SCK (SPI0) | — |
| GP3 | OUT | VFD MOSI (SPI0) | — |
| GP4 | OUT | VFD RST# | Active Low |
| GP8 | OUT | RS485 TX (UART1) | 3.3V |
| GP9 | IN | RS485 RX (UART1) | 3.3V (via divider) |
| GP10 | OUT | RS485 DE+RE | HIGH=TX, LOW=RX |
| GP25 | OUT | Heartbeat LED (Pico; NC on RP2040-Zero) | — |

Power: 5V (VBUS) + GND for the VFD module.

---

## File Structure

```
satellites/vfd/
├── main.py             # Main loop, protocol dispatch, splash + idle screens
├── dashboard.py        # Energy dashboard components (port of pygame vfd_satellite)
├── vfd_framebuffer.py  # framebuf wrapper + viper GRAM converter
├── gp1294ai.py         # Low-level GP1294AI SPI driver
├── rs485.py -> ../common/rs485.py   # symlink: shared bus driver
├── ota.py   -> ../common/ota.py     # symlink: shared OTA module
└── README.md           # This file
```

`rs485.py` and `ota.py` are symlinks into `../common/` — edit them there, never
in place. Both `mpremote fs cp` and `satellite_ota.py sync` follow the links.

---

## Display Modes

### Dashboard mode (default)

Driven by the host's `VFDDisplayRule` + `vfd_output.py` egress
(`E`/`S`/`C`/`R`/`K` messages, see
`cyberpank-prius-gen2-computer/docs/VFD_SATELLITE_PROTOCOL.md`):

```
│   FUEL GAUGE    │  POWER FLOW   │ ENERGY GRAPH  │ POWER BARS │
│  PTR LPG BTT    │  ICE→BAT→MG   │ assist/regen  │  MG  fuel  │
```

What is on screen in dashboard mode depends on **READY** (`rdy` in the `S`
message), not on gear:

| When | Screen | Brightness |
|:-----|:-------|:-----------|
| First 5 s after boot (`SPLASH_DURATION_MS`) | Boot splash — 2×-scaled `> Cyber Security` prompt | full |
| READY on | Energy dashboard | full |
| READY off (parked) | Idle screen | `IDLE_FADE_PCT` = 35 % |

Brightness ramps between the two levels at `FADE_STEP` = 5 %-points per frame
(~1 s at 20 FPS). `IDLE_MODE` selects the idle screen:

- `"prompt"` (default) — `security@prius:/var/logs$` in the top-left, 8×8 font
- `"clock"` — small date + time, top-right
- `"dark"` — fades to 0 and blanks the framebuffer

Canvas content (`T`/`D`/`B`) always jumps straight back to full brightness.

#### Host → satellite message types

Every frame is `{"id":110,"d":{"t":<type>,...}}`. Field-level definitions live in
`cyberpank-prius-gen2-computer/docs/VFD_SATELLITE_PROTOCOL.md`.

| `t` | Purpose | Example payload |
|:----|:--------|:----------------|
| `E` | Energy data — drives the dashboard | `{"t":"E","mg":0.4,"fl":0.3,"br":0,"spd":0.5,"soc":0.6,"ptr":25,"lpg":40,"ice":true}` |
| `S` | Vehicle state; `rdy` selects dashboard vs idle | `{"t":"S","rdy":true,"gear":"P","fuel":"OFF"}` |
| `C` | Config; returns brightness 0–100 % | `{"t":"C","bri":80}` |
| `R` | Reset — clear screen, back to dashboard mode | `{"t":"R"}` |
| `K` | Clock sync for the `"clock"` idle screen | `{"t":"K","y":2026,"mo":8,"d":14,"h":19,"mi":30,"s":0}` |
| `T` `D` `B` | Canvas text / draw ops / bitmap (below) | — |

A bare `{"cmd":"STATUS"}` (no `t`) triggers an immediate status reply.

### Canvas mode ("show anything")

Any `T`/`D`/`B` message switches to canvas mode; an `R` message returns
to the dashboard. The framebuffer persists between messages, so content
can be built up incrementally.

#### `T` — Text
```json
{"id":110,"d":{"t":"T","x":10,"y":10,"s":"Hello VFD!","clr":true}}
{"id":110,"d":{"t":"T","x":0,"y":0,"s":["line 1","line 2"],"f":5}}
```
- `s`: string or list of lines; `f`: font 8 (default, 8×8) or 5 (3×5 mini)
- `c`: color 1/0; `clr`: clear screen first

#### `D` — Draw primitives
```json
{"id":110,"d":{"t":"D","clr":true,"ops":[
  ["rect",0,0,256,48,1],
  ["line",0,0,255,47,1],
  ["fcirc",128,24,10,1],
  ["txt",8,8,"CANVAS",1]
]}}
```
Ops: `["fill",c]`, `["px",x,y,c]`, `["line",x0,y0,x1,y1,c]`,
`["hl",x,y,w,c]`, `["vl",x,y,h,c]`, `["rect",x,y,w,h,c]`,
`["frect",x,y,w,h,c]`, `["circ",cx,cy,r,c]`, `["fcirc",cx,cy,r,c]`,
`["txt",x,y,s,c]`. Add `"ack":true` for an OK response with op count.

#### `B` — Bitmap
```json
{"id":110,"d":{"t":"B","x":0,"y":0,"w":16,"h":16,"b64":"<base64 1bpp MSB-first rows>"}}
```

---

## Responses (Satellite → Host)

On boot:
```json
{"id":110,"d":{"msg":"VFD_READY","ver":"1.0.0","res":"256x48"}}
```

Status broadcast (every 5 s, also on `{"cmd":"STATUS"}` request):
```json
{"id":110,"d":{"cmd":"STATUS","mode":"dash","bri":100,"frames":12345,"ver":"1.0.0"}}
```

---

## Performance

- Framebuffer → GRAM conversion + bit reversal is a `@micropython.viper`
  routine (~1 ms vs ~150 ms in pure Python).
- SPI at 4 MHz pushes the 4 KB frame in ~8 ms → 20 FPS render loop with
  headroom for RS485 handling (measured ~21 FPS max on device; loop set to 20 FPS).

---

## Updating firmware

Normal path is OTA over RS485 — no physical access needed. Inside a maintenance
window (see [`../README.md`](../README.md#maintenance-window)):

```bash
tools/satellite_ota.py --port "$GW" --dev 110 sync satellites/vfd/
```

This sends only changed `.py` files (symlinked `rs485.py` / `ota.py` included),
commits atomically, reboots the satellite and re-verifies the manifest.
A full-file push is ~700–750 B/s, so a 3.7 KB file takes ~5 s.

Over USB instead (board on a bench machine, e.g. nokia1 `/dev/ttyACM0`):

```bash
python3 -m mpremote connect /dev/ttyACM0 fs cp main.py :main.py
python3 -m mpremote connect /dev/ttyACM0 reset
```

A bare `mpremote repl` needs a TTY and fails over ssh — use `fs cp`/`run`/`reset`,
or pyserial with `\x03` to interrupt `main.py` and `\x04` to soft-reboot it.
`exec`/`run` interrupt the running `main.py`, so soft-reboot afterwards to
resume it. When pasting into the REPL, send single-line statements or one
`exec("...\n...")` string — a multi-line block leaves the REPL in `...`
continuation mode and silently swallows what follows.

---

## Hardware Bring-Up Checklist

1. Flash MicroPython (RPI_PICO build) to the RP2040
2. Upload `main.py`, `dashboard.py`, `vfd_framebuffer.py`, `gp1294ai.py`,
   `rs485.py`, `ota.py`
3. Verify the boot banner on USB:
   ```
   BOOT: Satellite VFD (ID=110) starting...
     RS485: UART1 TX=GP8 RX=GP9 DE=GP10 @ 115200
     VFD:   SPI0 SCK=GP2 MOSI=GP3 CS=GP1 RST=GP4 FIL=GP0
   RS485: Ready
   VFD: Initialized
   READY: Satellite VFD (ID=110) running
   ```
4. Boot splash (`> Cyber Security`) shows for 5 s, then the idle prompt
   `security@prius:/var/logs$` at 35 % brightness
5. Confirm `VFD_READY` and a `STATUS` broadcast every 5 s on the bus
6. Send a canvas test over the bus:
   `{"id":110,"d":{"t":"T","s":"TEST","x":100,"y":20,"clr":true}}`
7. Enter READY and send demo energy data, confirm the dashboard renders:
   ```json
   {"id":110,"d":{"t":"S","rdy":true,"gear":"P","fuel":"OFF"}}
   {"id":110,"d":{"t":"E","mg":0.4,"fl":0.3,"br":0,"spd":0.5,"soc":0.6,"ptr":25,"lpg":40,"ice":true}}
   ```
8. Confirm the backend sees it: node `110` `online: true` with `last_seen`
   advancing every ~5 s in `/api/v1/state`
