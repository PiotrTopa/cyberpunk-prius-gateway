"""
GP1294AI VFD Display Driver for RP2040 (MicroPython)

Low-level driver for Chinese VFD modules using the GP1294AI controller.

Display Specifications:
    - Visible Resolution: 256 x 48 pixels
    - GRAM Memory: 512 columns x 8 bytes (4096 bytes total)
    - Memory Mapping: 2 GRAM columns = 1 physical pixel
    - Column Layout: 8 bytes per column (64 vertical pixels, bytes 0-5 visible)

SPI Configuration:
    - Mode 3 (CPOL=1, CPHA=1)
    - Bit Order: LSB-first (requires manual bit reversal)
    - Default Speed: 500 kHz

Default Pinout (RP2040 Zero):
    - GP0: FIL_EN (Filament Enable, Active High)
    - GP1: CS# (Chip Select, Active Low)
    - GP2: SCK (SPI Clock)
    - GP3: MOSI (SPI Data)
    - GP4: RST# (Reset, Active Low)
"""

from machine import Pin, SPI
import time


def _make_reverse_table():
    """Generate bit reversal lookup table."""
    table = []
    for i in range(256):
        # Reverse bits manually
        b = 0
        for bit in range(8):
            if i & (1 << bit):
                b |= (1 << (7 - bit))
        table.append(b)
    return bytes(table)


# Pre-computed bit reversal lookup table for fast LSB-first conversion
_REVERSE_BITS = _make_reverse_table()


def _reverse_byte(b):
    """Reverse bits in a single byte."""
    return _REVERSE_BITS[b]


def _reverse_bytes(data):
    """Reverse bits in all bytes of data (for LSB-first transmission)."""
    if isinstance(data, int):
        return bytes([_REVERSE_BITS[data]])
    return bytes([_REVERSE_BITS[b] for b in data])


class GP1294AI:
    """Low-level driver for GP1294AI VFD controller."""
    
    # Command definitions
    CMD_RESET = 0xAA
    CMD_FRAME_SYNC = 0x08
    CMD_BRIGHTNESS = 0xA0
    CMD_DISPLAY_MODE = 0x80
    CMD_WRITE_GRAM = 0xF0
    CMD_DISPLAY_OFFSET = 0xC0
    CMD_VFD_MODE = 0xCC
    CMD_OSC_SETTING = 0x78
    CMD_EXIT_STANDBY = 0x6D
    CMD_ENTER_STANDBY = 0x61
    
    # Display dimensions
    # GRAM: 512 columns × 8 bytes/column (64 vertical pixels, bytes 0-5 visible)
    # Physical: 256 × 48 visible pixels (2 GRAM columns = 1 physical pixel)
    GRAM_WIDTH = 512
    GRAM_HEIGHT = 64
    GRAM_STRIDE = 8  # Bytes per GRAM column
    VISIBLE_WIDTH = 256
    VISIBLE_HEIGHT = 48
    
    # GRAM size in bytes (512 columns * 8 bytes per column)
    GRAM_SIZE = GRAM_WIDTH * GRAM_STRIDE  # 4096 bytes
    
    # Legacy aliases
    WIDTH = GRAM_WIDTH
    HEIGHT = GRAM_HEIGHT
    
    # Default brightness (0x0000 - 0x00FF range, higher = brighter)
    DEFAULT_BRIGHTNESS = 0x0028
    
    def __init__(self, spi_id=0, sck_pin=2, mosi_pin=3, cs_pin=1, 
                 rst_pin=4, fil_en_pin=0, baudrate=500000):
        """
        Initialize the GP1294AI VFD driver.
        
        Args:
            spi_id: SPI peripheral ID (0 or 1)
            sck_pin: GPIO pin for SPI clock
            mosi_pin: GPIO pin for SPI MOSI (TX)
            cs_pin: GPIO pin for chip select
            rst_pin: GPIO pin for hardware reset
            fil_en_pin: GPIO pin for filament enable
            baudrate: SPI clock speed (default 500kHz)
        """
        # Initialize control pins
        self.cs = Pin(cs_pin, Pin.OUT, value=1)  # CS high (inactive)
        self.rst = Pin(rst_pin, Pin.OUT, value=1)  # RST high (not reset)
        self.fil_en = Pin(fil_en_pin, Pin.OUT, value=0)  # Filament off initially
        
        # Initialize SPI
        # Mode 3: CPOL=1, CPHA=1
        # Note: RP2040 MicroPython doesn't support LSB-first, so we reverse bits manually
        self.spi = SPI(
            spi_id,
            baudrate=baudrate,
            polarity=1,
            phase=1,
            bits=8,
            sck=Pin(sck_pin),
            mosi=Pin(mosi_pin),
            miso=None
        )
        
        self._brightness = self.DEFAULT_BRIGHTNESS
        self._initialized = False
    
    def _cs_low(self):
        """Assert chip select (active low)."""
        self.cs.value(0)
    
    def _cs_high(self):
        """Deassert chip select."""
        self.cs.value(1)
    
    def _write_cmd(self, data):
        """
        Write command/data to the display.
        Automatically reverses bits for LSB-first transmission.
        
        Args:
            data: bytes or list of bytes to send
        """
        if isinstance(data, int):
            data = bytes([data])
        elif isinstance(data, list):
            data = bytes(data)
        
        # Reverse bits for LSB-first transmission
        reversed_data = _reverse_bytes(data)
        
        self._cs_low()
        self.spi.write(reversed_data)
        self._cs_high()
    
    def hardware_reset(self):
        """Perform hardware reset of the display."""
        self.rst.value(0)
        time.sleep_ms(10)
        self.rst.value(1)
        time.sleep_ms(50)
    
    def software_reset(self):
        """Send software reset command."""
        self._write_cmd([self.CMD_RESET])
        time.sleep_ms(50)
    
    def filament_on(self):
        """Enable the VFD filament (must be on to display)."""
        self.fil_en.value(1)
    
    def filament_off(self):
        """Disable the VFD filament."""
        self.fil_en.value(0)
    
    def set_brightness(self, brightness):
        """
        Set display brightness.
        
        Args:
            brightness: 16-bit brightness value (0x0000 - 0x00FF typical range)
        """
        self._brightness = brightness & 0xFFFF
        cmd = [
            self.CMD_BRIGHTNESS,
            self._brightness & 0xFF,
            (self._brightness >> 8) & 0xFF
        ]
        self._write_cmd(cmd)
    
    def set_display_offset(self, x_offset=0, y_offset=0x38):
        """
        Set display offset for proper vertical alignment.
        
        Args:
            x_offset: Horizontal offset (default 0)
            y_offset: Vertical offset (default 0x38 for correct alignment)
        """
        cmd = [self.CMD_DISPLAY_OFFSET, x_offset & 0xFF, y_offset & 0xFF]
        self._write_cmd(cmd)
    
    def set_display_mode(self, mode=0):
        """
        Set display mode.
        
        Args:
            mode: Display mode value
        """
        self._write_cmd([self.CMD_DISPLAY_MODE, mode])
    
    def set_vfd_mode(self):
        """Configure VFD mode settings."""
        cmd = [self.CMD_VFD_MODE, 0x01, 0x1F, 0x00, 0xFF, 0x3F, 0x00, 0x20]
        self._write_cmd(cmd)
    
    def set_oscillator(self):
        """Configure oscillator settings."""
        self._write_cmd([self.CMD_OSC_SETTING, 0x08])
    
    def enter_standby(self):
        """Enter standby/power-saving mode."""
        self._write_cmd([self.CMD_ENTER_STANDBY])
    
    def exit_standby(self):
        """Exit standby mode."""
        self._write_cmd([self.CMD_EXIT_STANDBY])
    
    def init(self):
        """
        Initialize the display with default settings.
        Must be called before using the display.
        """
        # Hardware reset
        self.hardware_reset()
        
        # Software reset
        self.software_reset()
        
        # Configure VFD mode
        self.set_vfd_mode()
        
        # Set brightness
        self.set_brightness(self._brightness)
        
        # Clear display (with trigger fix applied)
        self._apply_trigger_and_clear()
        time.sleep_ms(20)
        
        # Set display offset (Y=0x38 shifts display UP by 8 pixels)
        self.set_display_offset(0, 0x38)
        
        # Set display mode
        self.set_display_mode(0)
        
        # Configure oscillator
        self.set_oscillator()
        
        # Enable filament
        self.filament_on()
        
        self._initialized = True
    
    def _apply_trigger(self, buffer):
        """
        Apply display trigger pattern to buffer.
        
        The GP1294AI requires GRAM column 0, byte 0 to be set
        for display updates to be processed correctly.
        Only column 0 is needed (not column 1), minimizing artifacts.
        """
        buffer[0 * self.GRAM_STRIDE + 0] = 0xFF
        return buffer
    
    def _apply_trigger_and_clear(self):
        """Clear the display with trigger fix applied."""
        buffer = bytearray(self.GRAM_SIZE)
        self._apply_trigger(buffer)
        self.write_gram(buffer)
    
    def clear(self):
        """Clear the display (all pixels off, but trigger preserved)."""
        self._apply_trigger_and_clear()
    
    def fill(self):
        """Fill the display (all pixels on)."""
        full_frame = bytes([0xFF] * self.GRAM_SIZE)
        self.write_gram(full_frame)
    
    def write_gram(self, data, x_start=0, y_start=0):
        """
        Write data to GRAM (Graphics RAM).
        
        Args:
            data: Pixel data bytes (1 bit per pixel, column-major order)
            x_start: Starting X position  
            y_start: Starting Y position (in pixel rows)
        """
        # Build command header (no height parameter needed)
        header = bytes([self.CMD_WRITE_GRAM, x_start, y_start])
        
        # Ensure data is bytes
        if isinstance(data, (list, bytearray)):
            data = bytes(data)
        
        # Reverse bits for LSB-first transmission
        reversed_header = _reverse_bytes(header)
        reversed_data = _reverse_bytes(data)
        
        # Send header + data
        self._cs_low()
        self.spi.write(reversed_header)
        self.spi.write(reversed_data)
        self._cs_high()
    
    def write_gram_raw(self, data, x_start=0, y_start=0):
        """
        Write pre-bit-reversed data to GRAM (fast path).

        Args:
            data: Pixel data already bit-reversed for LSB-first transmission
            x_start: Starting X position
            y_start: Starting Y position
        """
        header = _reverse_bytes(bytes([self.CMD_WRITE_GRAM, x_start, y_start]))
        self._cs_low()
        self.spi.write(header)
        self.spi.write(data)
        self._cs_high()

    def frame_sync(self):
        """Send frame sync command."""
        self._write_cmd([self.CMD_FRAME_SYNC])
    
    def deinit(self):
        """Deinitialize the display and turn off filament."""
        self.filament_off()
        self.enter_standby()
        self._initialized = False
    
    @property
    def is_initialized(self):
        """Check if display is initialized."""
        return self._initialized
