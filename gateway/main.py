import rp2
from machine import Pin, SPI, UART
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
FW_VERSION = "2.6.0"

# CAN CONFIG
CAN_BAUDRATE = 500000   # Prius Gen2 OBD-II uses 500kbps
CAN_CRYSTAL = 16000000  # 16MHz crystal (many modules marked 8MHz are actually 16MHz!)
PIN_SCK = 2
PIN_MOSI = 3
PIN_MISO = 4
PIN_CS = 5
PIN_INT = 6

# RS485 CONFIG
RS485_BAUDRATE = 115200
PIN_RS485_TX = 8
PIN_RS485_RX = 9
PIN_RS485_EN = 7

# SPI FREQUENCY
# 1MHz is safe for MCP2515, need speed to prevent RX overflow
SPI_BAUDRATE = 1000000  # 1MHz - faster to prevent overflow 

# --- DATA ARCHITECTURE ---
DEV_ID_GATEWAY = 0
DEV_ID_CAN     = 1
DEV_ID_AVCLAN  = 2

# CONFIG FLAGS
ENABLE_SEQ_COUNTER = True # Adds "seq": <int> to all RX frames for continuity check

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
# MCP2515 requires SPI Mode 0,0 (CPOL=0, CPHA=0)
spi = SPI(0, baudrate=SPI_BAUDRATE, polarity=0, phase=0, sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))
can = mcp2515.MCP2515(spi, PIN_CS)
can_int = Pin(PIN_INT, Pin.IN)

# --- SETUP RS485 ---
rs485 = None
rs485_en = None
rs485_ready = False

try:
    rs485_en = Pin(PIN_RS485_EN, Pin.OUT, value=0)
    rs485 = UART(1, baudrate=RS485_BAUDRATE, tx=Pin(PIN_RS485_TX), rx=Pin(PIN_RS485_RX))
    rs485_ready = True
except Exception as e:
    sys.stdout.write(f'{{"id":0,"d":{{"log":"RS485 init error: {str(e)}"}}}}\n')

def rs485_send(data_str):
    if not rs485 or not rs485_ready: return
    try:
        rs485_en.value(1)
        # Ensure data ends with newline for NDJSON
        payload = data_str + '\n'
        rs485.write(payload)
        
        # Blocking wait for TX complete (approximate)
        # 10 bits per char (Start + 8 Data + Stop)
        # Calculate us: bits * 1000000 / baud
        bits = len(payload) * 10
        wait_us = int(bits * 1000000 / RS485_BAUDRATE) + 100 # +100us margin
        utime.sleep_us(wait_us)
        
        rs485_en.value(0)
    except Exception as e:
        sys.stdout.write(f'{{"id":0,"d":{{"err":"RS485_TX_FAIL: {str(e)}"}}}}\n')

def debug_mcp2515_connection(spi, cs_pin):
    try:
        cs = Pin(cs_pin, Pin.OUT, value=1)
        # RESET
        cs.value(0)
        spi.write(b'\xC0')
        cs.value(1)
        utime.sleep_ms(10)
        
        # Write CNF1 (0x2A) -> 0x55
        cs.value(0)
        spi.write(b'\x02\x2A\x55')
        cs.value(1)
        
        # Read CNF1
        cs.value(0)
        spi.write(b'\x03\x2A')
        val = spi.read(1)[0]
        cs.value(1)
        return val
    except Exception as e:
        return -1

can_ready = False
# Retry loop for initialization
for i in range(5):
    try:
        if can.init(CAN_BAUDRATE, CAN_CRYSTAL):
            can_ready = True
            break
        else:
            # Handle case where init returns False (e.g. old library version)
            val = debug_mcp2515_connection(spi, PIN_CS)
            sys.stdout.write(f'{{"id":0,"d":{{"log":"CAN init returned False. Debug Read: 0x{val:02X}"}}}}\n')
    except Exception as e:
        sys.stdout.write(f'{{"id":0,"d":{{"log":"CAN init error: {str(e)}"}}}}\n')
        # Also try debug check if exception occurred
        val = debug_mcp2515_connection(spi, PIN_CS)
        sys.stdout.write(f'{{"id":0,"d":{{"log":"Debug Read: 0x{val:02X}"}}}}\n')

    if not can_ready:
        sys.stdout.write(f'{{"id":0,"d":{{"log":"CAN init failed, retrying... ({i+1}/5)"}}}}\n')
        utime.sleep_ms(200)

if can_ready:
    # Print CAN diagnostic info
    try:
        status = can.get_status_debug()
        sys.stdout.write(f'{{"id":0,"d":{{"log":"CAN Mode: {status["mode"]}, EFLG: 0x{status["eflg"]:02X}"}}}}\n')
    except:
        pass
else:
    can_ready = False

# --- RX BUFFERS ---
RX_BUF_SIZE = 512
rx_buffer = array.array('I', [0] * RX_BUF_SIZE)

serial_poll = uselect.poll()
serial_poll.register(sys.stdin, uselect.POLLIN)
input_buffer = ""

# Sequence Counter (Cyclic 0-65535)
tx_seq_counter = 0

def get_next_seq():
    global tx_seq_counter
    seq = tx_seq_counter
    tx_seq_counter = (tx_seq_counter + 1) & 0xFFFF
    return seq

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
    if ENABLE_SEQ_COUNTER:
        sys.stdout.write(',"seq":')
        sys.stdout.write(str(get_next_seq()))
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
    if ENABLE_SEQ_COUNTER:
        sys.stdout.write(',"seq":')
        sys.stdout.write(str(get_next_seq()))
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
        
        # System Commands (Configuration)
        if dev_id == DEV_ID_GATEWAY:
            cfg = cmd.get("d")
            if cfg and "seq" in cfg:
                global ENABLE_SEQ_COUNTER
                ENABLE_SEQ_COUNTER = bool(cfg["seq"])
                sys.stdout.write('{"id":0,"d":{"msg":"CFG_UPDATED","seq":' + str(ENABLE_SEQ_COUNTER).lower() + '}}\n')
            return

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
        
        elif dev_id > 5:
            # RS485 Forwarding
            if not rs485_ready:
                sys.stdout.write('{"id":0,"d":{"err":"RS485_OFFLINE"}}\n')
                return
            
            # Forward the original command object as NDJSON
            # We use ujson.dumps to ensure it's a valid JSON string
            msg = ujson.dumps(cmd)
            rs485_send(msg)
            sys.stdout.write('{"id":0,"d":{"msg":"TX_ACK"}}\n')

    except:
        sys.stdout.write('{"id":0,"d":{"err":"JSON_PARSE"}}\n')

# Initial Status Report
can_msg = "CAN_READY" if can_ready else "CAN_INIT_FAIL"
rs485_msg = "READY" if rs485_ready else "FAIL"
print('{"id":0,"d":{"msg":"GATEWAY_READY","ver":"' + FW_VERSION + '","can":"' + can_msg + '","rs485":"' + rs485_msg + '"}}')

rx_idx = 0
last_rx_time = utime.ticks_ms()
pending_tuple = None
pending_count = 0
FLUSH_TIMEOUT = 50

# CAN diagnostic timer
can_diag_last = utime.ticks_ms()
CAN_DIAG_INTERVAL = 5000  # Print CAN diagnostic every 5 seconds

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

    # 3. CAN RX Poll - Check both interrupt pin AND poll directly
    if can_ready:
        can_loops = 0
        # Poll RX even if interrupt pin is high (more reliable for sniffing)
        while can_loops < 10:
            res = can.recv()
            if res:
                c_id, c_data, c_ext = res
                print_can_frame(current_time, c_id, c_data, c_ext)
                can_loops += 1
            else:
                break
        
        # Periodic CAN diagnostic
        if utime.ticks_diff(current_time, can_diag_last) > CAN_DIAG_INTERVAL:
            can_diag_last = current_time
            try:
                tec, rec, eflg = can.get_errors()
                rx_stat = can.rx_status()
                mode = can.get_mode()
                sys.stdout.write(f'{{"id":0,"d":{{"can_diag":{{"mode":"{mode}","tec":{tec},"rec":{rec},"eflg":"{eflg:02X}","rxs":"{rx_stat:02X}"}}}}}}\n')
            except Exception as e:
                sys.stdout.write(f'{{"id":0,"d":{{"err":"CAN_DIAG: {e}"}}}}\n')

    # 4. RS485 RX Poll
    if rs485_ready:
        while rs485.any():
            try:
                line = rs485.readline()
                if line:
                    # Try to decode and forward
                    try:
                        line_str = line.decode('utf-8').strip()
                        if line_str:
                            obj = ujson.loads(line_str)
                            
                            # Inject Metadata if missing
                            if "ts" not in obj:
                                obj["ts"] = current_time
                            if ENABLE_SEQ_COUNTER and "seq" not in obj:
                                obj["seq"] = get_next_seq()
                                
                            # Re-serialize to Stdout
                            sys.stdout.write(ujson.dumps(obj) + '\n')
                    except ValueError:
                        # Malformed JSON or garbage on bus - ignore
                        pass
            except Exception:
                pass

    # 5. AVC-LAN Processing
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
