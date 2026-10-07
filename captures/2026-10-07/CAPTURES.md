# Capture log — 2026-10-07 (on-site, Prius, gateway v3.0.0)

All times CEST. Recorder = `gateway-rp2350/tools/avc_capture.py` (one JSON object per line:
`ht` host unix time, `raw` gateway line, `obj` parsed; `{"mark":n}` = event marker).
Gateway AVC polarity forced `pol=lo` from 13:00 on. "User said" = the operator's own words,
kept verbatim (typos included) so the captures can be re-analysed later.

| File | Time | Setup | What the user did (user said) | Notes |
|---|---|---|---|---|
| `run1_nav_attempt1_noframes.ndjson` | 12:51:50–12:54:47 | nav connected, gateway ground floating, H1 original | car start, "clicked phys as wel: menu 7x, dest: 9x, map: 11x consequitevely", car off | **0 frames** — no car ground on gateway (laptop USB only). Useless except as a failure record. |
| `test0_raw.csv` | 13:01:00–13:02:30 | ground fixed, H1 original | ACC on, "used", off | raw pulses: 41 s stuck dominant (bus off), 60 s idle, no traffic seen → H1 pair reversed for RX. |
| `test0b_raw.csv` | 13:04–13:05 | H1 swapped (RX-correct) | ACC on, buttons | clean 20/34/170 µs clusters, 0 parity errors. |
| `run1_nav.ndjson` | 13:07:15–13:10:15 (mark 1 = 13:08:38 cold bus) | **nav connected**, H1 RX-correct | from cold: car to READY; "left top, left bottom, right top, right bottom 1x each, then buttons menux7 destx9, mapx111" (= map ×11); car off | 1009 frames after mark, 0 errors. Reference capture WITH nav. |
| `run2_nonav_prewiring.ndjson` | 13:10:41–13:15:42 | nav being unplugged | (wiring work in progress) | discard. |
| `run2_nonav.ndjson` | 13:15:44–13:17:58 (mark 1 = 13:16:12 cold bus) | **nav unplugged**, H1 RX-correct | same routine as run 1, car off | 979 frames, 0 errors. Reference capture WITHOUT nav. |
| `emu1.ndjson` | 13:23:46–13:25:40 | nav unplugged, `nav_emu.py` | car start; display "sas it is disconnected" | 0 frames received (user: "ah, sorry my bad" — setup issue on the car side). |
| `emu2.ndjson` | 13:26:53–13:27:41 (emu stopped 13:28) | nav unplugged, `nav_emu.py` (listening) | car start; "still the samw" (display: nav disconnected) | roll call heard + answered (tx=3) but echo=0 → TX reversed relative to RX. |
| `emu3_blind.ndjson` | 13:36:15–13:37:37 | **H1 original (TX-correct)**, `nav_emu.py --blind`, 253 frames sent | "it worked by spamming broke the dispaly, but it thought the nav is on, just was behaving crazy, but i think it hear us" | proves TX reaches the display in original H1 orientation; RX deaf in that orientation. |
| `map1_audio.ndjson` | 13:43:58–13:44:59 | nav unplugged, H1 RX-correct | (user had done these once BEFORE the recorder ran, then repeated) audio on/off a couple of times, volume changes; outside temp shown = 20 °C ("always visible") | User: outside temp has min −40, "full int" → 20 °C = 0x3C. Audio "received by the radio unit, maybe it should be retransmited by it to jbl". Only a 1-min periodic 1C6 re-announce seen. |
| `map2_climate.ndjson` | 13:47:30–13:49:17 | nav unplugged, H1 RX-correct | inside temperature setting "3 steps up, 4 steps down"; "in the end i also put headlight on / off" | see analysis below. |

## map2_climate first-pass analysis (to be confirmed by the user's exact sequence)

- `1C6->110 00 E4 5F BA 00` + `1C6->FFF E5 01 9C 57 42 4C 41 45 4E` + `110->FFF 12 01 20 xx`
  (xx increments 98, 9B, 9C …) at 13:44:40, 13:47:38, 13:48:38 → **periodic 60 s re-registration**,
  not a user event.
- 13:47:43–13:48:10: `1C6->110 00 E4 5F 97 02 xx` at ~1 Hz with varying xx, plus
  `E4 5F B9 0C 0C 00` and `E5 5F D8 FF FE 40` for the same window; `E4 5F 96 xx` climbs 5A→66.
- 13:48:38–13:48:44: `1C6->110 00 E0 5D F5 NN 38`, NN 0B→0F (4 up) then 0F→07 (8 down) —
  stepwise user control; candidate: **volume or setpoint** (count does not match 3 up / 4 down).
- 13:48:48–13:48:50: `1C6->110 00 25 32 84 40 00 00` / `00 00 04` (switch frames).
- 13:48:56 `110->FFF 01 01 5B 40`, 13:48:58 `110->FFF 01 01 5A 80` → candidate **headlight / dimmer** on/off.
- Outside temp 0x3C only seen in `110->178 00 56 58 F0 49 3C 44` (run 1, display → nav); absent
  without the nav.

## Later captures (same day)

| File | Time | Setup | What the user did (user said) | Notes |
|---|---|---|---|---|
| `map3_marked.ndjson` + `map3_marked.notes.txt` | 13:51:05–14:10 | nav unplugged | marked one-action steps (markers 1–10; the user's words per marker are in the notes file): setpoint up/down, A/C auto off/on, climate screen + fan high/low + recirc, engine on/off, windscreen, fan 1→7, AUTO, vent modes, A/C, face, lights positions/low/high/fog/indicators, audio off/on/volume/mode | basis of AVC_MAP.md climate section |
| `drive1.ndjson` + notes | 14:15:09–14:17:38 | AVC only | "lets do small drive, so it will be data changin on energy monitor" | energy fields |
| `drive2_obd.ndjson` + notes | 14:54:49–14:58:19 | AVC + OBD polling 500 ms (fw 3.0.0) | short drive | OBD answered 9 % of requests |
| `drive3_can.ndjson.gz` + notes | 15:05:09–15:07:50 | AVC + full CAN sniff (fw 3.1.0), gzipped | short drive with engine cycling | engine flag vs CAN 0x3C8 rpm timing |
| `dashboard1.ndjson`, `dashboard2.ndjson` + notes | 15:12– | live dashboard logs (`tools/avc_dashboard.py`, raw lines only) | user compared dashboard with the car's screen: "screen 56-info, audio/info - is just trip info, main energy flow, (switching_ is actaul audio screen …)"; "outside temperature is not 21C and it is not updated only with nav." | screen names + outside-temp frame F7 |
| `../firmware/*.uf2` | 15:03 | RP2040-Zero images | 3.1.0 (flashed) and 3.0.0 rollback built from 5c180b0 | |
| `drive_home.ndjson` + `drive_home.notes.txt` | 15:21:32–15:46:55 | full drive office → home, `avc_dashboard.py` (AVC only), nav unplugged; 4 short (~3 s) gaps for dashboard restarts, listed in notes | live corrections by the user: arrow directions, rear window heater ~15:30, battery bars 4/3/4/5, outside 22 °C, EV on/off ×3, EV cancelled by throttle; "i am home, close it, save it, all works very well" | 19,790 AVC frames, 0 decode errors |
