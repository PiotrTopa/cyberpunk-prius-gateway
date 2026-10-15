#!/bin/bash
# Boot-time tuning for the Prius MFD board (Pi Zero v1.3, Raspberry Pi OS Lite 32-bit).
# Idempotent. Run on the Pi (sudo) or inside the image with: chroot <rootfs> /path/boot-tune.sh
# Measured 2026-10-15 (journal monotonic, i.e. from kernel start):
#   before: first frontend frames at ~130 s (mfd.service started at 116 s)
#   after : first frontend frames at ~60 s  (usb0 up at 35 s, mfd.service at 45 s, pygame up at 57 s)
# What is left is hardware: SD card reads at 11 MB/s ("Problem switching card into high-speed
# mode"), dev-mmcblk0p2 takes ~14 s to settle, python+pygame import ~12 s cold.
set -u
D=$(dirname "$(readlink -f "$0")")

# 1. No console, no keyboard: keyboard-setup sat in the critical chain BEFORE local-fs (43 s).
systemctl mask keyboard-setup.service console-setup.service

# 2. Swap: drop rpi-swap (26 s/boot resize job); zram via systemd-zram-generator instead.
if dpkg -s rpi-swap >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get -y -q remove rpi-swap; fi
install -d /etc/systemd/zram-generator.conf.d
install -m 644 "$D/zram-generator-50-prius.conf" /etc/systemd/zram-generator.conf.d/50-prius.conf

# 3. Hardware that does not exist / services an appliance does not need.
systemctl disable udisks2.service wpa_supplicant.service bluetooth.service e2scrub_reap.service 2>/dev/null
# 4. Maintenance timers: with Persistent=yes they all fire at every boot in the car (clock jumps);
#    logrotate alone took 39 s. The journal is size-capped and the app rotates its own log.
for t in apt-daily.timer apt-daily-upgrade.timer man-db.timer dpkg-db-backup.timer e2scrub_all.timer logrotate.timer; do
  systemctl disable "$t" 2>/dev/null; systemctl mask "$t"
done
# 5. cloud-init (28 s/boot, only used by Raspberry Pi Imager customisation).
touch /etc/cloud/cloud-init.disabled

# 6. Network: systemd-networkd for the single static usb0 instead of NetworkManager.
install -d /etc/systemd/network
install -m 644 "$D/10-usb0.network" /etc/systemd/network/10-usb0.network
systemctl enable systemd-networkd.service
systemctl disable NetworkManager.service NetworkManager-wait-online.service 2>/dev/null
systemctl mask NetworkManager.service
printf 'nameserver 192.168.100.1\n' > /etc/resolv.conf

# 7. Frontend: start right after basic.target (it reconnects to the backend by itself).
sed -i 's/^After=network.target$/After=basic.target/' /etc/systemd/system/mfd.service
rm -f /etc/systemd/system/mfd.service.d/early-start.conf
systemctl daemon-reload 2>/dev/null || true
echo "boot-tune applied"
