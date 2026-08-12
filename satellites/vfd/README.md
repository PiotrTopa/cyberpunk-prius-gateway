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
├── main.py             # Main loop, protocol dispatch, standby screen
├── dashboard.py        # Energy dashboard components (port of pygame vfd_satellite)
├── vfd_framebuffer.py  # framebuf wrapper + viper GRAM converter (~25 FPS)
├── gp1294ai.py         # Low-level GP1294AI SPI driver
├── rs485.py            # RS485 half-duplex NDJSON driver (shared with light)
└── README.md           # This file
```

---

## Display Modes

### Dashboard mode (default)

Driven by the host's `VFDDisplayRule` + `vfd_output.py` egress
(`E`/`S`/`C`/`R` messages, see
`cyberpank-prius-gen2-computer/docs/VFD_SATELLITE_PROTOCOL.md`):

```
│   FUEL GAUGE    │  POWER FLOW   │ ENERGY GRAPH  │ POWER BARS │
│  PTR LPG BTT    │  ICE→BAT→MG   │ assist/regen  │  MG  fuel  │
```

Before the first `E` message (or after 10 s without one) a standby
screen with the satellite ID is shown.

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

## Hardware Bring-Up Checklist

1. Flash MicroPython (RPI_PICO build) to the RP2040
2. Upload `main.py`, `dashboard.py`, `vfd_framebuffer.py`, `gp1294ai.py`, `rs485.py`
3. Verify boot banner: `BOOT: Satellite VFD (ID=110) starting...`
4. Standby screen appears ("PRIUS VFD SATELLITE / ID 110 WAITING")
5. Send a canvas test over the bus:
   `{"id":110,"d":{"t":"T","s":"TEST","x":100,"y":20,"clr":true}}`
6. Send demo energy data and confirm dashboard renders:
   `{"id":110,"d":{"t":"E","mg":0.4,"fl":0.3,"br":0,"spd":0.5,"soc":0.6,"ptr":25,"lpg":40,"ice":true}}`
7. Confirm `VFD_READY` and periodic `STATUS` on the bus
