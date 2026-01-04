import machine
import time
import framebuf
from ssd1306 import SSD1306_I2C

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

# Configuration
DEV_ID = 6
I2C_ID = 1
SDA_PIN = 2
SCL_PIN = 3
OLED_WIDTH = 128
OLED_HEIGHT = 32

def show_message(oled, writer, line1, line2, duration=10):
    """
    Displays two lines of centered text for a specified duration.
    """
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
    time.sleep(duration)

def main():
    print(f"BOOT: Satellite Clock (ID={DEV_ID}) starting...")
    
    # Initialize I2C
    print(f"Initializing I2C{I2C_ID} on SDA=GP{SDA_PIN}, SCL=GP{SCL_PIN}")
    i2c = machine.I2C(I2C_ID, sda=machine.Pin(SDA_PIN), scl=machine.Pin(SCL_PIN), freq=400000)
    
    # Scan I2C
    devices = i2c.scan()
    if not devices:
        print("Error: No I2C devices found!")
    else:
        print(f"I2C Devices found: {[hex(x) for x in devices]}")

    # Initialize OLED
    oled = None
    writer_big = None
    writer_small = None
    
    try:
        if devices:
            oled = SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)
            oled.fill(0)
            
            if font_big and font_small:
                writer_big = Writer(oled, font_big)
                writer_small = Writer(oled, font_small)
                
                # Show Intro using new function (centered)
                show_message(oled, writer_small, "CYBERPUNK", "INIT...", duration=2) 
                # Reduced duration for boot, user asked for function with default 10s usage, 
                # but boot usually is faster. User said "Tekst ma byc ... widoczny przez 10 sekund od wywolania".
                # I will stick to 2s for boot unless they implied boot should be 10s.
                # "jak powitalny" refers to the style (two lines).
                # I'll leave boot short, but the function defaults to 10.
                
            else:
                oled.text("Font Error", 0, 0)
                oled.show()
                time.sleep(2)
                
    except Exception as e:
        print(f"Error initializing OLED: {e}")
    
    led = machine.Pin(25, machine.Pin.OUT) # Onboard LED
    
    # Simple clock simulation
    h, m, s = 12, 0, 0
    
    while True:
        # Update time
        s += 1
        if s >= 60:
            s = 0
            m += 1
            if m >= 60:
                m = 0
                h += 1
                if h >= 24:
                    h = 0
        
        # Display time if OLED is present
        if oled:
            try:
                oled.fill(0)
                
                if writer_big:
                    # Format: HH:MM (24H)
                    time_str = "{:02d}:{:02d}".format(h, m)
                    
                    # Measure width
                    w_time = writer_big.measure_text(time_str, spacing=2)
                    
                    # Center
                    start_x = (OLED_WIDTH - w_time) // 2
                    if start_x < 0: start_x = 0 
                    
                    # Draw
                    writer_big.text(time_str, start_x, 0, spacing=2)
                    
                else:
                    # Fallback
                    time_str = "{:02d}:{:02d}".format(h, m)
                    oled.text(time_str, 32, 12)
                    
                oled.show()
            except Exception as e:
                print(f"OLED Error: {e}")
                pass
            
        # Heartbeat
        led.toggle()
        time.sleep(1)

if __name__ == "__main__":
    main()
