# Nav ECU (AVC-LAN 178) emulation spec — draft from captures 2026-10-07

Source captures (gateway v3.0.0, pol=lo, H1 swapped to correct orientation):

| File | Content |
|---|---|
| `run1_nav.ndjson` | cold bus → READY → 4 screen corners ×1, menu ×7, dest ×9, map ×11 → off. Nav connected. 1009 frames, 0 decode errors, 0 NAK, 0 USB drops. |
| `run2_nonav.ndjson` | same routine, nav computer unplugged. 979 frames, 0 errors, 0 NAK. |
| `test0b_raw.csv` | raw pulse widths: dominant 20 µs ("1") / 32–34 µs ("0") / 170 µs (start); bit period ≈39 µs. |
| `run1_nav_attempt1_noframes.ndjson`, `run2_nonav_prewiring.ndjson`, `test0_raw.csv` | failed / pre-fix attempts (floating ground, swapped H1); kept for reference only. |

Frame notation: `master->slave cCTRL data…` (hex). Data byte 0 is `00` for unicast, then
`<from-logical> <to-logical> <opcode> args…`. Logical IDs seen: **58 = navigation**,
24 / 85 = further nav-side logicals, 12 = comm control (110), 01 = system/broadcast,
56 / 5F / 5D / 32 / 34 / 6E = display-side functions, 25 = hardware switches,
21 = touch panel, E0/E4/E5 = 1C6 audio logicals. Meanings are provisional.

Physical units: **110** = display (EMV), **178** = nav ECU, **1C6** = audio unit.

## What disappears without the nav (run 1 vs run 2)

- Everything from/to 178 (130 frames sent by 178, 122 sent to it by 110).
- 110 does **not** probe for 178 at all in run 2: 0 frames addressed to 178, 0 NAKs.
  The display only talks to 178 after 178 answers the startup roll call → the roll-call
  reply is the gate for everything else.
- Hardware buttons (`25 58 84 xx`) and touch coordinates (`21 24 78 …`) are sent **to 178**
  in run 1; in run 2 they are not sent at all.
- 110's "active source" broadcast `12 01 60 58 01 00 05` (nav = 58) becomes
  `12 01 60 56 …` then `12 01 60 5F …` (display falls back to its own/audio screens), and
  `56 01 B9 06` becomes `56 01 B9 02`. 1C6's ~1 Hz audio status stream to the display
  (`00 E4 5F B9/B8/B4/96…`) is present in **both** runs at the same rate; the only new
  1C6 frame in run 2 is `00 E4 5F 97 …` (56×), plausibly because the display now shows audio.

## What the emulator must do (as master 178)

### 1. Startup roll call (t = 0–1.2 s after bus wake) — must answer within ~5–10 ms

| Trigger from 110 | 178 reply (run 1) |
|---|---|
| `110->FFF 12 01 00` (B) | `178->110 00 01 12 10 58 24 85` — "I host logicals 58, 24, 85" |
| `110->FFF 12 01 01` (B) | `178->110 00 01 12 12 58 28 29 32 60 74 A4 56` |
| `110->178 00 12 58 8F` | `178->110 00 58 12 9F 02 F9 D1 3D 0A 58 A6 E4 80 8C` — ID/version blob, replay verbatim |
| `110->178 00 12 01 02 17 80 11 03 11 07` | `178->110 00 01 12 12 27 58 40 64 62 61 55 6E 6D` |
| `110->178 00 12 01 02 17 81 11 06 11 07 11 08` | `178->110 00 01 12 12 34 A2 58 43 63 65 44 45 E0` |
| `110->178 00 12 01 02 11 00 17 82 1C 68` | (no direct reply; 178 starts the burst below) |

### 2. Initial burst right after the roll call (t ≈ 1.21–1.24 s)

```
178->110 00 58 32 E0
178->1C6 00 85 E0 E0          1C6 replies 00 E0 85 F0 00 71
178->110 00 58 56 E0
178->110 00 58 34 E0
178->1C6 00 85 E0 E4          1C6 replies 00 E0 85 F4 C3 00 00 00 00 20
178->1C6 00 85 E0 E6          1C6 replies 00 E0 85 F6 0B 38
```
Then `178->110 00 58 {32,56,34} E0` repeated every 300 ms until 110 answers (≈1.5–2.2 s).
The 85↔E0 link is nav ↔ audio (likely the voice-guidance channel). Whether the display
needs it is open: in run 2 the display itself runs the same 5D↔E0 exchange with 1C6.

### 3. Requests from 110 that need replies

| 110 sends | 178 replies |
|---|---|
| `00 01 07` (B, once) | `178->110 00 01 00 17` |
| `00 32 58 E0` | `00 58 32 F0 C9 00 00 01` |
| `00 6E 58 E0` | `00 58 6E F0 C9 00 00 01` |
| `00 56 58 F0 49 3C 44` | `00 58 56 B7 06` |
| `00 56 58 8E` (every 5 s) | `00 58 56 9E 00 03 01 23 31 SS FF` — SS is BCD and goes up by 5 every 5 s (03, 08, 13 … 53): looks like a seconds-of-clock field (23:31:SS?). Must be generated, not replayed. |
| `00 34 58 F0 00 01`, `00 32 58 F0 00 00 00 02` | no reply seen (command/ack only) |
| `00 12 58 42 02 01` | `00 58 12 52 02 01` + broadcast `178->1FF 58 31 F1 02 00` |

### 4. Periodic, unsolicited (steady state)

| Period | Frame |
|---|---|
| 5 s | `178->FFF 58 01 DB 00 00 00 00 00 00` (B) — heartbeat |
| 5 s | `178->1FF 58 31 F1 02 00` (B), 0.6 s before the DB heartbeat |

### 5. Input handling (what the RPi actually wants)

- Hardware switches: `110->178 00 25 58 84 KK 00`, release = `KK=00`.
  Measured: **menu = 01** (7 presses), **dest = 04** (9), **map = 02** (10 seen vs 11 pressed —
  one press may not have registered).
  Nav answers a press with `00 58 12 50 02 01` → 110 `00 12 58 42 02 01` →
  nav `00 58 12 52 02 01` + `1FF 58 31 F1 02 00` (a screen-ownership/refresh handshake).
- Touch: `110->178 00 21 24 78 X Y X Y` (17 frames for the 4 corners), `00 00 00 00` = release.
  Coordinates are 1 byte each.

## Open questions → next on-site test

1. **Minimum viable emulation:** transmit only §1 + §4 (roll call + heartbeats) with the nav
   unplugged, and check that the display keeps the `12 01 60 58` source and stops falling
   back to audio. Then add §2/§3 until it stays put.
2. Reply latency: 178 answers in 4–8 ms. Host round trip over USB is ~1.6 ms, so the RPi can
   answer through the gateway; if not, the roll call answers move into gateway firmware.
3. Meaning of the `9E … 23 31 SS` clock field and the `9F` ID blob (replaying them should work).
4. Whether `85↔E0` (nav ↔ audio) is required, or only needed for voice guidance.
5. Confirm map = 02 count (10 vs 11) with a dedicated button-only capture.

## On-car emulation attempts (2026-10-07, 13:23–13:37 CEST)

| Log | H1 orientation | Result |
|---|---|---|
| `emu1.ndjson` | RX-correct | no bus traffic seen (gateway tap issue during that start; user error) |
| `emu2.ndjson` | RX-correct | roll call received and answered within ms (`tx=3`), but **echo=0**; display ignored us, kept falling back to audio |
| `emu3_blind.ndjson` | original (TX-correct) | `--blind` timer mode, 253 frames sent: **display believed the nav was present** but behaved erratically (unsolicited answers, collisions, unACKed queries) |

Root cause: on this PHY board **TX and RX have opposite polarity relative to H1**. Raw RX of our
own TX (car off) shows only 2–4 µs spikes on each TX *release* edge (spacing 27/39/51 µs =
release-edge model), i.e. the receiver sees our dominant as reversed. Bench self-echo passed only
because AUTO polarity latched onto the comparator's offset and adopted the reversed sense.
With H1 RX-correct we hear the car but the car can't hear us; with H1 TX-correct the car hears us
but we are deaf (the comparator idles at the same level as a reversed dominant).

Full emulation needs RX and TX agreeing: cross R1/R2 (comparator inputs) or R7/R8 (TX legs) on
the board, or an external receiver on GP0. Firmware also needs: fixed `pol=lo`, slave ACK for
178 (display's unicasts are NAKed otherwise), and ideally the roll-call replies in firmware.
