#!/usr/bin/env python3
"""
Focused ISO-TP reliability test - runs PID 21C3 multiple times.
"""

import serial
import json
import time
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM9"
BAUD = 1000000


def drain(ser, timeout=0.5, show=False):
    """Read all available data."""
    messages = []
    end_time = time.time() + timeout
    while time.time() < end_time:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                messages.append(line)
                if show and ('"isotp"' in line or '"err"' in line or '"a":"resp"' in line):
                    print(f"  {line[:120]}")
        else:
            time.sleep(0.01)
    return messages


def send_isotp_request(ser, timeout=5.0):
    """Send PID 21C3 request and wait for response."""
    cmd = {
        "id": 1,
        "d": {
            "a": "req",
            "i": "0x7E2",
            "d": [3, 0x21, 0xC3, 0, 0, 0, 0, 0],
            "r": ["0x7EA"],
            "t": 3000,
            "isotp": True
        }
    }
    
    ser.write((json.dumps(cmd) + "\n").encode())
    
    end_time = time.time() + timeout
    while time.time() < end_time:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            
            # Show debug messages
            if '"isotp"' in line:
                print(f"  🔍 {line}")
            
            try:
                data = json.loads(line)
                if data.get("id") == 1:
                    payload = data.get("d", {})
                    if payload.get("a") == "resp":
                        if "err" in payload:
                            return None, payload.get("err")
                        else:
                            return payload.get("d", []), None
            except json.JSONDecodeError:
                pass
        else:
            time.sleep(0.01)
    
    return None, "SCRIPT_TIMEOUT"


def main():
    print(f"Opening {PORT} at {BAUD} baud...")
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(0.5)
    
    # Drain startup
    drain(ser, 0.5)
    
    # Enable debug
    ser.write(b'{"id":0,"d":{"isotp_debug":true}}\n')
    time.sleep(0.3)
    drain(ser, 0.3)
    
    # Switch to normal mode
    ser.write(b'{"id":1,"d":{"a":"mode","m":"normal"}}\n')
    time.sleep(0.5)
    drain(ser, 0.3)
    
    print("\n" + "="*60)
    print("ISO-TP Reliability Test - PID 21C3 (44 bytes)")
    print("="*60)
    
    success = 0
    fail = 0
    
    for i in range(5):
        print(f"\n--- Attempt {i+1}/5 ---")
        
        # Clear any pending data
        drain(ser, 0.2)
        
        # Wait a bit between attempts
        time.sleep(0.5)
        
        data, err = send_isotp_request(ser, timeout=5.0)
        
        if data:
            success += 1
            print(f"  ✅ SUCCESS! Got {len(data)} bytes")
            print(f"     Data: {[hex(b) for b in data[:20]]}...")
            if len(data) >= 26:
                inv1 = data[24] - 40 if data[24] != 0xFF else None
                inv2 = data[25] - 40 if data[25] != 0xFF else None
                print(f"     Inverter temps: MG1={inv1}°C, MG2={inv2}°C")
        else:
            fail += 1
            print(f"  ❌ FAILED: {err}")
    
    print("\n" + "="*60)
    print(f"Results: {success}/5 success, {fail}/5 failed")
    print("="*60)
    
    # Disable debug
    ser.write(b'{"id":0,"d":{"isotp_debug":false}}\n')
    time.sleep(0.2)
    
    ser.close()


if __name__ == "__main__":
    main()
