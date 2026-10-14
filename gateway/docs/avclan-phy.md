# AVC-LAN Physical Interface (PHY) — Reference for Rebuild

Reverse-documented 2026-09-08 from `docs/schematic.json` (EasyEDA netlist —
authoritative) cross-checked against `docs/schematic.png` and the PIO
configuration in `main.py`. This is the circuit between the Prius AVC-LAN
twisted pair and the RP2040-Zero (GP0 RX / GP1 TX).

AVC-LAN is Toyota's IEBus variant: a differential two-wire bus, pulse-width
encoded, dominant state = Data+ pulled above Data−. The PHY has two
independent halves sharing the bus connector H1.

## Connector — ⚠ LABEL BUG IN THE ORIGINAL SCHEMATIC

The original EasyEDA schematic prints "Data −" on H1's TOP pin and
"Data +" on the BOTTOM pin, but the netlist proves those text labels are
**swapped relative to electrical function**:

- the TOP pin is the one Q2 *sources toward 5 V* during dominant and the
  one feeding the comparator's INVERTING input — that is the bus **Data+**
  (IEBus dominant = Data+ pulled above Data−);
- the BOTTOM pin is sunk to GND during dominant and feeds IN+ — that is
  **Data−**.

Both RX polarity (firmware needs GP0 idle-HIGH / dominant-LOW, which
requires Data+ → IN−) and TX drive direction confirm this. The built
board works, so the car harness is attached per FUNCTION, not per the
printed labels.

**For the rebuild, wire by function and verify, don't trust the old
silk/labels:**

| H1 pin (top/bottom in schematic) | Electrical function | Connects to |
|----------------------------------|---------------------|-------------|
| TOP ("Data −" printed — wrong)   | **Data +**          | R1 → LM339 IN− (4); D1+R7 from Q2 |
| BOTTOM ("Data +" printed — wrong)| **Data −**          | R2 → LM339 IN+ (5); D2+R8 from Q1 |

Sanity checks after wiring: (1) with the bus connected and idle, **GP0
must sit HIGH**; if it idles low or chatters, the pair is swapped — valid
only once the RX threshold bias (below) is fitted; without it the idle level
is undefined and this check misleads (it did, 2026-10-07/08).
(2) On a scope, the line that pulses upward during bus traffic is Data+.

No GND pin on H1 — ground is common with board GND (RP2040 GND).

## Power rails

- **Shared 5V rail:** The LM339 VCC (pin 3), Q2 emitter, and R6 pull-up are powered directly from the same 5 V rail as the RP2040 (RP2040 5V / USB 5V). There is **no separate buck converter** for the LM339 front-end.
- **Bench operation:** Powering the RP2040 via USB automatically powers the entire AVC-LAN PHY (both LM339 RX comparator and discrete push-pull TX driver). No external 12V bench supply is needed for the PHY to operate.
- All grounds (LM339 pin 12, Q1 emitter, RP2040 GND) are one common ground.

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
- ⚠ **Measured 2026-10-08 (see "RX threshold bias" below): a zero-threshold
  compare does NOT work reliably.** With |Vdiff| ≤ 20 mV at idle the output
  rests wherever offset and bias current put it, which on the built board
  happened to be the *dominant* level in half of the wiring combinations
  ("pinned" / "deaf" receiver, loopback never passing). A recessive bias of
  ~100–160 mV is required.
- Hysteresis, if ever added: with the 100 k series inputs a feedback resistor
  R_h from OUT (3.3 V swing) gives ΔV ≈ 3.3 V · 100 k / (R_h + 100 k). 1 MΩ
  is ≈300 mV (far too much); ~11 MΩ for 30 mV. 100 nF decoupling at LM339
  VCC: do add.

### ⚠ The built board is NOT the schematic above — measured 2026-10-14 (scope + meter)

Superseded parts of the two sections above are kept for history; this is the authoritative state.

| Item | Doc / assumed | Built board (measured) |
|---|---|---|
| R1, R2 series input resistors | 100 kΩ | **10 kΩ** (9.62 k / 9.87 k) |
| hysteresis | none | **470 kΩ pin 1 → pin 7**, on the board since the first revision — **removed 2026-10-14** |
| bias | none (2 MΩ 3V3 → pin 7 added 10-08, moved to pin 6 10-13) | **220 kΩ pin 6 → GND**, undocumented — **GND end moved to LM339 pin 3 (5 V) 2026-10-14** |
| comparator unit | unit 1 | unit 2 (pins 6/7/1) |
| input hookup | — | H1 **left (T, Q2-driven) → pin 7 IN+**, H1 right → pin 6 IN− (user's cross of 10-12 kept) |
| car bus | — | common mode ≈2.6 V; idle white − brown ≈ +50 mV; dominant: brown (Data−) −0.5 V, white (Data+) +0.1 V |

Why nothing worked before (numbers with 10 k inputs, car line ≈2.6 V):

| Element | Shift on its pin, car | Bench (line ≈0 V) |
|---|---|---|
| 2 MΩ from 3V3 into pin 6 | +3.5 mV | +16 mV |
| 220 kΩ to GND on pin 6 | **−113 mV** | 0 |
| 470 kΩ feedback on pin 7, OUT high / low | +17 / −52 mV | +69 / 0 mV |
| 10x scope probe on a pin | −2.6 mV | 0 |

The 2 MΩ "bias" never decided anything. The idle state was the pull-down plus the feedback latch, so
the receiver only ever worked with Data− on pin 7 (the dominant dip on Data− is the only thing that
could flip it), and our own driver, which raises T, was invisible in loopback in that orientation.
The 10-12 "lift" hypothesis (Q2/D1 leak) was wrong; the 12 kΩ bleeder BC327 collector → GND added
2026-10-13 is harmless and left in place. Yesterday's bench pass was the 470 kΩ (+69 mV at 0 V) pointing
the same way as the test.

**Correct configuration (as of 2026-10-14, in the car, RX and TX both pass):**

```
H1 left  = T  = car WHITE (Data+) ──R1 10k──► LM339 pin 7 (IN+)
H1 right = T̄  = car BROWN (Data−) ──R2 10k──► LM339 pin 6 (IN−) ◄──220k── pin 3 (5 V)
LM339 pin 1 (OUT) ──4k7── 3V3, ──► GP0;   no feedback resistor;   firmware pol = hi
```

Pin 6 idles ≈ +105 mV above Data− in the car (+215 mV on the bench), so OUT idles low; a dominant (Data+
up, Data− down, ≈0.6 V differential) or our own 4.5 V drive on T flips OUT high. Margin at idle: the car's
own idle offset (≈50 mV, white above brown) must stay below ≈105 mV; a 150 kΩ instead of 220 kΩ gives
150 mV if that ever proves tight. Acceptance in the car: `avc_cfg pol:hi`, `cfg test avc` → `0,1,0`
(a sample may read 1,1,1 if a bus frame is in flight), car frames decode with 0 errors, own TX echoes.

How it was found (keep for the next board): comparator pins measured against their own H1 lines at
50 mV/div with both scope channels first checked on the same point (CH2 read +50 mV high); then the
bare board (H1 unplugged) showed pin 6 at 0.52 V where ≈2.7 V was expected; then 208 kΩ pin 6 → GND
with the LM339 out of its socket.

### RX threshold bias (required) and acceptance test — measured 2026-10-08 (superseded above)

On the built board the comparator in use is **LM339 unit 2: IN− = pin 6,
IN+ = pin 7, OUT = pin 1** (not unit 1 as drawn above). The line Q2 sources
(TX Data+, the *left* H1 pin with the connector facing down) feeds **pin 6
(IN−)**; the line Q1 sinks feeds **pin 7 (IN+)**. Our own dominant therefore
drives OUT **low** → firmware `pol lo`.

Fix: **2 MΩ from 3V3 to pin 7 (IN+)** → +160 mV on IN+ through the 100 k
series resistor (4.7–10 MΩ from 5 V, 100–50 mV, also fine). Idle then reads
recessive (OUT high) by design, a dominant from the bus *or from our own
driver* reads OUT low.

Acceptance test (bench, H1 off the car, load GND–1 k–left–1 k–right–1 k–GND,
no scope probe on pins 6/7 — 15 pF there delays the release edge by ~5 µs):
`{"a":"cfg","test":"avc"}` must return `rx_idle=0, rx_drive=1, rx_after=0`
with `pol lo`. Without the bias it returns no change (0,0,0 or 1,1,1).
After `tx_high`/`tx_low` holds, `reset` the gateway (stale TX FIFO word).

Known timing (bench, 4 V swing): TX releases ~2 µs late (Q2 tail), RX output
rises ~3 µs after the line falls (input RC + LM339 at low overdrive); the
car's own frames decode with 7 µs gaps intact. Candidate improvements, not
yet applied: R6 → 1 k + 100 pF across R5 (TX tail); R1/R2 → 10 k with the
bias resistor scaled to ~200 k (RX delay).

## TX: discrete push-pull dominant driver, high-Z recessive

```
GP1 ──R4 2.2k──► Q1 base (BC547 NPN), Q1 emitter ──► GND
Q1 collector ──┬──R5 2.2k──► Q2 base (BC327 PNP)
               │             Q2 base ──R6 1k──► 5 V rail   (holds Q2 off)
               └──|◄── D2 BAT54 ──R8 68Ω── Data− (H1.1)   [Cathode to Q1, Anode to R8]
Q2 emitter ──► 5 V rail
Q2 collector ──►|── D1 BAT54 ──R7 68Ω──► Data+ (H1.2)
```

![AVC-LAN PHY Rebuild Schematic](avclan-phy-rebuild.png)

### ⚠ Critical Physical Fix: D2 Orientation

Because Q1 is an NPN transistor sinking current to ground during dominant state, current flows **from** Data− **into** Q1 collector. Therefore:
- **D2 Cathode must connect to Q1 collector, Anode to R8 / Data−** (`Data− ── R8 ──►|── Q1 collector`).
- If D2 is installed with cathode toward Data− (as appeared in earlier rebuild diagrams), Q1 is blocked from sinking Data−, disabling dominant drive on Data−.

### Component Tuning & Upgrades:
- **D1, D2 (BAT54 / 1N4148W / BAS16):** Replace slow 1N4007W power rectifiers ($t_{rr} \sim \mu\text{s}$) with fast Schottky diodes (**BAT54**, $t_{rr} < 5\text{ ns}$, $V_f \approx 0.35\text{ V}$) or fast silicon switching diodes (**1N4148W / BAS16**, $t_{rr} < 4\text{ ns}$). Eliminates reverse-recovery charge trapping and pulse width distortion.
- **R4 (4.7 kΩ → 2.2 kΩ):** Guarantees hard saturation of Q1 from 3.3 V logic ($I_B \approx 1.2\text{ mA}$).
- **R5 (1 kΩ → 2.2 kΩ):** Prevents excessive overdrive/saturation of Q2, lowering stored base charge.
- **R6 (10 kΩ → 1 kΩ):** Strong base pull-up for Q2 to the 5 V rail; provides rapid base charge sweep-out when Q1 turns off, eliminating the turn-off tail.
- **R7, R8 (47 Ω → 68 Ω or 82 Ω):** Calibrates the differential drive voltage $V_{diff}$ across vehicle IEBus termination to nominal $\approx 0.8\text{ V} - 1.0\text{ V}$.

Operation:
- **GP1 HIGH = drive dominant.** Q1 saturates → its collector goes low,
  which (a) sinks Data− toward GND through D2+R8, and (b) pulls Q2's base
  low through R5, turning the PNP on so it sources Data+ toward 5 V
  through D1+R7. Differential drive ≈ 5 V − 2·V(diode) − V(ce,sat)×2 across
  ~136 Ω (or ~164 Ω) of driver series resistance.
- **GP1 LOW = recessive/high-Z.** Q1 off; R6 holds Q2 off; both diodes
  block back-feed from the bus, so the driver presents no load. The bus
  idles at the head unit's own bias.
- Firmware: `tx_phy = Pin(TX_PIN, Pin.OUT, value=0)` — GP1 idles LOW ✓,
  the PIO TX state machine (sideset on GP1) generates the pulse widths.

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
| AVC-LAN TX (to Q1 base via 2.2k) | GP1 |
| MCP2515 SCK / MOSI / MISO / CS / INT | GP2 / GP3 / GP4 / GP5 / GP6 |
| RS485 EN / TX / RX (UART1, 115200) | GP7 / GP8 / GP9 |

MCP2515 at 5 V needs the MISO divider/level shifter (see wiring.md); CAN
500 kbps; SPI 4 MHz.

## BOM (AVC-LAN PHY only)

| Ref | Part | Value/Type | Notes |
|-----|------|------------|-------|
| U2  | LM339 (1 unit used) | quad comparator, SOP-14 | Powered from 5V rail (shared with RP2040), 100 nF decoupling |
| Q1  | BC547 | NPN (SOT-23 / TO-92) | dominant sink driver |
| Q2  | BC327 | PNP (TO-92 / SOT-23) | dominant source driver |
| D1, D2 | BAT54 (or 1N4148W / BAS16) | Schottky / fast switching ($t_{rr} < 4\text{ ns}$) | SOD-123 / SOT-23. D2 Cathode → Q1 collector, Anode → R8 |
| R1, R2 | 100 kΩ | 0603 | comparator input series / ESD protection |
| R3  | 4.7 kΩ | 0603 | GP0 pull-up to 3V3 |
| R4  | 2.2 kΩ | 0603 | GP1 → Q1 base (hard saturation) |
| R5  | 2.2 kΩ | 0603 | Q1 collector → Q2 base (saturation control) |
| R6  | 1 kΩ | 0603 | Q2 base pull-up to 5 V (rapid charge sweep-out) |
| R7, R8 | 68 Ω (or 82 Ω) | 0603 | bus drive impedance ($V_{diff} \approx 0.8\text{ V} - 1.0\text{ V}$) |
| H1  | 2-pin header | Data+, Data− | Wire by function (pin labels on v1 silk were swapped) |
