# RS485 Satellites

Distributed MicroPython modules on a shared half-duplex RS485 bus. The gateway
bridges the host's USB-CDC link to this bus, so the host talks to every
satellite through one serial port.

```
host (prius backend)
  │  USB-CDC, NDJSON
  ▼
gateway (RP2040)  ── UART1 @115200, MAX485, DE=GP7 ──┐
                                                     │  RS485 A/B (multidrop)
                        ┌────────────────────────────┼────────────────┐
                        ▼                            ▼                ▼
                  vfd (110)                    light/DRL (106)   clock (6)
```

| Property | Value |
|:---------|:------|
| Bus | RS485 half-duplex, multidrop, single twisted pair (A/B) |
| Line rate | **115200** 8N1 |
| Framing | NDJSON — one JSON object per line, `\n` terminated |
| Envelope | `{"id":<dev>,"d":{...}}` |
| Max frame | **< 2 KB**; keep under ~1.5 KB (see *Frame size* below) |

---

## Device map

Authoritative source: `cyberpank-prius-gen2-computer/cyberpunk_computer/io/ports.py`.

| ID | Name | Direction | Source |
|:---|:-----|:----------|:-------|
| `0` | Gateway system/status | both | gateway firmware |
| `1` | Vehicle CAN | both | gateway firmware |
| `2` | AVC-LAN | both | gateway firmware |
| `6` | Clock satellite | output | `satellites/clock/` |
| `106` | DRL controller | output | `satellites/light/` |
| `107` | Rain/light sensor | input | — |
| `110` | VFD display | output | `satellites/vfd/` |
| `200`–`202` | Powerbox | both | separate USB device, not on RS485 |

New satellites take an ID **≥ 100** (`DEVICE_SATELLITE_BASE`). The gateway
forwards any `id > 5` to the RS485 bus verbatim; `6` predates that convention.

---

## Addressing and framing

The gateway is a transparent tunnel. It wraps nothing and inspects nothing
beyond the `id`:

- **Host → satellite:** the host writes `{"id":110,"d":{...}}` to the gateway's
  USB port; the gateway re-serialises it onto RS485 unchanged.
- **Satellite → host:** anything a satellite writes to the bus is forwarded to
  USB with `ts` (gateway uptime, ms) and `seq` (continuity counter) added.

Every satellite reads the whole bus and acts only on frames matching its own
`DEV_ID`; `RS485.read()` returns just the `d` payloads addressed to it. There is
no host-side arbitration — satellites transmit unsolicited (status broadcasts)
and the bus tolerates it because traffic is light and frames are short.

### Frame size

Both ends allocate 2048-byte UART RX and TX buffers, and reassembly buffers cap
at 2048 (satellite) / 4096 (gateway). Keep any single frame **under ~1.5 KB** for
margin. A frame that exceeds a receiver's reassembly cap is discarded silently —
there is no error reply and no UART error flag, so oversized frames look exactly
like a dead link. Split large payloads into chunks; OTA does this at 512 raw
bytes per frame (~730 B on the wire).

---

## Wiring

All satellites use a MAX485 with DE and RE tied together (HIGH = transmit).

| Node | UART | TX | RX | DE/RE |
|:-----|:-----|:---|:---|:------|
| gateway | UART1 | GP8 | GP9 | **GP7** |
| vfd (110) | UART1 | GP8 | GP9 | GP10 |
| light (106) | UART1 | GP8 | GP9 | GP10 |
| clock (6) | UART0 | GP12 | GP13 | GP14 |

Satellites are powered from the **OUT2 rail** on the powerbox, gated by the
backend's `satellite_power` rule (held on while ACC is on).

---

## Maintenance window

The backend holds the gateway's serial port open, so **any direct tool use
requires stopping it first**. Stopping the backend also stops the POCO
heartbeat the powerbox watches — after ~20 s without it the powerbox presses the
host's power button. Always run the heartbeat keeper for the whole window.

```bash
GW=/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_50443405b862d21c-if00
PB=/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_503359277a7c699f-if00

sudo systemctl stop prius-backend
python3 tools/powerbox_maint.py --port "$PB" --out2 keep --quiet &   # REQUIRED
MAINT=$!

# ... work on the bus ...

kill $MAINT
sudo systemctl start prius-backend
```

Wrap this in a script with `trap ... EXIT` so the backend is restarted even if
the work fails. `--out2 keep` leaves the satellite rail as-is; use `--out2 on`
to force it on.

Always address boards by their `/dev/serial/by-id/...-if00` path — `ttyACM*`
numbering flips on re-enumeration.

---

## Updating satellite code (OTA over RS485)

`tools/satellite_ota.py` updates a satellite's Python files over the bus, with
no physical access. Protocol details are in [`common/README.md`](common/README.md).

```bash
# inside a maintenance window, with $GW set as above
tools/satellite_ota.py --port "$GW" --dev 110 info                    # remote manifest
tools/satellite_ota.py --port "$GW" --dev 110 sync satellites/vfd/    # usual case
tools/satellite_ota.py --port "$GW" --dev 110 push satellites/vfd/main.py
tools/satellite_ota.py --port "$GW" --dev 110 abort                   # clear a session
tools/satellite_ota.py --port "$GW" --dev 110 reboot
```

- **`sync <dir>`** is the normal path: it diffs local `.py` against the remote
  manifest, sends only what changed, commits, reboots, then re-reads the
  manifest and prints `post-reboot verify: OK`. Symlinked shared files
  (`rs485.py`, `ota.py`) are followed, so syncing a satellite directory updates
  them too.
- **`push <files>`** sends the named files unconditionally, then commits and
  reboots. Add `--no-reboot` to stage several pushes.
- Throughput is ~**700–750 B/s** (stop-and-wait ARQ, one 512-byte chunk in
  flight). A 3.7 KB file takes ~5 s.

**Send `abort` before retrying a failed transfer.** `push`/`sync` do not clear a
previous session, and a stale one makes the next attempt fail at `FW_DATA`.

Recovery if an update leaves a satellite unbootable: nothing is overwritten
until `FW_COMMIT`, so a failure mid-transfer leaves the running code intact.
If a committed file is bad, reflash over USB (see the satellite's README).

---

## Adding a satellite

1. Pick an unused ID ≥ 100 and add it to `io/ports.py` in the backend.
2. Create `satellites/<name>/` with a `main.py` that sets `DEV_ID`, and
   **symlink** the shared modules so they stay single-source:
   ```bash
   ln -s ../common/rs485.py satellites/<name>/rs485.py
   ln -s ../common/ota.py   satellites/<name>/ota.py
   ```
3. Wire the main loop per [`common/README.md`](common/README.md) (`ota.handle(m)`
   first, then your dispatch; call `ota.tick(now)` once per loop).
4. Flash MicroPython, upload the directory over USB once; thereafter use OTA.

---

## Troubleshooting

| Symptom | Check |
|:--------|:------|
| Satellite `online: false` in the backend | Is OUT2 on? `powerbox.relays` / `out2` in `/api/v1/state`. Is the gateway connected (`connection.gateway_version`)? |
| No traffic at all from any satellite | Check the gateway is powered and running: it emits `GW_HB` on id `0` once a second whenever it has 5 V. No heartbeat means no power (relay ch4) or a wedged USB link — see the backend's gateway recovery. |
| Short frames work, long ones vanish | Frame exceeds a reassembly cap — see *Frame size*. Split the payload. |
| `no reply to FW_DATA` | Stale OTA session: run `abort`, then retry. |
| Garbled/partial frames | Two nodes transmitting at once. Satellites broadcast unsolicited, so avoid long host bursts while a satellite is mid-broadcast. |

Useful checks from the host (backend running):

```bash
# satellite liveness — last_seen should advance every ~5 s for the VFD
python3 -c "import urllib.request,json,time
s=json.load(urllib.request.urlopen('http://localhost:8080/api/v1/state'))['state']
for i,n in sorted(s['satellites']['nodes'].items()):
    print(i, n['online'], round(time.time()-n['last_seen'],1) if n['last_seen'] else 'never', n['fw_version'])"
```
