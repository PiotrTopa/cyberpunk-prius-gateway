#!/bin/sh
# USB Ethernet (CDC ECM) gadget via configfs, bound late and in one step:
# dwc2 is loaded only here (blacklisted otherwise) and the gadget is bound
# immediately after, once udev is idle, so the host never sees a device that
# cannot answer and usb0 is configured by networkd within a fraction of a second.
# Reason: xHCI hosts (P52, POCO) wedge after failed enumeration / early OUT traffic.
# Fixed MACs give the host a stable interface name (enx021e4d000001).
set -e
G=/sys/kernel/config/usb_gadget/prius
modprobe libcomposite
if [ ! -d $G ]; then
  mkdir -p $G && cd $G
  echo 0x2e8a > idVendor; echo 0x0013 > idProduct; echo 0x0100 > bcdDevice; echo 0x0200 > bcdUSB
  mkdir -p strings/0x409
  echo "Raspberry Pi Ltd." > strings/0x409/manufacturer
  echo "Raspberry Pi USB Gadget" > strings/0x409/product
  mkdir -p configs/c.1/strings/0x409; echo "ECM" > configs/c.1/strings/0x409/configuration
  echo 250 > configs/c.1/MaxPower
  mkdir -p functions/ecm.usb0
  echo 02:1e:4d:00:00:01 > functions/ecm.usb0/host_addr
  echo 02:1e:4d:00:00:02 > functions/ecm.usb0/dev_addr
  ln -s functions/ecm.usb0 configs/c.1/
fi
cd $G
udevadm settle -t 30 || true
modprobe dwc2
i=0; while [ -z "$(ls /sys/class/udc 2>/dev/null)" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i+1)); done
ls /sys/class/udc | head -1 > UDC
logger -t usb-gadget "bound $(cat UDC) as $(cat functions/ecm.usb0/ifname)"
