# RP2040 AVC-LAN Gateway

High-performance, hardware-offloaded bridge for Toyota/Lexus AVC-LAN (IEBus) multimedia networks using Raspberry Pi Pico (RP2040).

## 🌃 Project Context: Cyberpunk Prius Gen 2

This Gateway is a core component of a comprehensive "Cyberpunk" retro-modding project for the **Toyota Prius Gen 2**. The system aims to modernize the vehicle's capabilities while retaining OEM aesthetics.

**System Goals:**
*   **OEM Integration:** Reutilize the original dashboard display for custom telemetry and interfaces.
*   **Distributed Control:** Custom RS485 satellite network for decentralized control of vehicular functions (lighting, sensors, actuators).
*   **Deep Telemetry:** Real-time state analysis (button presses, vehicle status) via AVC-LAN and CAN bus interception.

## ⚡ Features

*   **Bidirectional:** Full RX (Sniffer) and TX (Injection).
*   **Hardware Offloading:** PIO State Machines handle microsecond-perfect signal timing.
*   **Zero-Allocation:** Static memory architecture prevents `ENOMEM` / heap fragmentation.
*   **Smart Error Correction:** Auto-corrects bit-shifts caused by physical signal imperfectons.
*   **CAN Integration:** Dedicated SPI-based CAN controller (MCP2515) integration.

## 🔌 Hardware Interface

Designed for **RP2040-Zero**.

**AVC-LAN (IEBus):**
| Signal | Pin | Direction | Notes |
| :--- | :--- | :--- | :--- |
| **RX** | **GP0** | Input | From Comparator (e.g., LM339) |
| **TX** | **GP1** | Output | To Transistor Driver |

**CAN Bus (MCP2515):**
| Signal | Pin | Type | Notes |
| :--- | :--- | :--- | :--- |
| **CS** | **GP5** | SPI CS | Chip Select |
| **INT** | **GP6** | Input | Interrupt |
| **SPI** | **GP2,3,4**| SPI0 | SCK, MOSI, MISO |

*Full wiring details: [docs/wiring.md](docs/wiring.md)*

## 📡 Host Communication Protocol

The Gateway communicates via USB Serial using **NDJSON** (Newline Delimited JSON).

**Full Specification:** [docs/PROTOCOL.md](docs/PROTOCOL.md)

**Quick Summary:**
All messages follow the root structure:
```json
{
  "id": <int>,      // Device ID (0=Sys, 1=CAN, 2=AVC-LAN, >5=Sat)
  "ts": <int>,      // Timestamp (ms)
  "seq": <int>,     // Sequence Counter (Optional, continuity check)
  "d":  <any>       // Payload
}
```

## 🧠 Architecture Notes

*   **PIO:** RX State Machine detects Start Bit (>150µs) and samples bits. TX State Machine generates pulse widths.
*   **Smart Decoding:** Speculatively attempts to decode frames with 0 or +1 bit offset to handle transceiver latency.
*   **Memory:** No dynamic allocation in the hot path. Uses pre-allocated bytearrays and direct stdout writes.

## 🛠️ Usage

1.  Flash standard MicroPython firmware to RP2040.
2.  Upload `main.py` to the device.
3.  Connect to USB Serial.
4.  Gateway sends `{"dev_id":0,"msg":"GATEWAY_READY",...}` on boot.

## 🚧 Project Status

*   [x] **Gateway Core:** Architecture, USB CDC, Zero-Alloc loop.
*   [x] **AVC-LAN:** Hardware-offloaded (PIO) Sniffer & Injector.
*   [x] **Car CAN:** OBDII / Body CAN integration (MCP2515).
*   [ ] **RS485:** Satellite network protocol & physical layer.

## ⚠️ Disclaimer

For research and educational purposes only. Connect to vehicle networks at your own risk.
