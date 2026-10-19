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

## Head unit over USB → ADB works (user said)

"New topic. I just connected my android chinese haedunit form car, I want to take control of it thorugh our
computer. But lets start with reaching device mode and adb. test" → "focus on usb for now, phone is connected
wia USB thethering, dont bother with that. We still trying USB, next port now, figure out if that works for now."

13:34:02 the head unit's *second* USB port enumerated on the laptop as `0e8d:201c MediaTek "9520"`, one
interface class ff/42/01 "ADB Interface" (device mode, ADB only — no MTP). `adb` (Debian package, udev rule
51-android.rules) installed on the laptop; `adb devices` → `MJU8DY59WS8LMB85 device product:full_8227L_demo
model:9520 device:8227L_demo` with NO authorisation prompt. Facts from the shell: MediaTek Autochips **AC8227L**
(`ro.hardware`/`ro.board.platform` ac8227l), build `9520_00033_V001`, manufacturer `alps`, `ro.build.version.
release` claims 10.0 but SDK 27 (= Android 8.1 API), `ro.debuggable=1`, `ro.secure=1`, `/system/xbin/su` present,
USB config `adb`, screen 1280×720 @160 dpi, 115 packages, foreground app `com.zjinnova.zlink` (ZLink CarPlay /
Android Auto), uptime 4 d 21 h, load ≈7. (The 14 Oct note "B9520B Android 9 kernel 4.14.116" is the same unit.)

Side note, same morning: the Pi on laptop port 6 hit `usb usb1-port6: disabled by hub (EMI?)` again at
12:39:44, 23 s after enumerating (then descriptor errors -71 at 12:40:43) — the 15 Oct port-2 event was not a
one-off; it recurs with this Pi gadget on this laptop. Not investigated today (user: focus on the head unit).
Root: `adb root` refused ("unable to connect for root: closed"), but `adb shell su 0 <cmd>` / `echo cmd | su`
give uid 0; SELinux **Permissive**; /system ext4 ro on mmcblk0p22. Screenshot via `adb exec-out screencap -p`
works (1280×720, ZLink "X-Car CarPlay/AA — please connect your phone with Bluetooth", BT name CarBT).
Control test: `adb shell input keyevent KEYCODE_HOME` → launcher `com.android.launcher/com.xyauto.common.
activity.MainActivity` came to the front (screenshot). Vendor packages: com.autochips.* (quickbootmanager,
bluetooth, backcar), com.mediatek.mtklogger, com.xy.zlinkactivationcode, com.zjinnova.zlink.

## Root inventory (user: "can we get full root access to that device, and how ?")

Already full root: `/system/xbin/su` is mode 4750 root:shell (adb shell may call it; apps may not), `su 0`
gives uid 0 with CapEff/CapBnd 3fffffffff (all capabilities), SELinux Permissive, dm-verity disabled
(`ro.boot.veritymode=disabled`, verifiedbootstate green), `/system` remounts rw (tested, remounted ro again),
build `user` with test-keys, kernel 3.18.79 armv7l, `ro.debuggable=1`. `adb root` is refused by this adbd,
but `su 0 setprop service.adb.root 1; su 0 setprop ctl.restart adbd` restarted adbd as root → `adb shell`
is now uid 0 directly (adbd pid 14278 root). Not persistent across reboot unless `service.adb.root=1` is
put in /system/build.prop. Apps still cannot call su (4750) — chmod 4755 or Magisk would change that.
Partitions (`/dev/block/platform/soc/11230000.mmc/by-name`): ANDROID=p22 (/system 2.9 G, 0.9 G free),
BOOTIMG=p10, RECOVERY=p11, LK=p6, LOGO=p14, VENDOR=p17, NVRAM=p2, userdata=p24 (111 G, 108 G free), TEE1/2=p7/8,
SECCFG=p5, SEC_RO=p12, MISC=p13, FRP=p21, CACHE=p23. /system/build.prop 0600 root.
