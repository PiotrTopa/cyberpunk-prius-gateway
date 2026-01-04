# Satellite: Digital Clock (ID 6)

RS485-connected digital clock module for the Cyberpunk Prius Gen 2 project.

## 📋 Specifications

*   **Device ID:** `6`
*   **Bus:** RS485
*   **Protocol:** [Project NDJSON](../../PROTOCOL.md)
*   **Hardware:** RP2040 (e.g., Raspberry Pi Pico) + OLED 0.91" (128x32, SSD1306)

## 🔌 Wiring (RP2040 Pico -> OLED)

| RP2040 Pin | Function | OLED Pin |
| :--- | :--- | :--- |
| 36 (3V3) | Power | VCC |
| 38 (GND) | Ground | GND |
| 4 (GP2) | I2C1 SDA | SDA |
| 5 (GP3) | I2C1 SCL | SCK/SCL |

## 📡 Commands

**RX (Host -> Clock):**
*   `{"cmd": "SET_TIME", "val": <timestamp>}`
*   `{"cmd": "SET_BRIGHTNESS", "val": <0-100>}`

**TX (Clock -> Host):**
*   `{"status": "OK", "temp": <celsius>}` (if configured with temp sensor)
