# Raspberry Pi MFD video board — configuration as deployed

The Pi drives the Prius MFD over DPI (VGA666 resistor DAC, 480×240 @ 15 kHz) and talks to the
car computer (Poco F1) over the USB Ethernet gadget `usb0` (Pi 192.168.100.2, Poco 192.168.100.1).
The Pi is **only** the display driver; the backend runs on the Poco.

## 2026-10-14: Zero 2 W → Zero v1.3

The Zero 2 W died (user: "i burned it by mistake") and the Zero 2 W cannot be sourced in October 2026
(substrate shortage; Kamami/Botland out of stock, Botland ETA 2027-04). A Pi Zero v1.3 (same footprint,
same header, same USB/DPI silicon features, ARMv6 single core, no Wi-Fi/BT) replaces it until a 2 W
is available again. Consequences:

- The old custom **Debian 13 arm64** image cannot boot ARMv6 → new image = **Raspberry Pi OS Lite
  32-bit (Trixie, 2026-10-06)**; cloud-init/netplan (`network-config.yaml`, kept for reference) are
  gone, NetworkManager profiles are used instead.
- No Wi-Fi: the frontend connects over `usb0` (`--host 192.168.100.1`). The old card had
  `--host 10.42.0.1` (the Poco's Wi-Fi AP) in `mfd.service`.
- Boot to picture takes longer (single core).

### What was carried over from the old card (verified against the running card, not the docs)

`zero13-image/` holds the exact files written into the new image:

| File | Origin | Notes |
|---|---|---|
| `config.txt` | old card `/boot/firmware/config.txt` | **`dpi_output_format=0x05`** (RGB666 config 1 — the VGA666 is wired for config 1; `0x06` scrambles the bit lanes = the "green cast", fixed 2026-09-08), `dtoverlay=vga666` (not `-6bpc`), `dpi_timings=480 1 24 46 60 240 1 4 3 15 0 0 0 60 0 9600000 1`, `disable_fw_kms_setup=1`, `max_framebuffers=2`, `enable_dpi_lcd=1`, `display_default_lcd=1`, `dpi_group=2`, `dpi_mode=87`, `dtoverlay=dwc2`, `enable_uart=1`. Removed: `arm_64bit=1`. Not added: `vc4-kms-v3d` (the app writes to the firmware framebuffer `/dev/fb0`). |
| `cmdline.txt` | old card | `modules-load=dwc2,g_ether net.ifnames=0 fbcon=map:99 logo.nologo` (+ `resize` for the first boot); PARTUUID is the new image's. |
| `usb0.nmconnection` | old card NetworkManager | static 192.168.100.2/24, gateway 192.168.100.1 |
| `usb0-managed.conf` | old card `/etc/NetworkManager/conf.d/` | **required**: NM's `85-nm-unmanaged.rules` leaves USB gadget interfaces unmanaged, so without it the usb0 profile never activates and the host sees the gadget with NO-CARRIER (first boot of the v1.3 image, 2026-10-14 22:34, missed on the first build; added to the image and the card 2026-10-15) |
| `mfd.service` | old card | identical except `--host 192.168.100.1`; env `SDL_VIDEODRIVER=dummy SDL_FBDEV=/dev/fb0 SDL_AUDIODRIVER=dummy FRAMEBUFFER=/dev/fb0`, `--fullscreen --scale 1 --production` |
| `mfd.service.d-equalizer.conf` | old card drop-in | `MFD_GAIN_R/G/B=1.00` (neutral since the 0x05 fix) |
| `99-framebuffer.rules` | old card | `KERNEL=="fb0", MODE="0666"` |
| `test-pattern.service`, `test_pattern.py` | old card | colour-bar test pattern straight to `/dev/fb0` (disabled; `systemctl start test-pattern` to check the panel) |
| `build-chroot-step.sh` | this build | package install + user + venv inside the image via qemu-user |

Also copied: ssh host keys (laptop/Poco `known_hosts` stay valid), `authorized_keys`, user `piotr`
(uid 1000, same password hash, NOPASSWD sudo, groups incl. video/tty/dialout/gpio), hostname `prius`,
timezone Europe/Warsaw, keyboard pl, `getty@tty1` masked, `/var/log/cyberpunk_computer`, the app tree
`/home/piotr/cyberpunk_computer` (rsync of the host repo with deploy.py's excludes) and
`.venv --system-site-packages` on apt `python3-pygame python3-zmq python3-serial` (no pip builds on ARMv6).

Documentation drift found while checking (fixed in the host repo the same day): `docs/MFD_VIDEO_TIMINGS.md`
listed `vga666-6bpc` + `dpi_output_format=0x00017` and `deployment/README.md` listed `0x06` with the
old (skewed) timings — neither was what the card ran.

### Build procedure (reproducible, laptop)

1. Backup the old card: `sudo dd if=/dev/mmcblk0 bs=4M | zstd -T4 -3 > ~/backups/prius-pi-zero2w-2026-10-14.img.zst`
   (full 29 GB card; restore with `zstd -dc … | sudo dd of=/dev/mmcblk0 bs=4M`).
2. `xz -dkc 2026-10-06-raspios-trixie-armhf-lite.img.xz > prius-mfd-zero13.img`; `truncate -s 6G`,
   `parted resizepart 2 100%`, `losetup -fP`, `resize2fs`; mount p2 then p1 on `boot/firmware`.
3. Write `zero13-image/config.txt`, `cmdline.txt` (keep the image's PARTUUID), `touch boot/firmware/ssh`.
4. Copy the files listed above into the rootfs; `apt install qemu-user qemu-user-binfmt` on the laptop and
   run `build-chroot-step.sh <rootfs>`.
5. `dd if=prius-mfd-zero13.img of=/dev/mmcblkX bs=4M conv=fsync`; first boot expands the root partition.

Image kept at `~/backups/raspios/prius-mfd-zero13-2026-10-14.img` (laptop only; includes the usb0-managed
override and the housekeeping below).

### Bench test 2026-10-15 (`captures/2026-10-15/CAPTURES.md`)

Enumerates as `cdc_ether`, usb0 192.168.100.2 up ≈2 min after power, SSH OK, `/dev/fb0` = BCM2708 FB
480×240 with `dpi_output_format=5` and the 15 kHz timings confirmed by the firmware, GPIO 2–21 in DPI
mode. Frontend renders at **21 fps** with the backend connected (replay from the laptop), ≈10 fps without a
backend; `/dev/fb0` dump = the real dashboard (`captures/2026-10-15/zero13_fb0_replay.png`). Second boot:
first frames ≈130 s after power (NetworkManager 40 s, console/keyboard-setup 43 s, swap resize 26 s —
untouched, see the capture log for the measured chain). Housekeeping on the card and in the image:
cloud-init disabled, journald persistent, userconf ssh banner removed.

### Boot time — measured and tuned 2026-10-15 (`zero13-image/boot-tune.sh`)

Measured on the Pi with `systemd-analyze` / `critical-chain` / journal (times from kernel start):

| Step | first frontend frames | what changed |
|---|---|---|
| as built | ≈130 s (mfd.service at 116 s) | keyboard-setup (43 s) sat in the critical chain before local-fs; NetworkManager 40 s (22 s inside its netplan generator); logrotate/apt timers firing at every boot (clock jumps in the car); rpi-swap resize job 26 s; udisks2, wpa_supplicant, bluetooth with no hardware |
| round 1 | ≈95 s (mfd at 69 s) | mask keyboard/console-setup + swap resize, disable timers and unused services |
| round 2 | ≈60 s (usb0 at 35 s, mfd at 45 s, pygame at 57 s) | systemd-networkd for usb0 instead of NetworkManager; mfd after basic.target |
| round 3 | no change | running the frontend as root gained nothing (reverted to piotr) |

Left: kernel 11 s, SD card at 11 MB/s (`mmc0: Problem switching card into high-speed mode!` — a
faster/other card is the only lever; the Zero 2 W used the same card), `dev-mmcblk0p2` ≈14 s to
settle, python + pygame import ≈12 s cold. A read-only overlay root (user: nothing needs persisting)
is planned as the last step for power-cut robustness; it does not shorten boot. Enable with
`sudo raspi-config nonint enable_overlayfs` (+ reboot), disable with `disable_overlayfs` before deploying code.

Laptop side: NM profile `prius-usb0` (`match.driver cdc_ether`, 192.168.100.1/24, method shared) — the Pi
gets its backend address and internet; `prius_mfd` in `~/.ssh/config` jumps via the Poco, so on the bench use
`ssh piotr@192.168.100.2` directly.
