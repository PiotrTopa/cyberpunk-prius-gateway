# Capture log — 2026-10-14 (car + scope, gateway fw 3.1.0 → 3.2.0)

All times CEST. Emulator logs = `gateway-rp2350/tools/nav_emu.py` line format (every gateway line
with `ht`/`raw`/`obj`, plus `{"tx":…}` for our transmissions and `{"note":…}` for the emulator's
own messages). "User said" = operator's words, verbatim.

## Board state at start (user said)

"back in the car, bleeder resistor installed" — 12 kΩ from BC327 collector (D1 anode) to GND added
at home; bias 2 MΩ 3V3 → LM339 pin 6; comparator inputs crossed (H1 left/T → pin 7 IN+, H1 right →
pin 6 IN−). First test: receiver pinned high, no pulses (wiring contact); after "ther ewas wiring
problem" fixed: RX decoded car frames with `pol lo` (brown on T), own TX invisible in loopback.

## Scope / meter facts (user's readings, scope 10x probes, GND = LM339 pin 12)

| # | Measurement | Result |
|---|---|---|
| M1 | H1 lines, car on | brown (left) 2.45 V, white (right) 2.75 V mean with traffic; idle gap ≈0.1 V white above brown ("idle differntail is closet to 0.1V"); dominant: brown −0.5 V, white +0.1 V → **white = Data+** |
| M2 | pin 7 vs pin 6 | idle pin 7 > pin 6 ≈100 mV; dominant pin 7 −0.5 V (pin 7 ← brown), pin 6 +0.1 V (pin 6 ← white) |
| M2b | pin 6 − white / pin 7 − brown | −100 mV / +50 mV raw; scope CH2 reads +50 mV vs CH1 on the same point → corrected −150 / ≈0 mV |
| — | scope absolute | 5 V reads 5.53, 3V3 reads 3.53 (≈6 % gain), zero exact |
| — | parts | R1 = R2 = **10 kΩ** (doc said 100 k); **470 kΩ feedback pin 1 → pin 7** ("it was there on this board revision the whole time"); H1 left→pin 7 9.62 k, right→pin 6 9.87 k |
| — | bare board, H1 unplugged | pin 6 **0.556 V** (expected ≈2.7 V), pin 7 3.36 V, pin 1 3.51 V |
| — | meter, unpowered | pin 6 → GND **208 kΩ**, → 3V3 1.82 MΩ, → 5 V 10 MΩ; stays 208 kΩ with the LM339 **out of its socket** |
| — | found | a **220 kΩ resistor pin 6 → GND** on the board ("red red black gold, i think, but its covered in polish nail") |

Conclusion (arithmetic with 10 k inputs, car common mode ≈2.6 V): the 2 MΩ bias adds +3.5 mV (nothing);
the 220 k pull-down pulls pin 6 ≈110 mV below its line; the 470 k feedback adds +17 mV (out high) /
−52 mV (out low) on pin 7. The receiver's idle state was set by those two parts, never by the bias.
This explains 10-12 completely (no Q2 leak; the 12 k bleeder is harmless and stays).

## Fix applied in the car (user)

- 220 kΩ: GND end lifted and moved to **LM339 pin 3 (V+ = 5 V)** → pin 6 idles +105 mV above its line
  in the car, +215 mV on the bench ("pin 6 open to GND 7MOh, 189kOhm to 5V").
- 470 kΩ feedback **cut**.
- Comparator cross kept (T → pin 7), white on T (left), brown on right, firmware `pol hi`.

Acceptance, car on: loopback `0,1,0` ×2 (one sample hit a bus frame), 130 frames / 0 errors, 3 TX →
3 echoes. **RX and TX agree on one orientation for the first time.**

## Emulator cold starts (files `emuN_*.ndjson` + `.stdout`)

| File | Time | Gateway / emulator | Result (user said) |
|---|---|---|---|
| `emu1_cold.ndjson` | 13:42–13:45 | fw 3.1.0, `--pol hi` | roll-call answer at 8 ms NAKed (collides with climate ECU's answer at ~2.5 ms start); "still says external sysem not connected" |
| `emu2_cold_retry.ndjson` | 13:45–13:50 | + NAK retry | registered (no "not connected") but no setup dialogue; "sort of buggy… cannot switch to NAV… battery bars were not visible for th first 2 mins… additional items in the menu… are not shown" |
| `emu3_cold_delay12.ndjson` | 13:50–13:54 | `--rc-delay 12` (answer after the climate ECU, clean ACK) | "same as last time" |
| `emu4_cold_fwauto.ndjson` | 13:55–13:59 | **fw 3.2.0 auto-reply** (gateway answers 12 01 00/12 01 01 itself, 5 ms, before the climate ECU — identical to the real nav) | "battery bars late, no reaction for menu buttons, no additional items, no 'External system not connecteD'" |
| `emu5_cold_fwauto_raw.ndjson` | 14:01–14:04 | + raw pulse log | **464 header-only frames 110→178 (28 bits, abort at the address ACK slot) every 25 ms from +1.12 s** — the display calls the nav, we never ACK |
| `emu6_cold_fwauto_ack.ndjson` | 14:06–14:15 | **fw 3.2.0 ACK** (`avc_cfg ack:"178"`) + auto-reply | full setup dialogue as in run1; "It thinks the nav is connectd… switch language to something strange (TAAL)… menu, desc, map buttons witch to external display… there was a memont when it said somehting doesnt work corclty on the extenral device"; display asked `00 12 58 43 02 00` ×110 (1/s) after every one of our unconditional `58 31 F1 02 00` broadcasts |
| `emu7_cold_screenstate.ndjson` | 14:15–14:19 | broadcasts only while display screen = 58 | "it works… When i am swithcing to nav, its instinat… when i click info it takes it 5s" — display sends `43 02 00` on leaving the nav screen, retries 1/s, gives up after ≈3.5 s |
| `emu8_release_ack.ndjson` | 14:19– | + reply `00 58 12 53 02 00` to `43 02 00` (inferred), + reply to `12 01 20 XX`; **touch calibration** strokes from 14:25 | "much better, 1s max. switching back"; TAAL button "lights up for 3s then goes off, nothing happens" (display asks `00 25 58 80 40 00 00`, reply unknown); touch: corners, two drags — see AVC_MAP.md |

Display UI language after our emulator: Dutch ("verbruik, actueel, verbinding"). User: "i dont really care
that much… I would rather spend time now on figuring out the screen touch button calibration".

## Afternoon: climate remote control, real nav re-observed, language (files as named)

| File | Time | What | Result (user said) |
|---|---|---|---|
| `climate_setpoint_touch.ndjson`, `climate_windshield_touch.ndjson`, `climate_off_touch.ndjson` | 14:37–14:42 | on-screen temp up/down, rear heater, front defrost, OFF | codes in AVC_MAP; "fan started blowing at 5th stage"; "says 20 and auto" |
| `emu9_language_check.ndjson` | 14:43 | emulator announced on the live bus after the user set GB with no nav | "instancly switched to Dutch, but nav works" |
| `realnav_language_part0_killed.ndjson`, `realnav_language.ndjson` | 14:45–14:58 | real nav reconnected (video cables already cut); recorder killed once by a concurrent port access | "started in dutch"; "clicked blindly on the screen and it is on english"; items: "maintanence, INFO to get back, Telephone (… MFD bultin), Calendar, language" |
| `emu10_cold_english.ndjson` | 15:00 | emulator with today's identification bytes | "Dutc"; blind touch on the language page: "no, still dutch" |
| `realnav_full.ndjson` | 15:06–15:08 | real nav cold start, end to end, gateway passive | "booted duch" → "it now just magically switch to english without me touching anything" = nav ready 20 s after boot, re-setup, `B7 02` |
| `emu11_cold_lang02.ndjson` | 15:09 | emulator with `B7 02` | **"english!"** |

Decision: nav computer can be removed (user: "Can i remove the nav computer now?"); nothing on the bus
depends on 178 besides the display dialogue and the climate subscriptions, both emulated.

## Drive home 15:23–16:05 (`drive2_emu_avc.ndjson`; full AVC+CAN log `drive2_emu_can.ndjson.gz` local only, 151 MB)

Emulator (`--fw-auto --fw-ack --can-sniff`, English) + dashboard tailing the log. User: "just record the
drive". Live corrections of the energy monitor against the MFD: "engine -> wheels arrow on the graph is
missing"; "when engine is on, wheels arrow shows reversed"; the steady-cruise state "does not show any
arrows from / to electric engine"; two MFD states had merged on the dashboard; final wording: "engine >
wheels, engine > mg, mg > wheel, mg > battery" (6C 6C) and "engine > wheel, engine > mg, mg > battery"
(6C 0C, just before the 16:00 engine stop); "loos good". CAN correlation table and bit model in AVC_MAP.md.
35,227 AVC frames (273 our echoes, 0 NAK), 4.15 M CAN frames. Head unit: Android 9 "android-trunk-p0",
model B9520B, kernel 4.14.116, build-number tap does nothing; 70mai hotspot `70mai_S410_814b` (pw given),
port scan not finished — next time, with laptop internet access planned.

## Evening: the MFD Pi (user said)

The Pi plugged into the laptop never enumerated (no USB event at all, two cables). Board identified as a
**Pi Zero v1.3** ("its 1.3V ubfortunatelly"), the Zero 2 W is dead ("i bjrned it bybmistake") and
unobtainable (Oct 2026 shortage). Decision: "so the only downside really is boot time. lets fo it. card
in reader. backup 2w for.when i will.be able to source it below 400pln... make sure to copy all the
important configuration from vga666 setup (there was real finding regarding color modes etc) from old
image - and i am not fully sure all of that is in config file. check in rpi repo changes first to make
sure we got all. then build new image with all inside there." → old card backed up
(`~/backups/prius-pi-zero2w-2026-10-14.img.zst`), config inventoried from the card itself (the repos
disagreed on `dpi_output_format`; the card's `0x05` is right, see
`raspberry_pi_config/README.md`), new 32-bit image built (`raspberry_pi_config/zero13-image/`).
Architecture reminder from the user: "pi is only a display driver, real computer is Poco F1".
