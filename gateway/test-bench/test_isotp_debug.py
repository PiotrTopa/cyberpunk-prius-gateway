#!/usr/bin/env python3
"""
ISO-TP Debug Test for Gateway.
Enables debug logging and tests multi-frame response.
"""

import serial
import json
import time
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM9"
BAUD = 1000000


def drain_and_print(ser, timeout=0.5, prefix=""):
    """Read and print all available data with timeout."""
    messages = []
    end_time = time.time() + timeout
    while time.time() < end_time:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                messages.append(line)
                # Highlight ISO-TP debug messages
                if '"isotp"' in line:
                    print(f"  🔍 DEBUG: {line}")
                elif '"err"' in line or "TIMEOUT" in line:
                    print(f"  ❌ {line}")
                elif '"a":"resp"' in line:
                    print(f"  ✅ RESP: {line}")
                elif prefix:
                    print(f"  {prefix}: {line}")
        else:
            time.sleep(0.01)
    return messages


def main():
    print(f"Opening {PORT} at {BAUD} baud...")
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(0.5)
    
    # Drain startup messages
    print("\n--- Startup Messages ---")
    drain_and_print(ser, 0.5, "INIT")
    
    # Step 1: Enable ISO-TP debug logging
    print("\n" + "="*60)
    print("Step 1: Enable ISO-TP Debug Logging")
    print("="*60)
    cmd = {"id": 0, "d": {"isotp_debug": True}}
    ser.write((json.dumps(cmd) + "\n").encode())
    time.sleep(0.3)
    drain_and_print(ser, 0.3, "CFG")
    
    # Step 2: Switch to Normal mode
    print("\n" + "="*60)
    print("Step 2: Switch to Normal Mode")
    print("="*60)
    cmd = {"id": 1, "d": {"a": "mode", "m": "normal"}}
    ser.write((json.dumps(cmd) + "\n").encode())
    time.sleep(0.5)
    drain_and_print(ser, 0.3, "MODE")
    
    # Step 3: Test single-frame first (sanity check)
    print("\n" + "="*60)
    print("Step 3: Sanity Check - RPM (single-frame)")
    print("="*60)
    cmd = {
        "id": 1,
        "d": {
            "a": "req",
            "i": "0x7DF",
            "d": [2, 1, 0x0C, 0, 0, 0, 0, 0],
            "r": ["0x7E8"],
            "t": 500
        }
    }
    print(f"TX: {json.dumps(cmd)}")
    ser.write((json.dumps(cmd) + "\n").encode())
    drain_and_print(ser, 1.0)
    
    time.sleep(0.3)
    
    # Step 4: Test ISO-TP multi-frame (PID 21C3)
    print("\n" + "="*60)
    print("Step 4: ISO-TP Multi-Frame Test - PID 21C3 (Inverter Temps)")
    print("="*60)
    print("Expected ECU behavior:")
    print("  1. Gateway TX: 0x7E2 -> [03 21 C3 00 00 00 00 00]")
    print("  2. ECU TX FF:  0x7EA -> [10 1F 61 C3 ...] (First Frame, 31 bytes)")
    print("  3. Gateway TX FC: 0x7E2 -> [30 00 00 00 00 00 00 00]")
    print("  4. ECU TX CF1: 0x7EA -> [21 ...] (Consecutive Frame 1)")
    print("  5. ECU TX CF2: 0x7EA -> [22 ...] (Consecutive Frame 2)")
    print("  etc...")
    print()
    
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
    print(f"TX: {json.dumps(cmd)}")
    ser.write((json.dumps(cmd) + "\n").encode())
    
    # Wait longer for debug output
    drain_and_print(ser, 4.0)
    
    # Step 5: Try alternative PID format (without padding)
    print("\n" + "="*60)
    print("Step 5: Try without padding bytes")
    print("="*60)
    cmd = {
        "id": 1,
        "d": {
            "a": "req",
            "i": "0x7E2",
            "d": [3, 0x21, 0xC3],
            "r": ["0x7EA"],
            "t": 3000,
            "isotp": True
        }
    }
    print(f"TX: {json.dumps(cmd)}")
    ser.write((json.dumps(cmd) + "\n").encode())
    drain_and_print(ser, 4.0)
    
    # Step 6: Check if PID 21C3 actually returns multi-frame
    print("\n" + "="*60)
    print("Step 6: Test PID 21C3 WITHOUT ISO-TP flag")
    print("="*60)
    print("This will show raw response - if ECU sends SF, we'll see it")
    cmd = {
        "id": 1,
        "d": {
            "a": "req",
            "i": "0x7E2",
            "d": [3, 0x21, 0xC3, 0, 0, 0, 0, 0],
            "r": ["0x7EA"],
            "t": 500,
            "isotp": False
        }
    }
    print(f"TX: {json.dumps(cmd)}")
    ser.write((json.dumps(cmd) + "\n").encode())
    drain_and_print(ser, 1.5)
    
    print("\n" + "="*60)
    print("Analysis")
    print("="*60)
    print("""
If you see:
  - 'TX REQ to 0x7E2' but no 'RX FF' → ECU not responding with First Frame
  - 'RX SF' → ECU sent Single Frame (response is ≤7 bytes, no ISO-TP needed)
  - 'RX FF' + 'TX FC' but no 'RX CF' → FC sent to wrong ID or timing issue
  - 'RX FF' + 'TX FC' + 'RX CF' → ISO-TP working, check reassembly

Common issues:
  1. PID 21C3 might return Single Frame on some Prius models
  2. HV ECU might need car in READY mode (not just IG-ON)
  3. Timing too fast - try longer timeout
""")
    
    # Disable debug logging
    cmd = {"id": 0, "d": {"isotp_debug": False}}
    ser.write((json.dumps(cmd) + "\n").encode())
    time.sleep(0.2)
    
    ser.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
