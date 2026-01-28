import machine
import time
import framebuf
import random
from ssd1306 import SSD1306_I2C
from ds3231 import DS3231
from rs485 import RS485

# Import fonts directly
try:
    import lib_fonts.marske_32 as font_big
    import lib_fonts.marske_16 as font_small
except ImportError:
    print("Error: Fonts not found. Please upload lib_fonts/marske_*.py")
    font_big = None
    font_small = None

# --- Writer Class ---
class Writer:
    def __init__(self, device, font):
        self.device = device
        self.font = font
        
    def text(self, string, x, y, spacing=0):
        curr_x = x
        for char in string:
            if char in self.font.GLYPHS:
                glyph = self.font.GLYPHS[char]
                w = glyph['w']
                h = glyph['h']
                data = glyph['data']
                
                # Create a framebuffer for the glyph
                glyph_buf = framebuf.FrameBuffer(bytearray(data), w, h, framebuf.MONO_VLSB)
                
                # Blit to device
                self.device.blit(glyph_buf, curr_x, y)
                
                curr_x += w + spacing
            else:
                # Space or unknown
                curr_x += self.font.HEIGHT // 4 + spacing
        
        return curr_x
        
    def measure_text(self, string, spacing=0):
        width = 0
        for char in string:
            if char in self.font.GLYPHS:
                width += self.font.GLYPHS[char]['w'] + spacing
            else:
                width += self.font.HEIGHT // 4 + spacing
        
        if width > 0:
            width -= spacing # Remove last spacing
            
        return width
    
    def get_char_width(self, char):
        if char in self.font.GLYPHS:
            return self.font.GLYPHS[char]['w']
        return self.font.HEIGHT // 4

# Configuration
DEV_ID = 6
I2C_ID = 1
SDA_PIN = 2
SCL_PIN = 3
OLED_WIDTH = 128
OLED_HEIGHT = 32

# RS485 Configuration
UART_ID = 0
TX_PIN = 12
RX_PIN = 13
DE_PIN = 14
BAUD_RATE = 115200

# --- Animation Helpers ---

def get_centered_positions(writer, text, spacing=2):
    """
    Returns a list of (char, x) tuples for the centered text.
    """
    w = writer.measure_text(text, spacing=spacing)
    start_x = (OLED_WIDTH - w) // 2
    if start_x < 0: start_x = 0
    
    positions = []
    curr_x = start_x
    for char in text:
        w_char = writer.get_char_width(char)
        positions.append({
            "char": char,
            "x": curr_x,
            "w": w_char
        })
        curr_x += w_char + spacing
    return positions

def anim_selective_scanline(oled, writer, old_text, new_text):
    """
    Scanline Wipe effect only on changing digits.
    """
    # Calculate positions for NEW text (assuming layout doesn't shift drastically)
    # If layout shifts (e.g. 1 -> 11), we might need to clear everything.
    # But clock is usually fixed width or centered.
    # We will use new_text layout.
    
    positions = get_centered_positions(writer, new_text)
    
    # Identify changed indices
    # Handle length mismatch (shouldn't happen for clock HH:MM)
    changed_indices = []
    min_len = min(len(old_text), len(new_text))
    
    for i in range(min_len):
        if old_text[i] != new_text[i]:
            changed_indices.append(i)
            
    # If lengths differ, treat all as changed/redraw
    if len(old_text) != len(new_text):
        changed_indices = list(range(len(new_text)))

    # Animation Loop
    # Scanline moves from 0 to 32
    step = 2 # Speed
    for y in range(0, 32 + step, step):
        oled.fill(0)
        
        for i, pos in enumerate(positions):
            char = pos["char"]
            x = pos["x"]
            w = pos["w"]
            
            if i in changed_indices:
                # CHANGED DIGIT: Scanline Effect
                # Draw Char
                writer.text(char, x, 0)
                
                # Mask bottom (below scanline)
                # We want to reveal from top. So we clear from y to 32.
                if y < 32:
                    oled.fill_rect(x, y, w, 32 - y, 0)
                
                # Draw Scanline Beam
                if y < 32:
                    oled.hline(x, y, w, 1)
                    
            else:
                # UNCHANGED: Draw normally
                writer.text(char, x, 0)
                
        oled.show()

# --- Main Functions ---

def draw_message(oled, writer, line1, line2):
    if not oled or not writer:
        return

    oled.fill(0)
    
    # Line 1 (Top)
    w1 = writer.measure_text(line1, spacing=1)
    x1 = (OLED_WIDTH - w1) // 2
    writer.text(line1, x1, 0, spacing=1)
    
    # Line 2 (Bottom - 16px down)
    w2 = writer.measure_text(line2, spacing=1)
    x2 = (OLED_WIDTH - w2) // 2
    writer.text(line2, x2, 16, spacing=1)
    
    oled.show()

def main():
    print(f"BOOT: Satellite Clock (ID={DEV_ID}) starting...")

    # Initialize RS485
    print(f"Initializing RS485 on UART{UART_ID} (TX=GP{TX_PIN}, RX=GP{RX_PIN}, DE=GP{DE_PIN})")
    rs485 = RS485(UART_ID, BAUD_RATE, TX_PIN, RX_PIN, DE_PIN, DEV_ID)
    
    # Initialize I2C
    print(f"Initializing I2C{I2C_ID} on SDA=GP{SDA_PIN}, SCL=GP{SCL_PIN}")
    i2c = machine.I2C(I2C_ID, sda=machine.Pin(SDA_PIN), scl=machine.Pin(SCL_PIN), freq=400000)
    
    # Scan I2C
    devices = i2c.scan()
    if not devices:
        print("Error: No I2C devices found!")
    else:
        print(f"I2C Devices found: {[hex(x) for x in devices]}")

    # Initialize RTC
    rtc = DS3231(i2c)
    
    # Set time if lost/invalid (year < 2026)
    # Sets to: 2026-01-04 17:59:00 (CET)
    curr_t = rtc.get_time()
    if curr_t is None or curr_t[0] < 2026:
        print("RTC: Time invalid/lost. Setting to 2026-01-04 17:59:00")
        rtc.set_time(2026, 1, 4, 17, 59, 0) 

    # Initialize OLED
    oled = None
    writer_big = None
    writer_small = None
    
    try:
        if devices:
            oled = SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)
            oled.fill(0)
            oled.contrast(255) 
            
            if font_big and font_small:
                writer_big = Writer(oled, font_big)
                writer_small = Writer(oled, font_small)
                
                draw_message(oled, writer_small, "CYBERPUNK", "INIT...")
                time.sleep(2)
                
            else:
                oled.text("Font Error", 0, 0)
                oled.show()
                time.sleep(2)
                
    except Exception as e:
        print(f"Error initializing OLED: {e}")
    
    led = machine.Pin(25, machine.Pin.OUT) 
    
    last_time_str = "" # Start empty to force initial update
    force_refresh = True

    # State
    display_mode = "CLOCK" # CLOCK, MESSAGE
    msg_line1 = ""
    msg_line2 = ""
    msg_expiry = 0
    msg_drawn = False
    
    last_broadcast = 0

    while True:
        # --- 1. Process RS485 ---
        msgs = rs485.read()
        for m in msgs:
            cmd = m.get("cmd")
            if cmd == "SET_TIME":
                # args: [2026, 1, 6, 18, 55, 0]
                args = m.get("args")
                if args and isinstance(args, list) and len(args) >= 6:
                    print(f"Setting time to: {args}")
                    rtc.set_time(*args)
                    rs485.send({"res": "OK", "cmd": "SET_TIME"})
                    last_time_str = "" # Force redraw
            
            elif cmd == "GET_TIME":
                t = rtc.get_time()
                temp = rtc.get_temperature()
                rs485.send({"cmd": "TIME", "val": t, "temp": temp})
            
            elif cmd == "TEXT":
                msg_line1 = m.get("line1", "")
                msg_line2 = m.get("line2", "")
                duration = m.get("duration", 5)
                
                display_mode = "MESSAGE"
                msg_expiry = time.ticks_add(time.ticks_ms(), duration * 1000)
                msg_drawn = False
                rs485.send({"res": "OK", "cmd": "TEXT"})
            
            elif cmd == "BRIGHTNESS":
                val = m.get("val", 255)
                if oled:
                    oled.contrast(val)
                rs485.send({"res": "OK", "cmd": "BRIGHTNESS", "val": val})

        # --- 2. Broadcast (Every 10s) ---
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, last_broadcast) > 10000:
            t = rtc.get_time()
            temp = rtc.get_temperature()
            rs485.send({"cmd": "TIME", "val": t, "temp": temp})
            last_broadcast = now_ms

        # --- 3. Update Time State ---
        now = rtc.get_time()
        if now:
            # (year, month, day, hour, minute, second)
            h, m = now[3], now[4]
            current_time_str = "{:02d}:{:02d}".format(h, m)
        else:
            current_time_str = "--:--"
        
        # --- 4. Display Logic ---
        if oled and writer_big:
            try:
                # Mode Switching
                if display_mode == "MESSAGE":
                    if time.ticks_diff(time.ticks_ms(), msg_expiry) > 0:
                        display_mode = "CLOCK"
                        oled.fill(0)
                        last_time_str = "" # Force redraw of clock
                    else:
                        # Draw Message (only once)
                        if not msg_drawn:
                            draw_message(oled, writer_small, msg_line1, msg_line2)
                            msg_drawn = True
                
                if display_mode == "CLOCK":
                    # Check for change
                    if current_time_str != last_time_str:
                        # Trigger Animation
                        if last_time_str != "":
                            anim_selective_scanline(oled, writer_big, last_time_str, current_time_str)
                        else:
                            pass
                        
                        last_time_str = current_time_str
                        force_refresh = True 
                        
                    # Static Refresh
                    if force_refresh:
                        oled.fill(0)
                        w = writer_big.measure_text(current_time_str, spacing=2)
                        x = (OLED_WIDTH - w) // 2
                        if x < 0: x = 0
                        writer_big.text(current_time_str, x, 0, spacing=2)
                        oled.show()
                        force_refresh = False
                
            except Exception as e:
                print(f"OLED Error: {e}")
                pass
            
        # Heartbeat & Loop Speed
        led.toggle()
        # Reduce sleep to make RS485 responsive
        time.sleep(0.1)

if __name__ == "__main__":
    main()
