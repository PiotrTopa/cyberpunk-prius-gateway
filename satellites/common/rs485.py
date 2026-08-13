import machine
import ujson
import time


class RS485:
    """
    RS485 half-duplex communication driver for satellite modules.
    Uses NDJSON framing with device addressing.
    """

    def __init__(self, uart_id, baudrate, tx_pin, rx_pin, de_pin, dev_id):
        self.baudrate = baudrate
        self.uart = machine.UART(
            uart_id,
            baudrate=baudrate,
            tx=machine.Pin(tx_pin),
            rx=machine.Pin(rx_pin),
            rxbuf=2048,  # big enough for one OTA chunk frame during a busy loop
        )
        self.de_pin = machine.Pin(de_pin, machine.Pin.OUT)
        self.de_pin.value(0)  # Start in RX mode (listen)
        self.dev_id = dev_id
        self.buffer = b""

    def send(self, payload):
        """Sends a JSON-encoded payload over RS485."""
        if not isinstance(payload, dict):
            return

        cmd = {"id": self.dev_id, "d": payload}
        data = ujson.dumps(cmd).encode("utf-8")

        self.de_pin.value(1)  # Enable transmission
        time.sleep_ms(2)  # Wait 2ms for DE line to stabilize properly
        
        self.uart.write(data)
        self.uart.write(b"\n")
        
        # Wait for hardware TX buffer to flush
        # 10 bits per byte at 8N1, plus margin
        wait_ms = int(len(data) * 10000 / self.baudrate) + 2
        time.sleep_ms(wait_ms)
        
        self.de_pin.value(0)  # Return to receive mode

    def read(self):
        """
        Process incoming UART data.
        Returns a list of payloads addressed to this device.
        """
        msgs = []
        if self.uart.any():
            try:
                chunk = self.uart.read()
                if chunk:
                    self.buffer += chunk
            except Exception as e:
                print("RX ERR:", e)
                pass

        # Prevent buffer overflow from garbage data
        if len(self.buffer) > 2048:
            # Keep only the tail
            self.buffer = self.buffer[-512:]

        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue

            try:
                line_str = line.decode("utf-8")
                obj = ujson.loads(line_str)

                if "id" in obj and obj["id"] == self.dev_id:
                    if "d" in obj:
                        msgs.append(obj["d"])
            except ValueError:
                pass
            except Exception:
                pass

        return msgs
