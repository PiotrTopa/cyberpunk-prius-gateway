# CAN Bus Test Bench

This folder contains tools to emulate a Toyota Prius Gen 2 CAN bus for testing the Gateway without a real vehicle.

## 🛠️ Hardware Setup

To create a valid CAN signal, we use a second **RP2040-Zero** coupled with an **MCP2515 Module**.

> **Note on SN65HVD230:** While this module is a valid 3.3V transceiver, the RP2040 does not have a native CAN controller. Using a transceiver directly requires a complex software-defined CAN controller (PIO) which often requires custom C-firmware. For simplicity and Python compatibility, we recommend using an **MCP2515** module for the emulator as well.

### Wiring (Emulator)

Connect the Emulator Pico to the MCP2515 exactly like the Gateway:

| MCP2515 Pin | Emulator Pico Pin |
| :--- | :--- |
| **VCC** | 5V |
| **GND** | GND |
| **CS** | **GP5** |
| **SO** | **GP4** |
| **SI** | **GP3** |
| **SCK** | **GP2** |
| **INT** | **GP6** |

### Bus Connection
Connect the **Gateway** and **Emulator** CAN lines together:
*   Gateway **CAN-H** <--> Emulator **CAN-H**
*   Gateway **CAN-L** <--> Emulator **CAN-L**

**Termination:** Ensure **at least one** MCP2515 module has the **J1 jumper INSTALLED** (120Ω resistor) to terminate the bus. Ideally, both ends should be terminated for long wires, but for a short test bench, one is often enough.

## 💾 Software Setup

1.  Flash MicroPython to the **Emulator Pico**.
2.  Copy `mcp2515.py` (from the root project folder) to the Emulator Pico.
3.  Copy `test-bench/can_emulator.py` to the Emulator Pico as `main.py`.
4.  Copy `test-bench/prius_can_dump.jsonl` to the Emulator Pico.

## 🚗 Simulation Data

The emulator plays back `prius_can_dump.jsonl`, which contains a synthetic sequence:
1.  Ignition ON
2.  Engine Idle
3.  Acceleration (Speed/RPM increase)
4.  Cruising
5.  Door events

The cycle repeats indefinitely.
