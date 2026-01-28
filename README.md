# Cyberpunk Prius Gen 2 Project

Comprehensive retro-modding project for the **Toyota Prius Gen 2**, modernizing the vehicle's capabilities while retaining OEM aesthetics.

## 📂 Project Structure

This monorepo contains the following components:

*   **[Gateway](./gateway/)** (`dev_id=0-2`)
    *   RP2040-based bridge for AVC-LAN and CAN networks.
    *   Handles USB communication with the Host.
*   **[Satellites](./satellites/)** (`dev_id=6-255`)
    *   Distributed RS485 modules for controlling vehicle functions.
    *   **[Clock](./satellites/clock/)** (`dev_id=6`): Custom digital clock replacement.

## 📡 Protocol

The system uses a unified **NDJSON** protocol over USB (Host <-> Gateway) and RS485 (Gateway <-> Satellites).

*   **Full Specification:** [PROTOCOL.md](./PROTOCOL.md)

## ⚠️ Disclaimer

For research and educational purposes only. Connect to vehicle networks at your own risk.
