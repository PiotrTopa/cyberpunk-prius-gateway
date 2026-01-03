import time
from machine import Pin, SPI
import mcp2515
import sys

# --- HARDWARE CONFIGURATION (Match main.py) ---
# CAN CONFIG
CAN_BAUDRATE = 500000
PIN_SCK = 2
PIN_MOSI = 3
PIN_MISO = 4
PIN_CS = 5
PIN_INT = 6
SPI_BAUDRATE = 1000000 # 1MHz

def run_diagnosis():
    print("--- NOISE SOURCE DIAGNOSIS ---")
    
    # 1. Setup SPI
    spi = SPI(0, baudrate=SPI_BAUDRATE, sck=Pin(PIN_SCK), mosi=Pin(PIN_MOSI), miso=Pin(PIN_MISO))
    can = mcp2515.MCP2515(spi, PIN_CS)
    
    # 2. Reset and Check SPI Connection
    try:
        can.reset()
        # Test Register Write/Read
        can.write_reg(0x2A, 0x55) # CNF1
        val = can.read_reg(0x2A)
        if val == 0x55:
            print("[PASS] SPI Connection verified (Read 0x55).")
        else:
            print(f"[FAIL] SPI Connection failed. Wrote 0x55, Read 0x{val:02X}")
            print("-> CONCLUSION: SPI Noise/Wiring Issue.")
            return
    except Exception as e:
        print(f"[FAIL] SPI Exception: {e}")
        return

    # 3. Initialize (Config Mode)
    # We won't fully init to Normal yet, we want to check Errors first
    
    # 4. Check Error Counters (Should be 0 after reset)
    tec, rec, eflg = can.get_errors()
    print(f"[INFO] Initial Errors (After Reset): TEC={tec}, REC={rec}, EFLG=0x{eflg:02X}")
    
    # 5. Enter Normal Mode (Listen to Floating Bus)
    # We need to set bitrate first
    can.set_bitrate(CAN_BAUDRATE)
    can.set_normal_mode()
    print("[INFO] Entered Normal Mode (Floating Bus). Listening for 2 seconds...")
    
    time.sleep(2)
    
    tec, rec, eflg = can.get_errors()
    print(f"[INFO] Errors after 2s Normal Mode: TEC={tec}, REC={rec}, EFLG=0x{eflg:02X}")
    
    if rec > 0 or eflg > 0:
        print("-> OBSERVATION: Receive Errors detected. The floating bus is generating noise interpreted as CAN frames/errors.")
    else:
        print("-> OBSERVATION: No CAN errors detected on floating bus (unusual if bus is truly floating).")

    # 6. LOOPBACK TEST (The definitive test)
    print("\n--- STARTING LOOPBACK TEST ---")
    print("Switching to Loopback Mode (Internal feedback, ignores external CAN bus)...")
    can.set_loopback_mode()
    
    # Send a frame
    test_id = 0x123
    test_data = [0x11, 0x22, 0x33, 0x44]
    print(f"Sending Frame: ID=0x{test_id:X}, Data={test_data}")
    
    can.send(test_id, test_data)
    
    # Wait for RX
    time.sleep(0.5)
    
    # Check RX
    res = can.recv()
    if res:
        rx_id, rx_data, rx_ext = res
        print(f"Received Frame: ID=0x{rx_id:X}, Data={rx_data}")
        
        if rx_id == test_id and rx_data == test_data:
            print("\n[PASS] Loopback Test PASSED.")
            print("-> CONCLUSION: SPI Communication is CLEAN.")
            print("-> ROOT CAUSE: The noise you see in Normal Mode is definitively from the floating CAN bus.")
        else:
            print("\n[FAIL] Loopback Test DATA MISMATCH.")
            print(f"Expected: {test_data}, Got: {rx_data}")
            print("-> CONCLUSION: SPI Communication is CORRUPTED (SPI Noise).")
    else:
        print("\n[FAIL] Loopback Test NO RX.")
        print("-> CONCLUSION: Transmission failed or status read failed (SPI Issue).")

if __name__ == "__main__":
    run_diagnosis()
