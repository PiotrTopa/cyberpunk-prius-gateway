# Raspberry Pi Network Configurations

This folder contains the native Netplan configurations required for the Raspberry Pi Zero 2W that acts as the Prius MFD Gateway. 
This folder contains the network configuration required for the Raspberry Pi Zero 2W that acts as the Prius MFD Gateway. 
Because the custom Debian 13 image uses **cloud-init**, it automatically generates Netplan configurations on boot by reading a `network-config` file from the boot partition.

## Files

- `network-config.yaml`: A combined template configuration for connecting the Pi to both the USB Gadget network (`usb0`) and a local Wi-Fi network. 

## Installation

When flashing a new SD card, DO NOT manually modify `/etc/netplan/` on the root filesystem, as cloud-init will overwrite it. 
Instead, copy the contents of `network-config.yaml`, enter your actual Wi-Fi credentials, and replace the `network-config` file on the `boot` partition (the FAT32 partition that appears when you plug the SD card into Windows/Mac).

```bash
cp network-config.yaml /path/to/sdcard/boot/network-config
```
