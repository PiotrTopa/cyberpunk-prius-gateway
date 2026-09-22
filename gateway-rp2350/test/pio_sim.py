#!/usr/bin/env python3
"""
Cycle-level simulation of the two AVC-LAN PIO programs, run against the
assembled instructions in build-*/avclan.pio.h.

  * TX: drives the state machine with a frame and measures every pulse on the
    side-set pin. Expected: start 166/19 us, '1' 20/19 us, '0' 32/7 us.
  * RX: synthesises the bus waveform of a frame (dominant = high), feeds it to
    the receiver and checks the pushed dominant-width words classify to the
    right symbols and that the last word is pushed within a few us of the last
    bit's dominant edge (that is the "immediate" property).

Only the instruction subset used by avclan.pio is implemented.
"""
import glob
import re
import sys

# ---------------------------------------------------------------- decoding
def load_program(header, name):
    src = open(header).read()
    m = re.search(rf"{name}_program_instructions\[\] = \{{(.*?)\}};", src, re.S)
    words = [int(x, 16) for x in re.findall(r"0x([0-9a-fA-F]{4})", m.group(1))]
    wrap_target = int(re.search(rf"#define {name}_wrap_target (\d+)", src).group(1))
    wrap = int(re.search(rf"#define {name}_wrap (\d+)", src).group(1))
    ss = re.search(rf"#define {name}_pio_version|// {name}", src)  # not needed
    return words, wrap_target, wrap


class SM:
    def __init__(self, prog, wrap_target, wrap, sideset_bits, pin_in=None, autopull=False,
                 shift_left_in=True, shift_left_out=True):
        self.prog, self.wt, self.wrap = prog, wrap_target, wrap
        self.ss_bits = sideset_bits
        self.delay_bits = 5 - sideset_bits
        self.pc = 0
        self.x = self.y = 0
        self.isr = self.osr = 0
        self.isr_cnt = 0
        self.osr_cnt = 32          # 32 = empty
        self.tx_fifo, self.rx_fifo = [], []
        self.pin_in = pin_in or (lambda t: 0)
        self.side_pin = 0
        self.autopull = autopull
        self.t = 0                 # cycles
        self.stall = 0
        self.push_log = []         # (cycle, word)
        self.side_log = []         # (cycle, level)

    # helpers
    def _try_autopull(self):
        if self.autopull and self.osr_cnt >= 32 and self.tx_fifo:
            self.osr = self.tx_fifo.pop(0)
            self.osr_cnt = 0
            return True
        return False

    def step(self):
        """Execute one instruction (or stall one cycle). Advances self.t."""
        ins = self.prog[self.pc]
        op = ins >> 13
        ds = (ins >> 8) & 0x1F
        if self.ss_bits:
            side = ds >> self.delay_bits
            delay = ds & ((1 << self.delay_bits) - 1)
            if side != self.side_pin:
                self.side_pin = side
                self.side_log.append((self.t, side))
        else:
            delay = ds
        stalled = False
        next_pc = self.pc + 1

        if op == 0:  # JMP
            cond = (ins >> 5) & 7
            addr = ins & 0x1F
            take = False
            if cond == 0: take = True
            elif cond == 1: take = self.x == 0
            elif cond == 2:
                take = self.x != 0
                self.x = (self.x - 1) & 0xFFFFFFFF
            elif cond == 3: take = self.y == 0
            elif cond == 4:
                take = self.y != 0
                self.y = (self.y - 1) & 0xFFFFFFFF
            elif cond == 5: take = self.x != self.y
            elif cond == 6: take = self.pin_in(self.t) == 1
            elif cond == 7: take = self.osr_cnt < 32
            if take: next_pc = addr
        elif op == 1:  # WAIT
            pol = (ins >> 7) & 1
            lvl = self.pin_in(self.t)
            if lvl != pol:
                stalled = True
        elif op == 2:  # IN
            src = (ins >> 5) & 7
            cnt = ins & 0x1F or 32
            val = {0: self.pin_in(self.t), 1: self.x, 2: self.y, 3: 0, 6: self.isr, 7: self.osr}[src]
            val &= (1 << cnt) - 1
            self.isr = ((self.isr << cnt) | val) & 0xFFFFFFFF
            self.isr_cnt = min(32, self.isr_cnt + cnt)
        elif op == 3:  # OUT
            dst = (ins >> 5) & 7
            cnt = ins & 0x1F or 32
            if self.osr_cnt >= 32 and self.autopull:
                if not self._try_autopull():
                    stalled = True
            if not stalled:
                val = (self.osr >> (32 - cnt)) & ((1 << cnt) - 1)
                self.osr = (self.osr << cnt) & 0xFFFFFFFF
                self.osr_cnt = min(32, self.osr_cnt + cnt)
                if dst == 1: self.x = val
                elif dst == 2: self.y = val
                elif dst == 3: pass
                else: raise NotImplementedError("out dst %d" % dst)
        elif op == 4:  # PUSH / PULL
            if (ins >> 7) & 1:  # PULL
                if not self.tx_fifo:
                    if (ins >> 5) & 1: stalled = True
                else:
                    self.osr = self.tx_fifo.pop(0)
                    self.osr_cnt = 0
            else:  # PUSH
                if len(self.rx_fifo) >= 8:
                    if (ins >> 5) & 1: stalled = True
                    # noblock: drop
                else:
                    self.rx_fifo.append(self.isr)
                    self.push_log.append((self.t, self.isr))
                self.isr = 0
                self.isr_cnt = 0
        elif op == 5:  # MOV
            dst = (ins >> 5) & 7
            mop = (ins >> 3) & 3
            src = ins & 7
            val = {0: self.pin_in(self.t), 1: self.x, 2: self.y, 3: 0, 6: self.isr, 7: self.osr}[src]
            if mop == 1: val = (~val) & 0xFFFFFFFF
            elif mop == 2: val = int(f"{val:032b}"[::-1], 2)
            if dst == 1: self.x = val
            elif dst == 2: self.y = val
            elif dst == 6: self.isr = val; self.isr_cnt = 32
            elif dst == 7: self.osr = val; self.osr_cnt = 0
            else: raise NotImplementedError("mov dst %d" % dst)
        elif op == 7:  # SET
            dst = (ins >> 5) & 7
            val = ins & 0x1F
            if dst == 1: self.x = val
            elif dst == 2: self.y = val
            else: raise NotImplementedError("set dst %d" % dst)
        else:
            raise NotImplementedError("opcode %d at pc %d" % (op, self.pc))

        if stalled:
            self.t += 1
            return
        self.t += 1 + delay
        if self.pc == self.wrap and next_pc == self.pc + 1:
            next_pc = self.wt
        self.pc = next_pc

    def run(self, cycles):
        end = self.t + cycles
        while self.t < end:
            self.step()


# ---------------------------------------------------------------- frame helpers
def encode_bits(master, slave, control, data, broadcast=False):
    bits = [0 if broadcast else 1]
    def field(v, w, ack):
        nonlocal bits
        fb = [(v >> i) & 1 for i in range(w - 1, -1, -1)]
        bits += fb + [sum(fb) & 1] + ([1] if ack else [])
    field(master, 12, False); field(slave, 12, True); field(control, 4, True); field(len(data), 8, True)
    for b in data: field(b, 8, True)
    return bits


def pack_words(bits):
    words = []
    for i in range(0, len(bits), 32):
        chunk = bits[i:i + 32] + [0] * (32 - len(bits[i:i + 32]))
        words.append(int("".join(map(str, chunk)), 2))
    return words


# ---------------------------------------------------------------- tests
def test_tx(header):
    prog, wt, wrap = load_program(header, "avclan_tx")
    bits = encode_bits(0x110, 0x440, 0xF, [0x00, 0x5E, 0x29, 0x60, 0x01])
    sm = SM(prog, wt, wrap, sideset_bits=1, autopull=True)
    sm.tx_fifo = [len(bits) - 1] + pack_words(bits)
    sm.run(400 + len(bits) * 39 + 200)   # 1 MHz: cycles == us

    # pulses from the side log
    log = sm.side_log
    assert log and log[0][1] == 1, "first edge must be dominant"
    pulses = []
    for (t0, l0), (t1, l1) in zip(log, log[1:]):
        pulses.append((l0, t1 - t0))
    highs = [d for l, d in pulses if l == 1]
    lows = [d for l, d in pulses if l == 0]
    ok = True
    if highs[0] != 166 or lows[0] != 19:
        print(f"  TX start bit: high={highs[0]} low={lows[0]} (want 166/19)"); ok = False
    for i, b in enumerate(bits):
        h = highs[1 + i]
        want_h, want_l = (20, 19) if b else (32, 7)
        l = lows[1 + i] if 1 + i < len(lows) else None
        if h != want_h or (l is not None and i < len(bits) - 1 and l != want_l):
            print(f"  TX bit {i} ({b}): high={h} low={l} want {want_h}/{want_l}"); ok = False
    assert len(highs) == 1 + len(bits), f"pulse count {len(highs)} != {1 + len(bits)}"
    assert sm.side_pin == 0, "line must idle recessive"
    print(f"TX: {len(bits)} bits, start 166/19, all pulse widths exact: {'OK' if ok else 'FAIL'}")
    return ok


def test_rx(header, jitter=0):
    prog, wt, wrap = load_program(header, "avclan_rx")
    bits = encode_bits(0x190, 0x110, 0xF, [0x00, 0x25, 0x74, 0x9C, 0x01])
    # waveform at 4 MHz (0.25 us per cycle): list of (start_cycle, end_cycle) dominant intervals
    us = 4
    t = 100 * us
    dom = [(t, t + 166 * us)]
    t += (166 + 19) * us
    for b in bits:
        h = (20 if b else 32) * us + jitter
        dom.append((t, t + h))
        t += 39 * us
    end_t = t + 2000 * us

    def pin(tc):
        for a, b_ in dom:
            if a <= tc < b_:
                return 1
        return 0

    sm = SM(prog, wt, wrap, sideset_bits=0, pin_in=pin)
    sm.osr = 0xFFFFFFFF  # pio_sm_exec(mov osr, ~null)
    sm.osr_cnt = 0
    while sm.t < end_t:
        sm.step()
        if len(sm.rx_fifo) > 4:   # the IRQ handler drains promptly
            sm.rx_fifo.clear()

    doms = [(tc, w) for tc, w in sm.push_log if not (w & 0x80000000)]
    gaps = [(tc, (~w) & 0xFFFFFFFF) for tc, w in sm.push_log if (w & 0x80000000)]
    assert len(doms) == 1 + len(bits), f"dominant words {len(doms)} != {1 + len(bits)}"

    def to_us(c):
        return (c + 5) // 2          # RX_DOM_TO_US in avclan.c

    jit_us = jitter / us
    ok = True
    widths = [to_us(w) for _, w in doms]
    if not (150 <= widths[0] <= 175):
        print(f"  RX start width {widths[0]} us"); ok = False
    for i, b in enumerate(bits):
        wv = widths[1 + i]
        want = (20 if b else 32) + jit_us
        sym_ok = (wv < 26) == bool(b)
        if not sym_ok or abs(wv - want) > 1:
            print(f"  RX bit {i} ({b}): measured {wv} us (want ~{want})"); ok = False
    # latency: push time of the last dominant word vs. the end of its dominant pulse
    last_push_t, _ = doms[-1]
    last_dom_end = dom[-1][1]
    lat_us = (last_push_t - last_dom_end) / us
    if not (0 <= lat_us <= 3):
        print(f"  RX last word pushed {lat_us:.2f} us after the dominant edge"); ok = False
    gw = [(g + 4) // 2 for _, g in gaps]          # RX_GAP_TO_US in avclan.c
    exp_gaps = [19] + [(19 if b else 7) - jit_us for b in bits[:-1]]
    bad_gaps = [(i, g, e) for i, (g, e) in enumerate(zip(gw, exp_gaps)) if abs(g - e) > 1]
    if bad_gaps:
        print(f"  RX gaps off: {bad_gaps[:5]}"); ok = False
    print(f"RX (jitter {jitter/4:+.2f} us): {len(bits)} bits, widths {min(widths[1:])}..{max(widths[1:])} us, "
          f"start {widths[0]} us, last word {lat_us:.2f} us after edge: {'OK' if ok else 'FAIL'}")
    return ok


def main():
    headers = sorted(glob.glob("build-*/avclan.pio.h"))
    if not headers:
        print("no build-*/avclan.pio.h - run ./build.sh first"); sys.exit(2)
    h = headers[0]
    print("using", h)
    ok = test_tx(h)
    for j in (0, -4, 4, -8, 8):    # -2..+2 us of comparator asymmetry
        ok &= test_rx(h, jitter=j)
    print("ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
