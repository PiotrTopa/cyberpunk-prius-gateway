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

    def set_bitrate(self, baudrate):
        # Configuration for 8MHz Crystal
        # http://www.bittiming.can-wiki.info/
        # Target: 500kbps (Toyota standard)
        # 8MHz / 500kbps = 16 TQ.
        # TQ = 16
        # PropSeg + PhaseSeg1 >= PhaseSeg2
        # PhaseSeg2 >= SJW
        
        if baudrate == 500000:
            # 500kbps @ 8MHz
            # TQ = 16
            # Sync(1) + Prop(2) + Ph1(7) + Ph2(6) = 16.
            # CNF1 = 0x00 (SJW=1, BRP=0)
            # CNF2 = 0xB1 (BTL=1, SAM=0, PH1=6->7TQ, PR=1->2TQ) => 1011 0001
            # CNF3 = 0x05 (PH2=5->6TQ) => 0000 0101
            
            self.write_reg(CNF1, 0x00)
            self.write_reg(CNF2, 0xB1)
            self.write_reg(CNF3, 0x05)
            
        elif baudrate == 250000:
            # 250kbps @ 8MHz (BRP=1 -> /2)
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

    def set_loopback_mode(self):
        self.modify_reg(CANCTRL, 0xE0, 0x40)

    def init(self, baudrate=500000):
        self.reset()
        
        # Check connection by writing/reading a register
        # CNF1 is a good candidate in config mode
        test_val = 0x55
        self.write_reg(CNF1, test_val)
        read_val = self.read_reg(CNF1)
        if read_val != test_val:
            raise RuntimeError("MCP2515 Init Failed: Wrote 0x55, Read 0x{:02X}".format(read_val))
            
        self.set_bitrate(baudrate)
        
        # Configure interrupts (RX only)
        self.write_reg(CANINTE, 0x03) # RX0IE | RX1IE
        
        # Configure RX buffers (Turn off filters/masks -> Receive All)
        self.write_reg(RXB0CTRL, 0x60) # RXM=11 (Any msg), BUKT=0
        self.modify_reg(RXB0CTRL, 0x04, 0x04) # BUKT=1 (Rollover)
        
        if not self.set_normal_mode():
            raise RuntimeError("MCP2515 Init Failed: Could not enter Normal Mode")
        
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

    def recv(self):
        status = self.read_reg(READ_STATUS)
        rx_id = 0
        ext = False
        data = []
        
        # Check RXB0
        if status & 0x01:
            base = 0x61 # RXB0SIDH
        elif status & 0x02:
            base = 0x71 # RXB1SIDH
        else:
            return None
            
        # Read Header
        self.cs.value(0)
        self.spi.write(bytes([READ, base]))
        h = self.spi.read(5) # SIDH, SIDL, EID8, EID0, DLC
        self.cs.value(1)
        
        sidh = h[0]
        sidl = h[1]
        eid8 = h[2]
        eid0 = h[3]
        dlc = h[4] & 0x0F
        
        if sidl & 0x08: # EXIDE
            ext = True
            rx_id = (sidh << 21) | ((sidl & 0xE0) << 13) | ((sidl & 0x03) << 16) | (eid8 << 8) | eid0
        else:
            rx_id = (sidh << 3) | (sidl >> 5)
            
        # Read Data
        if dlc > 0:
            self.cs.value(0)
            self.spi.write(bytes([READ, base+5]))
            d = self.spi.read(dlc)
            self.cs.value(1)
            data = list(d)
            
        # Clear Interrupt flag
        if status & 0x01:
            self.modify_reg(CANINTF, 0x01, 0x00)
        else:
            self.modify_reg(CANINTF, 0x02, 0x00)
            
        return (rx_id, data, ext)

    def get_errors(self):
        tec = self.read_reg(0x1C)
        rec = self.read_reg(0x1D)
        eflg = self.read_reg(0x2D)
        return (tec, rec, eflg)
