"""
Light Satellite - Hardware Test Script
Run this file directly on the RP2040 to verify relay wiring.
Cycles relays 1-4 ON/OFF with visible delays.
"""

import machine
import time

# Relay pins (Active Low: 0=ON, 1=OFF)
RELAY_PINS = [2, 3, 4, 5]

def main():
    print("=== Light Satellite - Relay Test ===")
    
    # Initialize all relays OFF (HIGH)
    relays = []
    for pin_num in RELAY_PINS:
        p = machine.Pin(pin_num, machine.Pin.OUT, value=1)
        relays.append(p)
    print("All relays OFF")
    time.sleep(1)

    # Cycle each relay individually
    for i, r in enumerate(relays):
        ch = i + 1
        print(f"Relay {ch} (GP{RELAY_PINS[i]}) -> ON")
        r.value(0)  # Active Low
        time.sleep(0.8)
        print(f"Relay {ch} (GP{RELAY_PINS[i]}) -> OFF")
        r.value(1)
        time.sleep(0.4)

    print("--- Individual test done ---")
    time.sleep(1)

    # All ON at once
    print("All relays ON")
    for r in relays:
        r.value(0)
    time.sleep(1.5)

    # All OFF
    print("All relays OFF")
    for r in relays:
        r.value(1)

    print("=== Test complete ===")

main()
