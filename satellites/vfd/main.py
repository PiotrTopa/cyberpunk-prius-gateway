"""
Satellite: VFD Display (device ID 110)

RP2040 + GP1294AI 256x48 VFD + MAX485.

Renders the energy dashboard (fuel gauge / power flow / energy graph /
power bars — ported from the pygame vfd_satellite simulator) driven by
E/S/C/R messages, and additionally supports a free-form CANVAS mode so
the host can show anything (text, primitives, raw bitmaps).

Protocol: NDJSON over RS485, {"id":110,"d":{...}} — see
cyberpank-prius-gen2-computer/docs/VFD_SATELLITE_PROTOCOL.md
"""

import machine
import time
import ubinascii
from rs485 import RS485
from vfd_framebuffer import VFDFramebuffer
from dashboard import Dashboard, draw_text_3x5

VERSION = "1.0.0"

# ==============================================================================
# Configuration
# ==============================================================================

DEV_ID = 110  # Satellite address on RS485 bus

# --- RS485 (UART1) — same wiring as the light satellite ---
UART_ID = 1
TX_PIN = 8
RX_PIN = 9
DE_PIN = 10
BAUD_RATE = 115200

# --- VFD (SPI0) — same wiring as rp2040-05-fluorite-vfd-controller ---
SPI_ID = 0
FIL_EN_PIN = 0   # Filament enable (active high)
CS_PIN = 1       # Chip select (active low)
SCK_PIN = 2      # SPI clock
MOSI_PIN = 3     # SPI data
RST_PIN = 4      # Reset (active low)
SPI_BAUDRATE = 4_000_000

# --- Timing ---
FRAME_INTERVAL_MS = 50            # 20 FPS render (measured: render ~38ms + show ~10ms)
STATUS_BROADCAST_INTERVAL_MS = 5000
DATA_TIMEOUT_MS = 10000           # No E-messages -> treat as parked/dark
SPLASH_DURATION_MS = 5000         # Boot splash time
FADE_STEP = 5                     # Fade %-points per frame (~1s full fade at 20 FPS)

# Brightness mapping: protocol 0-100% -> GP1294AI raw value
BRIGHTNESS_MAX_RAW = 0x50

# Display modes
MODE_DASHBOARD = 0
MODE_CANVAS = 1


# ==============================================================================
# Canvas mode — free-form drawing commands
# ==============================================================================

class Canvas:
    """
    Free-form drawing surface, addressed via 'T' (text), 'D' (draw ops)
    and 'B' (bitmap) messages. Entering canvas mode pauses the dashboard;
    an 'R' reset (or data-driven dashboard messages after 'R') resumes it.
    """

    def __init__(self, fb):
        self.fb = fb

    def handle_text(self, d):
        """
        'T' message: {"t":"T","x":0,"y":0,"s":"Hello","f":8,"c":1,"clr":true}
          x, y : position (default 0,0)
          s    : string (or list of strings, one per line)
          f    : font height — 8 (framebuf 8x8, default) or 5 (3x5 mini)
          c    : color 1/0 (default 1)
          clr  : clear framebuffer first (default false)
        """
        if d.get("clr"):
            self.fb.fill(0)
        x = int(d.get("x", 0))
        y = int(d.get("y", 0))
        c = int(d.get("c", 1))
        font = int(d.get("f", 8))
        s = d.get("s", "")
        lines = s if isinstance(s, list) else [s]
        line_h = 6 if font == 5 else 10
        for line in lines:
            if font == 5:
                draw_text_3x5(self.fb, x, y, str(line), c)
            else:
                self.fb.text(str(line), x, y, c)
            y += line_h

    def handle_draw(self, d):
        """
        'D' message: {"t":"D","ops":[[op, ...args], ...],"clr":false}
        Ops (args as in framebuf, color always last):
          ["fill", c]
          ["px",   x, y, c]
          ["line", x0, y0, x1, y1, c]
          ["hl",   x, y, w, c]
          ["vl",   x, y, h, c]
          ["rect", x, y, w, h, c]
          ["frect",x, y, w, h, c]
          ["circ", cx, cy, r, c]
          ["fcirc",cx, cy, r, c]
          ["txt",  x, y, s, c]
        """
        if d.get("clr"):
            self.fb.fill(0)
        ops = d.get("ops", [])
        done = 0
        for op in ops:
            try:
                name = op[0]
                a = op[1:]
                if name == "fill":
                    self.fb.fill(a[0])
                elif name == "px":
                    self.fb.pixel(a[0], a[1], a[2])
                elif name == "line":
                    self.fb.line(a[0], a[1], a[2], a[3], a[4])
                elif name == "hl":
                    self.fb.hline(a[0], a[1], a[2], a[3])
                elif name == "vl":
                    self.fb.vline(a[0], a[1], a[2], a[3])
                elif name == "rect":
                    self.fb.rect(a[0], a[1], a[2], a[3], a[4])
                elif name == "frect":
                    self.fb.fill_rect(a[0], a[1], a[2], a[3], a[4])
                elif name == "circ":
                    self.fb.draw_circle(a[0], a[1], a[2], a[3])
                elif name == "fcirc":
                    self.fb.fill_circle(a[0], a[1], a[2], a[3])
                elif name == "txt":
                    self.fb.text(str(a[2]), a[0], a[1], a[3])
                else:
                    continue
                done += 1
            except (IndexError, TypeError, ValueError):
                pass
        return done

    def handle_bitmap(self, d):
        """
        'B' message: {"t":"B","x":0,"y":0,"w":32,"h":16,"b64":"..."}
        Raw 1bpp bitmap, MSB-first rows, base64 encoded.
        """
        try:
            x = int(d.get("x", 0))
            y = int(d.get("y", 0))
            w = int(d["w"])
            h = int(d["h"])
            data = ubinascii.a2b_base64(d["b64"])
        except (KeyError, ValueError, TypeError):
            return False
        byte_w = (w + 7) // 8
        if len(data) < byte_w * h:
            return False
        for row in range(h):
            base = row * byte_w
            for col in range(w):
                bit = (data[base + (col >> 3)] >> (7 - (col & 7))) & 1
                self.fb.pixel(x + col, y + row, bit)
        return True


# ==============================================================================
# Idle screen — "CYBER SECURITY" splash (shown until car enters driving mode)
# ==============================================================================

class CyberSplash:
    """
    Idle screen: terminal-style '> Cyber Security' prompt (2x-scaled,
    pre-rendered once into a blit buffer) with a blinking block cursor.
    """

    TEXT = "> CyberSecurity"

    def __init__(self, fb):
        import framebuf
        self.fb = fb
        self.frame = 0

        # Pre-render 2x-scaled text: 15 chars * 8px = 120px -> 240x16
        w1, h1 = len(self.TEXT) * 8, 8
        small = framebuf.FrameBuffer(bytearray(w1 * ((h1 + 7) // 8)), w1, h1,
                                     framebuf.MONO_VLSB)
        small.text(self.TEXT, 0, 0, 1)

        self.tw, self.th = w1 * 2, h1 * 2
        self.tbuf = bytearray(self.tw * ((self.th + 7) // 8))
        self.tfb = framebuf.FrameBuffer(self.tbuf, self.tw, self.th,
                                        framebuf.MONO_VLSB)
        for y in range(h1):
            for x in range(w1):
                if small.pixel(x, y):
                    self.tfb.fill_rect(x * 2, y * 2, 2, 2, 1)

        # Center text + cursor as a group (cursor: 4px gap + 10px block)
        self.tx = (256 - (self.tw + 14)) // 2
        self.ty = (48 - self.th) // 2

    def render(self):
        fb = self.fb
        self.frame += 1

        fb.fill(0)
        fb.blit(self.tfb, self.tx, self.ty)

        # Blinking block cursor after the text
        if (self.frame // 12) % 2:
            fb.fill_rect(self.tx + self.tw + 4, self.ty + 2,
                         10, self.th - 4, 1)


# ==============================================================================
# Main
# ==============================================================================

def main():
    print("BOOT: Satellite VFD (ID=%d) starting..." % DEV_ID)
    print("  RS485: UART%d TX=GP%d RX=GP%d DE=GP%d @ %d" %
          (UART_ID, TX_PIN, RX_PIN, DE_PIN, BAUD_RATE))
    print("  VFD:   SPI%d SCK=GP%d MOSI=GP%d CS=GP%d RST=GP%d FIL=GP%d" %
          (SPI_ID, SCK_PIN, MOSI_PIN, CS_PIN, RST_PIN, FIL_EN_PIN))

    rs485 = RS485(UART_ID, BAUD_RATE, TX_PIN, RX_PIN, DE_PIN, DEV_ID)
    print("RS485: Ready")

    fb = VFDFramebuffer(
        spi_id=SPI_ID, sck_pin=SCK_PIN, mosi_pin=MOSI_PIN,
        cs_pin=CS_PIN, rst_pin=RST_PIN, fil_en_pin=FIL_EN_PIN,
        baudrate=SPI_BAUDRATE,
    )
    fb.init()
    print("VFD: Initialized")

    dashboard = Dashboard(fb)
    canvas = Canvas(fb)
    mode = MODE_DASHBOARD

    # Heartbeat LED: GP25 on Pico; RP2040-Zero has a WS2812 on GP16 instead,
    # where GP25 is harmlessly unconnected.
    led = machine.Pin(25, machine.Pin.OUT)

    brightness_pct = 100

    def apply_brightness(pct):
        fb.set_brightness(max(1, pct * BRIGHTNESS_MAX_RAW // 100))

    apply_brightness(brightness_pct)

    rs485.send({"msg": "VFD_READY", "ver": VERSION, "res": "256x48"})
    print("READY: Satellite VFD (ID=%d) running" % DEV_ID)

    last_frame = time.ticks_ms()
    last_broadcast = time.ticks_ms()
    last_data = 0            # ticks of last E/T/D/B message, 0 = never
    canvas_dirty = False
    frame_count = 0
    splash = CyberSplash(fb)
    boot_time = time.ticks_ms()
    fade_pct = 100           # 100 = full brightness, 0 = dark (parked)

    while True:
        now = time.ticks_ms()

        # --- 1. Process RS485 messages ---
        for m in rs485.read():
            t = m.get("t")
            if t == "E":
                dashboard.handle_energy(m)
                last_data = now
            elif t == "S":
                dashboard.handle_state(m)
            elif t == "C":
                bri = dashboard.handle_config(m)
                if bri is not None:
                    brightness_pct = bri
                    apply_brightness(brightness_pct * fade_pct // 100)
            elif t == "R":
                dashboard.handle_reset(m)
                mode = MODE_DASHBOARD
                fb.fill(0)
            elif t in ("T", "D", "B"):
                mode = MODE_CANVAS
                canvas_dirty = True
                last_data = now
                # Canvas content always wakes the display
                if fade_pct < 100:
                    fade_pct = 100
                    apply_brightness(brightness_pct)
                if t == "T":
                    canvas.handle_text(m)
                elif t == "D":
                    n = canvas.handle_draw(m)
                    if m.get("ack"):
                        rs485.send({"res": "OK", "t": "D", "ops": n})
                else:
                    if not canvas.handle_bitmap(m):
                        rs485.send({"err": "BAD_BITMAP"})
            elif m.get("cmd") == "STATUS":
                rs485.send(_status(mode, brightness_pct, frame_count))

        # --- 2. Render frame ---
        if time.ticks_diff(now, last_frame) >= FRAME_INTERVAL_MS:
            if mode == MODE_DASHBOARD:
                in_splash = time.ticks_diff(now, boot_time) < SPLASH_DURATION_MS
                have_data = last_data and time.ticks_diff(now, last_data) < DATA_TIMEOUT_MS
                driving = dashboard.ready and dashboard.gear != "P" and have_data

                # Fade toward full brightness when driving (or in splash),
                # toward dark when parked / not ready / stale data.
                target = 100 if (driving or in_splash) else 0
                if fade_pct != target:
                    step = FADE_STEP if target > fade_pct else -FADE_STEP
                    fade_pct = max(0, min(100, fade_pct + step))
                    apply_brightness(brightness_pct * fade_pct // 100)
                    if fade_pct == 0:
                        # Fully dark: blank the screen too
                        fb.fill(0)
                        fb.show()

                if fade_pct > 0:
                    if in_splash:
                        splash.render()
                    else:
                        dashboard.render()
                    fb.show()
                    frame_count += 1
            elif canvas_dirty:
                fb.show()
                frame_count += 1
                canvas_dirty = False
            last_frame = now

        # --- 3. Periodic status broadcast ---
        if time.ticks_diff(now, last_broadcast) >= STATUS_BROADCAST_INTERVAL_MS:
            rs485.send(_status(mode, brightness_pct, frame_count))
            last_broadcast = now
            led.toggle()  # Heartbeat

        time.sleep_ms(2)


def _status(mode, brightness_pct, frame_count):
    return {
        "cmd": "STATUS",
        "mode": "canvas" if mode == MODE_CANVAS else "dash",
        "bri": brightness_pct,
        "frames": frame_count,
        "ver": VERSION,
    }


if __name__ == "__main__":
    main()
