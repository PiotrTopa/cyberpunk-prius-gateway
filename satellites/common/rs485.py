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
        self._has_flush = hasattr(self.uart, "flush")

    def send(self, payload):
        """Sends a JSON-encoded payload over RS485."""
        if not isinstance(payload, dict):
            return

        cmd = {"id": self.dev_id, "d": payload}
        data = ujson.dumps(cmd).encode("utf-8") + b"\n"

        self.de_pin.value(1)  # Enable transmission (driver on)
        time.sleep_ms(2)      # Let DE settle before clocking data out

        self.uart.write(data)

        # Keep DE asserted until the LAST bit (incl. the "\n" terminator) is
        # physically on the wire, or a receiver may miss the frame delimiter.
        # flush() blocks until the TX shift register is empty (exact); fall
        # back to a byte-time estimate on ports without it.
        if self._has_flush:
            self.uart.flush()
        else:
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
