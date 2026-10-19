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

## Steering wheel keys and audio path (user said: "thee is no panel, just wheel; 3 times volume up, 4 time vol down")

Linux input layer (`getevent`, devices mtk-kpd/mtk-tpd) shows ONLY touch events — wheel keys do not pass
through it. They come from the MCU over `/dev/ttyMT2` (held open by system_server, fd 223; ttyMT3 fd 159
also held by system_server), read by the vendor class `NewkeypadMonitor` in system_server (log
`E/NewkeypadMonitor: key_dev_read16` per press AND per release = 2 reads per press; `key_dev_read105` every 5 s
is a status frame → `xy.android.B.vibration.voltage` broadcast). Wheel VOL+ ×3 at 19:52:03.6–04.2 (unit
clock, laptop 13:52): TDA7729 master volume 35→36→37→38; VOL− from 19:52:11: 38→37→36… Each step:
`AudioSettings: setTDA7729MasterVolume enter value>N`, `VolumeDialog vlevel=N`, broadcast
`xy.android.volume.change` (+ `android.media.VOLUME_CHANGED_ACTION`), then AudioService mirrors N (and N/2)
onto every stream type for device 8. Earlier (19:50:04/05) two wheel presses were forwarded to ZLink instead
(`D/zj: [keycode]keyCode 5 / 6`) via `NewkeypadMonitor.onReceive action=com.zjinnova.zlink` — ZLink's own key
codes when it is in front; ZLink reports `status=MAIN_PAGE_SHOW` to the framework. Vendor framework also tries
to start `com.suding.speedplay` (absent). CAN box app: `com.xygala.canbus` (pid 1216, broadcasts
`com.acloud.intent.android.XY.ANDROID.CANBUSDISPINFO1/3` ~1 Hz), settings app `com.xygala.pvcanset`.
MCU reader threads in system_server: tid 13337 "Thread-136" blocks in read(fd 223=/dev/ttyMT2, 255 bytes);
tid 13330 "Thread-135" in read(fd 159=/dev/ttyMT3, 64 bytes). Device has /system/xbin/strace, tcpdump,
gdbserver, toybox. SYSTEM_ALERT_WINDOW appop for zlink = default (overlays grantable). Raw serial frames
traced with strace below.

**MCU serial protocol (strace on system_server tid 13337, /dev/ttyMT2):** frames `5A A5 LEN CMD DATA… CHK`,
LEN = bytes after it including CHK, CHK = (−(CMD + DATA…)) mod 256 (two's complement of the sum; verified on
3 frames). Every 5 s the MCU sends `5A A5 04 69 0E 17 72` / `… 69 0E 0C 7D` (cmd 0x69 status, data 0E 17 /
0E 0C = probably battery voltage, cf. `xy.android.B.vibration.voltage`). First key frame seen 19:54:43 (unit
clock): `5A A5 04 10 01 0C E3` → cmd 0x10 = key, data 01 0C.

**Wheel key map (user: "3 short clics/relesaes, 1 long click on volup;;; 3 short 1 long on vol down"; strace
file log, unit clock):** key frame `5A A5 04 10 SS KK CHK`, SS = 01 press / 02 release, KK = key code.
VOL+ = **0x0C** (19:56:34–42), VOL− = **0x0D** (19:56:59–57:07). Short click = one 01 frame + one 02 frame on
release; long press = 01 frames repeated every ≈100 ms (MCU auto-repeat) until the 02 release frame.
User "1x mode, 2x previous, 3x next" (19:57:54–58:05): MODE = **0x06**, PREVIOUS (seek−) = **0x0B**, NEXT (seek+) =
**0x0A**. Full wheel map so far: 06 MODE, 0A NEXT, 0B PREV, 0C VOL+, 0D VOL−.
User: MAP and INFO (the MFD bezel buttons on the wheel side) pressed 19:58:05–59:40 → NOTHING on either serial
port, nothing in the CAN-box app or logcat; user: "i think they just internaly rpelicate thse buttons" (they
act on the Toyota MFD/AVC-LAN side, not the head unit). Then "1x SPEAK, 2x ODBIERZ (answer), 3x
ZAKONCZ_POLACZENIE (end call)" (20:00:30–01:15): SPEAK (voice) = **0x50** (only a press frame logged, no
release), ANSWER = **0x0F**, END CALL = **0x10**.

**Android → MCU writes (strace -f on system_server, 20:03:03–20:04:59 unit clock, user pressed VOL+/VOL− then
switched sources on screen):** only two commands ever written to /dev/ttyMT2 by system_server: `5A A5 08 0B 01
RR GG BB 05 64 CHK` once per second cycling red/orange/yellow/green/cyan/blue/white = **key backlight RGB LED
colour cycle** (cmd 0x0B, 7 steps, brightness 0x64), and `5A A5 03 05 03 F8` (once `05 04`) in bursts while
the screen was being tapped = **touch beep** (cmd 0x05). NO volume or source command goes to the MCU from
system_server, and system_server touches no I2C device → the TDA7729 volume/source path is in the audio HAL
process (see fd scan below). Wheel presses in this window arrived as reads (`10 02 0C` 20:03:26, `10 02 0D`
20:03:30 releases). Trace files: `headunit/mcu_trace.txt` (reads), `headunit/mcu_rw_trace.txt` (all).

**Audio / source facts (user: "done" after VOL+, VOL−, Radio→Music→back; radio tuned 95.90→88.10):**
volume broadcast `xy.android.volume.change` carries extra `volume=N` (0–63 TDA7729 scale; a companion
broadcast carries `vol=N`). Source-related vendor broadcasts seen in `dumpsys activity broadcasts history`
(saved as `headunit/dumpsys_broadcast_history.txt`): `xy.notify.cur.mediasource`, `xy.kill.mediaapp`,
`xy.release.mediaappres`, `xy.android.radio.isplay`, `xy.fmradio.quit`, `xy.android.hw.fmpower.enable`,
`xy.android.4735.fm` (Si4735 tuner), `xy.android.galaxradio.setaudiotogps`, `xy.btmusic.stop`,
`xy.media.ringer.mode.change`, `com.autochips.adau1701set` (×144 — an ADAU1701 SigmaDSP audio processor is
set through broadcasts), `com.acloud.intent.android.MAINUI_UPDATE`, `update.widget.*`. No process holds
the I2C devices permanently (only z-link keeps /dev/i2c-4); system_server owns both ttyMT2 (MCU) and ttyMT3.
Volume/source are therefore applied in the audio HAL / vendor services, not through the MCU — to be read
from the dumped system+vendor images. Screenshots `headunit/hu_01…03.png`. Unit unplugged after this.
