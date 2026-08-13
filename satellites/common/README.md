# satellites/common — shared satellite modules

Single source of truth for code shared by all RS485 satellites. The
per-satellite directories (`light/`, `clock/`, `vfd/`) contain **symlinks**
to these files, so a normal `scp`/`mpremote fs cp` deploy from a satellite
directory picks them up automatically.

| File | Purpose |
|------|---------|
| `rs485.py` | Half-duplex NDJSON RS485 driver (`{"id":N,"d":{...}}` framing, `rxbuf=2048`) |
| `ota.py`   | OTA code updates over RS485 (`FW_*` commands) |

## OTA code updates (`ota.py`)

Reliable Python-file updates over the bus — no need to physically remove a
satellite for small fixes. Companion host tool: `tools/satellite_ota.py`.

### Design

- **Stop-and-wait ARQ** — one chunk in flight, each ACKed with its sequence
  number; duplicates are re-ACKed idempotently, mismatches return the
  expected index so the host resyncs. Suits the half-duplex bus.
- **Integrity** — per-file sha256, streamed on the satellite during
  reception and verified on `FW_END` (size + hash) before a file is
  accepted as staged.
- **Atomic update** — data is written to `<file>.new`; only `FW_COMMIT`
  renames staged files onto the live names (littlefs rename is atomic).
  Power loss mid-transfer leaves boot code untouched.
- **Sessions** — a transfer stalls for 30 s → partial stage is deleted.
  While a transfer is active, satellites skip heavy work (`ota.active`).
- **Diff-based sync** — `FW_INFO` reports a `{file: sha256}` manifest of
  all `.py` files so the host only sends what changed.

### Message flow

```
FW_INFO                                   -> {"res":"OK","files":{...},"proto":1}
FW_BEGIN {file, size, sha256}             -> OK            (opens file.new)
FW_DATA  {n, b:<base64>}   x N chunks     -> OK {n} / {"err":"SEQ","want":k}
FW_END                                    -> OK {sha256} / {"err":"HASH"}
  ... repeat BEGIN/DATA/END per file ...
FW_COMMIT                                 -> OK {files}    (atomic renames)
FW_REBOOT                                 -> OK, then machine.reset()
FW_ABORT                                  -> OK            (drop session + staged)
```

### Satellite integration (one-time, already done in all satellites)

```python
from ota import OTA
ota = OTA(rs485)

for m in rs485.read():
    if ota.handle(m):
        continue
    # ...normal dispatch...
ota.tick(now)  # somewhere in the main loop (session timeout)
```

### Host usage (maintenance mode: backend stopped, satellite rail on)

```bash
tools/satellite_ota.py --port /dev/ttyACM0 --dev 110 info
tools/satellite_ota.py --port /dev/ttyACM0 --dev 110 sync satellites/vfd/
tools/satellite_ota.py --port /dev/ttyACM0 --dev 102 push satellites/light/main.py
tools/satellite_ota.py --port /dev/ttyACM0 --dev 110 abort   # recover
```

`sync` diffs against the remote manifest, transfers only changed `.py`
files, commits, reboots and re-verifies the manifest afterwards.
