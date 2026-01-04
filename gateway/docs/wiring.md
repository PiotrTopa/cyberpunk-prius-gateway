# Hardware Wiring Guide

## 1. AVC-LAN (Existing)
*   **RX:** GP0
*   **TX:** GP1
*   **GND:** Common Ground

## 2. CAN Bus (MCP2515)
We use **SPI0** on the RP2040-Zero.

| MCP2515 Pin | RP2040-Zero Pin | Function | Notes |
| :--- | :--- | :--- | :--- |
| **VCC** | 5V | Power | TJA1050 requires 5V. |
| **GND** | GND | Ground | |
| **CS** | **GP5** | SPI CS | Chip Select |
| **SO** | **GP4** | SPI RX | MISO |
| **SI** | **GP3** | SPI TX | MOSI |
| **SCK** | **GP2** | SPI SCK | Clock |
| **INT** | **GP6** | Interrupt | Active Low |

### ⚠️ Voltage Levels Warning
The MCP2515 module typically runs at 5V. The RP2040 is 3.3V.
1.  **MISO (SO) Protection:** The `SO` pin may output 5V. **Use a voltage divider (e.g., 2kΩ/3kΩ) or level shifter** to protect the RP2040 `GP4` pin.
2.  **Logic Thresholds:** 3.3V logic high from RP2040 is formally out of spec for a 5V-powered MCP2515 (needs ~3.5V), but usually works in practice. For vehicle reliability, a bidirectional Logic Level Converter (LLC) is recommended.

### 🔧 Jumpers Configuration

*   **J1 (Termination):** Connects a 120Ω resistor between CAN-H and CAN-L.
    *   **IN CAR (OBDII/Tap):** **REMOVE** (Open). The vehicle bus is already terminated. Adding it may corrupt the bus.
    *   **ON DESK (Bench Test):** **INSTALL** (Closed) if you only have 2 devices.
*   **H / L:** These are the **Signal Terminals** (CAN High / CAN Low), not jumpers. Connect them to the twisted pair in the vehicle.
