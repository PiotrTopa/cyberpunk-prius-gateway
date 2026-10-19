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

**Volume API test (20:14 unit clock):** `media volume --stream 3 --get` → "35 in range [0..63]" (reads the
TDA7729 scale). `media volume --stream 3 --set 30` and `input keyevent KEYCODE_VOLUME_UP` did NOT change it
(still 35) → the vendor volume path bypasses the standard stream API; the setter is vendor-specific (to be
found in the decompiled framework). System setting `Amp_Power=0` exists (the on-screen amplifier button),
`sysinfo_android_amplifier_isshow=1`.
**JBL amp vs AVC-LAN (user asked):** across ALL our bus captures the only addresses are 110 (EMV display),
1C6 (G/W: climate/trip gateway), 178 (nav), broadcasts 1FF/FFF — no 440 DSP-AMP / 480 AMP frames at all
(AVC_MAP.md mark10: "aftermarket radio + its amp on/off button … no AVC frames"). Published Prius frames
(softservice.com.pl/corolla/avc/avclan.php): head unit 190 → DSP-AMP 440 `00 25 74 91 bb` balance, `92 ff`
fade, `93 bb` bass, `94 mm` mid; EMV 110 → 440 `00 5E 29 60 dd` beep via speakers; Corolla broadcast
`160→1FF 74 31 F1 90 vv bal fade 10 bass 10 treb 0 0 0 3 0` carries volume vv 0–FF. No published amp
power-on or Prius volume frame.

## Is the JBL amplifier on the bus? (user: "Are you sure it is not connected anymore at all to the bus? How do we now that?")

Test 14:24–14:26 (`emu2_amp_on.ndjson`): head unit amplifier button ON (`Amp_Power=1`), gateway logging with
nav_emu, user power-cycled the car. Roll call `110→FFF 12 01 00` at 14:25:21.08 answered ONLY by 178 (our nav
emulator: `00 01 12 10 58 24 85`) and 1C6 (`00 01 12 10 E0 E4 E5`); device tables `12 01 01` → 178 `58 28 29 32
60 74 A4 56` (the recorded real nav's table — it claims tuner 60 and audio amplifier 74 logical devices), 1C6
`5D 00 5F 32`. No 440/480, no other address, over the whole file (masters 110/178/1C6 only). Conclusion: with
the amp powered, nothing answers for it → the JBL amp is NOT connected to the AVC-LAN pair we tap (or is not
powered by that button). Note: the stock nav box's device table includes logical 74 (amplifier) and 60
(tuner): in this car the nav/audio ECU hosted those functions on the bus.

**Corrections from the decompiled framework (offline lane, mediatek-services `NewkeypadMonitor`):** the
`05 03`/`05 04` frames are NOT a touch beep — they are `dosetRadioPower` (cmd 0x05 = power control: 06 power
off, 15 ACC-off ack, 16 sleep, 0C reboot, 13/14 lock/unlock, A2/A3 amp), triggered by a `CANBUSDISPINFO1`
broadcast; the 5 s `69 0E xx` frame is `B_vibration_voltage_left/right`, not battery (battery comes in cmd
0x82 → `sys.xy.mcu.battery`). `/dev/ttyMT3` is the CAN-box UART (`CanbusMonitor`, 38400 baud), not a second
MCU port; the unit writes `2E C4 01 vv chk` (volume) to it on every volume change and nothing answers.
Vendor key names: 06 PLAY_PAUSE (our "MODE"), 0A FORWARD, 0B BACKWARD, 0C/0D VOL, 0F PHONE, 10 HANGUP, 50
VOICE. `settings put system newkeypad_debug 1` logs raw MCU bytes. Volume chain: `setStreamVolume(STREAM_MUSIC,
0..63)` → `autosetTDA7729MasterVolume` → vendor.autochips audio HAL → ALSA `TDA7729*_Switch`; the plain
`media volume --set` test at 20:14 did not take, the vendor setter is broadcast `xy.android.gtpkey.volset`.

## Wrap-up 19 Oct (user said)

"dtop it, i have som picture, its not my top priority, with full contorl over the head unit android and JBL
bascially working I think I am fine. It works. lets wrap it up, make sure we have all documented and praepare
for next fun step."

State at close: nav emulation re-verified on the car (emu1, emu2); head unit fully reachable (ADB over its
OTG port, su root, adbd restarted as root until next reboot), wheel keys and MCU protocol mapped, vendor
control broadcasts documented in the host repo `docs/HEADUNIT_INTEGRATION.md`; full partition images +
decompiled framework in `~/backups/headunit-9520-2026-10-19/`; JBL amp confirmed off the AVC-LAN; head-unit
integration PARKED (user: not top priority). Left on the unit: `/data/local/tmp/mcu_trace.txt`,
`mcu_rw_trace.txt`, `amp_trace.txt` (amp-button toggle never traced). Pending hardware: 74HC86 back into the
VGA666 sync socket (MFD picture), then Pi-in-car test; unmapped MFD wire test (ground vs YS).

## 70mai dashcam over its hotspot (user said)

"now i want to get access to 70main in my prius to get porssiblity of connecitn to this device and
potenatially useit later for detecting the weather / auto light based on the picutre. Password to wifi i
12345678" … "It is myown car, my own dashcam, and I now the password for it, as well I have had to manually
switch it on".

Laptop joined `70mai_S410_814b` (WPA2, ch 10, BSSID B8:59:C8:2B:81:4B) with NM profile set to
`ipv4.never-default yes` (internet stays on the phone tether); DHCP gave 192.168.0.2/24, camera = 192.168.0.1.
Open TCP ports: 80 (HTTP, `/cgi-bin/Config.cgi` answers `{"ResultCode":"-4444"}` to every property, root
gives an empty reply), 554 (RTSP), 3333 (silent on connect; the 70mai app's control channel). RTSP: Novatek
("Nvt RTSP, LIVE555 v2013.07.03"), `rtsp://192.168.0.1/liveRTSP/av4`, H.264 High, **640×360 @ 30 fps**, ≈0.7
Mbit/s, no authentication; DESCRIBE answers 200 for any path. `ffmpeg -rtsp_transport tcp -i
rtsp://192.168.0.1/liveRTSP/av4 -frames:v 1 frame.jpg` works (frame in `70mai/frame1_live.jpg`); 5 s clip =
127 frames. ffmpeg installed on the laptop (apt). The camera must be switched on by hand for the hotspot
to appear (user).
User, after seeing the frames in ~/Pictures: "good, looks perfect for my usecase. good, lets make sure we
have all that documented for future work." → host repo `docs/DASHCAM_70MAI.md`, `tools/dashcam_brightness.py`,
README index of peripheral docs; frames also in `~/Pictures/70mai_live_2026-10-19_*.jpg`.

## Rear camera via adb (user: "1. can we get picture form rear camera? 2. can we force it to witch to rea camera view via adb?")

Open-air brightness check for lights management: pending the next drive (user).
From the decompiled framework (`NewkeypadMonitor`): broadcasts `xy.android.force.back.in` / `xy.android.force.back.out`
send MCU `07 05` / `07 06` (force reverse view in/out); the MCU answers with state cmd `12` value 8/7 → the
framework sets `sys.xy.backcar.status`, `SerialPort.setBackcarStatus(1/0)`, mutes audio (`forcebackcar_mute`)
and broadcasts `android.backcar.action.PREPARE_START` / `FINISH` (`xy.android.mcu.backcar.in` when ARM1 is
ready). `canbus.intent.action.cmd` extra `mcu_cmd` is a byte array whose FIRST byte is the payload length,
followed by CMD+DATA (no 5A A5/LEN/CHK — the native sender frames it); max 16 bytes; sends are queued 20 ms
apart. Backcar app `com.autochips.android.backcar`: service `.BackCarService` (action
`android.intent.action.BACKCAR_SERVICE`), activities `.BackCarActivity`, `.DVRActivity` (action
`com.autochips.android.backcar.dvr`, exported), `.AVInActivity` and `.RightAVInActivity` (MAIN, exported),
`.BackCarEmptyActivity` (action `android.media.action.IMAGE_CAMERA`, exported); its code is odexed (the pulled
APK has no classes.dex), native `SerialPort.setAvinVideo(int)`. Video input constant `VIDEO_INPUT_REARVIEW = 5`.

**Forced camera view (user: "lets then force it to camera view, so i can adjast camera safetly with car being
parked"):** `am broadcast -a xy.android.force.back.in` → `sys.xy.backcar.status` 0→1, `BackCarEmptyActivity`
in front, BackCarService "xy.android.mcu.backcar.in"; `screencap` shows only the app's icons, the video plane
is black (hardware overlay, not capturable). User: "it shows some camera view... but i dont think it is rear
camera" / "its another camera. I swtched to R and it switchted to dirrefernt camrea (same UI) then on parked
it goes back to black screen". Tried `xy.android.avin.path --ei path 0..5` (→ `SerialPort.setAvinVideo`): no
change. Direct serial writes to /dev/ttyMT2 as root work (`5A A5 03 07 06 F4` = back out, `…07 05 F4`… = back
in, verified 15:05:48/52). MCU cmd 07 = "mcu cvbs route" (`action.mcucvbs.route.set` extra `bcroute` byte
array → `07 RR`): routes 0x00–0x04 twice: no change; 0x0A–0x14 (15:06:05–15:07:25): user: "the screen now
exited to normal view, then back to cam - balck screen". Interpretation: the unit has two camera inputs; the
forced view shows the always-powered one, the rear camera (shown in R) is powered from the reverse-lamp
circuit and is dark when parked — consistent with the black screen after leaving R. Other 07-family codes
from the framework: 07 = main volume, 08 = QuickBoot on, 09 = HW backcar first. Direct-write recipe: frame
`5A A5 LEN CMD DATA CHK`, CHK = (256 − ΣCMD..DATA) mod 256, `printf` as root into /dev/ttyMT2.

## Dashcam light samples for the drive home (user said)

"AHHHH, YEAP. MAKES SENSE! oK, GOT IT, nOW PREPARE FOR PICTURE CAPTURING WHEN I DRIVE HOE. i WANT TO HAVE
DATA FORM MYGARAGE, AND DURING THE DRIVE. nOT LIKA AMOVIE, BUT LIEK SAMPLES WITH different lightning
conditions, so i can start figuring out values and image processing required to get that in the future - so
to corelate sky color / brighnets / values."

Sampler: host repo `tools/dashcam_sampler.py` (one JPEG every 10 s from the RTSP live stream, one RTSP session
per frame; CSV `samples.csv` with full-frame Y avg/min/max, U/V avg, top-third "sky" Y/U/V, bottom-half
"road" Y; `sampler.log`), run under `systemd-inhibit --what=sleep:idle:handle-lid-switch` so the laptop keeps
sampling with the lid closed; output `captures/2026-10-19/70mai/drive_home/`. NM profile for the hotspot set
to autoconnect (priority 10, never-default) so the link comes back whenever the camera is on.

**Drive home (15:22–15:52 laptop clock; camera clock runs ≈ +5 min 57 s ahead, visible in the burned-in
timestamps):** 174 frames, 10 s apart, `70mai/drive_home/` (`samples.csv`, `annotations.txt`, `sampler.log`,
JPEGs). User notes while driving: 15:25:08 "outside, sunny afternoon", 15:29:54 "directly into the sun now",
15:35:27 "now it is straight in", 15:39:12 "used screen wipers", 15:48:10 "shade". Then: "back home, lets
now chrck pictures, figure out a good alogirhm for cheap corelating them tomauto lights, maybe also figure
out ifnwe could tepreticslly inomwmnt some envirnent understanding eith doem AI tensor works - any good tolls
thwre to read street signs, lights etc?" 9 grab failures (camera off before start / hotspot lost at the end).
