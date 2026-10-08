# Capture log — 2026-10-08 (PHY board fixed: comparator inputs swapped by the user)

All times CEST. "User said" = the operator's own words, verbatim.

| File | Time | Setup | What the user did (user said) | Notes |
|---|---|---|---|---|
| `rxtest1.ndjson` | 14:16:16– | fw 3.1.0, pol forced lo, `avc_dashboard.py` | "PHY board for avc lan is fixed, i swithced the inputs. lets test it out … first test if receiving works. i have car off now" | car-off self-test inconclusive (rx stuck dominant on unpowered bus, as on 10-07) |
| `rxtest1_raw.csv` | 14:17– | car awake (CAN 5k fr/3s), H1 orientation A | user then: "I NOW CHANched avc polarity? better? if not, isnt it like switching +- on cmparator switched lo-hi ?" | orientation A: GP0 pinned, 0 pulses; orientation B (first try): 2–12 µs chatter both pol; user: "i just switched the inputs from AVC lan…" |
| (raw, scratchpad) | ~14:3x | after user re-checked the swapped wires ("check again now, both hi and low") | — | **pol hi: clean 20/34/170 µs, frames decode, 0 parity; pol lo: garbage** → fixed board needs pol "hi" |
| `rxtest2.ndjson` | 14:28:28– | dashboard `--pol hi` | — | RX working |
| `emu_fixed1.ndjson` | 14:30:20– | nav_emu.py --pol hi (listening), fixed board | user: "it does some kind of the helthcheck on boot, so we need to stop it, enable emulator, then start and seez" | |
| (stats/raw, scratchpad) | 14:30–15:1x | fw 3.1.0; user swapped AVC inputs at the LM339; H1 flipped twice during tests | user: "I NOW CHANched avc polarity…", "wiring is ok; can you check if the TX polarity is actually right?", "i was just chekcing for cold solderings, check again pls, h1 flipped" | RX: works in one H1 orientation only, with **pol hi** (0 parity); other orientation GP0 pinned. **TX: no effect on the comparator in either orientation, car on or off** (loopback rx_drive = idle; raw capture of own frame: 0 pulses, 0 glitches; echo 0). Yesterday the same TX produced edge spikes + display reaction → TX path suspected broken since the rework. `pol` affects RX only (`avclan.c:260`); TX sense is hardware (Q2 → H1). |

## Bench session (evening, board on USB, H1 off the car)

Facts established by measurement (user's scope + firmware tests):

| # | Measurement | Result |
|---|---|---|
| 1 | Comparator unit in use | **LM339 unit 2**: IN− = pin 6, IN+ = pin 7, OUT = pin 1 (doc says unit 1 / pins 4,5,2 — wrong) |
| 2 | TX direction (driver held dominant into GND–1k–L–1k–R–1k–GND) | **left H1 pin = TX Data+** (4.55 V), right = TX Data− (0 V, sunk by Q1 → D2 correct way, Schottky-level drops → rebuild-spec parts) |
| 3 | Line → comparator mapping (pins measured during hold) | left → **pin 6 (IN−)** 4.86 V, right → **pin 7 (IN+)** 0 V ⇒ TX dominant → OUT **low** ⇒ firmware **`pol lo`** |
| 4 | Idle without bias | undefined (offset parks OUT low = dominant) → loopback "no change", "pinned" orientations in the car |
| 5 | Bias **2 MΩ 3V3 → pin 7 (IN+)** ≈ +160 mV | idle OUT high (recessive); loopback `rx_idle=0, rx_drive=1, rx_after=0` 3/3 (acceptance test) |
| 6 | Bench echo of own frame | bits arrive, but dominant +5 µs / gaps −5 µs (20/32/7 → 25/37/2); with t1=31, glitch=1 one frame decoded as `178→1FF 58 31 F1 02 00 echo:1` → full TX→RX chain OK |
| 7 | Scope (blue = left H1 line, yellow = pin 1), 20 µs/div | line gap between "0" bits ≈5 µs (TX release ~2 µs late, Q2 tail); OUT rises ≈3 µs after the line falls (RX input RC + LM339 at low overdrive); onset immediate |
| 8 | In-car reference (afternoon, no bias) | bus frames 20/34/172, gaps 7/18 → RX delay ≈1 µs on the car's own frames |

Consequences: yesterday's comparator-input swap did not fix TX-vs-RX (the undefined idle followed the swap); with the bias the orientation question is simply "does it decode", `pol` stays `lo`. The orientation that "pinned" today is the correct one (car Data+ on the left pin = TX Data+). Scope photos: filedrop `1000027529.jpg`, `1000027530.jpg` (19:24).
Open: TX release tail (R6 / 100 pF across R5), RX delay (R1/R2 100k→10k, bias 200k), firmware glitch filter 6 µs vs our own 5 µs gaps.
| (bench, final) | ~21:xx | 2 MΩ 3V3→pin 7 **soldered**, load GND–2k2–L–120Ω–R–2k2–GND, `pol lo`, after gateway reset | user: "i fixed someyhig, test again" (after a first soldering attempt that left the idle parked dominant) | **PASS**: loopback 0,1,0 ×3; 3/3 own frames decoded `178→1FF 58 31 F1 02 00 echo:1`, 0 parity; widths 22/34 µs, gaps 16/4 µs (car-like 120 Ω swing → RX delay ≈2 µs). Bench acceptance complete. |
