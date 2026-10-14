#!/bin/bash
set -e
N=${1:?mounted rootfs}
mount -t proc proc $N/proc; mount --rbind /sys $N/sys; mount --rbind /dev $N/dev; mount --make-rslave $N/sys; mount --make-rslave $N/dev
if [ -L $N/etc/resolv.conf ]; then mv $N/etc/resolv.conf $N/etc/resolv.conf.link; fi
cp /etc/resolv.conf $N/etc/resolv.conf
printf '#!/bin/sh\nexit 101\n' > $N/usr/sbin/policy-rc.d; chmod +x $N/usr/sbin/policy-rc.d
cleanup() { rm -f $N/usr/sbin/policy-rc.d $N/etc/resolv.conf; [ -e $N/etc/resolv.conf.link ] && mv $N/etc/resolv.conf.link $N/etc/resolv.conf; umount -R $N/dev $N/sys $N/proc 2>/dev/null || true; }
trap cleanup EXIT
chroot $N /bin/bash -e <<'INNER'
export DEBIAN_FRONTEND=noninteractive LC_ALL=C
uname -m
apt-get update -q
apt-get install -y -q --no-install-recommends python3-pygame python3-zmq python3-serial python3-venv rsync avahi-daemon htop vim-tiny
apt-get clean
# user piotr uid 1000 with the old card's password hash and groups
useradd -m -u 1000 -s /bin/bash -G users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,input,gpio,spi,i2c,render,sudo,tty piotr 2>&1 || true
usermod -p '<hash from the old card user-data>' piotr
chown -R piotr:piotr /home/piotr
# venv on system packages (no pip builds on ARMv6)
su piotr -c 'cd /home/piotr/cyberpunk_computer && python3 -m venv --system-site-packages .venv && .venv/bin/python -c "import pygame, zmq, serial; print(pygame.version.ver, zmq.zmq_version())"'
systemctl enable ssh mfd avahi-daemon
systemctl disable userconfig.service regenerate_ssh_host_keys.service 2>&1 || true
systemctl mask getty@tty1.service
systemctl is-enabled rpi-resize.service || true
INNER
echo CHROOT-DONE
