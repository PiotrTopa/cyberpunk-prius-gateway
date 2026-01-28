import time
from machine import SPI, Pin

# Registers
CANCTRL   = 0x0F
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

class MCP2515:
    def __init__(self, spi, cs_pin):
        self.spi = spi
        self.cs = Pin(cs_pin, Pin.OUT, value=1)
        self.buf = bytearray(1)
        self.rx_buf = bytearray(14) # Max frame size

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

    def write_reg(self, addr, val):
        self.cs.value(0)
        self.spi.write(bytes([WRITE, addr, val]))
        self.cs.value(1)

    def modify_reg(self, addr, mask, val):
        self.cs.value(0)
        self.spi.write(bytes([BIT_MOD, addr, mask, val]))
        self.cs.value(1)

    def set_bitrate(self, baudrate, crystal=16000000):
        # Configuration for MCP2515 CAN Controller
        # Values from Arduino MCP_CAN library (mcp_can_dfs.h) - BATTLE TESTED
        # Most cheap modules use 16MHz crystal (not 8MHz!) despite marking
        
        if crystal == 16000000:
            # ===== 16MHz Crystal Settings - Arduino MCP_CAN library =====
            if baudrate == 500000:
                # MCP_16MHz_500kBPS from Arduino library
                self.write_reg(CNF1, 0x00)  # SJW=1, BRP=0
                self.write_reg(CNF2, 0xF0)  # BTL=1, SAM=1, PHSEG1=6, PRSEG=0
                self.write_reg(CNF3, 0x86)  # SOF, PHSEG2=6
                
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
            # EXACT values from Arduino MCP_CAN library (mcp_can_dfs.h)
            # DO NOT MODIFY - these are battle-tested
            if baudrate == 500000:
                # MCP_8MHz_500kBPS_CFG1/2/3 from Arduino library
                self.write_reg(CNF1, 0x00)  # SJW=1, BRP=0
                self.write_reg(CNF2, 0x90)  # BTLMODE=1, SAM=0, PHSEG1=2, PRSEG=0
                self.write_reg(CNF3, 0x02)  # PHSEG2=2
                
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
            # EID8, EID0 ignored
        
        # Setup DLC and Data
        dlc = len(data)
        if dlc > 8: dlc = 8
        self.write_reg(TXB0SIDH+4, dlc | (0x40 if False else 0)) # RTR support? assume data frame
        
        for i in range(dlc):
            self.write_reg(TXB0SIDH+5+i, data[i])
            
        # Request TX
        self.modify_reg(TXB0CTRL, 0x08, 0x08)
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
