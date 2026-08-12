"""
VFD Dashboard - MicroPython port of the pygame vfd_satellite renderer.

Four 64px-wide components on the 256x48 VFD:
    FUEL GAUGE | POWER FLOW | ENERGY GRAPH | POWER BARS

Ported from cyberpank-prius-gen2-computer/vfd_satellite/ (pygame simulator).
Pixel layouts are kept identical; the pixel-list framebuffer was replaced
with MicroPython framebuf primitives and time.time() with ticks_ms.
"""

import time
import math

# ==============================================================================
# 3x5 pixel font (shared by fuel gauge indicators and energy graph readout)
# ==============================================================================

FONT_3X5 = {
    '0': (0b111, 0b101, 0b101, 0b101, 0b111),
    '1': (0b010, 0b110, 0b010, 0b010, 0b111),
    '2': (0b111, 0b001, 0b111, 0b100, 0b111),
    '3': (0b111, 0b001, 0b111, 0b001, 0b111),
    '4': (0b101, 0b101, 0b111, 0b001, 0b001),
    '5': (0b111, 0b100, 0b111, 0b001, 0b111),
    '6': (0b111, 0b100, 0b111, 0b101, 0b111),
    '7': (0b111, 0b001, 0b010, 0b010, 0b010),
    '8': (0b111, 0b101, 0b111, 0b101, 0b111),
    '9': (0b111, 0b101, 0b111, 0b001, 0b111),
    '-': (0b000, 0b000, 0b111, 0b000, 0b000),
    '+': (0b000, 0b010, 0b111, 0b010, 0b000),
    '.': (0b000, 0b000, 0b000, 0b000, 0b010),
    ' ': (0b000, 0b000, 0b000, 0b000, 0b000),
    'O': (0b111, 0b101, 0b101, 0b101, 0b111),
    'F': (0b111, 0b100, 0b110, 0b100, 0b100),
    'P': (0b110, 0b101, 0b110, 0b100, 0b100),
    'T': (0b111, 0b010, 0b010, 0b010, 0b010),
    'R': (0b110, 0b101, 0b110, 0b101, 0b101),
    'L': (0b100, 0b100, 0b100, 0b100, 0b111),
    'G': (0b111, 0b100, 0b101, 0b101, 0b111),
    'B': (0b110, 0b101, 0b110, 0b101, 0b110),
}


def draw_text_3x5(fb, x, y, text, color=1):
    """Draw text using the 3x5 font. Returns x after the text."""
    cx = x
    for ch in text.upper():
        rows = FONT_3X5.get(ch)
        if rows:
            for ri in range(5):
                row = rows[ri]
                for col in range(3):
                    if row & (1 << (2 - col)):
                        fb.pixel(cx + col, y + ri, color)
        cx += 4
    return cx


def draw_text_3x5_xor(fb, x, y, text):
    """Draw text using the 3x5 font, inverting the pixels underneath."""
    cx = x
    for ch in text.upper():
        rows = FONT_3X5.get(ch)
        if rows:
            for ri in range(5):
                row = rows[ri]
                for col in range(3):
                    if row & (1 << (2 - col)):
                        px, py = cx + col, y + ri
                        if 0 <= px < 256 and 0 <= py < 48:
                            fb.pixel(px, py, 1 - fb.pixel(px, py))
        cx += 4
    return cx


# ==============================================================================
# Icons (11x11, one tuple of row bitmasks each, MSB = leftmost pixel)
# ==============================================================================

def _rows(*bits):
    return bits

ICON_LIGHTNING = _rows(
    0b00001111000,
    0b00011110000,
    0b00011100000,
    0b00111100000,
    0b01111111100,
    0b00001111000,
    0b00001110000,
    0b00011100000,
    0b00011000000,
    0b00110000000,
    0b01100000000,
)

ICON_ENGINE = _rows(
    0b00000000000,
    0b00011111000,
    0b00000100000,
    0b10111111100,
    0b10111111101,
    0b11110001101,
    0b10110001101,
    0b10111111101,
    0b00011111100,
    0b00000000000,
    0b00000000000,
)

ICON_BATTERY = _rows(
    0b00110001100,
    0b11111111111,
    0b10000000001,
    0b10000001001,
    0b10111011101,
    0b10000001001,
    0b10000000001,
    0b10000000001,
    0b10000000001,
    0b11111111111,
    0b01111111110,
)

ICON_WHEEL = _rows(
    0b00111111100,
    0b01111111110,
    0b11100100111,
    0b11010101011,
    0b11001110011,
    0b11111011111,
    0b11001110011,
    0b11010101011,
    0b11100100111,
    0b01111111110,
    0b00111111100,
)

ICON_W = 11
ICON_H = 11


def draw_icon(fb, x, y, icon, color=1):
    """Draw an 11x11 icon at (x, y)."""
    for ri in range(ICON_H):
        row = icon[ri]
        for ci in range(ICON_W):
            if row & (1 << (ICON_W - 1 - ci)):
                fb.pixel(x + ci, y + ri, color)


def draw_icon_centered(fb, cx, cy, icon, color=1):
    """Draw an icon centered at (cx, cy)."""
    draw_icon(fb, cx - ICON_W // 2, cy - ICON_H // 2, icon, color)


def _now():
    """Monotonic seconds as float (ticks_ms based)."""
    return time.ticks_ms() / 1000.0


# ==============================================================================
# Fuel Gauge (x: 0-63)
# ==============================================================================

class FuelGauge:
    REGION_X = 0
    REGION_WIDTH = 64
    REGION_HEIGHT = 48

    PETROL_MAX = 45
    LPG_MAX = 60

    def __init__(self, fb):
        self.fb = fb
        self.petrol_level = 0
        self.lpg_level = 0
        self.battery_soc = 0.6
        self.active_fuel = "OFF"  # "OFF" | "PTR" | "LPG"

    def update(self, petrol_level, lpg_level, battery_soc, active_fuel):
        self.petrol_level = petrol_level
        self.lpg_level = lpg_level
        self.battery_soc = battery_soc
        self.active_fuel = active_fuel

    def render(self):
        fb = self.fb
        fb.fill_rect(self.REGION_X, 0, self.REGION_WIDTH, self.REGION_HEIGHT, 0)

        indicator_height = 9
        indicator_y = self.REGION_HEIGHT - indicator_height
        bar_height = indicator_y

        bar_width = 19
        bar_gap = 2

        petrol_x = self.REGION_X + 2
        lpg_x = petrol_x + bar_width + bar_gap
        battery_x = lpg_x + bar_width + bar_gap

        self._render_segments(petrol_x, bar_height, bar_width,
                              self._fuel_segments(self.petrol_level, self.PETROL_MAX))
        self._render_segments(lpg_x, bar_height, bar_width,
                              self._fuel_segments(self.lpg_level, self.LPG_MAX))
        self._render_segments(battery_x, bar_height, bar_width,
                              self._battery_segments(self.battery_soc))

        self._render_indicators(indicator_y, bar_width, bar_gap)

    @staticmethod
    def _fuel_segments(level, max_level):
        if max_level <= 0:
            return 0
        ratio = min(1.0, max(0.0, level / max_level))
        return int(ratio * 8 + 0.5)

    @staticmethod
    def _battery_segments(soc):
        # Authentic Prius Gen 2 SOC mapping
        for threshold, segs in ((0.75, 8), (0.70, 7), (0.60, 6), (0.55, 5),
                                (0.50, 4), (0.45, 3), (0.40, 2), (0.35, 1)):
            if soc >= threshold:
                return segs
        return 0

    def _render_segments(self, x, h, w, filled):
        fb = self.fb
        seg_h = 4
        seg_gap = 1
        inner_x = x + 1
        inner_w = w - 2
        for i in range(filled):
            seg_y = h - (i + 1) * seg_h - i * seg_gap
            fb.fill_rect(inner_x, seg_y, inner_w, seg_h, 1)

    def _render_indicators(self, y, bar_width, bar_gap):
        fb = self.fb
        indicators = (
            ("PTR", self.REGION_X + 2, self.active_fuel == "PTR"),
            ("LPG", self.REGION_X + 2 + bar_width + bar_gap, self.active_fuel == "LPG"),
            ("BTT", self.REGION_X + 2 + 2 * (bar_width + bar_gap), False),
        )
        for text, base_x, is_active in indicators:
            text_width = 11
            tx = base_x + (bar_width - text_width) // 2
            ty = y + 2
            draw_text_3x5(fb, tx, ty, text, 1)
            if is_active:
                cy = ty + 2
                # Left arrow
                ax = tx - 2
                fb.pixel(ax, cy, 1)
                fb.pixel(ax - 1, cy - 1, 1)
                fb.pixel(ax - 1, cy + 1, 1)
                # Right arrow
                ax = tx + text_width + 1
                fb.pixel(ax, cy, 1)
                fb.pixel(ax + 1, cy - 1, 1)
                fb.pixel(ax + 1, cy + 1, 1)


# ==============================================================================
# Power Flow (x: 64-127)
# ==============================================================================

class PowerFlow:
    REGION_X = 64
    REGION_WIDTH = 64
    REGION_HEIGHT = 48

    THRESHOLD = 0.033  # ~1kW normalized

    def __init__(self, fb):
        self.fb = fb
        self._ice_to_battery = 0.0
        self._battery_to_wheels = 0.0
        self._wheels_to_battery = 0.0
        self._ice_to_wheels = 0.0
        self._anim_phase = 0

    def update(self, mg_power, speed, ice_running):
        t = self.THRESHOLD
        self._ice_to_battery = 0.0
        self._battery_to_wheels = 0.0
        self._wheels_to_battery = 0.0
        self._ice_to_wheels = 0.0

        if mg_power > t:
            self._battery_to_wheels = min(1.0, mg_power)
        if mg_power < -t and speed > 0.01:
            self._wheels_to_battery = min(1.0, abs(mg_power))
        if ice_running and mg_power < -t and self._wheels_to_battery < t:
            self._ice_to_battery = min(1.0, abs(mg_power))
        if ice_running and speed > 0.01:
            self._ice_to_wheels = min(1.0, speed)

    def render(self):
        fb = self.fb
        fb.fill_rect(self.REGION_X, 0, self.REGION_WIDTH, self.REGION_HEIGHT, 0)

        self._anim_phase = (self._anim_phase + 1) % 240

        cx = self.REGION_X + self.REGION_WIDTH // 2
        ice_x, ice_y = cx, 10
        battery_x, battery_y = self.REGION_X + 16, 38
        mg_x, mg_y = self.REGION_X + self.REGION_WIDTH - 16, 38

        draw_icon_centered(fb, ice_x, ice_y, ICON_ENGINE)
        draw_icon_centered(fb, battery_x, battery_y, ICON_BATTERY)
        draw_icon_centered(fb, mg_x, mg_y, ICON_WHEEL)

        if self._ice_to_battery > 0.05:
            self._flow_arrow(ice_x - 3, ice_y + 5, battery_x + 3, battery_y - 3)
        if self._battery_to_wheels > 0.05:
            self._flow_arrow(battery_x + 5, battery_y, mg_x - 5, mg_y)
        if self._wheels_to_battery > 0.05:
            self._flow_arrow(mg_x - 5, mg_y, battery_x + 5, battery_y)
        if self._ice_to_wheels > 0.05:
            self._flow_arrow(ice_x + 3, ice_y + 5, mg_x - 3, mg_y - 3)

    def _flow_arrow(self, x0, y0, x1, y1):
        dx = x1 - x0
        dy = y1 - y0
        length = int(math.sqrt(dx * dx + dy * dy))
        if length == 0:
            return

        is_horizontal = abs(dx) > abs(dy)
        is_right = dx > 0
        is_down = dy > 0

        spacing = 14
        num = max(3, length // spacing)
        for i in range(num):
            offset = (i * spacing + self._anim_phase / 1.5) % length
            t = offset / length
            tx = int(x0 + dx * t)
            ty = int(y0 + dy * t)
            self._chevron(tx, ty, is_horizontal, is_right, is_down)

    def _chevron(self, x, y, is_horizontal, is_right, is_down):
        fb = self.fb
        if is_horizontal:
            if is_right:
                fb.pixel(x, y, 1)
                fb.pixel(x - 1, y - 1, 1)
                fb.pixel(x - 1, y + 1, 1)
            else:
                fb.pixel(x, y, 1)
                fb.pixel(x + 1, y - 1, 1)
                fb.pixel(x + 1, y + 1, 1)
        else:
            if is_down:
                fb.pixel(x, y, 1)
                fb.pixel(x - 1, y - 1, 1)
                fb.pixel(x + 1, y - 1, 1)
            else:
                fb.pixel(x, y, 1)
                fb.pixel(x - 1, y + 1, 1)
                fb.pixel(x + 1, y + 1, 1)


# ==============================================================================
# Energy Graph (x: 128-191)
# ==============================================================================

class EnergyGraph:
    REGION_X = 128
    REGION_WIDTH = 64
    REGION_HEIGHT = 48

    def __init__(self, fb, time_base_sec=60.0):
        self.fb = fb
        self._graph_w = self.REGION_WIDTH
        self._time_base_sec = time_base_sec
        self._time_per_pixel = time_base_sec / self._graph_w

        # Per column: [assist_sum, regen_sum, count, ice_was_running]
        self._history = [[0.0, 0.0, 0, False] for _ in range(self._graph_w)]
        self._current_column = self._graph_w - 1
        self._column_start_time = None

        self._mg_power = 0.0
        self._ice_running = False
        self._current_column_ice_active = False

    def update(self, mg_power, ice_running):
        now = _now()
        if self._column_start_time is None:
            self._column_start_time = now

        self._mg_power = max(-1.0, min(1.0, mg_power))
        self._ice_running = ice_running
        if ice_running:
            self._current_column_ice_active = True

        col = self._history[self._current_column]
        if self._mg_power > 0:
            col[0] += self._mg_power
        else:
            col[1] += abs(self._mg_power)
        col[2] += 1
        col[3] = col[3] or self._current_column_ice_active

        if now - self._column_start_time >= self._time_per_pixel:
            self._advance_column(now)

    def set_time_base(self, seconds):
        self._time_base_sec = seconds
        self._time_per_pixel = seconds / self._graph_w
        self._history = [[0.0, 0.0, 0, False] for _ in range(self._graph_w)]
        self._current_column = self._graph_w - 1
        self._column_start_time = _now()
        self._current_column_ice_active = False

    def clear_history(self):
        self.set_time_base(self._time_base_sec)

    def _display_exponent(self):
        min_t, max_t = 15.0, 3600.0
        tb = max(min_t, min(max_t, self._time_base_sec))
        log_ratio = (math.log(tb) - math.log(min_t)) / (math.log(max_t) - math.log(min_t))
        return 1.0 - 0.7 * log_ratio

    def _advance_column(self, now):
        self._current_column_ice_active = self._ice_running
        self._current_column += 1
        if self._current_column >= self._graph_w:
            self._history.pop(0)
            self._history.append([0.0, 0.0, 0, self._ice_running])
            self._current_column = self._graph_w - 1
        self._column_start_time = now

    def tick(self):
        now = _now()
        if self._column_start_time is None:
            self._column_start_time = now
            return
        elapsed = now - self._column_start_time
        for _ in range(int(elapsed / self._time_per_pixel)):
            self._advance_column(now)

    def render(self):
        self.tick()
        fb = self.fb
        fb.fill_rect(self.REGION_X, 0, self.REGION_WIDTH, self.REGION_HEIGHT, 0)

        exponent = self._display_exponent()
        center_y = self.REGION_HEIGHT // 2
        max_offset = center_y - 1

        # Dotted center line
        for x in range(self.REGION_X, self.REGION_X + self.REGION_WIDTH, 3):
            fb.pixel(x, center_y, 1)

        for i in range(self._current_column + 1):
            x = self.REGION_X + i
            assist_sum, regen_sum, count, ice_was_running = self._history[i]

            if ice_was_running:
                fb.pixel(x, self.REGION_HEIGHT - 1, 1)

            if count > 0:
                assist_val = assist_sum / count
                regen_val = regen_sum / count
            else:
                assist_val = regen_val = 0.0

            if assist_val > 0.001:
                assist_val = assist_val ** exponent
            if regen_val > 0.001:
                regen_val = regen_val ** exponent

            if assist_val > 0.01:
                px = min(int(assist_val * max_offset), max_offset)
                fb.vline(x, center_y - px, px, 1)
            if regen_val > 0.01:
                px = min(int(regen_val * max_offset), max_offset)
                fb.vline(x, center_y + 1, px, 1)

        # Current value readout (kW), XOR so it stays visible over bars
        val_str = "%+d" % round(self._mg_power * 30)
        text_x = self.REGION_X + self.REGION_WIDTH - len(val_str) * 4 - 2
        draw_text_3x5_xor(fb, text_x, 1, val_str)


# ==============================================================================
# Power Bars (x: 192-255)
# ==============================================================================

class PowerBars:
    REGION_X = 192
    REGION_WIDTH = 64
    REGION_HEIGHT = 48

    EMA_ALPHA = 0.15

    def __init__(self, fb):
        self.fb = fb
        self._mg_power = 0.0
        self._fuel_brake = 0.0
        self._mg_power_target = 0.0
        self._fuel_brake_target = 0.0

        self._bar_width = 30
        bar_spacing = 2
        total = self._bar_width * 2 + bar_spacing
        start_x = self.REGION_X + (self.REGION_WIDTH - total) // 2
        self._mg_bar_x = start_x
        self._fuel_bar_x = start_x + self._bar_width + bar_spacing

    def update(self, mg_power, fuel_flow, brake, ice_running):
        self._mg_power_target = max(-1.0, min(1.0, mg_power))
        if brake > 0.04:
            self._fuel_brake_target = -brake
        elif ice_running and fuel_flow > 0.01:
            self._fuel_brake_target = fuel_flow
        else:
            self._fuel_brake_target = 0.0

    def tick(self):
        a = self.EMA_ALPHA
        self._mg_power = a * self._mg_power_target + (1 - a) * self._mg_power
        self._fuel_brake = a * self._fuel_brake_target + (1 - a) * self._fuel_brake

    def render(self):
        self.tick()
        fb = self.fb
        fb.fill_rect(self.REGION_X, 0, self.REGION_WIDTH, self.REGION_HEIGHT, 0)
        self._render_bar(self._mg_bar_x, self._mg_power, ICON_LIGHTNING)
        self._render_bar(self._fuel_bar_x, self._fuel_brake, ICON_ENGINE)

    def _render_bar(self, bar_x, value, icon):
        fb = self.fb
        bar_w = self._bar_width
        bar_h = self.REGION_HEIGHT
        center_y = bar_h // 2

        # Dotted center line
        for x in range(bar_x, bar_x + bar_w, 3):
            fb.pixel(x, center_y, 1)

        max_fill = bar_h // 2 - 1
        fill_height = int(abs(value) * max_fill)

        if fill_height > 0:
            if value > 0:
                fill_y = center_y - fill_height
            else:
                fill_y = center_y + 1
            fb.fill_rect(bar_x + 1, fill_y, bar_w - 2, fill_height, 1)

        # Icon at 1/4 height, XOR against the bar so it inverts on overlap
        icon_x = bar_x + (bar_w - ICON_W) // 2
        icon_y = self.REGION_HEIGHT // 4 - ICON_H // 2
        for ri in range(ICON_H):
            row = icon[ri]
            for ci in range(ICON_W):
                if row & (1 << (ICON_W - 1 - ci)):
                    px = icon_x + ci
                    py = icon_y + ri
                    fb.pixel(px, py, 1 - fb.pixel(px, py))


# ==============================================================================
# Dashboard - combines all components
# ==============================================================================

class Dashboard:
    """The four-component energy dashboard, driven by E/S/C messages."""

    def __init__(self, fb, time_base_sec=60.0):
        self.fb = fb
        self.fuel_gauge = FuelGauge(fb)
        self.power_flow = PowerFlow(fb)
        self.energy_graph = EnergyGraph(fb, time_base_sec)
        self.power_bars = PowerBars(fb)

        # Raw state mirrors (protocol values)
        self.mg_power = 0.0
        self.fuel_flow = 0.0
        self.brake = 0.0
        self.speed = 0.0
        self.battery_soc = 0.6
        self.petrol_level = 30
        self.lpg_level = 45
        self.ice_running = False
        self.active_fuel = "OFF"
        self.gear = "P"
        self.ready = False

    def handle_energy(self, d):
        """Apply an 'E' message payload."""
        if "mg" in d:
            self.mg_power = max(-1.0, min(1.0, float(d["mg"])))
        if "fl" in d:
            self.fuel_flow = max(0.0, min(1.0, float(d["fl"])))
        if "br" in d:
            self.brake = max(0.0, min(1.0, float(d["br"])))
        if "spd" in d:
            self.speed = max(0.0, min(1.0, float(d["spd"])))
        if "soc" in d:
            self.battery_soc = max(0.0, min(1.0, float(d["soc"])))
        if "ptr" in d:
            self.petrol_level = max(0, min(45, int(d["ptr"])))
        if "lpg" in d:
            self.lpg_level = max(0, min(60, int(d["lpg"])))
        if "ice" in d:
            self.ice_running = bool(d["ice"])

        self.fuel_gauge.update(self.petrol_level, self.lpg_level,
                               self.battery_soc, self.active_fuel)
        self.power_flow.update(self.mg_power, self.speed, self.ice_running)
        self.energy_graph.update(self.mg_power, self.ice_running)
        self.power_bars.update(self.mg_power, self.fuel_flow,
                               self.brake, self.ice_running)

    def handle_state(self, d):
        """Apply an 'S' message payload."""
        if "fuel" in d:
            f = str(d["fuel"]).upper()
            self.active_fuel = f if f in ("PTR", "LPG") else "OFF"
            self.fuel_gauge.update(self.petrol_level, self.lpg_level,
                                   self.battery_soc, self.active_fuel)
        if "gear" in d:
            g = str(d["gear"]).upper()
            if g in ("P", "R", "N", "D", "B"):
                self.gear = g
        if "rdy" in d:
            self.ready = bool(d["rdy"])

    def handle_config(self, d):
        """Apply a 'C' message payload. Returns brightness or None."""
        if "tb" in d:
            tb = int(d["tb"])
            if tb in (15, 60, 300, 900, 3600):
                self.energy_graph.set_time_base(float(tb))
        if "bri" in d:
            return max(0, min(100, int(d["bri"])))
        return None

    def handle_reset(self, d):
        """Apply an 'R' message payload."""
        if d.get("hist"):
            self.energy_graph.clear_history()

    def render(self):
        """Render all components into the framebuffer (no show())."""
        self.fuel_gauge.render()
        self.power_flow.render()
        self.energy_graph.render()
        self.power_bars.render()
