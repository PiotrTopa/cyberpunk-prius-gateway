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
| `110->178 00 21 24 78 X Y X Y` | touch coordinates to nav, 00 00 00 00 = release |
| `1C6->110 00 E0 5D F7 TT` (1 Hz, always) | **outside temperature = TT − 48 °C** — confirmed at 20, 21, 22 °C against the car's screen |
| `110->178 00 56 58 F0 49 3C 44` | display → nav (run 1 only); last byte 44 = same raw outside temp as F7; 49 / 3C unknown (earlier −40 reading of 3C was wrong) |
| `110->FFF 01 01 5B 40` / `01 01 5A 80` | **lights on → display dims / lights off** (mark9: one event for parking→low→high, one at off; map2 same). Fog lights and indicators: nothing on AVC. |
| (audio) | aftermarket radio + its amp on/off button, volume, mode: **no AVC frames** (mark10) — radio/amp not on AVC; amp likely switched by a wire |
| `1C6/110 … 12 01 20 xx`, `E5 01 9C 57 42 4C 41 45 4E` | 60 s periodic re-registration (not user events) |

## Energy monitor

Flow arrows `E4 5F B9 F1 F2 00` (dashboard, directions corrected live by the user on the drive home): F1 ≠ 0 engine running; F2 0x20 battery link with 0x40 = battery → motor and 0x80 = → battery; 0x04 wheel link with 0x10 = → wheels and 0x08 = wheels → (regen). `00 74` = battery → wheels (user-confirmed). Engine combinations (6C 6C / 6C 60 / 6C 0C) not yet confirmed against the screen.

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
