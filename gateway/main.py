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
FW_VERSION = "2.27.0"  # AVC-LAN: drain PIO FIFO during CAN RX burst, diagnostics, and RS485 reads

# CAN CONFIG
CAN_BAUDRATE = 500000   # Prius Gen2 OBD-II uses 500kbps
# !!! DO NOT CHANGE CAN_CRYSTAL OR BITRATE REGISTERS IN mcp2515.py !!!
# 8MHz crystal is CONFIRMED WORKING with this module.
# Changing to 16MHz or modifying CNF1/CNF2/CNF3 values BREAKS ALL CAN communication.
# Tested and confirmed on 2026-02-17.
CAN_CRYSTAL = 8000000   # 8MHz crystal (marked 8.000) - CONFIRMED WORKING, DO NOT CHANGE
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
# MCP2515 supports up to 10MHz SPI on ideal PCB traces, but prototype
# wiring (jumper wires, breadboard) corrupts data above ~5MHz.
# 4MHz is 4x faster than original 1MHz while staying reliable.
SPI_BAUDRATE = 4000000  # 4MHz - safe for prototype wiring

# --- DATA ARCHITECTURE ---
DEV_ID_GATEWAY = 0
DEV_ID_CAN     = 1
DEV_ID_AVCLAN  = 2

# CONFIG FLAGS
ENABLE_SEQ_COUNTER = True # Adds "seq": <int> to all RX frames for continuity check
ENABLE_ISOTP_DEBUG = False  # Enable ISO-TP state machine debug logging

# CAN MODE FLAGS
CAN_TX_ENABLED = False  # Start in listen-only mode (passive sniffing)

# --- CAN SUBSCRIPTION MANAGER ---
# Subscriptions allow periodic polling of OBD-II PIDs or custom CAN requests.
# Each subscription is a dict:
#   {
#       "slot": int,           # Unique slot ID (0-15)
#       "req_id": int,         # Request CAN ID (e.g., 0x7DF for OBD broadcast)
#       "req_data": bytes,     # Request payload (e.g., [0x02, 0x01, 0x0C] for RPM)
#       "resp_ids": list,      # Expected response IDs (e.g., [0x7E8])
#       "interval_ms": int,    # Polling interval in milliseconds
#       "last_poll": int,      # Timestamp of last poll
#       "timeout_ms": int,     # Response timeout (default 100ms)
#       "ext": bool,           # Extended frame flag
#       "isotp": bool          # Use ISO-TP multi-frame reassembly
#   }
CAN_SUBSCRIPTIONS = {}  # slot_id -> subscription dict
MAX_SUBSCRIPTIONS = 16
can_sub_rr = 0  # Round-robin index for fair subscription polling

# OBD-II Standard Response IDs (ECUs respond on 0x7E8-0x7EF)
OBD2_RESPONSE_IDS = [0x7E8, 0x7E9, 0x7EA, 0x7EB, 0x7EC, 0x7ED, 0x7EE, 0x7EF]

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
can = mcp2515.MCP2515(spi, PIN_CS, PIN_INT)
can_int = can.int_pin  # Use the same pin object

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

# --- CAN DIAGNOSTICS (periodic, from Core 0 main loop) ---
can_diag_last = 0
CAN_DIAG_INTERVAL = 5000  # ms

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

def print_avclan_frame(ts, m, s, c, data_bytes):
    # Single sys.stdout.write() to minimize USB CDC packet fragmentation
    d_str = ','.join('"' + '{:02X}'.format(b) + '"' for b in data_bytes)
    seq_str = ',"seq":' + str(get_next_seq()) if ENABLE_SEQ_COUNTER else ''
    sys.stdout.write('{"id":2,"ts":' + str(ts) + seq_str + ',"d":{"m":"' + '{:03X}'.format(m) + '","s":"' + '{:03X}'.format(s) + '","c":' + str(c) + ',"d":[' + d_str + ']}}\n')

def print_can_frame(ts, can_id, data, ext):
    # Single sys.stdout.write() to minimize USB CDC packet fragmentation
    d_str = ','.join(str(b) for b in data)
    seq_str = ',"seq":' + str(get_next_seq()) if ENABLE_SEQ_COUNTER else ''
    sys.stdout.write('{"id":1,"ts":' + str(ts) + seq_str + ',"d":{"i":"0x' + '{:X}'.format(can_id) + '","d":[' + d_str + ']}}\n')

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
    global CAN_TX_ENABLED, CAN_SUBSCRIPTIONS
    try:
        clean_line = json_line.strip()
        if not clean_line: return
        cmd = ujson.loads(clean_line)
        dev_id = cmd.get("id")
        
        # Debug: echo received command type for diagnostics
        data_peek = cmd.get("d", {})
        action_peek = data_peek.get("a", "") if isinstance(data_peek, dict) else ""
        sys.stdout.write('{"id":0,"d":{"log":"USB_RX","dev":' + str(dev_id) + ',"a":"' + str(action_peek) + '"}}\n')
        
        # System Commands (Configuration)
        if dev_id == DEV_ID_GATEWAY:
            cfg = cmd.get("d")
            if not cfg: return
            
            if "seq" in cfg:
                global ENABLE_SEQ_COUNTER
                ENABLE_SEQ_COUNTER = bool(cfg["seq"])
                sys.stdout.write('{"id":0,"d":{"msg":"CFG_UPDATED","seq":' + str(ENABLE_SEQ_COUNTER).lower() + '}}\n')
            
            if "isotp_debug" in cfg:
                global ENABLE_ISOTP_DEBUG
                ENABLE_ISOTP_DEBUG = bool(cfg["isotp_debug"])
                sys.stdout.write('{"id":0,"d":{"msg":"CFG_UPDATED","isotp_debug":' + str(ENABLE_ISOTP_DEBUG).lower() + '}}\n')
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

        elif dev_id == DEV_ID_CAN:
            if not can_ready:
                sys.stdout.write('{"id":0,"d":{"err":"CAN_OFFLINE"}}\n')
                return
            
            action = data.get("a", "tx")  # Default action is "tx" (send frame)
            
            # --- ACTION: tx (Send raw CAN frame, legacy behavior) ---
            if action == "tx":
                can_id_str = data.get("i")
                if isinstance(can_id_str, str):
                    can_id = int(can_id_str, 16)
                else:
                    can_id = int(can_id_str)
                    
                can_data = data.get("d", [])
                is_ext = data.get("e", False)
                
                # Enable TX mode if not already
                if not CAN_TX_ENABLED:
                    if can.enable_tx():
                        CAN_TX_ENABLED = True
                    else:
                        sys.stdout.write('{"id":0,"d":{"err":"CAN_MODE_SWITCH_FAIL"}}\n')
                        return
                
                if not can.send(can_id, can_data, is_ext):
                    sys.stdout.write('{"id":0,"d":{"err":"CAN_TX_FULL"}}\n')
            
            # --- ACTION: req (Single request-response query) ---
            elif action == "req":
                # Request format:
                # {"id":1,"d":{"a":"req","i":"0x7DF","d":[2,1,12],"r":["0x7E8"],"t":100}}
                # For multi-frame (ISO-TP) responses, add "isotp":true
                can_id_str = data.get("i")
                if isinstance(can_id_str, str):
                    can_id = int(can_id_str, 16)
                else:
                    can_id = int(can_id_str)
                    
                can_data = data.get("d", [])
                is_ext = data.get("e", False)
                timeout = data.get("t", 100)  # Default 100ms timeout
                use_isotp = data.get("isotp", False)  # Use ISO-TP reassembly
                
                # Auto-enable ISO-TP for longer timeout (likely multi-frame response)
                if timeout >= 300 and not use_isotp:
                    use_isotp = True
                
                # Parse response IDs
                resp_ids_raw = data.get("r", OBD2_RESPONSE_IDS)
                resp_ids = []
                for rid in resp_ids_raw:
                    if isinstance(rid, str):
                        resp_ids.append(int(rid, 16))
                    else:
                        resp_ids.append(int(rid))
                
                # Perform request-response (with optional ISO-TP reassembly)
                # Enable TX mode if not already
                if not CAN_TX_ENABLED:
                    if can.enable_tx():
                        CAN_TX_ENABLED = True
                    else:
                        sys.stdout.write('{"id":0,"d":{"err":"CAN_MODE_SWITCH_FAIL"}}\n')
                        return
                
                if use_isotp:
                    result = can.send_and_wait_isotp(can_id, can_data, resp_ids, timeout, is_ext, ENABLE_ISOTP_DEBUG)
                else:
                    result = can.send_and_wait(can_id, can_data, resp_ids, timeout, is_ext)
                
                if result:
                    resp_id, resp_data = result
                    # Single write for USB CDC efficiency
                    d_str = ','.join(str(b) for b in resp_data)
                    seq_str = ',"seq":' + str(get_next_seq()) if ENABLE_SEQ_COUNTER else ''
                    sys.stdout.write('{"id":1,"ts":' + str(utime.ticks_ms()) + seq_str + ',"d":{"a":"resp","i":"0x' + '{:X}'.format(resp_id) + '","d":[' + d_str + ']}}\n')
                else:
                    sys.stdout.write('{"id":1,"d":{"a":"resp","err":"TIMEOUT"}}\n')
            
            # --- ACTION: sub (Subscribe to periodic polling) ---
            elif action == "sub":
                # Subscribe format:
                # {"id":1,"d":{"a":"sub","slot":0,"i":"0x7DF","d":[2,1,12],"r":["0x7E8"],"int":500,"t":100}}
                slot = data.get("slot")
                if slot is None or slot < 0 or slot >= MAX_SUBSCRIPTIONS:
                    sys.stdout.write('{"id":0,"d":{"err":"INVALID_SLOT"}}\n')
                    return
                
                can_id_str = data.get("i")
                if isinstance(can_id_str, str):
                    can_id = int(can_id_str, 16)
                else:
                    can_id = int(can_id_str)
                
                can_data = bytes(data.get("d", []))
                interval = data.get("int", 1000)  # Default 1 second
                timeout = data.get("t", 100)
                is_ext = data.get("e", False)
                use_isotp = data.get("isotp", False)  # Use ISO-TP multi-frame reassembly
                
                # Auto-enable ISO-TP for longer timeout (likely multi-frame response)
                if timeout >= 300 and not use_isotp:
                    use_isotp = True
                
                # Parse response IDs
                resp_ids_raw = data.get("r", OBD2_RESPONSE_IDS)
                resp_ids = []
                for rid in resp_ids_raw:
                    if isinstance(rid, str):
                        resp_ids.append(int(rid, 16))
                    else:
                        resp_ids.append(int(rid))
                
                # Create subscription
                CAN_SUBSCRIPTIONS[slot] = {
                    "slot": slot,
                    "req_id": can_id,
                    "req_data": can_data,
                    "resp_ids": resp_ids,
                    "interval_ms": interval,
                    "last_poll": 0,  # Will trigger immediately
                    "timeout_ms": timeout,
                    "ext": is_ext,
                    "isotp": use_isotp,
                }
                
                # Enable TX mode if not already
                if not CAN_TX_ENABLED:
                    if can.enable_tx():
                        CAN_TX_ENABLED = True
                    else:
                        sys.stdout.write('{"id":0,"d":{"err":"CAN_MODE_SWITCH_FAIL"}}\n')
                        del CAN_SUBSCRIPTIONS[slot]
                        return
                
                sys.stdout.write('{"id":0,"d":{"msg":"SUB_OK","slot":' + str(slot) + '}}\n')
            
            # --- ACTION: unsub (Unsubscribe from slot) ---
            elif action == "unsub":
                slot = data.get("slot")
                if slot is not None and slot in CAN_SUBSCRIPTIONS:
                    del CAN_SUBSCRIPTIONS[slot]
                    sys.stdout.write('{"id":0,"d":{"msg":"UNSUB_OK","slot":' + str(slot) + '}}\n')
                elif slot == "all":
                    CAN_SUBSCRIPTIONS.clear()
                    sys.stdout.write('{"id":0,"d":{"msg":"UNSUB_ALL"}}\n')
                else:
                    sys.stdout.write('{"id":0,"d":{"err":"SLOT_NOT_FOUND"}}\n')
            
            # --- ACTION: mode (Switch CAN mode) ---
            elif action == "mode":
                mode = data.get("m", "listen")
                if mode == "normal" or mode == "tx":
                    if can.enable_tx():
                        CAN_TX_ENABLED = True
                        sys.stdout.write('{"id":0,"d":{"msg":"CAN_MODE","m":"NORMAL"}}\n')
                    else:
                        sys.stdout.write('{"id":0,"d":{"err":"MODE_SWITCH_FAIL"}}\n')
                elif mode == "listen":
                    if can.disable_tx():
                        CAN_TX_ENABLED = False
                        CAN_SUBSCRIPTIONS.clear()  # Clear subscriptions when going passive
                        sys.stdout.write('{"id":0,"d":{"msg":"CAN_MODE","m":"LISTEN"}}\n')
                    else:
                        sys.stdout.write('{"id":0,"d":{"err":"MODE_SWITCH_FAIL"}}\n')
                else:
                    sys.stdout.write('{"id":0,"d":{"err":"INVALID_MODE"}}\n')
            
            # --- ACTION: subs (List active subscriptions) ---
            elif action == "subs":
                subs_list = []
                for slot, sub in CAN_SUBSCRIPTIONS.items():
                    subs_list.append({
                        "slot": slot,
                        "i": "0x{:X}".format(sub["req_id"]),
                        "int": sub["interval_ms"]
                    })
                sys.stdout.write('{"id":0,"d":{"subs":' + ujson.dumps(subs_list) + '}}\n')
            
            else:
                sys.stdout.write('{"id":0,"d":{"err":"UNKNOWN_ACTION"}}\n')
        
        elif dev_id > 5:
            # RS485 Forwarding
            if not rs485_ready:
                sys.stdout.write('{"id":0,"d":{"err":"RS485_OFFLINE"}}\n')
                return
            
            # Forward the original command object as NDJSON
            # We use ujson.dumps to ensure it's a valid JSON string
            msg = ujson.dumps(cmd)
            rs485_send(msg)

    except:
        sys.stdout.write('{"id":0,"d":{"err":"JSON_PARSE"}}\n')

# Initial Status Report
can_msg = "CAN_READY" if can_ready else "CAN_INIT_FAIL"
rs485_msg = "READY" if rs485_ready else "FAIL"
print('{"id":0,"d":{"msg":"GATEWAY_READY","ver":"' + FW_VERSION + '","can":"' + can_msg + '","rs485":"' + rs485_msg + '","cores":1}}')

rx_idx = 0
last_rx_time = utime.ticks_ms()
last_gc_time = utime.ticks_ms()
GC_INTERVAL_MS = 2000  # GC at most every 2 seconds (was every idle cycle)

# Helper: Output subscription response frame
def print_sub_response(ts, slot, resp_id, resp_data):
    # Single sys.stdout.write() to minimize USB CDC packet fragmentation
    d_str = ','.join(str(b) for b in resp_data)
    seq_str = ',"seq":' + str(get_next_seq()) if ENABLE_SEQ_COUNTER else ''
    sys.stdout.write('{"id":1,"ts":' + str(ts) + seq_str + ',"d":{"a":"sub","slot":' + str(slot) + ',"i":"0x' + '{:X}'.format(resp_id) + '","d":[' + d_str + ']}}\n')

# AVC-LAN drain callback: called during blocking CAN waits to prevent PIO FIFO overflow.
# The RP2040 PIO FIFO is only 8 entries deep. At AVC-LAN data rates, it fills in ~2ms.
# Without draining, any CAN send_and_wait (100-500ms) causes total AVC-LAN data loss.
def drain_avclan_fifo():
    global rx_idx, last_rx_time
    while sm_rx.rx_fifo() > 0:
        val = sm_rx.get()
        if rx_idx < RX_BUF_SIZE:
            rx_buffer[rx_idx] = val
            rx_idx += 1
        last_rx_time = utime.ticks_ms()

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

    # 3. CAN RX - Direct polling on Core 0 (burst read up to 8 frames)
    # MCP2515 has 2 RX buffers. Burst read catches new frames that arrive
    # while processing. No lock needed — single-core, no thread contention.
    # drain_avclan_fifo() between SPI reads prevents PIO FIFO overflow.
    if can_ready:
        for _ in range(8):
            drain_avclan_fifo()
            res = can.recv_fast()
            if res:
                c_id, c_data, c_ext = res
                print_can_frame(current_time, c_id, tuple(c_data), c_ext)
            else:
                break
        
        # Periodic CAN diagnostics (every 5 seconds)
        if utime.ticks_diff(current_time, can_diag_last) > CAN_DIAG_INTERVAL:
            can_diag_last = current_time
            try:
                drain_avclan_fifo()
                tec, rec, eflg = can.get_errors()
                drain_avclan_fifo()
                rx_stat = can.rx_status()
                drain_avclan_fifo()
                mode = can.get_mode()
                drain_avclan_fifo()
                stats = can.get_rx_stats()
                overflow = stats.get("rx_overflow", 0)
                sys.stdout.write('{\"id\":0,\"d\":{\"can_diag\":{\"mode\":\"' + mode + '\",\"tec\":' + str(tec) + ',\"rec\":' + str(rec) + ',\"eflg\":\"' + '{:02X}'.format(eflg) + '\",\"rxs\":\"' + '{:02X}'.format(rx_stat) + '\",\"ovf\":' + str(overflow) + '}}}\n')
            except:
                pass

    # 4. RS485 RX Poll
    if rs485_ready:
        while rs485.any():
            drain_avclan_fifo()
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

    # 5. CAN Subscription Polling (Periodic OBD-II/Diagnostic Queries)
    # ALL subscriptions use BLOCKING send_and_wait() for reliability.
    # Single-core: no thread contention, just blocks the main loop briefly.
    # Round-robin: scan from can_sub_rr to prevent lower slots from starving
    # higher ones. Each cycle starts where the previous one left off.
    if CAN_TX_ENABLED and CAN_SUBSCRIPTIONS:
        # Find ONE subscription that needs polling (round-robin)
        sub_to_poll = None
        for i in range(MAX_SUBSCRIPTIONS):
            slot = (can_sub_rr + i) % MAX_SUBSCRIPTIONS
            if slot in CAN_SUBSCRIPTIONS:
                sub = CAN_SUBSCRIPTIONS[slot]
                if utime.ticks_diff(current_time, sub["last_poll"]) >= sub["interval_ms"]:
                    sub_to_poll = (slot, sub)
                    can_sub_rr = (slot + 1) % MAX_SUBSCRIPTIONS
                    break
        
        if sub_to_poll:
            slot, sub = sub_to_poll
            try:
                if sub.get("isotp", False):
                    result = can.send_and_wait_isotp(
                        sub["req_id"],
                        sub["req_data"],
                        sub["resp_ids"],
                        sub["timeout_ms"],
                        sub["ext"],
                        ENABLE_ISOTP_DEBUG,
                        poll_cb=drain_avclan_fifo
                    )
                else:
                    result = can.send_and_wait(
                        sub["req_id"],
                        sub["req_data"],
                        sub["resp_ids"],
                        sub["timeout_ms"],
                        sub["ext"],
                        poll_cb=drain_avclan_fifo
                    )
            except Exception as e:
                result = None
                sys.stdout.write('{"id":0,"d":{"err":"SUB_POLL_ERR","slot":' + str(slot) + '}}\n')
            
            CAN_SUBSCRIPTIONS[slot]["last_poll"] = current_time
            if result:
                resp_id, resp_data = result
                print_sub_response(current_time, slot, resp_id, resp_data)

    # 6. AVC-LAN Processing
    # Process as soon as we have data and a brief silence (frame boundary).
    # Low threshold to minimize UI delay for button presses, track changes, etc.
    should_process = (rx_idx > 0 and utime.ticks_diff(current_time, last_rx_time) > 8)

    if should_process:
        total_bits = rx_idx * 32
        ptr = 0
        while ptr < total_bits - 40:
            frame_tuple, bit_len = decode_smart_static(rx_buffer, ptr, rx_idx)
            if frame_tuple:
                print_avclan_frame(current_time, *frame_tuple)
                ptr += bit_len
            else:
                ptr += 1
        rx_idx = 0

    # Run GC only periodically during idle (was every idle cycle, now every 2s)
    if rx_idx == 0:
        if utime.ticks_diff(current_time, last_gc_time) > GC_INTERVAL_MS:
            gc.collect()
            last_gc_time = current_time
