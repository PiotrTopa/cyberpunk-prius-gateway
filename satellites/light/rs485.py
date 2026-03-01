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
        )
        self.de = machine.Pin(de_pin, machine.Pin.OUT)
        self.de.value(0)  # Start in RX mode (listen)
        self.dev_id = dev_id
        self.buffer = b""

    def send(self, payload):
        """
        Send a JSON packet on the bus.
        Wraps payload in {"id": <dev_id>, "d": <payload>}
        """
        msg_dict = {"id": self.dev_id, "d": payload}
        msg_str = ujson.dumps(msg_dict) + "\n"

        # Switch to TX mode
        self.de.value(1)
        self.uart.write(msg_str)

        # Wait for hardware TX buffer to flush
        # 10 bits per byte at 8N1, plus margin
        wait_ms = int(len(msg_str) * 10000 / self.baudrate) + 2
        time.sleep_ms(wait_ms)

        # Switch back to RX mode
        self.de.value(0)

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
            except Exception:
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
