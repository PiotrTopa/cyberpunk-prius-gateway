import rp2
from machine import Pin, SPI
import utime
import gc
import array
import sys
import uselect
import ujson
import mcp2515

# --- HARDWARE CONFIGURATION ---
# RP2040-Zero
RX_PIN = 0
TX_PIN = 1
BAUDRATE = 1000000
FW_VERSION = "2.5.0-can-alpha"

# CAN CONFIG
CAN_BAUDRATE = 500000
PIN_SCK = 2
PIN_MOSI = 3
PIN_MISO = 4
PIN_CS = 5
PIN_INT = 6

# --- DATA ARCHITECTURE ---
DEV_ID_GATEWAY = 0
DEV_ID_CAN     = 1
DEV_ID_AVCLAN  = 2

gc.collect()

# --- PIO 1: RX (SNIFFER - STABLE) ---
@rp2.asm_pio(set_init=rp2.PIO.IN_HIGH, autopush=True, push_thresh=32)
def avclan_rx_framed():
    wrap_target()
    label("idle_state")
    set(x, 31)
    wait(0, pin, 0)
    label("check_start")
    jmp(pin, "idle_state")
    jmp(x_dec, "check_start") [2]
    wait(1, pin, 0)

    label("read_next_bit")
    set(x, 20)
    label("wait_edge")
    jmp(pin, "check_timeout")
    jmp("got_edge")
    label("check_timeout")
    jmp(x_dec, "wait_edge") [9]
    push()
    jmp("idle_state")

    label("got_edge")
    wait(1, pin, 0)
    
    # Standard sampling point
    set(x, 15)
    label("delay_sample")
    jmp(x_dec, "delay_sample") [1]
    in_(pins, 1)
    jmp("read_next_bit")
    wrap()

# --- PIO 2: TX (GENERATOR - STANDARD) ---
@rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW, out_init=rp2.PIO.OUT_LOW, set_init=rp2.PIO.OUT_LOW, autopull=False)
def avclan_tx():
    pull() .side(0)
    set(x, 29) .side(1)
    label("start_on")
    jmp(x_dec, "start_on") [5]
    set(x, 19) .side(0)
    label("start_off")
    jmp(x_dec, "start_off")

    label("bit_loop")
    out(x, 1) .side(0)
    jmp(not_x, "send_zero") .side(0)

    set(y, 19) .side(1)
    label("one_on")
    jmp(y_dec, "one_on")
    set(y, 26) .side(0)
    label("one_off")
    jmp(y_dec, "one_off") [1]
    jmp("check_end") .side(0)

    label("send_zero")
    set(y, 19) .side(1)
    label("zero_on")
    jmp(y_dec, "zero_on")
    set(y, 19) .side(0)
    label("zero_off")
    jmp(y_dec, "zero_off")

    label("check_end")
    jmp(not_osre, "bit_loop") .side(0)
    nop() .side(0)
    wrap()

# --- SETUP AVC-LAN ---
sm_rx = rp2.StateMachine(0, avclan_rx_framed, freq=BAUDRATE, in_base=Pin(RX_PIN), jmp_pin=Pin(RX_PIN))
sm_rx.active(1)

tx_phy = Pin(TX_PIN, Pin.OUT, value=0)
sm_tx = rp2.StateMachine(4, avclan_tx, freq=BAUDRATE, sideset_base=tx_phy, out_shiftdir=rp2.PIO.SHIFT_LEFT)
sm_tx.active(1)

# --- SETUP CAN ---
spi = SPI(0, baudrate=10000000, sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))
can = mcp2515.MCP2515(spi, PIN_CS)
can_int = Pin(PIN_INT, Pin.IN)

can_ready = False
if can.init(CAN_BAUDRATE):
    can_ready = True
    # Can message is printed later with GATEWAY_READY
else:
    can_ready = False

# --- RX BUFFERS ---
RX_BUF_SIZE = 512
rx_buffer = array.array('I', [0] * RX_BUF_SIZE)

serial_poll = uselect.poll()
serial_poll.register(sys.stdin, uselect.POLLIN)
input_buffer = ""

# --- LOGIC ---
def get_bits_static(buf, start_bit, count):
    result = 0
    for i in range(count):
        curr_ptr = start_bit + i
        word_idx = curr_ptr // 32
        if word_idx >= RX_BUF_SIZE: return -1
        bit_in_word = 31 - (curr_ptr % 32)
        bit = (buf[word_idx] >> bit_in_word) & 1
        result = (result << 1) | bit
    return result

def check_parity_fast(val, width, parity_bit):
    count = 0
    v = val
    while v: v &= (v - 1); count += 1
    return ((count + parity_bit) % 2) != 0

def print_avclan_frame(ts, m, s, c, data_bytes, cnt):
    sys.stdout.write('{"id":2,"ts":')
    sys.stdout.write(str(ts))
    sys.stdout.write(',"d":{"m":"')
    sys.stdout.write('{:03X}'.format(m))
    sys.stdout.write('","s":"')
    sys.stdout.write('{:03X}'.format(s))
    sys.stdout.write('","c":')
    sys.stdout.write(str(c))
    sys.stdout.write(',"d":[')
    first = True
    for b in data_bytes:
        if not first: sys.stdout.write(',')
        sys.stdout.write('"{:02X}"'.format(b))
        first = False
    sys.stdout.write('],"cnt":' + str(cnt) + '}}\n')

def print_can_frame(ts, can_id, data, ext):
    # {"id":1,"ts":...,"d":{"i":"0x123","d":[...]}}
    sys.stdout.write('{"id":1,"ts":')
    sys.stdout.write(str(ts))
    sys.stdout.write(',"d":{"i":"')
    sys.stdout.write("0x{:X}".format(can_id))
    sys.stdout.write('","d":[')
    first = True
    for b in data:
        if not first: sys.stdout.write(',')
        sys.stdout.write(str(b))
        first = False
    sys.stdout.write(']}}\n')

# Helper function for frame decoding (used in retry loop)
def try_decode(buf, ptr):
    m = get_bits_static(buf, ptr, 12)
    p = get_bits_static(buf, ptr+12, 1)
    if not check_parity_fast(m, 12, p): return None
    
    s = get_bits_static(buf, ptr+13, 12)
    p = get_bits_static(buf, ptr+25, 1)
    if not check_parity_fast(s, 12, p): return None
    
    c = get_bits_static(buf, ptr+26, 4)
    p = get_bits_static(buf, ptr+30, 1)
    if not check_parity_fast(c, 4, p): return None
    
    l = get_bits_static(buf, ptr+31, 8)
    p = get_bits_static(buf, ptr+39, 1)
    if not check_parity_fast(l, 8, p): return None
    
    if l > 32: return None
    
    d_list = []
    curr = ptr + 40
    for _ in range(l):
        val = get_bits_static(buf, curr, 8)
        d_list.append(val)
        curr += 9
        
    return (m, s, c, bytes(d_list), 40 + (l*9))

def decode_smart_static(buf, ptr, limit_idx):
    if (ptr // 32) > limit_idx: return None, 0
    
    # 1. Normal attempt (Shift = 0)
    res = try_decode(buf, ptr)
    if res:
        m, s, c, d, length = res
        return (m, s, c, d), length
    
    # 2. Rescue attempt (Shift = +1)
    # If first attempt failed, try 1-bit shift
    # (only if we have enough data)
    res = try_decode(buf, ptr + 1)
    if res:
        m, s, c, d, length = res
        # Return length + 1 to adjust pointer for the shift
        return (m, s, c, d), length + 1
        
    return None, 0

def tx_push(val, w, acc, fill):
    for i in range(w - 1, -1, -1):
        bit = (val >> i) & 1
        acc = (acc << 1) | bit
        fill += 1
        if fill == 32:
            sm_tx.put(acc)
            acc = 0; fill = 0
    return acc, fill

def process_usb_command(json_line):
    try:
        clean_line = json_line.strip()
        if not clean_line: return
        cmd = ujson.loads(clean_line)
        dev_id = cmd.get("id")
        data = cmd.get("d")
        if not data: return

        if dev_id == DEV_ID_AVCLAN:
            m = int(data["m"], 16); s = int(data["s"], 16); c = int(data["c"])
            d_arr = [int(x, 16) for x in data["d"]]
            acc = 0; fill = 0
            for val, w in [(m,12), (s,12), (c,4), (len(d_arr),8)]:
                cnt = 0; v=val
                while v: v &= (v-1); cnt += 1
                p = 1 if (cnt % 2) == 0 else 0
                acc, fill = tx_push(val, w, acc, fill)
                acc, fill = tx_push(p, 1, acc, fill)
            for b in d_arr:
                cnt = 0; v=b
                while v: v &= (v-1); cnt += 1
                p = 1 if (cnt % 2) == 0 else 0
                acc, fill = tx_push(b, 8, acc, fill)
                acc, fill = tx_push(p, 1, acc, fill)
            if fill > 0: sm_tx.put(acc << (32 - fill))
            sys.stdout.write('{"id":0,"d":{"msg":"TX_ACK"}}\n')

        elif dev_id == DEV_ID_CAN:
            if not can_ready:
                sys.stdout.write('{"id":0,"d":{"err":"CAN_OFFLINE"}}\n')
                return
            
            can_id_str = data.get("i")
            if isinstance(can_id_str, str):
                can_id = int(can_id_str, 16)
            else:
                can_id = int(can_id_str)
                
            can_data = data.get("d", [])
            is_ext = data.get("e", False) # Extended frame flag, optional
            
            if can.send(can_id, can_data, is_ext):
                sys.stdout.write('{"id":0,"d":{"msg":"TX_ACK"}}\n')
            else:
                sys.stdout.write('{"id":0,"d":{"err":"CAN_TX_FULL"}}\n')

    except:
        sys.stdout.write('{"id":0,"d":{"err":"JSON_PARSE"}}\n')

# Initial Status Report
can_msg = "CAN_READY" if can_ready else "CAN_INIT_FAIL"
print('{"id":0,"d":{"msg":"GATEWAY_READY","ver":"' + FW_VERSION + '","can":"' + can_msg + '"}}')

rx_idx = 0
last_rx_time = utime.ticks_ms()
pending_tuple = None
pending_count = 0
FLUSH_TIMEOUT = 50

while True:
    # 1. USB Poll
    while serial_poll.poll(0):
        ch = sys.stdin.read(1)
        if ch:
            if ch == '\n':
                process_usb_command(input_buffer)
                input_buffer = ""
            else:
                input_buffer += ch
    
    # 2. AVC-LAN RX Poll
    loops = 0
    while sm_rx.rx_fifo() > 0:
        val = sm_rx.get()
        if rx_idx < RX_BUF_SIZE:
            rx_buffer[rx_idx] = val
            rx_idx += 1
        last_rx_time = utime.ticks_ms()
        loops += 1
        if loops > 50: break

    current_time = utime.ticks_ms()

    # 3. CAN RX Poll
    if can_ready and can_int.value() == 0:
        # Loop limit to prevent starvation
        can_loops = 0
        while can_int.value() == 0 and can_loops < 10:
            res = can.recv()
            if res:
                c_id, c_data, c_ext = res
                print_can_frame(current_time, c_id, c_data, c_ext)
            can_loops += 1

    # 4. AVC-LAN Processing
    should_process = (rx_idx > (RX_BUF_SIZE * 0.75)) or (rx_idx > 0 and utime.ticks_diff(current_time, last_rx_time) > 15)

    if should_process:
        total_bits = rx_idx * 32
        ptr = 0
        while ptr < total_bits - 40:
            frame_tuple, bit_len = decode_smart_static(rx_buffer, ptr, rx_idx)
            if frame_tuple:
                if pending_tuple == frame_tuple:
                    pending_count += 1
                else:
                    if pending_tuple is not None:
                        print_avclan_frame(current_time, *pending_tuple, pending_count)
                    pending_tuple = frame_tuple
                    pending_count = 1
                ptr += bit_len
            else:
                ptr += 1
        rx_idx = 0
        if pending_tuple and utime.ticks_diff(current_time, last_rx_time) > FLUSH_TIMEOUT:
            print_avclan_frame(current_time, *pending_tuple, pending_count)
            pending_tuple = None
            pending_count = 0
        gc.collect()
