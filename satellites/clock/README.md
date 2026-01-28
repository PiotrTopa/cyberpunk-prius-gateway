# Satellite: Digital Clock (ID 6)

RS485-connected digital clock module for the Cyberpunk Prius Gen 2 project.

## 📋 Specifications

*   **Device ID:** `6`
*   **Bus:** RS485
*   **Protocol:** [Project NDJSON](../../PROTOCOL.md)
*   **Hardware:** RP2040 (e.g., Raspberry Pi Pico) + OLED 0.91" (128x32, SSD1306)

## 🔌 Wiring

### OLED Display
| RP2040 Pin | Function | OLED Pin |
| :--- | :--- | :--- |
| 36 (3V3) | Power | VCC |
| 38 (GND) | Ground | GND |
| 4 (GP2) | I2C1 SDA | SDA |
| 5 (GP3) | I2C1 SCL | SCK/SCL |

### RS485 Module
| RP2040 Pin | Function | Module Pin |
| :--- | :--- | :--- |
| GP12 | UART0 TX | TXD |
| GP13 | UART0 RX | RXD |
| GP14 | DE/RE Control | En |
| 3V3 | Power | VCC |
| GND | Ground | GND |

## 📡 Commands

All commands are wrapped in standard JSON packets.
**Target ID:** `6`

### RX (Host -> Clock)

**1. Set Time**
Updates the DS3231 RTC.
```json
{
  "cmd": "SET_TIME", 
  "args": [2026, 1, 6, 18, 55, 0] // [YYYY, MM, DD, HH, mm, ss]
}
```

**2. Get Time**
Requests current time and temperature.
```json
{
  "cmd": "GET_TIME"
}
```

**3. Display Text**
Displays a temporary message on the OLED.
```json
{
  "cmd": "TEXT", 
  "line1": "HELLO", 
  "line2": "WORLD", 
  "duration": 5 // Seconds (optional, default 5)
}
```

**4. Set Brightness**
Adjusts OLED contrast.
```json
{
  "cmd": "BRIGHTNESS", 
  "val": 255 // 0-255
}
```

### TX (Clock -> Host)

**1. Time Broadcast (Every 10s)**
Or response to `GET_TIME`.
```json
{
  "cmd": "TIME", 
  "val": [2026, 1, 6, 18, 55, 10], 
  "temp": 24.25
}
```

**2. Command Acknowledgment**
```json
{
  "res": "OK", 
  "cmd": "SET_TIME" // Echoed command
}
```
