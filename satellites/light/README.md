# Satellite: Light Controller

**Device ID:** `106`  
**MCU:** RP2040 (MicroPython)  
**Role:** DRL & BiLED headlight control via relays and PWM with current monitoring.

---

## Hardware Overview

| Subsystem | IC / Module | Channels | Notes |
|:----------|:------------|:---------|:------|
| PWM Power | BTS7960 (HW-039) | 2 | Split half-bridge, ~43A per channel |
| Relays | HW-316 | 4 | Active Low, optoisolated |
| Current Sense | BTS7960 IS pin | 2 | Via modified shunt (R_eq = 1803Ω) |
| Communication | MAX485 | 1 | Half-duplex RS485, UART1 |

### Pin Map

| Pin | Direction | Function | Logic |
|:----|:----------|:---------|:------|
| GP0 | OUT | PWM_CH1 (Right BiLED) | Active High |
| GP1 | OUT | PWM_CH2 (Left BiLED) | Active High |
| GP2 | OUT | RELAY_IN1 | **Active Low** |
| GP3 | OUT | RELAY_IN2 | **Active Low** |
| GP4 | OUT | RELAY_IN3 | **Active Low** |
| GP5 | OUT | RELAY_IN4 | **Active Low** |
| GP6 | OUT | PWM_ENABLE (L_EN+R_EN) | Active High |
| GP8 | OUT | RS485 TX (UART1) | 3.3V |
| GP9 | IN | RS485 RX (UART1) | 3.3V (via divider) |
| GP14 | OUT | RS485 DE+RE | HIGH=TX, LOW=RX |
| GP26 | IN | ADC CH1 current sense | Analog |
| GP27 | IN | ADC CH2 current sense | Analog |

---

## File Structure

```
satellites/light/
├── main.py       # Main satellite logic, command processor, main loop
├── easing.py     # PWM transition engine with easing functions
├── rs485.py -> ../common/rs485.py   # symlink: shared bus driver
├── ota.py   -> ../common/ota.py     # symlink: shared OTA module
└── README.md     # This file
```

`rs485.py` and `ota.py` are symlinks into `../common/` — edit them there, never
in place.

## Updating firmware

OTA over RS485, inside a maintenance window (see [`../README.md`](../README.md)):

```bash
tools/satellite_ota.py --port "$GW" --dev 106 sync satellites/light/
```

---

## RS485 Protocol (ID = 106)

All commands are sent as NDJSON: `{"id": 7, "d": { ... }}`

### Commands (Host → Satellite)

#### RELAY — Toggle a relay
```json
{"id":106, "d":{"cmd":"RELAY", "ch":1, "val":true}}
```
- `ch`: 1–4
- `val`: `true` = ON, `false` = OFF

#### PWM — Set BiLED brightness
```json
{"id":106, "d":{"cmd":"PWM", "ch":1, "val":80}}
{"id":106, "d":{"cmd":"PWM", "ch":1, "val":80, "dur":1000, "ease":"in_out"}}
```
- `ch`: 1 (right) or 2 (left)
- `val`: 0–100 (%)
- `dur`: *(optional)* transition duration in ms
- `ease`: *(optional)* easing function, default `"linear"`

Available easing functions:
| Name | Curve |
|:-----|:------|
| `linear` | Constant speed |
| `in` | Quadratic ease-in (slow start) |
| `out` | Quadratic ease-out (slow end) |
| `in_out` | Quadratic ease-in-out |
| `in_cubic` | Cubic ease-in |
| `out_cubic` | Cubic ease-out |
| `in_out_cubic` | Cubic ease-in-out |

#### PWM_EN — Enable/disable power stage
```json
{"id":106, "d":{"cmd":"PWM_EN", "val":true}}
```
Must be enabled before PWM has any effect on load. Acts as hardware safety gate.

#### STATUS — Request current state
```json
{"id":106, "d":{"cmd":"STATUS"}}
```

#### STOP — Emergency stop all outputs
```json
{"id":106, "d":{"cmd":"STOP"}}
```

#### OCP_RESET — Reset over-current protection flag
```json
{"id":106, "d":{"cmd":"OCP_RESET"}}
```
After OCP trip, PWM_EN remains OFF. Send `OCP_RESET`, then `PWM_EN` to resume.

#### TEST — Hardware verification
```json
{"id":106, "d":{"cmd":"TEST", "what":"relay"}}
{"id":106, "d":{"cmd":"TEST", "what":"pwm"}}
{"id":106, "d":{"cmd":"TEST", "what":"adc"}}
{"id":106, "d":{"cmd":"TEST", "what":"all"}}
```

### Responses (Satellite → Host)

#### Command ACK
```json
{"id":106, "d":{"res":"OK", "cmd":"PWM", "ch":1, "val":80, "dur":1000, "ease":"in_out"}}
```

#### Status Broadcast (every 5s)
```json
{"id":106, "d":{
  "cmd": "STATUS",
  "pwm_en": true,
  "pwm": [80.0, 50.0],
  "relay": [true, false, false, false],
  "amps": [2.15, 1.03],
  "ocp": false,
  "easing": [false, true]
}}
```

#### Over-Current Event
```json
{"id":106, "d":{"evt":"OCP", "amps":[15.2, 0.5]}}
```

---

## Hardware Bring-Up Checklist

### 1. Power & Basic Boot
- [ ] Flash MicroPython to RP2040
- [ ] Upload `main.py`, `easing.py`, `rs485.py`, `ota.py`
- [ ] Verify serial output: `BOOT: Satellite Light (ID=106) starting...`
- [ ] Confirm onboard LED blinks (heartbeat)

### 2. Relays
- [ ] Send `{"id":106, "d":{"cmd":"TEST", "what":"relay"}}`
- [ ] Listen for relay clicks (R1→R2→R3→R4)
- [ ] Verify individual: `{"id":106, "d":{"cmd":"RELAY", "ch":1, "val":true}}`
- [ ] Confirm Active Low logic: relay ON when pin reads LOW

### 3. PWM + BiLED
- [ ] Send `{"id":106, "d":{"cmd":"PWM_EN", "val":true}}` — enable power stage
- [ ] Send `{"id":106, "d":{"cmd":"PWM", "ch":1, "val":10}}` — dim right
- [ ] Gradually increase to verify smooth control
- [ ] Test easing: `{"id":106, "d":{"cmd":"PWM", "ch":1, "val":100, "dur":2000, "ease":"in_out"}}`
- [ ] Send `{"id":106, "d":{"cmd":"PWM_EN", "val":false}}` — verify hard stop

### 4. Current Sensing
- [ ] With load connected, send `{"id":106, "d":{"cmd":"TEST", "what":"adc"}}`
- [ ] Verify readings correlate with known load
- [ ] Test OCP: ramp duty while monitoring `amps` in STATUS broadcasts

### 5. RS485 Communication
- [ ] Verify two-way communication with Gateway
- [ ] Check STATUS broadcasts arrive every ~5s
- [ ] Send rapid commands, verify no dropped messages

---

## Current Measurement Formula

$$I_{load} = ADC_{val} \cdot 0.0038 \text{ [A]}$$

Where $ADC_{val}$ is the 12-bit ADC reading (0–4095). Max measurable current ≈ 15.55 A.

---

## Safety Features

1. **Boot-safe relays**: All relay pins initialized HIGH (OFF) before anything else
2. **PWM Enable gate**: Power stage disabled by default, explicit enable required
3. **Over-Current Protection**: Automatic PWM shutdown at >14A, requires manual reset
4. **Emergency Stop**: `STOP` command kills all outputs instantly
