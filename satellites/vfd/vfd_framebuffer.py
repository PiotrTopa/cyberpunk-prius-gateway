"""VFD Framebuffer - High-level graphics interface for GP1294AI VFD

Provides a framebuffer interface using MicroPython's framebuf module
for drawing graphics primitives on the VFD display.

Display Specifications:
    - Visible Resolution: 256 x 48 pixels
    - Uses physical coordinates for all drawing operations
    - Automatic conversion to GRAM format on show()

Usage:
    from vfd_framebuffer import VFDFramebuffer
    
    vfd = VFDFramebuffer()
    vfd.init()
    vfd.text("Hello VFD!", 0, 0, 1)
    vfd.rect(0, 0, 100, 40, 1)
    vfd.show()
"""

import framebuf
import micropython
from gp1294ai import GP1294AI, _REVERSE_BITS


@micropython.viper
def _fb_to_gram(src: ptr8, dst: ptr8, rev: ptr8):
    """
    Convert MONO_VLSB framebuffer (256x48) to GP1294AI GRAM layout (512x8),
    duplicating each physical column into 2 GRAM columns and bit-reversing
    every byte for LSB-first SPI transmission. Runs in ~1ms (viper).
    """
    for x in range(256):
        base = x << 4  # gram_col0 * 8, gram_col0 = x*2
        for yb in range(6):
            b = int(rev[int(src[(yb << 8) + x])])
            dst[base + yb] = b
            dst[base + 8 + yb] = b


class VFDFramebuffer(framebuf.FrameBuffer):
    """
    Framebuffer wrapper for GP1294AI VFD display.
    
    Inherits from framebuf.FrameBuffer providing drawing methods:
        - fill(c): Fill entire buffer with color (0 or 1)
        - pixel(x, y, c): Set pixel at (x, y) to color c
        - hline(x, y, w, c): Draw horizontal line
        - vline(x, y, h, c): Draw vertical line
        - line(x1, y1, x2, y2, c): Draw line between points
        - rect(x, y, w, h, c): Draw rectangle outline
        - fill_rect(x, y, w, h, c): Draw filled rectangle
        - text(s, x, y, c): Draw text string
        - scroll(xstep, ystep): Scroll buffer contents
        - blit(fbuf, x, y): Copy another framebuffer
    """
    
    # Display dimensions
    # Physical display: 256 × 48 visible pixels
    # GRAM memory: 512 columns × 8 bytes (2 GRAM columns = 1 physical pixel)
    WIDTH = 256   # Physical width (for drawing)
    HEIGHT = 48   # Physical height (for drawing)
    GRAM_WIDTH = 512
    GRAM_HEIGHT = 64
    GRAM_STRIDE = 8  # Bytes per GRAM column
    
    # Aliases for clarity
    VISIBLE_WIDTH = WIDTH
    VISIBLE_HEIGHT = HEIGHT
    
    def __init__(self, spi_id=0, sck_pin=2, mosi_pin=3, cs_pin=1,
                 rst_pin=4, fil_en_pin=0, baudrate=4000000):
        """
        Initialize VFD Framebuffer.
        
        Args:
            spi_id: SPI peripheral ID (0 or 1)
            sck_pin: GPIO pin for SPI clock
            mosi_pin: GPIO pin for SPI MOSI
            cs_pin: GPIO pin for chip select
            rst_pin: GPIO pin for hardware reset
            fil_en_pin: GPIO pin for filament enable
            baudrate: SPI clock speed
        """
        # Create the underlying display driver
        self._display = GP1294AI(
            spi_id=spi_id,
            sck_pin=sck_pin,
            mosi_pin=mosi_pin,
            cs_pin=cs_pin,
            rst_pin=rst_pin,
            fil_en_pin=fil_en_pin,
            baudrate=baudrate
        )
        
        # Allocate framebuffer memory using PHYSICAL dimensions
        # MONO_VLSB: Monochrome, vertical byte layout, LSB at top
        # Each byte represents 8 vertical pixels
        # Buffer size: 256 * (48 // 8) = 256 * 6 = 1536 bytes
        self._buffer = bytearray(self.WIDTH * (self.HEIGHT // 8))
        
        # Initialize parent FrameBuffer with PHYSICAL dimensions
        # Drawing uses physical coordinates (0-255, 0-47)
        # show() expands to GRAM (2 GRAM columns per physical pixel)
        super().__init__(self._buffer, self.WIDTH, self.HEIGHT, framebuf.MONO_VLSB)
        
        # Pre-allocated, pre-bit-reversed GRAM transfer buffer
        self._gram = bytearray(self.GRAM_WIDTH * self.GRAM_STRIDE)
        
        self._auto_show = False
    
    def init(self):
        """Initialize the display hardware."""
        self._display.init()
        self.fill(0)  # Clear framebuffer
    
    def _apply_trigger(self, buffer):
        """
        Apply display trigger pattern to GRAM buffer.
        Only GRAM column 0, byte 0 needed (minimizes visible artifact).
        """
        buffer[0 * self.GRAM_STRIDE + 0] = 0xFF
    
    def show(self):
        """
        Transfer framebuffer contents to display.
        
        Converts the physical framebuffer (256x48) to GRAM format (512x64)
        using a viper-compiled converter that also pre-reverses bits, then
        streams it via the raw fast path.
        """
        _fb_to_gram(self._buffer, self._gram, _REVERSE_BITS)
        # Display trigger: GRAM col 0 byte 0 must be set; 0xFF reversed is 0xFF
        self._gram[0] = 0xFF
        self._display.write_gram_raw(self._gram)
    
    def clear(self):
        """Clear the framebuffer and update display."""
        self.fill(0)
        self.show()
    
    def set_brightness(self, brightness):
        """
        Set display brightness.
        
        Args:
            brightness: Brightness value (0-255 typical range)
        """
        self._display.set_brightness(brightness)
    
    @property
    def auto_show(self):
        """Get auto-show mode status."""
        return self._auto_show
    
    @auto_show.setter
    def auto_show(self, value):
        """
        Enable/disable auto-show mode.
        When enabled, show() is called automatically after each draw operation.
        Warning: This can significantly slow down complex drawings.
        """
        self._auto_show = value
    
    def filament_on(self):
        """Enable VFD filament."""
        self._display.filament_on()
    
    def filament_off(self):
        """Disable VFD filament (display will be dark)."""
        self._display.filament_off()
    
    def standby(self, enable=True):
        """
        Enter or exit standby mode.
        
        Args:
            enable: True to enter standby, False to exit
        """
        if enable:
            self._display.enter_standby()
        else:
            self._display.exit_standby()
    
    def invert(self):
        """Invert all pixels in the framebuffer."""
        for i in range(len(self._buffer)):
            self._buffer[i] ^= 0xFF
    
    def draw_bitmap(self, x, y, bitmap, width, height, color=1):
        """
        Draw a bitmap image.
        
        Args:
            x: X position
            y: Y position
            bitmap: Bitmap data (bytes, 1 bit per pixel)
            width: Bitmap width in pixels
            height: Bitmap height in pixels
            color: 1 for on, 0 for off
        """
        byte_width = (width + 7) // 8
        for row in range(height):
            for col in range(width):
                byte_idx = row * byte_width + col // 8
                bit_idx = 7 - (col % 8)  # MSB first in bitmap
                if byte_idx < len(bitmap):
                    if (bitmap[byte_idx] >> bit_idx) & 1:
                        self.pixel(x + col, y + row, color)
                    else:
                        self.pixel(x + col, y + row, 1 - color)
    
    def draw_circle(self, cx, cy, r, color=1):
        """
        Draw a circle outline using Bresenham's algorithm.
        
        Args:
            cx: Center X coordinate
            cy: Center Y coordinate
            r: Radius
            color: 1 for on, 0 for off
        """
        x = r
        y = 0
        err = 0
        
        while x >= y:
            self.pixel(cx + x, cy + y, color)
            self.pixel(cx + y, cy + x, color)
            self.pixel(cx - y, cy + x, color)
            self.pixel(cx - x, cy + y, color)
            self.pixel(cx - x, cy - y, color)
            self.pixel(cx - y, cy - x, color)
            self.pixel(cx + y, cy - x, color)
            self.pixel(cx + x, cy - y, color)
            
            y += 1
            err += 1 + 2 * y
            if 2 * (err - x) + 1 > 0:
                x -= 1
                err += 1 - 2 * x
    
    def fill_circle(self, cx, cy, r, color=1):
        """
        Draw a filled circle.
        
        Args:
            cx: Center X coordinate
            cy: Center Y coordinate
            r: Radius
            color: 1 for on, 0 for off
        """
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                if x * x + y * y <= r * r:
                    self.pixel(cx + x, cy + y, color)
    
    def draw_progress_bar(self, x, y, width, height, progress, color=1):
        """
        Draw a progress bar.
        
        Args:
            x: X position
            y: Y position
            width: Total width
            height: Height
            progress: Progress value (0.0 to 1.0)
            color: 1 for on, 0 for off
        """
        # Draw outline
        self.rect(x, y, width, height, color)
        
        # Draw fill
        fill_width = int((width - 4) * max(0, min(1, progress)))
        if fill_width > 0:
            self.fill_rect(x + 2, y + 2, fill_width, height - 4, color)
    
    def center_text(self, text, y, color=1):
        """
        Draw centered text.
        
        Args:
            text: Text string to draw
            y: Y position
            color: 1 for on, 0 for off
        """
        # Each character is 8 pixels wide in default font
        text_width = len(text) * 8
        x = max(0, (self.VISIBLE_WIDTH - text_width) // 2)
        self.text(text, x, y, color)
    
    def deinit(self):
        """Deinitialize the display."""
        self._display.deinit()
    
    @property
    def buffer(self):
        """Get direct access to the framebuffer memory."""
        return self._buffer
    
    @property
    def display(self):
        """Get access to the underlying GP1294AI driver."""
        return self._display
