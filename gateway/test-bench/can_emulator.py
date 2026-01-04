import time
from machine import SPI, Pin
import ujson
import mcp2515

# --- CONFIG ---
CAN_BAUDRATE = 500000
# Test Bench Pinout (can be same as Gateway for simplicity)
PIN_SCK = 2
PIN_MOSI = 3
PIN_MISO = 4
PIN_CS = 5
PIN_INT = 6

# --- SETUP ---
spi = SPI(0, baudrate=1000000, sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))
can = mcp2515.MCP2515(spi, PIN_CS)

print("Initializing CAN Emulator...")
if can.init(CAN_BAUDRATE):
    print("CAN Initialized OK")
else:
    print("CAN Init Failed!")
    # Loop forever or exit
    while True: time.sleep(1)

def play_dump(filename):
    print(f"Playing dump: {filename}")
    try:
        with open(filename, 'r') as f:
            last_ts = 0
            for line in f:
                if not line.strip(): continue
                try:
                    frame = ujson.loads(line)
                    ts = frame.get('ts', 0)
                    can_id = frame.get('id')
                    data = frame.get('data', [])
                    desc = frame.get('desc', '')
                    
                    # Time sync
                    diff = ts - last_ts
                    if diff > 0:
                        time.sleep_ms(diff)
                    last_ts = ts
                    
                    # Send
                    print(f"TX: ID=0x{can_id:X} Data={data} ({desc})")
                    can.send(can_id, data)
                    
                except Exception as e:
                    print(f"Error parsing line: {e}")
    except OSError:
        print("File not found.")

while True:
    play_dump("prius_can_dump.jsonl")
    print("Restarting dump...")
    time.sleep(1)
