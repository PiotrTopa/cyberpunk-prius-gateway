# Captures 2026-10-19

All times CEST. Emulator logs = `gateway-rp2350/tools/nav_emu.py` line format.

## Nav emulation re-check (user said)

"ok, now run again the emulator for avc lan to emulate navigation. My goal is to make sur eit works, so I can
test rpi actually connected to the car"

Bench/car state at 12:30: gateway on `/dev/ttyACM0` (2e8a:000a), Pi not connected to the laptop.
`emu1_nav.ndjson` / `.stdout`: `nav_emu.py --pol hi --fw-auto --fw-ack` started 12:34:04; bus already awake
(display screen 5F at 12:34:09), waiting for the display's roll call.
Result: car switched off/on by the user; 12:34:55 roll call `12 01 00` answered by the gateway auto-reply slot,
device table + ident accepted, screen 00 → setup done 12:34:57 (initial burst; `00 58 34 E0` NAKed as on
14 Oct) → screen 5F. 12:35:05 MENU button → screen request `00 12 58 42 02 01` → grant `00 58 12 52 02 01` +
`58 31 F1 02 00` → screen 58 within 30 ms; 12:35:07 release request (menu, screen 56) acked; 12:35:27 second
screen request → screen 58 and the display stayed on the nav screen (RGB input) from then on, heartbeats
`58 31 F1 02 00` every 5 s answered by `12 01 60 58`. Re-registration ping replies `00 01 12 30 XX FF` NAKed
twice (12:36:56, 12:42:57) — also seen in emu8 on 14 Oct, no effect. Nav emulation works; emulator left
running for the Pi-in-car test.

## No picture on the MFD: wrong chip in the VGA666 sync socket (user said)

"I dont have sync, but now I see i hav LM339 as IC on the vga666.... was it comparator for making a sync or
was it something else and i put the wrong uC?" → "yes, and wiring make total snes efor 74hc86, i just pushed
wrong piece on the podstawka, but looking at it, it shoudl not break anything, i should be able to relace it
when back home and got it to work". The VGA666 sync combiner socket is wired for a **74HC86** (XOR of H-sync
GPIO 3 and V-sync GPIO 2 → composite sync for the MFD); an LM339 (same DIP-14) had been inserted by mistake.
Nothing in the repos documented this circuit before today. Pi in the car not tested further; emulator kept
running meanwhile.

**Closed 13:12 (user said):** "stop it, we go to the next step of our tsting, which will be diffrent topic, lets
clos that one and park it until i fix the sync. Overal, something was on the screen, just smuged no sync, so
cool." Emulator stopped 13:12:25 (tx=1304, echoes=1306, display->178 NAKed=0; 27 259 log lines). PARKED until
the 74HC86 is back in the VGA666 socket.

**Open question (user):** "On the MFD cable there is one wire I have not mapped. When tested it it looked like
it as fixing a foucs just a little bit. … with normal sync connected, the picture was ok, but with this pin
connected to e.g. RED it become much cleared, less gaussain blured, a little tiny bit. Qusiton: is that some
additional magical sync, or just a floadting ground?" Web search 13:1x found no Gen2 MFD RGB (M14 connector)
pinout online (techno-fandom teardown covers only AVC-LAN; pinoutguide covers head-unit plugs). Assessment:
no Toyota RGB link carries a pixel clock or a second sync; the behaviour fits a floating signal ground /
shield of the RGB group (tie it to the DAC ground, not to RED). To discriminate: ohm the pin to MFD ground
unpowered (≈0 Ω = ground/shield; kΩ–MΩ = a logic input such as YS, the RGB/video select line).
