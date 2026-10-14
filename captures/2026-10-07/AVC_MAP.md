# AVC-LAN signal map (Prius Gen2) — confirmed from marked captures 2026-10-07

Source: `map3_marked.ndjson` + `map3_marked.notes.txt` (markers with the user's words), plus
`map2_climate.ndjson`, `run1_nav.ndjson`. Units: 110 = display, 1C6 = climate/info ECU side
(logicals E0 climate, E4/E5 info), 178 = nav (logical 58). Frame text = data bytes.

## Climate status — `1C6->110 00 E0 5D F3 b1 b2 b3 b4 b5 b6` (every 5 s + on change)

| Field | Values seen | Meaning (confirmed by) |
|---|---|---|
| b1 bit 0x80 | C3/A3 vs 43/23/22/41 | **AUTO** (mark3 off/on, mark7 AUTO press) |
| b1 bit 0x40 | C3, 43, 41 | **fresh air** |
| b1 bit 0x20 | 23, A3, 22 | **recirculation** (mark4 recirc press 43→23) |
| b1 bit 0x02 | 22↔20 on A/C button (mark8) | **A/C (compressor) on** |
| b1 bit 0x01 | set with b2 = 00 | **face-only vent** (mark9: face press → 23 00); AUTO states C3/A3 also show face |
| b1 bit 0x08 | AB vs A3 | **rear window heater** (drive home 15:29:38–15:29:55) |
| b1 bit 0x10 | 52 | **front windshield defrost** (2026-10-14 on-screen button; comes with A/C on, AUTO off, fan 2) |
| b2 vent mode | 80 / 40 / 20 / 00 | **face+foot / foot / windscreen+foot / face (with b1 bit 0x01)** (mark7–9) |
| b3 0x04 | one frame after each press | button-accepted pulse |
| b6 >> 5 | 0x20…0xE0 | **fan speed 1…7** (mark7: 1→7 one step each); 0 when the climate system is OFF (mark3: F3 = 41 00 00 00 00 00) |
| b6 bit 0x20 at AUTO | C3 … 20 | (AUTO with fan 1) |

## Climate setpoint — `1C6->110 00 E0 5D F5 NN 38`

°C = 15.5 + 0.5 × NN (07 = 19.0, 0A = 20.5, 0B = 21.0, 0F = 23.0); NN = 39 while the climate system is OFF (mark3).

## Climate touch buttons — `110->1C6 00 25 E0 84 B1 B2 B3 B4 B5 B6`, release = all 00

| Button | Bytes after `84` |
|---|---|
| AUTO | `08 00 00 00 00 00` |
| OFF (climate system off) | `04 00 00 00 00 00` (2026-10-14; F3 → `41 00 00 00 00 00`, fan 0, setpoint F5 = 39; AUTO restores the previous setpoint) |
| recirculation | `02 00 00 00 00 00` |
| windscreen+foot | `00 01 00 00 00 00` |
| foot | `00 02 00 00 00 00` |
| face+foot | `00 04 00 00 00 00` |
| face | `00 08 00 00 00 00` |
| A/C on/off (toggle) | `00 20 00 00 00 00` |
| fan 1 | `00 00 80 00 00 00` |
| fan 2 | `00 00 40 00 00 00` |
| fan 3 | `00 00 20 00 00 00` |
| fan 4 | `00 00 10 00 00 00` |
| fan 5 | `00 00 00 00 08 00` |
| fan 6 | `00 00 00 00 04 00` |
| fan 7 | `00 00 08 00 00 00` |
| temperature up (+0.5 °C, on-screen) | `80 00 00 00 00 00` (2026-10-14; held ≈0.6 s = 2 steps, auto-repeat) |
| temperature down (−0.5 °C, on-screen) | `40 00 00 00 00 00` (2026-10-14) |
| rear window heater toggle (on-screen) | `00 80 00 00 00 00` (2026-10-14; F3 b1 bit 0x08 follows) |
| front windshield blower / defrost toggle (on-screen) | `01 00 00 00 00 00` (2026-10-14; F3 goes `C3 00 … 20` → `52 00 … 40`: AUTO off, **b1 bit 0x10 = front defrost**, A/C on, fan 2; second press returns to AUTO) |

## Engine / energy (provisional)

| Frame | Meaning |
|---|---|
| `1C6->110 00 E4 5F B9 0C 0C 00` / `00 00 00` | **ICE running / stopped** (starts 13:56:28, 13:59:52, 14:01:21; stops 13:56:51.9, 14:00:06.2, 14:01:36.7) |
| `1C6->110 00 E4 5F 97 HH LL` (~1 Hz while running) | power-like value 0x2A3–0x2F9 while running; ramps to 0 after stop |
| `1C6->110 00 E5 5F D8 FF FE 40` / `00 00 40` | follows engine running (~1.5 s lag) |
| `1C6->110 00 E4 5F 96 TT` (1 Hz) | slowly rising counter-like value: 0x4D at first cold start → 0x70 at 14:01 → 0x8C–0xA6 during drive1. NOT coolant (would be 126 °C). Unknown. |
| `1C6->110 00 E4 5F B8 00 00 XX 00 00` | slowly varying (83/82/81) — unknown |

## Display / nav

| Frame | Meaning |
|---|---|
| `110->FFF 12 01 60 XX 05 00 05` | active screen (user-confirmed): 58 nav, 5F energy flow / trip info, 5D climate, 5E audio (radio side not working — stock JBL head unit removed), 56 info |
| `110->178 00 25 58 84 KK 00` | hardware buttons to nav: menu 01, dest 04, map 02, release 00 |
| `110->178 00 21 24 78 X Y X Y` | touch coordinates to nav (calibrated 2026-10-14, see below), 00 00 00 00 = release |
| `1C6->110 00 E0 5D F7 TT` (1 Hz, always) | **outside temperature = TT − 48 °C** — confirmed at 20, 21, 22 °C against the car's screen |
| `110->178 00 56 58 F0 49 3C 44` | display → nav (run 1 only); last byte 44 = same raw outside temp as F7; 49 / 3C unknown (earlier −40 reading of 3C was wrong) |
| `110->FFF 01 01 5B 40` / `01 01 5A 80` | **lights on → display dims / lights off** (mark9: one event for parking→low→high, one at off; map2 same). Fog lights and indicators: nothing on AVC. |
| (audio) | aftermarket radio + its amp on/off button, volume, mode: **no AVC frames** (mark10) — radio/amp not on AVC; amp likely switched by a wire |
| `1C6/110 … 12 01 20 xx`, `E5 01 9C 57 42 4C 41 45 4E` | 60 s periodic re-registration (not user events) |

## Energy monitor — confirmed on the MFD, 2026-10-14 drive (CAN-correlated, user-verified arrows)

`1C6->110 00 E4 5F B9 F1 F2 00`. The MFD draws an MG node; there is no direct engine→battery arrow,
charging is always drawn engine→MG→battery. One bit per arrow:

| Byte | Bit | Arrow on the MFD |
|---|---|---|
| F1 | 0x40 | engine → wheels |
| F1 | 0x08 | engine → MG (generator) |
| F1 | 0x20, 0x04 | link flags (always with the above) |
| F2 | 0x40 | MG → wheels (motor driving) |
| F2 | 0x80 | wheels → MG (regen) |
| F2 | 0x10 | battery → MG (discharging) |
| F2 | 0x08 | MG → battery (charging: generator or regen) |
| F2 | 0x20, 0x04 | link flags (MG–wheels, MG–battery) |

States seen, with the CAN averages of the same seconds (rpm from 0x3C8 bytes 2–3 ÷ 8, ICE flag 0x038,
speed 0x0B4, throttle 0x244, battery current 0x03B; − = charging):

| F1 F2 | MFD arrows (user) | rpm | km/h | throttle | battery A |
|---|---|---|---|---|---|
| 00 00 | none | 0 | 0 | 0 | ≈0 |
| 0C 0C | engine→MG, MG→battery (idling, charging) | 1280 | 0 | 0 | −14 |
| 6C 0C | engine→wheels, engine→MG, MG→battery (steady cruise) | 1540 | 35 | 33 | −18 |
| 6C 6C | engine→wheels, engine→MG, MG→wheels, MG→battery | 1830 | 28 | 60 | −16 |
| 6C 60 | engine→wheels, engine→MG, MG→wheels | 1980 | 30 | 71 | ≈0 |
| 6C 74 | engine→wheels, engine→MG, battery→MG, MG→wheels | 1820 | 21 | 82 | +18…+61 |
| 00 74 | battery→MG, MG→wheels (EV) | 0 | 8 | 21 | +8 |
| 00 AC | wheels→MG, MG→battery (regen) | 250 | 25 | brake | −20…−73 |

Engine running = F1 ≠ 0 (0C included: CAN ICE flag 1, 1280 rpm at standstill). The 2026-10-07 reading
(F2 0x40 = "battery →", 0x08 = "wheels →") was wrong and is superseded; `tools/avc_dashboard.py` implements
this table. Source: `captures/2026-10-14/drive2_emu_avc.ndjson` (AVC) and the local full log with CAN.

### Earlier provisional notes (drive1.ndjson, 14:15–14:17)

| Frame | Observation | Candidate |
|---|---|---|
| `E4 5F B9 F1 F2 00` (F1 = 6C ⇔ engine running. drive3_can vs CAN 0x3C8 rpm, 9 starts/9 stops: ON coincides with engine start (−0.28…+0.06 s, B9 sent ~2 Hz); OFF = engine stops delivering power — rpm still 990–2370, spins down to 0 within 1.1–2.8 s) | F1 ∈ {00, 6C}, F2 ∈ {00, 0C, 6C, 74, AC}; 6C 6C while accelerating with engine, 00 AC cruising/EV, 00 74 decelerating, 00 00 stopped | **energy-flow arrows** (F1 = engine side, F2 = battery/motor/wheels side) |
| `E4 5F 97 HH LL` | 16-bit, ~950–1180 while OBD RPM was 1300–2260; frozen while engine off | engine-related but **not RPM** (drive2_obd) |
| `E5 5F D8 HH LL 40` | signed 16-bit, 0 in EV, +40…+600 with engine pulling, −2 while engine idles parked | engine power / torque-like |
| `E4 5F B4 XX` | 84 parked → 0C at 14:15:16 → 84 at 14:17:24; drive3: 84 → 04 → 0C and back via 04 | **shift position** (84 = P, 04 = R/N in transit, 0C = D) |
| `E5 5F DC 2F NN 80` | NN 94 → 99 during the drive only, constant while parked | **distance counter**, 0.1 km steps? |
| `E4 5F B8 00 00 XX YY 00` | XX & 0x07 + 1 = **battery bars** (confirmed 4→3→4→5 on the drive home); XX bit 0x08 toggles every few s (unknown); YY bit 0x40 = **EV mode active**, bit 0x80 = **EV cancelled** notice (~3.5 s) | confirmed by user live |

## Cross-check vs host repo (cyberpank-prius-gen2-computer), 2026-10-07

- Host AVC decoders were fitted to v2.x gateway output, which is a bit-misaligned re-reading of the
  same traffic (v2 sampler skips/aliases bits, ignores ACK slots). Simulated v2-on-v3 reproduces v2's
  odd addresses: v2 `10C->310` = v3 `1C6->110 00 E4 5F B9` (ICE flag); v2 `040->200 28 00 60xx/C0xx`
  ("button heartbeats") = v3 climate setpoint `E0 5D F5 NN 38`. → host AVC climate / outside-temp /
  target-temp decoders are v2 artefacts; only touch `21 24 78` matches.
- Host's reliable signals come from CAN/OBD: ICE from CAN 0x038, gear from CAN, SOC 0x3C8/0x3CB/0x03B,
  fuel flow 0x520, outside temp OBD PID 0x46. In drive3_can: CAN 0x038 byte1 = 0x1F–0x22 while the AVC
  engine flag is on, 0x00 while off → consistent with the AVC flag. CAN 0x3B6 (host's flow-arrow source)
  is NOT present on the bus the gateway taps.

## Touch panel calibration — measured 2026-10-14 (emu8_release_ack.ndjson, 12 strokes)

Frame `110->178 00 21 24 78 X Y X Y` while the display is on the nav screen (58); bytes 6–7 always
repeat 4–5; ≈10–15 frames/s while the finger is down; `00 00 00 00` on release.

| Touch | X | Y |
|---|---|---|
| top-left corner | 4–13 | 245–255 |
| top-right corner | 246–249 | 249–255 |
| bottom-right corner | 244–246 | 9–19 |
| bottom-left corner | 5–9 | 9–15 |
| drag left → right (middle) | 4 → 248 | ≈135 |
| drag top → bottom (middle) | ≈128 | 253 → 13 |

**X grows left → right, Y grows bottom → top** (origin bottom-left). For the 480×240 native picture
(`cyberpank-prius-gen2-computer/docs/MFD_VIDEO_TIMINGS.md`):

    px = (X − 4) · 480 / 245      (≈ 1.96 px per count)
    py = (255 − Y) · 240 / 246    (≈ 0.98 px per count)

Live viewer: `gateway-rp2350/tools/touch_console.py LOG.ndjson` (tails the emulator log, port 8766).

## Nav protocol additions — 2026-10-14

| Frame | Meaning |
|---|---|
| `110->FFF 12 01 20 XX` (60 s) | re-registration ping; each unit answers `00 01 12 30 XX FF` (nav) / `… 00` (1C6) |
| `110->178 00 12 58 42 02 01` → `178->110 00 58 12 52 02 01` + `178->1FF 58 31 F1 02 00` | screen request / grant; display then switches to screen 58 |
| `110->178 00 12 58 43 02 00` | **screen release request** when leaving the nav screen; display retries 1/s for ≈3.5 s then switches anyway. Reply `00 58 12 53 02 00` (inferred from the 42/52 pair) removes the delay (user: "1s max") |
| `178->1FF 58 31 F1 02 00`, `178->FFF 58 01 DB 00…` (5 s) | sent by the real nav **only while the display is on screen 58**. Sent on another screen the display answers each with `43 02 00` and shows "external device not working correctly" |
| `110->178 00 56 58 8E` → `00 58 56 9E 00 03 01 HH MM SS FF` | time request; HH MM SS BCD (run1: 23:29:25 … 23:31:03) |
| `110->178 00 25 58 80 KK 00 00` | info-screen soft buttons to the nav: 01 maintenance, 08 calendar, 40 language (nav draws the page; ack `00 58 12 50 02 01`) |
| `110->178 00 56 58 F0 49 3C 44` → `178->110 00 58 56 B7 LL` | **display UI language** set by the nav at setup: 06 Dutch, 02 English; display echoes `56 01 B9 LL 00 FF` |
| `110->178 00 32 58 F0 00 00 00 02`, `00 34 58 F0 00 01` | display status notifications; real nav replied `00 58 56 B7 06` to the former, nothing to the latter |

## Remote climate control — verified in the car 2026-10-14

Sending the display's touch frames from the gateway works: `gwctl.py avc 110 1C6 F 00 25 E0 84 B1 B2 B3 B4 B5 B6`
(press) followed ≈150 ms later by the release `… 84 00 00 00 00 00 00`. Verified live (user: "fan started
blowing at 5th stage", then recirculation + fan 7 + A/C off, then AUTO), each confirmed by the next
`E0 5D F3` status. The physical temperature buttons and the physical rear-heater button send no frame (mark1/mark2 of map3,
drive home), but the **on-screen** buttons for both exist and work remotely (`climate_setpoint_touch.ndjson`,
2026-10-14): temp up `80 00 …`, temp down `40 00 …`, rear heater `00 80 …`; press ≈100 ms then release from ONE serial connection, one
step per press (a 0.6 s hold auto-repeats; two separate `gwctl.py avc` invocations are too slow and auto-repeat). Verified: 18.5 → 20.0 °C with three remote presses.
