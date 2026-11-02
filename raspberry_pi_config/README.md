# Raspberry Pi MFD video board — configuration as deployed

The Pi drives the Prius MFD over DPI (VGA666 resistor DAC, 480×240 @ 15 kHz) and talks to the
car computer (Poco F1) over a USB Ethernet gadget `usb0` (Pi 192.168.100.2, host 192.168.100.1).
The Pi is **only** the display driver; the backend runs on the Poco.

## Board and OS

- **Raspberry Pi Zero v1.3** (BCM2835, ARMv6, single core, 512 MB, no Wi-Fi/BT). This is the board
  of record; there is no plan to change it.
- **Raspberry Pi OS Lite 32-bit (Trixie, 2026-10-06)**, kernel `6.18.50+rpt-rpi-v6`, hostname `prius`,
  user `piotr` (uid 1000, NOPASSWD sudo).
- The frontend connects to the backend over `usb0` only (`--host 192.168.100.1`).

## Files in `zero13-image/`

The exact files written into the image (and running on the card):

| File | Installed as | Notes |
|---|---|---|
| `config.txt` | `/boot/firmware/config.txt` | **`dpi_output_format=0x05`** (RGB666 config 1 — the VGA666 is wired for config 1; `0x06` scrambles the bit lanes), `dtoverlay=vga666` (not `-6bpc`), `dpi_timings=480 1 24 46 60 240 1 4 3 15 0 0 0 60 0 9600000 1`, `disable_fw_kms_setup=1`, `max_framebuffers=2`, `enable_dpi_lcd=1`, `display_default_lcd=1`, `dpi_group=2`, `dpi_mode=87`, `dtoverlay=dwc2,dr_mode=peripheral`, `arm_boost=1`, `enable_uart=1`. No `vc4-kms-v3d` (the app writes to the firmware framebuffer `/dev/fb0`). |
| `cmdline.txt` | `/boot/firmware/cmdline.txt` | `net.ifnames=0 fbcon=map:99 logo.nologo` (+ `resize` for the first boot). **No `modules-load`** (see USB gadget). PARTUUID is the image's. |
| `usb-gadget-ecm.sh` | `/usr/local/sbin/` | creates and binds the configfs ECM gadget (see below) |
| `g-ether.service` | `/etc/systemd/system/` | runs the gadget script after networkd and udev trigger |
| `modprobe-dwc2-late.conf` | `/etc/modprobe.d/dwc2-late.conf` | `blacklist dwc2` (must also be in the initramfs) |
| `10-usb0.network` | `/etc/systemd/network/` | static 192.168.100.2/24, gw/DNS .1, no IPv6/link-local, `ConfigureWithoutCarrier=yes` |
| `mfd.service` | `/etc/systemd/system/` | `--host 192.168.100.1 --fullscreen --scale 1 --production`, env `SDL_VIDEODRIVER=dummy SDL_FBDEV=/dev/fb0 SDL_AUDIODRIVER=dummy FRAMEBUFFER=/dev/fb0`, After=basic.target |
| `mfd.service.d-equalizer.conf` | `/etc/systemd/system/mfd.service.d/equalizer.conf` | `MFD_GAIN_R/G/B=1.00` |
| `99-framebuffer.rules` | `/etc/udev/rules.d/` | `KERNEL=="fb0", MODE="0666"` |
| `zram-generator-50-prius.conf` | `/etc/systemd/zram-generator.conf.d/50-prius.conf` | 256 MB zram swap (rpi-swap removed) |
| `test-pattern.service`, `test_pattern.py` | | colour bars straight to `/dev/fb0` (disabled; `systemctl start test-pattern` to check the panel) |
| `build-chroot-step.sh` | | package install + user + venv inside the image via qemu-user |
| `boot-tune.sh` | | idempotent boot tuning + USB gadget install (run on the Pi or in a chroot) |

Also in the image: ssh host keys and `authorized_keys`, timezone Europe/Warsaw, keyboard pl,
`getty@tty1` masked, `/var/log/cyberpunk_computer`, the app tree `/home/piotr/cyberpunk_computer`
(rsync of the host repo with deploy.py's excludes) and `.venv --system-site-packages` on apt
`python3-pygame python3-zmq python3-serial` (no pip builds on ARMv6), journald persistent,
cloud-init disabled, NetworkManager masked (systemd-networkd handles `usb0`).

## USB gadget (xHCI-safe)

xHCI hosts (the P52 laptop, the Poco's dwc3) wedge their bulk-OUT path to this gadget when they see
a pulled-up device that cannot answer (failed enumerations) or transmit before `usb0` is up: the host
then logs `NETDEV WATCHDOG: transmit queue 0 timed out`, Pi→host traffic still flows, host→Pi is dead.
EHCI hosts are not affected. The gadget is therefore brought up late and in one step:

1. `dwc2` is blacklisted (`/etc/modprobe.d/dwc2-late.conf`, baked into the initramfs) and not in
   `cmdline.txt`, so the controller does not pull up D+ during boot.
2. `g-ether.service` (after systemd-networkd and udev trigger) runs `usb-gadget-ecm.sh`: create the
   configfs gadget (IDs `2e8a:0013`, "Raspberry Pi USB Gadget", CDC ECM, host MAC `02:1e:4d:00:00:01`,
   Pi MAC `02:1e:4d:00:00:02`), `udevadm settle`, `modprobe dwc2`, write the UDC.
3. networkd configures `usb0` within ~0.5 s of the bind, before the host has finished enumerating.

Measured on the P52 (2026-11-02): one clean high-speed enumeration at ≈43 s after power, dwc2 load →
bind 0.15 s, `usb0` up 0.3 s after SET_ADDRESS, no failed attempts, no TX watchdogs. The fixed host MAC
gives the host a stable interface name `enx021e4d000001`.

After any change in `/etc/modprobe.d`: `sudo update-initramfs -u -k 6.18.50+rpt-rpi-v6` (~2 min,
copies to `/boot/firmware/initramfs`).

Recovering a host that is already wedged: P52 `xhci_hcd` unbind/bind of `0000:00:14.0`; Poco: the backend
MFD watchdog VBUS-cycles the Pi, else dwc3 unbind/bind (`a600000.usb`).

## Boot time

Measured on the Pi with `systemd-analyze` / journal (times from kernel start):

| Step | first frontend frames | what changed |
|---|---|---|
| as built | ≈130 s (mfd.service at 116 s) | keyboard-setup (43 s) in the critical chain; NetworkManager 40 s; logrotate/apt timers at every boot (clock jumps in the car); rpi-swap resize 26 s; udisks2, wpa_supplicant, bluetooth with no hardware |
| tuned | ≈60 s (mfd at ≈37 s, pygame ≈57 s) | `boot-tune.sh`: masks, timers off, systemd-networkd for usb0, mfd after basic.target, zram |
| gadget late bind | link at ≈43 s | xHCI-safe gadget (above); the picture does not wait for the link |

Left: kernel 11 s, SD card at 11 MB/s (`mmc0: Problem switching card into high-speed mode!` — a
faster card is the only lever), `dev-mmcblk0p2` ≈14 s to settle, python + pygame import ≈12 s cold.
A read-only overlay root (nothing needs persisting) is planned for power-cut robustness:
`sudo raspi-config nonint enable_overlayfs` (+ reboot), `disable_overlayfs` before deploying code.

Frontend: ≈21 fps with the backend connected, ≈10 fps without.

## Build procedure (reproducible, laptop)

1. `xz -dkc 2026-10-06-raspios-trixie-armhf-lite.img.xz > prius-mfd-zero13.img`; `truncate -s 6G`,
   `parted resizepart 2 100%`, `losetup -fP`, `resize2fs`; mount p2 then p1 on `boot/firmware`.
2. Write `zero13-image/config.txt`, `cmdline.txt` (keep the image's PARTUUID), `touch boot/firmware/ssh`.
3. Copy the files listed above into the rootfs; `apt install qemu-user qemu-user-binfmt` on the laptop and
   run `build-chroot-step.sh <rootfs>`, then `chroot <rootfs> /path/boot-tune.sh`.
4. `dd if=prius-mfd-zero13.img of=/dev/mmcblkX bs=4M conv=fsync`; first boot expands the root partition.

Base image: `~/backups/raspios/2026-10-06-raspios-trixie-armhf-lite.img.xz` (laptop).

## Host side

- Laptop (P52): NM profile `prius-usb0` (`match.driver cdc_ether`, 192.168.100.1/24, method shared);
  on the bench use `ssh piotr@192.168.100.2` directly (`prius_mfd` in `~/.ssh/config` jumps via the Poco).
- Any other Linux host: `ip link set enx021e4d000001 up; ip addr add 192.168.100.1/24 dev enx021e4d000001`.
