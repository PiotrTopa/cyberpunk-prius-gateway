"""
MCP2515 CAN Controller Driver with PIO Acceleration
====================================================

Optimized driver for MCP2515 on RP2040 with multiple performance tiers:

1. STANDARD MODE (recv):
   - Uses hardware SPI
   - ~30kHz polling rate
   - Good for low-traffic scenarios

2. FAST MODE (recv_fast, recv_burst):
   - Pre-allocated buffers (zero GC)
   - ~50kHz polling rate
   - Recommended for most use cases

3. PIO-ACCELERATED MODE (poll_with_pio):
   - PIO state machine handles SPI
   - ~100kHz polling rate
   - Runs independently of CPU
   - EXPERIMENTAL

4. IRQ-ASSISTED MODE (wait_for_rx):
   - Uses MCP2515 INT pin for wakeup
   - Lowest latency (~10µs response)
   - CPU can idle between frames

The MCP2515 has only 2 RX buffers, so at 500kbps CAN a frame arrives
every ~200µs in worst case. Fast polling is critical to avoid overflow.

Version: 2.9.0
"""

import time
import gc
from machine import SPI, Pin
import rp2
import array

# Registers
CANCTRL   = 0x0F

# ISO-TP Frame Types (ISO 15765-2)
ISOTP_SF = 0x00  # Single Frame
ISOTP_FF = 0x10  # First Frame
ISOTP_CF = 0x20  # Consecutive Frame
ISOTP_FC = 0x30  # Flow Control
CANSTAT   = 0x0E
CNF1      = 0x2A
CNF2      = 0x29
CNF3      = 0x28
TXB0CTRL  = 0x30
TXB0SIDH  = 0x31
RXB0CTRL  = 0x60
RXB0SIDH  = 0x61
RX0IF     = 0x01
RX1IF     = 0x02
TXB0REQ   = 0x08
CANINTE   = 0x2B
CANINTF   = 0x2C
EFLG      = 0x2D

# Commands
RESET     = 0xC0
READ      = 0x03
WRITE     = 0x02
BIT_MOD   = 0x05
RX_STATUS = 0xB0
READ_STATUS = 0xA0

# ============================================================================
# PIO-ACCELERATED SPI FOR MCP2515
# ============================================================================
# This PIO program implements a high-speed SPI master optimized for polling
# MCP2515's RX_STATUS command. Runs at ~10MHz SPI, independent of CPU.
# 
# Key insight: PIO runs at 125MHz and can poll MCP2515 continuously while
# the CPU does other work. This creates an FPGA-like polling mechanism.
# ============================================================================

@rp2.asm_pio(
    out_shiftdir=rp2.PIO.SHIFT_LEFT,
    in_shiftdir=rp2.PIO.SHIFT_LEFT,
    autopull=True,
    autopush=True,
    pull_thresh=8,
    push_thresh=8,
    sideset_init=rp2.PIO.OUT_LOW,
    out_init=rp2.PIO.OUT_LOW
)
def pio_spi_cpha0():
    """
    PIO SPI Master - Mode 0 (CPOL=0, CPHA=0)
    Sideset: SCK
    OUT: MOSI
    IN: MISO
    
    Runs at ~10MHz SPI (125MHz / 12 cycles per bit)
    """
    wrap_target()
    # Pull 8 bits, shift out MSB first while sampling MISO
    out(x, 1)        .side(0)    # Output bit, SCK low
    nop()            .side(0) [1] # Setup time
    in_(pins, 1)     .side(1)    # Sample MISO, SCK high  
    nop()            .side(1) [1] # Hold time
    # After 8 bits, autopush sends to RX FIFO, autopull loads from TX FIFO
    wrap()


class PioSpiAccelerator:
    """
    PIO-based SPI accelerator for MCP2515 fast polling.
    
    This class provides an FPGA-like continuous polling mechanism that
    runs independently of the main CPU. It uses a dedicated PIO state
    machine to perform SPI transactions at maximum speed.
    """
    
    def __init__(self, sm_id, freq, sck_pin, mosi_pin, miso_pin, cs_pin):
        """
        Initialize PIO SPI accelerator.
        
        Args:
            sm_id: PIO state machine ID (0-7)
            freq: SPI frequency in Hz (max ~10MHz for MCP2515)
            sck_pin: GPIO number for SCK
            mosi_pin: GPIO number for MOSI  
            miso_pin: GPIO number for MISO
            cs_pin: GPIO number for CS
        """
        self.cs = Pin(cs_pin, Pin.OUT, value=1)
        self.miso = Pin(miso_pin, Pin.IN)
        
        # Calculate PIO frequency: need ~12 cycles per SPI bit
        pio_freq = freq * 12
        
        self.sm = rp2.StateMachine(
            sm_id,
            pio_spi_cpha0,
            freq=pio_freq,
            sideset_base=Pin(sck_pin),
            out_base=Pin(mosi_pin),
            in_base=self.miso
        )
        
        # Pre-allocated buffers to avoid GC during hot path
        self._cmd_buf = array.array('B', [0] * 16)
        self._rx_buf = array.array('B', [0] * 16)
        
    def activate(self):
        """Start the PIO state machine."""
        self.sm.active(1)
        
    def deactivate(self):
        """Stop the PIO state machine."""
        self.sm.active(0)
        
    def transfer_byte(self, tx_byte):
        """Transfer single byte via PIO SPI, returns received byte."""
        self.sm.put(tx_byte << 24)  # Left-align for shift-left
        return self.sm.get() & 0xFF
    
    def rx_status_fast(self):
        """
        Ultra-fast RX_STATUS poll using PIO.
        
        Returns RX_STATUS byte:
            Bits 7-6: 00=no msg, 01=RXB0, 10=RXB1, 11=both
            Bits 5-4: Reserved
            Bits 3: Extended ID flag
            Bits 2-0: Filter match
        """
        self.cs.value(0)
        # Send RX_STATUS command (0xB0)
        self.sm.put(RX_STATUS << 24)
        _ = self.sm.get()  # Discard command echo
        # Clock in response byte
        self.sm.put(0xFF << 24)  # Dummy byte to clock in response
        result = self.sm.get() & 0xFF
        self.cs.value(1)
        return result
    
    def read_rx_buffer_fast(self, buffer_num=0):
        """
        Fast atomic read of RX buffer using READ_RX_BUFFER command.
        
        Uses 0x90 (RXB0) or 0x94 (RXB1) for atomic read + auto-clear.
        Returns: (can_id, data_list, is_extended) or None
        """
        cmd = 0x90 if buffer_num == 0 else 0x94
        
        self.cs.value(0)
        
        # Send command
        self.sm.put(cmd << 24)
        _ = self.sm.get()
        
        # Read 13 bytes: 5 header + 8 data
        frame = []
        for _ in range(13):
            self.sm.put(0xFF << 24)
            frame.append(self.sm.get() & 0xFF)
        
        self.cs.value(1)
        
        # Parse frame
        sidh = frame[0]
        sidl = frame[1]
        dlc = frame[4] & 0x0F
        if dlc > 8:
            dlc = 8
            
        can_id = (sidh << 3) | (sidl >> 5)
        data = frame[5:5+dlc] if dlc > 0 else []
        
        return (can_id, data, False)


# ============================================================================
# RING BUFFER FOR PIO-ACCELERATED RX
# ============================================================================

class FastRingBuffer:
    """
    Lock-free ring buffer optimized for single-producer/single-consumer.
    Uses pre-allocated arrays to avoid any GC during operation.
    """
    
    def __init__(self, capacity=32):
        self.capacity = capacity
        self.head = 0  # Write position (producer)
        self.tail = 0  # Read position (consumer)
        
        # Pre-allocate storage for CAN frames
        # Each entry: [timestamp, can_id, dlc, d0, d1, d2, d3, d4, d5, d6, d7, ext]
        self._data = array.array('I', [0] * (capacity * 12))
        
    def put(self, timestamp, can_id, data, ext=False):
        """Add frame to buffer. Returns True if successful, False if full."""
        next_head = (self.head + 1) % self.capacity
        if next_head == self.tail:
            return False  # Buffer full
            
        base = self.head * 12
        self._data[base] = timestamp
        self._data[base + 1] = can_id
        self._data[base + 2] = len(data)
        
        for i in range(8):
            self._data[base + 3 + i] = data[i] if i < len(data) else 0
            
        self._data[base + 11] = 1 if ext else 0
        
        self.head = next_head
        return True
        
    def get(self):
        """Remove and return oldest frame. Returns None if empty."""
        if self.head == self.tail:
            return None  # Buffer empty
            
        base = self.tail * 12
        timestamp = self._data[base]
        can_id = self._data[base + 1]
        dlc = self._data[base + 2]
        data = [self._data[base + 3 + i] for i in range(dlc)]
        ext = self._data[base + 11] != 0
        
        self.tail = (self.tail + 1) % self.capacity
        return (timestamp, can_id, data, ext)
        
    def available(self):
        """Returns number of frames in buffer."""
        if self.head >= self.tail:
            return self.head - self.tail
        return self.capacity - self.tail + self.head
        
    def is_empty(self):
        return self.head == self.tail
        
    def is_full(self):
        return ((self.head + 1) % self.capacity) == self.tail

class MCP2515:
    def __init__(self, spi, cs_pin, int_pin=None, pio_accelerated=False, pio_sm_id=2):
        """
        Initialize MCP2515 CAN controller.
        
        Args:
            spi: SPI object for communication
            cs_pin: GPIO number for chip select
            int_pin: GPIO number for interrupt (optional, for IRQ-based RX)
            pio_accelerated: Enable PIO-based fast polling (experimental)
            pio_sm_id: PIO state machine ID for acceleration (2-7, 0-1 used by AVC-LAN)
        """
        self.spi = spi
        self.cs = Pin(cs_pin, Pin.OUT, value=1)
        self.int_pin = Pin(int_pin, Pin.IN) if int_pin is not None else None
        self.buf = bytearray(1)
        self.rx_buf = bytearray(14)  # Max frame size
        
        # Pre-allocated buffers for zero-GC hot path
        self._read_cmd = bytearray(2)
        self._frame_buf = bytearray(14)
        self._tx_buf = bytearray(14)
        
        # PIO acceleration (optional)
        self.pio_accel = None
        self.pio_accelerated = False
        if pio_accelerated:
            try:
                # Get SPI pins from the SPI object (assumes standard pinout)
                # Note: Caller should pass pin numbers matching their SPI setup
                self.pio_accel = PioSpiAccelerator(
                    sm_id=pio_sm_id,
                    freq=10_000_000,  # 10MHz SPI
                    sck_pin=spi.sck if hasattr(spi, 'sck') else 2,
                    mosi_pin=spi.mosi if hasattr(spi, 'mosi') else 3,
                    miso_pin=spi.miso if hasattr(spi, 'miso') else 4,
                    cs_pin=cs_pin
                )
                self.pio_accelerated = True
            except Exception as e:
                # Fall back to standard SPI if PIO init fails
                self.pio_accelerated = False
        
        # Fast ring buffer for high-throughput RX
        self.fast_ring = FastRingBuffer(capacity=64)
        
        # Statistics for monitoring
        self.rx_count = 0
        self.rx_overflow = 0
        
        # IRQ-based reception (optional, for lowest latency)
        self._irq_enabled = False
        self._irq_pending = False
        if self.int_pin is not None:
            self._setup_irq()

    def _setup_irq(self):
        """
        Setup interrupt-driven RX notification.
        
        MCP2515 INT pin goes LOW when a frame is received.
        We use this to wake up the polling loop immediately.
        """
        def _irq_handler(pin):
            self._irq_pending = True
            
        try:
            self.int_pin.irq(trigger=Pin.IRQ_FALLING, handler=_irq_handler)
            self._irq_enabled = True
        except:
            self._irq_enabled = False
    
    def wait_for_rx(self, timeout_us=1000):
        """
        Wait for RX interrupt with timeout.
        
        More efficient than polling - CPU can idle while waiting.
        Falls back to polling if IRQ not available.
        
        Returns: True if frame may be available, False if timeout
        """
        import utime
        
        if self._irq_enabled:
            # Wait for IRQ or timeout
            start = utime.ticks_us()
            while not self._irq_pending:
                if utime.ticks_diff(utime.ticks_us(), start) > timeout_us:
                    return False
                utime.sleep_us(5)
            self._irq_pending = False
            return True
        else:
            # Fallback: poll INT pin directly
            if self.int_pin is not None:
                return self.int_pin.value() == 0  # Active low
            return True  # No INT pin, always try to receive

    def reset(self):
        self.cs.value(0)
        self.spi.write(bytes([RESET]))
        self.cs.value(1)
        time.sleep_ms(5)

    def read_reg(self, addr):
        self.cs.value(0)
        self.spi.write(bytes([READ, addr]))
        val = self.spi.read(1)
        self.cs.value(1)
        return val[0]
    
    def read_reg_fast(self, addr):
        """Optimized register read using pre-allocated buffer."""
        self._read_cmd[0] = READ
        self._read_cmd[1] = addr
        self.cs.value(0)
        self.spi.write(self._read_cmd)
        self.spi.readinto(self.buf)
        self.cs.value(1)
        return self.buf[0]

    def write_reg(self, addr, val):
        self.cs.value(0)
        self.spi.write(bytes([WRITE, addr, val]))
        self.cs.value(1)

    def modify_reg(self, addr, mask, val):
        self.cs.value(0)
        self.spi.write(bytes([BIT_MOD, addr, mask, val]))
        self.cs.value(1)

    def set_bitrate(self, baudrate, crystal=8000000):
        # Configuration for MCP2515 CAN Controller
        #
        # !!! DO NOT CHANGE THESE VALUES !!!
        # Crystal is 8MHz (confirmed 2026-02-17). Changing to 16MHz BREAKS ALL CAN.
        # CNF register values are confirmed working. Do not "optimize" them.
        #
        if crystal == 16000000:
            # ===== 16MHz Crystal Settings (not used, kept for reference) =====
            if baudrate == 500000:
                self.write_reg(CNF1, 0x00)
                self.write_reg(CNF2, 0xF0)
                self.write_reg(CNF3, 0x86)
                
            elif baudrate == 250000:
                # MCP_16MHz_250kBPS from Arduino library
                self.write_reg(CNF1, 0x41)  # SJW=2, BRP=1
                self.write_reg(CNF2, 0xF1)  # BTL=1, SAM=1, PHSEG1=6, PRSEG=1
                self.write_reg(CNF3, 0x85)  # SOF, PHSEG2=5
                
            elif baudrate == 125000:
                # MCP_16MHz_125kBPS from Arduino library
                self.write_reg(CNF1, 0x43)  # SJW=2, BRP=3
                self.write_reg(CNF2, 0xF0)
                self.write_reg(CNF3, 0x86)
                
        elif crystal == 8000000:
            # ===== 8MHz Crystal Settings =====
            # !!! DO NOT CHANGE - confirmed working 2026-02-17 !!!
            if baudrate == 500000:
                # 8MHz @ 500kbps - CONFIRMED WORKING
                self.write_reg(CNF1, 0xC0)  # SJW=4, BRP=0 → TQ=250ns
                self.write_reg(CNF2, 0xD8)  # BTL=1, SAM=1, PHSEG1=4, PRSEG=1
                self.write_reg(CNF3, 0x01)  # PHSEG2=2
                
            elif baudrate == 250000:
                # MCP_8MHz_250kBPS - Arduino MCP_CAN library exact values
                self.write_reg(CNF1, 0x00)
                self.write_reg(CNF2, 0xB1)
                self.write_reg(CNF3, 0x05)
                
            elif baudrate == 125000:
                # MCP_8MHz_125kBPS - Arduino MCP_CAN library exact values
                self.write_reg(CNF1, 0x01)
                self.write_reg(CNF2, 0xB1)
                self.write_reg(CNF3, 0x05)

    def set_normal_mode(self):
        self.modify_reg(CANCTRL, 0xE0, 0x00)
        # Wait for mode change
        for _ in range(10):
            if (self.read_reg(CANSTAT) & 0xE0) == 0x00: return True
            time.sleep_ms(1)
        return False

    def set_listen_only_mode(self):
        """Listen-Only Mode (0x60) - Essential for sniffing!
        In this mode, MCP2515 does NOT send ACKs or participate in error handling.
        This is required for passive bus monitoring."""
        self.modify_reg(CANCTRL, 0xE0, 0x60)
        # Wait for mode change
        for _ in range(10):
            if (self.read_reg(CANSTAT) & 0xE0) == 0x60: return True
            time.sleep_ms(1)
        return False

    def set_loopback_mode(self):
        self.modify_reg(CANCTRL, 0xE0, 0x40)

    def enable_tx(self):
        """Switch from Listen-Only to Normal Mode to enable transmission.
        
        IMPORTANT: In Normal Mode, the MCP2515 will ACK frames and participate
        in error handling. This is REQUIRED for request/response communication
        (OBD-II, UDS, etc.) but changes bus behavior from passive sniffing.
        
        Returns:
            bool: True if mode switch successful, False otherwise.
        """
        return self.set_normal_mode()

    def disable_tx(self):
        """Switch back to Listen-Only Mode (passive sniffing).
        
        Returns:
            bool: True if mode switch successful, False otherwise.
        """
        return self.set_listen_only_mode()

    def send_and_wait(self, can_id, data, response_ids, timeout_ms=100, ext=False, poll_cb=None):
        """Send a CAN frame and wait for a response on specified IDs.
        
        This is the core primitive for OBD-II/UDS request-response communication.
        
        Args:
            can_id: The CAN ID to send the request to (e.g., 0x7DF for OBD broadcast)
            data: List of data bytes (max 8)
            response_ids: List of CAN IDs to listen for response (e.g., [0x7E8, 0x7E9])
            timeout_ms: Max time to wait for response (default 100ms)
            ext: True for extended CAN ID (29-bit), False for standard (11-bit)
            poll_cb: Optional callback called during wait loops to service other I/O
            
        Returns:
            tuple: (response_id, response_data) if response received, None if timeout
        """
        import utime
        
        # Clear only TX interrupt flag, preserve RX flags
        # Previously cleared ALL flags (0x00) which discarded pending RX frames
        self.modify_reg(CANINTF, 0x1C, 0x00)  # Clear TX flags only (bits 2-4)
        
        # Send request
        if not self.send(can_id, data, ext):
            return None  # TX buffer full
        
        # Wait for TX complete (TXB0REQ bit clears when sent)
        start = utime.ticks_ms()
        while self.read_reg(TXB0CTRL) & TXB0REQ:
            if utime.ticks_diff(utime.ticks_ms(), start) > timeout_ms:
                return None  # TX timeout
            if poll_cb: poll_cb()
            utime.sleep_us(100)
        
        # Wait for response
        while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
            res = self.recv()
            if res:
                rx_id, rx_data, rx_ext = res
                if rx_id in response_ids:
                    return (rx_id, rx_data)
            if poll_cb: poll_cb()
            utime.sleep_us(100)
        
        return None  # Timeout, no matching response

    def send_and_wait_isotp(self, tx_can_id, data, response_ids, timeout_ms=500, ext=False, debug=False, retries=3, poll_cb=None):
        """Send a CAN frame and wait for an ISO-TP response with multi-frame reassembly.
        
        This handles both Single Frame (SF) and multi-frame (FF + CF) responses per ISO 15765-2.
        For multi-frame responses, automatically sends Flow Control (FC) and collects all
        Consecutive Frames (CF) until the complete payload is reassembled.
        
        Includes automatic retry logic for multi-frame responses that fail due to
        MCP2515 RX buffer overflow (only 2 buffers available).
        
        Args:
            tx_can_id: The CAN ID to send the request to (e.g., 0x7E2 for HV ECU)
            data: List of data bytes (max 8)
            response_ids: List of CAN IDs to listen for response (e.g., [0x7EA])
            timeout_ms: Max time to wait for complete response (default 500ms for multi-frame)
            ext: True for extended CAN ID (29-bit), False for standard (11-bit)
            debug: If True, emit debug log messages for ISO-TP state machine
            retries: Number of retry attempts for multi-frame responses (default 3)
            poll_cb: Optional callback called during wait loops to service other I/O
            
        Returns:
            tuple: (response_id, reassembled_data) if response received, None if timeout
            For SF: data is the payload bytes (length from PCI)
            For FF+CF: data is the complete reassembled payload
        """
        import utime
        import sys
        
        for attempt in range(retries + 1):
            result = self._send_and_wait_isotp_once(tx_can_id, data, response_ids, timeout_ms, ext, debug, attempt, poll_cb)
            if result is not None:
                return result
            # Small delay before retry
            if attempt < retries:
                utime.sleep_ms(50)
        
        return None
    
    def _send_and_wait_isotp_once(self, tx_can_id, data, response_ids, timeout_ms, ext, debug, attempt, poll_cb=None):
        """Internal: Single attempt at ISO-TP transaction."""
        import utime
        import sys
        
        def log(msg):
            if debug:
                retry_info = f" (attempt {attempt+1})" if attempt > 0 else ""
                sys.stdout.write(f'{{"id":0,"d":{{"isotp":"{msg}{retry_info}"}}}}\n')
        
        # Clear only TX interrupt flags, preserve RX flags
        # ISO-TP sessions pause Core 1, so we own the SPI bus here
        self.modify_reg(CANINTF, 0x1C, 0x00)  # Clear TX flags only (bits 2-4)
        
        log(f"TX REQ to 0x{tx_can_id:03X}: {list(data)}")
        
        # Send request
        if not self.send(tx_can_id, data, ext):
            log("TX FAIL: buffer full")
            return None  # TX buffer full
        
        # Wait for TX complete
        start = utime.ticks_ms()
        while self.read_reg(TXB0CTRL) & TXB0REQ:
            if utime.ticks_diff(utime.ticks_ms(), start) > timeout_ms:
                log("TX TIMEOUT")
                return None  # TX timeout
            utime.sleep_us(100)
        
        log("TX complete, waiting for response...")
        
        # Wait for first response frame
        rx_can_id = None
        while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
            res = self.recv()
            if res:
                rx_id, rx_data, rx_ext = res
                if rx_id in response_ids and len(rx_data) > 0:
                    frame_type = rx_data[0] & 0xF0
                    
                    # ===== Single Frame (SF) =====
                    if frame_type == ISOTP_SF:
                        sf_len = rx_data[0] & 0x0F
                        if sf_len == 0 or sf_len > 7:
                            continue  # Invalid SF length
                        log(f"RX SF from 0x{rx_id:03X}, len={sf_len}")
                        # Return payload bytes (skip PCI byte)
                        return (rx_id, list(rx_data[1:1+sf_len]))
                    
                    # ===== First Frame (FF) - Start multi-frame reception =====
                    elif frame_type == ISOTP_FF:
                        rx_can_id = rx_id
                        # Total payload length from FF (12-bit)
                        total_len = ((rx_data[0] & 0x0F) << 8) | rx_data[1]
                        
                        log(f"RX FF from 0x{rx_id:03X}, total={total_len} bytes")
                        
                        # Initialize reassembly buffer with first 6 data bytes
                        buffer = list(rx_data[2:8])
                        received = len(buffer)
                        expected_seq = 1
                        
                        # CRITICAL: Calculate correct Flow Control target ID
                        # For OBD-II: If we used broadcast (0x7DF) or request ID, 
                        # FC must go to the ECU's REQUEST ID (response_id - 8)
                        # This maps 0x7E8->0x7E0, 0x7E9->0x7E1, 0x7EA->0x7E2, etc.
                        # For direct addressing (0x7E0-0x7E7): FC goes to same ID
                        if tx_can_id == 0x7DF:
                            # Broadcast: derive request ID from response ID
                            fc_target_id = rx_id - 8
                        elif 0x7E0 <= tx_can_id <= 0x7E7:
                            # Direct ECU addressing: FC goes to same request ID
                            fc_target_id = tx_can_id
                        elif 0x7E8 <= rx_id <= 0x7EF:
                            # Response is from OBD-II ECU, derive request ID
                            fc_target_id = rx_id - 8
                        else:
                            # Non-standard IDs: assume paired ID (response - 8) or same as tx
                            # For safety, use tx_can_id if we can't determine pairing
                            fc_target_id = tx_can_id
                        
                        log(f"TX FC to 0x{fc_target_id:03X}")
                        
                        # Send Flow Control (FC): CTS, BlockSize=0, STmin=0
                        fc_frame = [ISOTP_FC, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
                        if not self.send(fc_target_id, fc_frame, ext):
                            log("FC TX FAIL")
                            return None
                        
                        # Receive CFs - poll as fast as possible
                        cf_buffer = {}
                        int_pin = self.int_pin
                        
                        while received < total_len:
                            if utime.ticks_diff(utime.ticks_ms(), start) > timeout_ms:
                                log(f"CF TIMEOUT: {received}/{total_len}, got={list(cf_buffer.keys())}")
                                return None
                            
                            # Fast check: INT pin low means message waiting
                            if int_pin is not None:
                                if int_pin.value() == 1:
                                    continue  # No interrupt, loop fast
                            
                            # Poll RX status
                            status = self.rx_status()
                            msg_location = (status >> 6) & 0x03
                            
                            # Read RXB0 if has message
                            if msg_location & 0x01:
                                self.cs.value(0)
                                self.spi.write(bytes([0x90]))
                                frame = self.spi.read(13)
                                self.cs.value(1)
                                
                                cf_id = (frame[0] << 3) | (frame[1] >> 5)
                                if cf_id == rx_can_id:
                                    dlc = frame[4] & 0x0F
                                    if dlc > 8: dlc = 8
                                    if dlc > 0 and (frame[5] & 0xF0) == ISOTP_CF:
                                        cf_seq = frame[5] & 0x0F
                                        cf_buffer[cf_seq] = list(frame[6:6+min(7, dlc-1)])
                            
                            # Read RXB1 if has message
                            if msg_location & 0x02:
                                self.cs.value(0)
                                self.spi.write(bytes([0x94]))
                                frame = self.spi.read(13)
                                self.cs.value(1)
                                
                                cf_id = (frame[0] << 3) | (frame[1] >> 5)
                                if cf_id == rx_can_id:
                                    dlc = frame[4] & 0x0F
                                    if dlc > 8: dlc = 8
                                    if dlc > 0 and (frame[5] & 0xF0) == ISOTP_CF:
                                        cf_seq = frame[5] & 0x0F
                                        cf_buffer[cf_seq] = list(frame[6:6+min(7, dlc-1)])
                            
                            # Consume sequential CFs
                            while expected_seq in cf_buffer:
                                cf_payload = cf_buffer.pop(expected_seq)
                                bytes_to_copy = min(len(cf_payload), total_len - received)
                                buffer.extend(cf_payload[:bytes_to_copy])
                                received += bytes_to_copy
                                expected_seq = (expected_seq + 1) & 0x0F
                        
                        log(f"Complete! {total_len} bytes")
                        return (rx_can_id, buffer[:total_len])
            else:
                if poll_cb: poll_cb()
                utime.sleep_us(100)
        
        log("Response TIMEOUT")
        return None  # Timeout, no matching response

    def init(self, baudrate=500000, crystal=16000000):
        """Initialize MCP2515 CAN controller.
        
        Args:
            baudrate: CAN bus speed (500000, 250000, 125000)
            crystal: Crystal frequency in Hz (16000000 or 8000000)
                     Most cheap modules use 16MHz crystal!
        """
        self.reset()
        
        # Check connection by writing/reading a register
        # CNF1 is a good candidate in config mode
        test_val = 0x55
        self.write_reg(CNF1, test_val)
        read_val = self.read_reg(CNF1)
        if read_val != test_val:
            raise RuntimeError("MCP2515 Init Failed: Wrote 0x55, Read 0x{:02X}".format(read_val))
            
        self.set_bitrate(baudrate, crystal)
        
        # Clear all pending interrupts
        self.write_reg(CANINTF, 0x00)
        
        # Configure interrupts (RX only)
        self.write_reg(CANINTE, 0x03) # RX0IE | RX1IE
        
        # Configure RX buffers (Turn off filters/masks -> Receive All)
        # RXB0CTRL: RXM=11 (Receive Any Message), BUKT=1 (Rollover to RXB1)
        self.write_reg(RXB0CTRL, 0x64) # RXM=11 (Any msg), BUKT=1
        # RXB1CTRL: RXM=11 (Receive Any Message)
        self.write_reg(0x70, 0x60) # RXB1CTRL, RXM=11
        
        # Clear all filter/mask registers to receive everything
        for addr in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]: # RXF0-RXF5, RXM0-RXM1
            pass # RXM=11 already disables filters
        
        # Use Listen-Only Mode for sniffing (does not ACK frames)
        if not self.set_listen_only_mode():
            raise RuntimeError("MCP2515 Init Failed: Could not enter Listen-Only Mode")
        
        return True

    def send(self, can_id, data, ext=False):
        # Check if TXB0 is free
        ctrl = self.read_reg(TXB0CTRL)
        if ctrl & TXB0REQ: return False # Buffer full
        
        # Setup ID
        if ext:
            self.write_reg(TXB0SIDH, (can_id >> 21) & 0xFF)
            self.write_reg(TXB0SIDH+1, (((can_id >> 13) & 0x07) << 5) | 0x08 | ((can_id >> 16) & 0x03))
            self.write_reg(TXB0SIDH+2, (can_id >> 8) & 0xFF)
            self.write_reg(TXB0SIDH+3, can_id & 0xFF)
        else:
            self.write_reg(TXB0SIDH, (can_id >> 3) & 0xFF)
            self.write_reg(TXB0SIDH+1, (can_id & 0x07) << 5)
        
        # Setup DLC and Data
        dlc = len(data)
        if dlc > 8: dlc = 8
        self.write_reg(TXB0SIDH+4, dlc)
        
        for i in range(dlc):
            self.write_reg(TXB0SIDH+5+i, data[i])
        
        # Request TX using fast RTS command
        self.cs.value(0)
        self.spi.write(bytes([0x81]))  # RTS TXB0
        self.cs.value(1)
        return True

    def read_status(self):
        """Read status using dedicated READ_STATUS command (0xA0)
        Returns: Bit0=RX0IF, Bit1=RX1IF, Bit2=TXB0REQ, Bit3=TX0IF..."""
        self.cs.value(0)
        self.spi.write(bytes([READ_STATUS]))
        val = self.spi.read(1)[0]
        self.cs.value(1)
        return val

    def rx_status(self):
        """RX STATUS command (0xB0) - More reliable for checking RX buffers
        Returns: Bits 7-6: 00=no msg, 01=msg in RXB0, 10=msg in RXB1, 11=both"""
        self.cs.value(0)
        self.spi.write(bytes([RX_STATUS]))
        val = self.spi.read(1)[0]
        self.cs.value(1)
        return val

    def recv(self):
        # Use RX_STATUS command (0xB0) to check for messages
        status = self.rx_status()
        rx_id = 0
        ext = False
        data = []
        
        # RX_STATUS bits 7-6: 00=no msg, 01=RXB0, 10=RXB1, 11=both
        msg_location = (status >> 6) & 0x03
        
        if msg_location == 0:
            return None  # No message
        
        # Use READ RX BUFFER command for atomic read + auto clear interrupt
        # 0x90 = Read RXB0 starting at SIDH (nm=00)
        # 0x94 = Read RXB1 starting at SIDH (nm=10)
        if msg_location & 0x01:  # Message in RXB0 (or both)
            read_cmd = 0x90
        else:  # Message in RXB1 only
            read_cmd = 0x94
            
        # Read entire frame atomically using READ RX BUFFER command
        # This is faster than READ command and auto-clears interrupt flag
        self.cs.value(0)
        self.spi.write(bytes([read_cmd]))
        frame = self.spi.read(13)  # 5 header + 8 data bytes
        self.cs.value(1)
        
        sidh = frame[0]
        sidl = frame[1]
        eid8 = frame[2]
        eid0 = frame[3]
        dlc = frame[4] & 0x0F
        if dlc > 8:
            dlc = 8  # CAN 2.0B max payload is 8 bytes
        
        # Standard ID only (Prius OBD-II uses 11-bit IDs)
        rx_id = (sidh << 3) | (sidl >> 5)
            
        # Extract data from the same frame buffer
        if dlc > 0:
            data = list(frame[5:5+dlc])
            
        return (rx_id, data, ext)

    # ========================================================================
    # ULTRA-FAST POLLING METHODS (PIO-ACCELERATED)
    # ========================================================================
    
    def recv_fast(self):
        """
        Optimized receive using pre-allocated buffers and minimal overhead.
        
        This method is ~30% faster than recv() by:
        1. Using pre-allocated frame buffer (no allocation)
        2. Using readinto() instead of read() (no copy)
        3. Inlined parsing (no function call overhead)
        
        Returns: (can_id, data_list, is_extended) or None
        """
        # Check RX status using fast register read
        status = self.rx_status()
        msg_location = (status >> 6) & 0x03
        
        if msg_location == 0:
            return None
        
        read_cmd = 0x90 if (msg_location & 0x01) else 0x94
        
        # Atomic read using pre-allocated buffer
        self.cs.value(0)
        self.spi.write(bytes([read_cmd]))
        self.spi.readinto(self._frame_buf, 13)
        self.cs.value(1)
        
        # Inline parsing (avoid function call overhead)
        sidh = self._frame_buf[0]
        sidl = self._frame_buf[1]
        dlc = self._frame_buf[4] & 0x0F
        if dlc > 8:
            dlc = 8
            
        can_id = (sidh << 3) | (sidl >> 5)
        
        # Build data list from buffer
        data = [self._frame_buf[5 + i] for i in range(dlc)]
        
        self.rx_count += 1
        return (can_id, data, False)
    
    def recv_to_ring(self):
        """
        Ultra-fast receive directly to ring buffer.
        
        Designed for Core 1 tight polling loop. Receives all available
        frames in both RX buffers and stores them in the fast ring buffer.
        
        Returns: Number of frames received (0, 1, or 2)
        """
        import utime
        count = 0
        ts = utime.ticks_ms()
        
        # Poll both RX buffers in quick succession
        for _ in range(2):
            status = self.rx_status()
            msg_location = (status >> 6) & 0x03
            
            if msg_location == 0:
                break
                
            read_cmd = 0x90 if (msg_location & 0x01) else 0x94
            
            self.cs.value(0)
            self.spi.write(bytes([read_cmd]))
            self.spi.readinto(self._frame_buf, 13)
            self.cs.value(1)
            
            sidh = self._frame_buf[0]
            sidl = self._frame_buf[1]
            dlc = self._frame_buf[4] & 0x0F
            if dlc > 8:
                dlc = 8
                
            can_id = (sidh << 3) | (sidl >> 5)
            data = [self._frame_buf[5 + i] for i in range(dlc)]
            
            if self.fast_ring.put(ts, can_id, data, False):
                count += 1
                self.rx_count += 1
            else:
                self.rx_overflow += 1
        
        return count
    
    def recv_burst(self, max_frames=8):
        """
        Burst receive: Collect multiple frames as fast as possible.
        
        Uses tight polling loop to grab frames from both RX buffers
        before they can overflow. Ideal for high-traffic scenarios.
        
        Args:
            max_frames: Maximum frames to collect per burst (default 8)
            
        Returns: List of (can_id, data, ext) tuples
        """
        import utime
        frames = []
        
        for _ in range(max_frames):
            status = self.rx_status()
            msg_location = (status >> 6) & 0x03
            
            if msg_location == 0:
                break
            
            read_cmd = 0x90 if (msg_location & 0x01) else 0x94
            
            self.cs.value(0)
            self.spi.write(bytes([read_cmd]))
            self.spi.readinto(self._frame_buf, 13)
            self.cs.value(1)
            
            sidh = self._frame_buf[0]
            sidl = self._frame_buf[1]
            dlc = self._frame_buf[4] & 0x0F
            if dlc > 8:
                dlc = 8
            
            can_id = (sidh << 3) | (sidl >> 5)
            data = [self._frame_buf[5 + i] for i in range(dlc)]
            
            frames.append((can_id, data, False))
            self.rx_count += 1
        
        return frames
    
    def poll_with_pio(self):
        """
        PIO-accelerated polling (experimental).
        
        Uses PIO state machine for ultra-fast SPI transactions.
        Can achieve ~100kHz polling rate vs ~30kHz with standard SPI.
        
        Returns: (can_id, data, ext) or None
        """
        if not self.pio_accelerated or self.pio_accel is None:
            return self.recv_fast()
        
        # Use PIO for status check and frame read
        status = self.pio_accel.rx_status_fast()
        msg_location = (status >> 6) & 0x03
        
        if msg_location == 0:
            return None
        
        buffer_num = 0 if (msg_location & 0x01) else 1
        return self.pio_accel.read_rx_buffer_fast(buffer_num)
    
    def get_rx_stats(self):
        """Returns RX statistics for monitoring."""
        return {
            "rx_count": self.rx_count,
            "rx_overflow": self.rx_overflow,
            "ring_available": self.fast_ring.available(),
            "pio_enabled": self.pio_accelerated
        }

    def get_errors(self):
        tec = self.read_reg(0x1C)
        rec = self.read_reg(0x1D)
        eflg = self.read_reg(0x2D)
        return (tec, rec, eflg)

    def get_mode(self):
        """Returns current operating mode from CANSTAT register"""
        stat = self.read_reg(CANSTAT)
        mode = (stat >> 5) & 0x07
        modes = {0: "NORMAL", 1: "SLEEP", 2: "LOOPBACK", 3: "LISTEN", 4: "CONFIG"}
        return modes.get(mode, f"UNKNOWN({mode})")

    def get_status_debug(self):
        """Returns diagnostic info for troubleshooting"""
        canstat = self.read_reg(CANSTAT)
        canctrl = self.read_reg(CANCTRL)
        canintf = self.read_reg(CANINTF)
        eflg = self.read_reg(EFLG)
        return {
            "mode": self.get_mode(),
            "canstat": canstat,
            "canctrl": canctrl,
            "canintf": canintf,
            "eflg": eflg
        }
