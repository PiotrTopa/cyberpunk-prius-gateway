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
