# satellites/common — shared satellite modules

Single source of truth for code shared by every RS485 satellite. The
per-satellite directories (`light/`, `clock/`, `vfd/`) hold **symlinks** to
these files, so a normal `mpremote fs cp` or `satellite_ota.py sync` from a
satellite directory picks them up automatically.

| File | Purpose |
|:-----|:--------|
| `rs485.py` | Half-duplex NDJSON RS485 driver |
| `ota.py` | Code updates over RS485 (`FW_*` commands) |

Bus-level facts (device map, wiring, frame limits, maintenance procedure) live
in [`../README.md`](../README.md).

---

## `rs485.py` — bus driver

```python
from rs485 import RS485
rs485 = RS485(uart_id, baudrate, tx_pin, rx_pin, de_pin, dev_id)

rs485.send({"cmd": "STATUS", "ver": VERSION})   # -> {"id":<dev_id>,"d":{...}}\n
for payload in rs485.read():                    # only frames addressed to us
    ...
```

- **`send(payload)`** wraps `payload` as `{"id":dev_id,"d":payload}`, appends
  `\n`, asserts DE, writes every byte, waits for the shift register to drain
  (`uart.flush()`), then releases DE. Non-dict payloads are ignored.
- **`read()`** drains the UART, splits on `\n`, and returns a list of the `d`
  payloads whose `id` matches this device. Frames for other devices and
  malformed JSON are dropped silently.

Both directions use 2048-byte UART buffers, and `send()` keeps writing until the
whole frame is queued. Inbound reassembly is capped at 2048 bytes: a frame
larger than that is discarded without any error, so respect the size guidance in
[`../README.md`](../README.md#frame-size).

DE is held for the entire transmission including the `\n`; dropping it early
truncates the terminator and the receiver discards the frame.

---

## `ota.py` — code updates over RS485

Python-file updates without physically removing a satellite. Companion host
tool: `tools/satellite_ota.py` (usage in [`../README.md`](../README.md#updating-satellite-code-ota-over-rs485)).

### Design

- **Stop-and-wait ARQ** — one chunk in flight, each ACKed with its sequence
  number; duplicates are re-ACKed idempotently, mismatches return the expected
  index so the host resyncs. Suits the half-duplex bus.
- **Integrity** — per-file sha256, streamed on the satellite during reception
  and verified on `FW_END` (size + hash) before a file is accepted as staged.
- **Atomic update** — data is written to `<file>.new`; only `FW_COMMIT` renames
  staged files onto the live names (littlefs rename is atomic per file). Power
  loss mid-transfer leaves boot code untouched and only inert `.new` files
  behind.
- **Sessions** — a transfer idle for `SESSION_TIMEOUT_MS` (30 s) is dropped and
  its partial stage deleted. While a transfer is active, `ota.active` is `True`
  so the main loop can skip heavy work (the VFD pauses rendering).
- **Diff-based sync** — `FW_INFO` returns a `{file: sha256}` manifest of all
  `.py` files, so the host sends only what changed.

`handle()` claims any payload whose `cmd` starts with `FW_` and returns `True`;
everything else returns `False` and falls through to the satellite's own
dispatch.

### Message flow

```
FW_INFO                                -> {"res":"OK","cmd":"FW_INFO","proto":1,"files":{...}}
FW_BEGIN {file, size, sha256}          -> OK                      (opens <file>.new)
FW_DATA  {n, b:<base64>}  × N          -> OK {n} | {"err":"SEQ","want":k}
FW_END                                 -> OK | {"err":"HASH"}     (size + sha verified)
  ... repeat BEGIN/DATA/END per file ...
FW_COMMIT                              -> OK {files}              (atomic renames)
FW_REBOOT                              -> OK, then machine.reset()
FW_ABORT                               -> OK                      (drop session + staged)
```

Errors come back as `{"err":...,"cmd":...}`; an unexpected exception replies
`{"err":"FW_FAIL","cmd":...,"msg":...}` and drops the session.

The `FW_INFO` reply carries one 64-char sha per `.py` file and runs ~570 B for
six files. It also costs a few seconds to produce (sha256 over every file on an
RP2040), so allow a generous reply timeout.

### Satellite integration

Already wired into every satellite; the pattern for a new one:

```python
from ota import OTA
ota = OTA(rs485)

while True:
    for m in rs485.read():
        if ota.handle(m):
            continue
        ...normal dispatch...

    if not ota.active:
        ...heavy work (rendering, etc.)...

    ota.tick(now)   # once per loop: drops a stalled session
```
