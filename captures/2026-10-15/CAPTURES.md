# Capture log — 2026-10-15 (bench: Pi Zero v1.3 MFD board on the laptop USB link)

All times CEST. User said: "test it, make sure you have communication to it, logs, etc, all to prove the
functionality is there, to the extent possible without the screen"; "check also old card configuration,
last time we were fixing this 10 times over".

## First boot of the new card (2026-10-14 22:34) — link stayed NO-CARRIER

Gadget enumerated on the laptop (`2e8a:0013 Raspberry Pi USB Gadget`, `cdc_ether`), but no carrier for
1.5 h: NetworkManager's `85-nm-unmanaged.rules` leaves `DEVTYPE=gadget` interfaces unmanaged, so the Pi's
usb0 profile never activated. The old card had `/etc/NetworkManager/conf.d/99-manage-usb0.conf`
(`[device] match-device=interface-name:usb0 managed=1`); missed in the first build. Added to the card,
the stored image and the repo (`zero13-image/usb0-managed.conf`).

Old-card re-audit (every file under /etc, /boot/firmware, /usr/local, /opt modified after 2026-01-01 on
the Zero 2 W backup): all accounted for — carried over (config.txt, cmdline.txt, usb0 profile + managed
override, mfd.service + equalizer drop-in, test-pattern.service, fb0 udev rule, hostname/hosts/timezone/
keyboard, user/groups/password, authorized_keys, ssh host keys), not applicable (two Wi-Fi profiles,
wpa_supplicant, netplan, cloud-init network-disable), identical defaults (NetworkManager.conf, modprobe.d,
modules-load.d, udev). Nothing else was ever changed on the old card.

## Bench test 10:04–10:16 (card patched, Pi on the laptop's USB, `prius-usb0` NM profile = 192.168.100.1 shared)

| Check | Result |
|---|---|
| USB enumeration | 10:04:28, `cdc_ether`, host iface `enx…`; carrier + ping at 10:06:29 (≈2 min after plug-in, first boot after the patch) |
| SSH `piotr@192.168.100.2` | key auth OK. `Raspberry Pi Zero Rev 1.3`, kernel `6.18.50+rpt-rpi-v6 armv6l`, Raspbian 13; root fs auto-expanded to 29 G; 427 MB RAM, 218 MB free with the frontend running |
| Framebuffer | `/dev/fb0` = `BCM2708 FB`, 480×240, 32 bpp, mode 0666; kernel: `Registered framebuffer for display 0, size 480x240` |
| DPI / VGA666 | firmware reports `dpi_output_format=5`, `dpi_timings=480 1 24 46 60 240 1 4 3 15 0 0 0 60 0 9600000 1`, `enable_dpi_lcd=1`, `disable_fw_kms_setup=1`; GPIO 2–21 in ALT2 (DPI) — the VGA666 pins are driven. `dtoverlay -l` shows nothing because config.txt overlays are not runtime overlays |
| Gadget | `dwc2 20980000.usb` + `g_ether gadget.0` at +29 s; NM `usb0` activated, 192.168.100.2/24; internet through the laptop works (`ping 1.1.1.1` 40 ms) |
| Services | `mfd`, `ssh`, `avahi-daemon`, `NetworkManager` active; `getty@tty1` masked; `userconfig`/`regenerate_ssh_host_keys` disabled |
| Frontend, no backend | renders the home dashboard into fb0 at ≈10 fps, `link=DOWN`, retries 8081/8082 |
| Frontend + backend replay (laptop: `python -m cyberpunk_computer.backend --replay assets/data/full.ndjson --replay-loop --api-host 0.0.0.0`, `BACKEND_MFD_ENABLED=0`) | `link=UP connected=True`, state snapshots applied, **21 fps** steady (one 30 s window at 8.5 fps while 67 snapshots were applied), python ≈77 % CPU, 39 MB RSS. `/dev/fb0` dump decoded as BGRA = the real dashboard with replay data (SOC 51 %, 231 V, ICE 58 °C): `zero13_fb0_replay.png` |
| Second boot (clean reboot over SSH) | kernel 11 s + userspace 1 min 46 s; link up 126 s after `reboot`; `mfd` started at +116 s, pygame up at +126 s, first frames ≈+130 s at 21 fps |

Boot-time facts (second boot, `systemd-analyze blame` / critical chain): `console-setup` 43 s and
`keyboard-setup` 43 s (parallel, cache present), `NetworkManager` 40 s (starts at 74 s, "startup complete"
at 116 s; usb0 carrier only when NM gets to it at 114 s although the gadget was ready at 30 s),
`rpi-resize-swap-file` 26 s, `dev-mmcblk0p2` 23 s; `mfd.service` waits for `network.target` (= NM).
`wpa_supplicant` and `bluetooth` are enabled with no hardware. Not changed — candidates for a measured
boot-time pass: start `mfd` after `basic.target` instead of `network.target` (it reconnects by itself),
mask `wpa_supplicant`/`bluetooth`/`rpi-resize-swap-file`/`console-setup`/`keyboard-setup`.

Housekeeping applied over SSH (also applied to the stored image): `/etc/cloud/cloud-init.disabled`
(cloud-init 28 s per boot, unused), persistent journal (`journald.conf.d/persistent.conf`, Pi OS default is
volatile), removed `sshd_config.d/rename_user.conf` (userconf banner).

## Afternoon: backend AVC rewrite, touch-as-mouse, boot tuning (user said)

"reimplement backend avc completely to prioritise usage of avc data wherever available (test with recorded
data) and implement full touch support to work identically as mouse events. this includes also missing
external temperature, not working climate controls, etc. … also check if boot time could be significantly
improved, we will not have keyboard, other network than gadget, etc. why gadget network takes this long?";
later: "the board can use readonly system, we will not be persisting anything on sd, if that could help";
"give me some of those on a filedrop" → gallery https://claude.ai/artifact/WRzMKMTJKQPxCnY72LsM3R.

Host repo `cyberpank-prius-gen2-computer` main (b9cea45): `comm/avc/` package (decoder, touch calibration,
nav emulator, climate remote, scheduler), `io/avc_ingest.py` (AVC priority over CAN/OBD with freshness),
pointer model (`ui/pointer.py`, `ui/hw_buttons.py`) feeding mouse (dev) and backend `touch`/`button` events;
138 tests. Verified against these captures: outside temp 22 °C at 15:32:26 (drive_home), 20 °C (map3),
13–15 °C (drive2); all 8 energy states of AVC_MAP in drive2; emu8 touch strokes → four screen corners
(≤25 px) and the two drags; nav replies byte-identical to nav_emu.py's recorded TX (emu11, emu8).

Bench on the Pi Zero v1.3 (laptop backend replaying `drive2_emu_avc.ndjson`): climate panel OUT 14° / SET 20°
from AVC, energy arrows from AVC (`flow_source: avc`). Replaying `emu8_release_ack.ndjson`: 511 touch/button
events received by the frontend, taps opened Audio Settings, put AMBIENT in quick-edit, changed SET 20→19
(7 commands back to the backend); fb0 dumps in the gallery. Frame rate 14–30 fps during touch handling.

Boot: 130 s → 60 s to first frames (`raspberry_pi_config/README.md`, `zero13-image/boot-tune.sh`). Gadget
network was slow because NetworkManager (40 s start, 22 s of it in its netplan generator) only configured
usb0 at the end of its startup; systemd-networkd now brings it up at 35 s after power. Read-only overlay root:
planned last (`sudo raspi-config nonint enable_overlayfs`), after the panel work settles.

## 14:50 USB link loss on the bench (user said)

"btw nothing changed with pi, noone was close it, i can see power led green, nobody touched it whatsoever,
its software caused." Later: "replugged" (≈18:22).

Laptop kernel log (all times CEST): every Pi boot since 14 Oct enumerated the same way (full-speed attempt,
descriptor error -110, then high-speed `2e8a:0013` ≈18 s later). At 14:50:46 the laptop's root hub logged
`usb1-port2: disabled by hub (EMI?), re-enabling...` → `USB disconnect` → `attempt power cycle` →
`unable to enumerate USB device`. That first line is the hub's port-enable bit being cleared by hardware
(signal error on the link), not a software disconnect on either side: the laptop did not suspend, no backend
was running, uhubctl is not installed. Since then every connect attempt (17:06:11, 18:22:52, 18:23:03 after
the replug, 18:28:07 and 18:29:01 after a port power cycle from the laptop via sysfs `usb1-port2/disable`)
fails at port reset, before any device descriptor is read. The Pi does react to the power cycle (connect
attempts ≈6 s and ≈54 s after power returned), so the SoC boots; the USB data link does not negotiate.
Pending: different cable / different laptop port; ACT LED pattern at power-up; `journalctl -b -1` on the Pi
around 14:50:46 once the link is back (persistent journal enabled 10:1x).

**Resolution (18:22–18:47).** User: "its not physical - nothing changed as I told you. no physicsl changes of any
kindz not even a draft. something in the config caused that." Then: "this is powerfull p52 usb port, reliable
cable, 1.3V dont rven have eifi to blame for high current... make sure and try to find 5hr csuse" and (moved the
Pi to another laptop port) "it shoes all thebs9gns of booing looking at the let, it id bkinking fast, then dtoped
eithbsolid light".

Pi-side journal (persistent, boot d827369f = 13:19:24 → 18:22:08): the Pi never crashed. The frontend logged
FRONTEND ALIVE at 30 fps every 30 s from 13:19 until the replug at 18:22. At 14:50:47 it saw only `usb0: Lost
carrier` followed by a storm of `dwc2 20980000.usb: new device is high-speed/full-speed` (bus resets from the
host every ~200 ms, 14:50:47–14:50:50), the same storm at 17:06:10–13, nothing else — no OOM, no dwc2 error,
zram 256 MB with 0 used. Fresh boot on the same laptop port (boot 543200ee, 18:20): g_ether bound at 21 s, 19
resets answered at high speed in 21–23 s, never a `new address` — the host never completed enumeration;
further reset bursts at 323–326 s and 377–378 s (laptop port power cycles via sysfs; VBUS evidently not cut,
the Pi did not reboot). Fresh boot on laptop port 1-6 (boot a82496b4, 18:33): 3 resets then `new address 41`
at 20 s, usb0 carrier at 26 s, SSH fine. Laptop side: `usb usb1-port2: disabled by hub (EMI?)` is the first such
line on this laptop since at least 1 Sep (all boots); the gadget was never autosuspended (power/control=on,
runtime_suspended_time=0); no xhci error lines. Conclusion: the laptop's xHCI (Cannon Lake 8086:a36d, kernel
7.0.0-38) port 2 went into a state where it issues resets but never enables the port; the Pi, its config and
the cable answered every reset. At 18:41:47 the xHCI controller was unbound/rebound (all ports reset, Pi back
on 1-6 after 2 s). Whether port 2 works again after that reset is untested (needs a device plugged into it).
Trigger of the 14:50:46 port error: not recorded on either side.

Deploy of host-repo main c723c41 to the Pi (18:36): mfd restarted, 20 fps without backend, "--" placeholders
on IN/OUT/ICE/INV/kW/V/A (fb0 dump). Navigation check with a synthetic gateway-v3 capture replayed by the
laptop backend (`00 25 58 84 04 00` DEST press/release, then touch `00 21 24 78 7f 2f 7f 2f` = screen
(240,203) = engine-menu row 6, release): frontend logged `MFD button 'dest' -> engine_menu`, the AVC-LAN STATUS
screen opened on fb0 showing TOUCH UP 241,203 / LAST BTN DEST / STALE 28s / all signals "--". Engine-menu rows:
first_y 34, stride 31, row_h 28 (a tap at y=180 hits row 5 = SOLICITED MONITOR).
