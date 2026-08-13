import machine
import time
from rs485 import RS485
from ota import OTA
from easing import EasingEngine, EASING_FUNCTIONS

# ==============================================================================
# Configuration
# ==============================================================================

DEV_ID = 106  # Satellite address on RS485 bus

# --- RS485 (UART1) ---
UART_ID = 1
TX_PIN = 8
RX_PIN = 9
DE_PIN = 10
BAUD_RATE = 115200

# --- PWM Channels (HW-039 / BTS7960 half-bridges) ---
PWM_CH1_PIN = 6   # RPWM -> Right headlight BiLED
PWM_CH2_PIN = 7   # LPWM -> Left headlight BiLED
PWM_ENABLE_R_PIN = 5 # R_EN
PWM_ENABLE_L_PIN = 4 # L_EN
PWM_FREQ = 1000    # 1 kHz base frequency

# --- Relay Module (HW-316, Active Low) ---
RELAY_PINS = [3, 2, 1, 0]  # GP3=R1, GP2=R2, GP1=R3, GP0=R4

# --- ADC Current Sense ---
ADC_CH1_PIN = 26  # R_IS (right channel)
ADC_CH2_PIN = 27  # L_IS (left channel)

# --- Digital Inputs ---
INPUT_PINS = [11, 12, 13, 14]  # GP11=IN1, GP12=IN2, GP13=IN3, GP14=IN4 (Active Low 12V sense)

# Current conversion constant:
# I_load = ADC_val * 0.0038 [A]
# Derived from: V_adc = (adc_val/4095)*3.3, I = V_adc * 8500 / 1803.28
ADC_TO_AMPS = 0.0038

# Over-current protection threshold [A]
OVERCURRENT_THRESHOLD = 14.0

# --- Timing ---
STATUS_BROADCAST_INTERVAL_MS = 5000
EASING_TICK_INTERVAL_MS = 10  # ~100 Hz update rate for smooth transitions
ADC_SAMPLE_INTERVAL_MS = 100  # Current sampling rate

# ==============================================================================
# Hardware Abstraction
# ==============================================================================


class LightController:
    """
    Hardware abstraction layer for the light satellite.
    Manages relays, PWM outputs, current sensing, and safety interlocks.
    """

    def __init__(self):
        # --- Initialize Relays (FIRST - safety critical) ---
        # Must be HIGH immediately to prevent relay activation during boot
        self.relays = []
        for pin_num in RELAY_PINS:
            pin = machine.Pin(pin_num, machine.Pin.OUT, value=1)  # Active Low: 1 = OFF
            self.relays.append(pin)
        self.relay_states = [False] * len(RELAY_PINS)
        print("INIT: Relays OFF (Active Low, pins HIGH)")

        # --- Initialize PWM Enable (LOW = disabled, safe) ---
        self.pwm_enable_r_pin = machine.Pin(PWM_ENABLE_R_PIN, machine.Pin.OUT, value=0)
        self.pwm_enable_l_pin = machine.Pin(PWM_ENABLE_L_PIN, machine.Pin.OUT, value=0)
        self.pwm_enabled = False
        print("INIT: PWM power stage DISABLED")

        # --- Initialize PWM Channels ---
        self.pwm_ch1 = machine.PWM(machine.Pin(PWM_CH1_PIN))
        self.pwm_ch1.freq(PWM_FREQ)
        self.pwm_ch1.duty_u16(0)

        self.pwm_ch2 = machine.PWM(machine.Pin(PWM_CH2_PIN))
        self.pwm_ch2.freq(PWM_FREQ)
        self.pwm_ch2.duty_u16(0)

        self.pwm_duties = [0, 0]  # Current duty values (0-65535)
        print(f"INIT: PWM channels at 0% duty, {PWM_FREQ} Hz")

        # --- Initialize ADC ---
        self.adc_ch1 = machine.ADC(machine.Pin(ADC_CH1_PIN))
        self.adc_ch2 = machine.ADC(machine.Pin(ADC_CH2_PIN))
        self.current_amps = [0.0, 0.0]  # Last measured current [A]
        print("INIT: ADC current sense ready")

        # --- Initialize Digital Inputs ---
        self.inputs = []
        for pin_num in INPUT_PINS:
            # Active Low: 2n7000 pulls to GND when 12V is present
            pin = machine.Pin(pin_num, machine.Pin.IN, machine.Pin.PULL_UP)
            self.inputs.append(pin)
        self.input_states = [False] * len(INPUT_PINS)
        self.input_debounce = [0] * len(INPUT_PINS)
        print(f"INIT: Digital inputs ready on {INPUT_PINS}")

        # --- Easing Engine ---
        self.easing = EasingEngine(num_channels=2)

        # --- OCP (Over-Current Protection) ---
        self.ocp_tripped = False

    # --- Relay Control ---

    def set_relay(self, channel, state):
        """
        Set relay state.
        channel: 1-4 (user-facing), maps to index 0-3
        state: True = ON (energized), False = OFF
        """
        idx = channel - 1
        if 0 <= idx < len(self.relays):
            # Active Low: 0 = ON, 1 = OFF
            self.relays[idx].value(0 if state else 1)
            self.relay_states[idx] = state
            return True
        return False

    def get_relay(self, channel):
        """Get relay state (1-4)."""
        idx = channel - 1
        if 0 <= idx < len(self.relay_states):
            return self.relay_states[idx]
        return None

    # --- PWM Control ---

    def set_pwm_enable(self, enabled):
        """Enable/disable the PWM power stage (hardware safety gate)."""
        val = 1 if enabled else 0
        self.pwm_enable_r_pin.value(val)
        self.pwm_enable_l_pin.value(val)
        self.pwm_enabled = enabled
        if not enabled:
            # When disabling, also zero out PWM signals for clean state
            self.set_pwm_duty(1, 0)
            self.set_pwm_duty(2, 0)
            self.easing.cancel_all()

    def set_pwm_duty(self, channel, duty_u16):
        """
        Set PWM duty cycle directly (no easing).
        channel: 1 or 2
        duty_u16: 0-65535 (0-100%)
        """
        duty_u16 = max(0, min(65535, int(duty_u16)))

        if channel == 1:
            self.pwm_ch1.duty_u16(duty_u16)
            self.pwm_duties[0] = duty_u16
        elif channel == 2:
            self.pwm_ch2.duty_u16(duty_u16)
            self.pwm_duties[1] = duty_u16

    def set_pwm_percent(self, channel, percent):
        """Set PWM duty as percentage (0.0 - 100.0)."""
        duty = int((percent / 100.0) * 65535)
        self.set_pwm_duty(channel, duty)

    def get_pwm_duty(self, channel):
        """Get current PWM duty (0-65535) for channel 1 or 2."""
        idx = channel - 1
        if 0 <= idx < 2:
            return self.pwm_duties[idx]
        return 0

    def get_pwm_percent(self, channel):
        """Get current PWM duty as percentage."""
        return round(self.get_pwm_duty(channel) / 65535.0 * 100.0, 1)

    # --- PWM with Easing ---

    def start_pwm_transition(self, channel, target_percent, duration_ms, easing_name="linear"):
        """
        Start an eased PWM transition.
        channel: 1 or 2
        target_percent: Target duty cycle 0-100 (%)
        duration_ms: Transition duration in milliseconds
        easing_name: Easing function name (see easing.py)
        """
        idx = channel - 1
        if idx not in (0, 1):
            return False

        current_duty = self.pwm_duties[idx]
        target_duty = int((target_percent / 100.0) * 65535)
        target_duty = max(0, min(65535, target_duty))

        if duration_ms <= 0:
            # Instant set
            self.set_pwm_duty(channel, target_duty)
            return True

        self.easing.start(idx, current_duty, target_duty, duration_ms, easing_name)
        return True

    def update_easing(self):
        """
        Tick the easing engine and apply updated duty values.
        Should be called frequently (~100Hz) for smooth transitions.
        Returns True if any transition is active.
        """
        results = self.easing.tick()
        for ch_idx, duty_val, is_done in results:
            channel = ch_idx + 1
            self.set_pwm_duty(channel, duty_val)
        return self.easing.any_active()

    def update_inputs(self):
        """
        Poll inputs and debounce them.
        Returns True if any input state changed.
        """
        changed = False
        raw_states = [pin.value() == 0 for pin in self.inputs]
        for i in range(len(self.inputs)):
            if raw_states[i] != self.input_states[i]:
                self.input_debounce[i] += 1
                if self.input_debounce[i] >= 5:  # 5 ticks of 10ms = 50ms stable
                    self.input_states[i] = raw_states[i]
                    changed = True
            else:
                self.input_debounce[i] = 0
        return changed

    # --- Current Sensing ---

    def read_current(self):
        """
        Read current from both ADC channels.
        Averages samples over 2 PWM periods to avoid aliasing with PWM signal.
        Updates self.current_amps and returns (ch1_amps, ch2_amps).
        """
        # Sample over 2 full PWM periods (2ms at 1kHz) for stable average
        num_samples = 50
        sum1 = 0
        sum2 = 0
        for _ in range(num_samples):
            sum1 += self.adc_ch1.read_u16()
            sum2 += self.adc_ch2.read_u16()

        # Average and convert 16-bit to 12-bit equivalent for our formula
        adc_val1 = (sum1 // num_samples) >> 4
        adc_val2 = (sum2 // num_samples) >> 4

        self.current_amps[0] = round(adc_val1 * ADC_TO_AMPS, 2)
        self.current_amps[1] = round(adc_val2 * ADC_TO_AMPS, 2)

        return self.current_amps[0], self.current_amps[1]

    def check_overcurrent(self):
        """
        Check for over-current condition.
        If tripped, disables PWM power stage as hardware safety.
        Returns True if OCP is tripped.
        """
        i1, i2 = self.current_amps
        if i1 > OVERCURRENT_THRESHOLD or i2 > OVERCURRENT_THRESHOLD:
            if not self.ocp_tripped:
                print(f"OCP TRIPPED! CH1={i1:.2f}A CH2={i2:.2f}A (threshold={OVERCURRENT_THRESHOLD}A)")
                self.set_pwm_enable(False)
                self.ocp_tripped = True
            return True
        return False

    def reset_ocp(self):
        """Reset over-current protection flag (does NOT re-enable PWM)."""
        self.ocp_tripped = False

    # --- Emergency Stop ---

    def emergency_stop(self):
        """Cut all outputs immediately."""
        # PWM off
        self.set_pwm_enable(False)
        self.pwm_ch1.duty_u16(0)
        self.pwm_ch2.duty_u16(0)
        self.pwm_duties = [0, 0]
        self.easing.cancel_all()

        # Relays off
        for i, pin in enumerate(self.relays):
            pin.value(1)  # Active Low: HIGH = OFF
            self.relay_states[i] = False

        print("EMERGENCY STOP: All outputs disabled")

    # --- Status ---

    def get_status(self):
        """Get full status dictionary for reporting."""
        return {
            "pwm_en": self.pwm_enabled,
            "pwm": [self.get_pwm_percent(1), self.get_pwm_percent(2)],
            "relay": self.relay_states[:],
            "amps": [self.current_amps[0], self.current_amps[1]],
            "ocp": self.ocp_tripped,
            "easing": [self.easing.is_active(0), self.easing.is_active(1)],
            "inputs": self.input_states[:],
        }


# ==============================================================================
# Command Processor
# ==============================================================================


def process_command(hw, msg):
    """
    Process an incoming RS485 command and return a response dict.

    Command reference:
      {"cmd":"RELAY",    "ch":1,  "val":true}
      {"cmd":"PWM",      "ch":1,  "val":50}                        # instant 50%
      {"cmd":"PWM",      "ch":1,  "val":80, "dur":1000, "ease":"in_out"}  # eased
      {"cmd":"PWM_EN",   "val":true}
      {"cmd":"STATUS"}
      {"cmd":"STOP"}
      {"cmd":"OCP_RESET"}
      {"cmd":"TEST",     "what":"relay"|"pwm"|"adc"|"all"}
    """
    cmd = msg.get("cmd")
    if not cmd:
        return {"err": "NO_CMD"}

    # --- RELAY ---
    if cmd == "RELAY":
        ch = msg.get("ch", 1)
        val = msg.get("val", False)
        ok = hw.set_relay(ch, val)
        if ok:
            return {"res": "OK", "cmd": "RELAY", "ch": ch, "val": val}
        return {"err": "INVALID_CH", "cmd": "RELAY"}

    # --- PWM ---
    if cmd == "PWM":
        if hw.ocp_tripped:
            return {"err": "OCP_ACTIVE", "cmd": "PWM"}

        ch = msg.get("ch")
        val = msg.get("val")

        if ch is None or val is None:
            return {"err": "MISSING_PARAMS", "cmd": "PWM"}

        if ch not in (1, 2):
            return {"err": "INVALID_CH", "cmd": "PWM"}

        val = max(0.0, min(100.0, float(val)))
        dur = msg.get("dur", 0)
        ease = msg.get("ease", "linear")

        if ease not in EASING_FUNCTIONS:
            return {"err": "INVALID_EASE", "cmd": "PWM", "valid": list(EASING_FUNCTIONS.keys())}

        if dur > 0:
            hw.start_pwm_transition(ch, val, dur, ease)
            return {"res": "OK", "cmd": "PWM", "ch": ch, "val": val, "dur": dur, "ease": ease}
        else:
            hw.set_pwm_percent(ch, val)
            return {"res": "OK", "cmd": "PWM", "ch": ch, "val": val}

    # --- PWM ENABLE ---
    if cmd == "PWM_EN":
        val = msg.get("val", False)
        if val and hw.ocp_tripped:
            return {"err": "OCP_ACTIVE", "cmd": "PWM_EN"}
        hw.set_pwm_enable(val)
        return {"res": "OK", "cmd": "PWM_EN", "val": val}

    # --- STATUS ---
    if cmd == "STATUS":
        status = hw.get_status()
        status["cmd"] = "STATUS"
        return status

    # --- EMERGENCY STOP ---
    if cmd == "STOP":
        hw.emergency_stop()
        return {"res": "OK", "cmd": "STOP"}

    # --- OCP RESET ---
    if cmd == "OCP_RESET":
        hw.reset_ocp()
        return {"res": "OK", "cmd": "OCP_RESET", "note": "PWM_EN still OFF"}

    # --- TEST MODES ---
    if cmd == "TEST":
        what = msg.get("what", "all")
        return run_test(hw, what)

    return {"err": "UNKNOWN_CMD", "cmd": cmd}


# ==============================================================================
# Test Routines
# ==============================================================================


def run_test(hw, what):
    """
    Run hardware verification test routines.
    These are blocking and meant for initial hardware bring-up.
    """
    results = {}

    if what in ("relay", "all"):
        results["relay"] = test_relays(hw)

    if what in ("pwm", "all"):
        results["pwm"] = test_pwm(hw)

    if what in ("adc", "all"):
        results["adc"] = test_adc(hw)

    results["cmd"] = "TEST"
    results["what"] = what
    return results


def test_relays(hw):
    """Cycle each relay ON/OFF with a short delay."""
    print("TEST: Relay sequence start")
    results = []
    for ch in range(1, len(RELAY_PINS) + 1):
        hw.set_relay(ch, True)
        time.sleep(0.3)
        results.append(f"R{ch}:ON")
        hw.set_relay(ch, False)
        time.sleep(0.2)
        results.append(f"R{ch}:OFF")
    print("TEST: Relay sequence done")
    return results


def test_pwm(hw):
    """Ramp PWM channels up and down for visual verification."""
    print("TEST: PWM ramp start")

    # Enable power stage
    hw.set_pwm_enable(True)

    # Ramp both channels 0% -> 50% -> 0%
    for duty_pct in range(0, 51, 5):
        hw.set_pwm_percent(1, duty_pct)
        hw.set_pwm_percent(2, duty_pct)
        time.sleep(0.05)

    for duty_pct in range(50, -1, -5):
        hw.set_pwm_percent(1, duty_pct)
        hw.set_pwm_percent(2, duty_pct)
        time.sleep(0.05)

    # Disable power stage
    hw.set_pwm_enable(False)
    print("TEST: PWM ramp done")
    return "OK"


def test_adc(hw):
    """Read ADC values multiple times and report."""
    print("TEST: ADC read")
    samples = []
    for _ in range(5):
        i1, i2 = hw.read_current()
        samples.append([i1, i2])
        time.sleep(0.05)
    print(f"TEST: ADC samples={samples}")
    return samples


# ==============================================================================
# Main Loop
# ==============================================================================


def main():
    print(f"BOOT: Satellite Light (ID={DEV_ID}) starting...")
    print(f"  RS485: UART{UART_ID} TX=GP{TX_PIN} RX=GP{RX_PIN} DE=GP{DE_PIN}")
    print(f"  PWM:   CH1=GP{PWM_CH1_PIN} CH2=GP{PWM_CH2_PIN} EN_R=GP{PWM_ENABLE_R_PIN} EN_L=GP{PWM_ENABLE_L_PIN}")
    print(f"  Relay: GP{RELAY_PINS}")
    print(f"  ADC:   CH1=GP{ADC_CH1_PIN} CH2=GP{ADC_CH2_PIN}")
    print(f"  Inputs: GP{INPUT_PINS}")

    # Initialize RS485
    rs485 = RS485(UART_ID, BAUD_RATE, TX_PIN, RX_PIN, DE_PIN, DEV_ID)
    ota = OTA(rs485)
    print("RS485: Ready")

    # Initialize Hardware
    hw = LightController()
    print("Hardware: Initialized")

    # Onboard LED for heartbeat
    led = machine.Pin(25, machine.Pin.OUT)

    # --- Timing State ---
    last_broadcast = time.ticks_ms()
    last_adc_read = time.ticks_ms()
    last_easing_tick = time.ticks_ms()
    heartbeat_counter = 0

    print(f"READY: Satellite Light (ID={DEV_ID}) running")

    # === Main Loop ===
    while True:
        now = time.ticks_ms()

        # --- 1. Process RS485 Commands ---
        msgs = rs485.read()
        for m in msgs:
            if ota.handle(m):
                continue
            print(f"RX: {m}")
            response = process_command(hw, m)
            if response:
                rs485.send(response)
                print(f"TX: {response}")

        # --- 2. Easing Engine Tick ---
        if time.ticks_diff(now, last_easing_tick) >= EASING_TICK_INTERVAL_MS:
            hw.update_easing()
            
            if hw.update_inputs():
                rs485.send({
                    "evt": "INPUTS",
                    "val": hw.input_states[:]
                })
                print(f"INPUTS CHANGED: {hw.input_states}")
                
            last_easing_tick = now

        # --- 3. Current Sensing & OCP ---
        if time.ticks_diff(now, last_adc_read) >= ADC_SAMPLE_INTERVAL_MS:
            hw.read_current()
            if hw.check_overcurrent():
                # Send OCP alert
                rs485.send({
                    "evt": "OCP",
                    "amps": [hw.current_amps[0], hw.current_amps[1]],
                })
            last_adc_read = now

        # --- 4. Periodic Status Broadcast ---
        ota.tick(now)
        if time.ticks_diff(now, last_broadcast) >= STATUS_BROADCAST_INTERVAL_MS:
            status = hw.get_status()
            status["cmd"] = "STATUS"
            rs485.send(status)
            print(f"BCAST: {status}")
            last_broadcast = now

        # --- 5. Heartbeat LED ---
        heartbeat_counter += 1
        if heartbeat_counter >= 50:  # ~every 500ms at 10ms loop
            led.toggle()
            heartbeat_counter = 0

        # --- Loop Pacing ---
        # Fast enough for smooth easing, slow enough to not waste CPU
        time.sleep_ms(EASING_TICK_INTERVAL_MS)


if __name__ == "__main__":
    main()
