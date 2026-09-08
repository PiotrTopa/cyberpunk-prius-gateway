# AVC-LAN Physical Interface (PHY) — Reference for Rebuild

Reverse-documented 2026-09-08 from `docs/schematic.json` (EasyEDA netlist —
authoritative) cross-checked against `docs/schematic.png` and the PIO
configuration in `main.py`. This is the circuit between the Prius AVC-LAN
twisted pair and the RP2040-Zero (GP0 RX / GP1 TX).

AVC-LAN is Toyota's IEBus variant: a differential two-wire bus, pulse-width
encoded, dominant state = Data+ pulled above Data−. The PHY has two
independent halves sharing the bus connector H1.

## Connector

| H1 pin | Signal |
|--------|--------|
| 1      | Data − |
| 2      | Data + |

No GND pin on H1 — ground is common through the 12V supply input.

## Power rails

- **U3: buck converter 12 V → 5 V.** Feeds ONLY the analog rail: LM339 VCC
  (pin 3), Q2 emitter, and R6. The buck input is car 12 V (ACC).
- **RP2040-Zero is powered from USB.** Its 5V pin (23) is NOT connected in
  the schematic. All grounds (buck GND, LM339 pin 12, Q1 emitter, RP2040
  GND) are one net.
- **Bench gotcha:** with USB only (no 12 V), the MCU enumerates but the
  AVC-LAN front-end is completely dead — both RX comparator and TX driver
  run from the buck's 5 V rail.

## RX: LM339 differential comparator (unit 1 of 4)

```
Data+ (H1.2) ──R1 100k──► LM339 IN1−  (pin 4)
Data− (H1.1) ──R2 100k──► LM339 IN1+  (pin 5)
LM339 VCC (pin 3)  = analog 5 V rail
LM339 GND (pin 12) = GND
LM339 OUT1 (pin 2) ──┬──► RP2040 GP0
                     └──R3 4.7k──► RP2040 3V3 (pin 21)
```

- Open-collector output pulled up to **3.3 V** (not 5 V!) — this is the
  level-shifting trick: the comparator runs at 5 V for input common-mode
  range, but GP0 never sees more than 3V3. Keep this in the rebuild.
- Polarity: **dominant (Data+ > Data−) → GP0 LOW**. The PIO RX program
  (`avclan_rx_framed`) confirms it: idle waits for `wait(0, pin)` as the
  start condition and qualifies it low for ~32 µs before syncing.
- There is deliberately NO bias network and NO hysteresis — a pure
  differential compare through 100 k series resistors (which double as
  input protection). It works because IEBus dominant differential is
  ~120 mV+ and the bus common mode sits inside the LM339 input range
  (0 … VCC−1.5 V).
- Optional rebuild improvements (not present in the original, both safe):
  ~1 MΩ positive feedback from OUT1 to pin 5 for a few mV of hysteresis;
  100 nF decoupling at LM339 VCC (do add this one).

## TX: discrete push-pull dominant driver, high-Z recessive

```
GP1 ──R4 4.7k──► Q1 base (BC547 NPN), Q1 emitter ──► GND
Q1 collector ──┬──R5 1k──► Q2 base (BC327 PNP)
               │           Q2 base ──R6 10k──► 5 V rail   (holds Q2 off)
               └──D2 1N4007W──R8 47Ω──► Data− (H1.1)
Q2 emitter ──► 5 V rail
Q2 collector ──D1 1N4007W──R7 47Ω──► Data+ (H1.2)
```

Operation:
- **GP1 HIGH = drive dominant.** Q1 saturates → its collector goes low,
  which (a) sinks Data− toward GND through D2+R8, and (b) pulls Q2's base
  low through R5, turning the PNP on so it sources Data+ toward 5 V
  through D1+R7. Differential drive ≈ 5 V − 2·V(diode) − V(ce,sat)×2 across
  ~94 Ω of series resistance.
- **GP1 LOW = recessive/high-Z.** Q1 off; R6 holds Q2 off; both diodes
  block back-feed from the bus, so the driver presents no load. The bus
  idles at the head unit's own bias.
- Firmware: `tx_phy = Pin(TX_PIN, Pin.OUT, value=0)` — GP1 idles LOW ✓,
  the PIO TX state machine (sideset on GP1) generates the pulse widths.
- Rebuild note: 1N4007 is a slow rectifier and still works at IEBus pulse
  widths (tens of µs), but 1N4148 (or BAT54 Schottky for lower drop /
  slightly hotter drive) is the better choice in a new build. Keep the
  47 Ω values — they set the drive impedance the bus expects.

## RP2040 firmware contract (what the PHY must satisfy)

- `RX_PIN = GP0`, `TX_PIN = GP1`; both PIO state machines run at
  `freq = 1 MHz` (1 µs per instruction — all pulse-width constants in
  `main.py` are in these units).
- RX signal on GP0: idle HIGH, dominant LOW, clean edges (open-collector +
  4.7k pull-up gives ~µs rise on a few dozen pF — fine at IEBus speeds).
- TX signal on GP1: HIGH = assert dominant. Never idle high (that would
  jam the bus).

## Complete new-gateway pin map (unchanged from wiring.md, for one sheet)

| Function | RP2040-Zero pin |
|----------|-----------------|
| AVC-LAN RX (from LM339) | GP0 |
| AVC-LAN TX (to Q1 base via 4.7k) | GP1 |
| MCP2515 SCK / MOSI / MISO / CS / INT | GP2 / GP3 / GP4 / GP5 / GP6 |
| RS485 EN / TX / RX (UART1, 115200) | GP7 / GP8 / GP9 |

MCP2515 at 5 V needs the MISO divider/level shifter (see wiring.md); CAN
500 kbps; SPI 4 MHz.

## BOM (AVC-LAN PHY only)

| Ref | Part | Value/Type |
|-----|------|-----------|
| U2  | LM339 (1 unit used) | quad comparator, SOP-14 |
| U3  | Buck module | 12 V → 5 V |
| Q1  | BC547 | NPN |
| Q2  | BC327 | PNP |
| D1, D2 | 1N4007W (SOD-123) | rectifier (1N4148 recommended in rebuild) |
| R1, R2 | 100 kΩ | comparator input series |
| R3  | 4.7 kΩ | GP0 pull-up to 3V3 |
| R4  | 4.7 kΩ | GP1 → Q1 base |
| R5  | 1 kΩ | Q1 collector → Q2 base |
| R6  | 10 kΩ | Q2 base pull-up to 5 V |
| R7, R8 | 47 Ω | bus drive series |
| H1  | 2-pin header | Data−, Data+ |
