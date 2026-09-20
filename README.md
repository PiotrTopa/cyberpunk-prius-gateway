# Cyberpunk Prius Gen 2 Project

Comprehensive retro-modding project for the **Toyota Prius Gen 2**, modernizing the vehicle's capabilities while retaining OEM aesthetics.

## 📂 Project Structure

This monorepo contains the following components:

*   **[Gateway v3](./gateway-rp2350/)** (`dev_id=0-2`) — current firmware
    *   RP2350-Zero, C / pico-sdk. Immediate AVC-LAN frame delivery, solicited-only CAN, RS485 tunnel.
*   **[Gateway v2.x](./gateway/)** — previous MicroPython firmware (RP2040-Zero), kept for reference.
    *   Wiring and AVC-LAN PHY documentation in `gateway/docs/` still applies to v3 (same pinout).
*   **[Satellites](./satellites/)** (`dev_id>5`)
    *   Distributed RS485 modules for controlling vehicle functions.
    *   Bus overview, device map, maintenance and OTA procedures:
        **[satellites/README.md](./satellites/README.md)**
    *   **[VFD](./satellites/vfd/)** (`dev_id=110`): 256×48 GP1294AI energy dashboard + canvas.
    *   **[Light](./satellites/light/)** (`dev_id=106`): DRL & BiLED headlight control.
    *   **[Clock](./satellites/clock/)** (`dev_id=6`): Custom digital clock replacement.

## 📡 Protocol

The system uses a unified **NDJSON** protocol over USB (Host <-> Gateway) and RS485 (Gateway <-> Satellites).

*   **Full Specification:** [PROTOCOL.md](./PROTOCOL.md)

## ⚠️ Disclaimer

For research and educational purposes only. Connect to vehicle networks at your own risk.
