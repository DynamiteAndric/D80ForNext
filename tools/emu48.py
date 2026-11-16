"""Minimal 48K ZX Spectrum harness (screen rendering, keyboard, frames).

This is not a real emulator: there is no contention, no border, no sound,
and the frame length is approximate. It is just enough to:

* restore a converted snapshot, run it for some frames and render the screen;
* boot the 48K ROM, type ``LOAD ""`` and load a .tap through a ROM trap at
  LD-BYTES (0x0556), then render what the program puts on screen.

The 48K ROM is not included; pass its path (any standard 16384-byte 48.rom).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from snapshot import Snapshot
from z80mini import Z80, FLAG_C

INSTR_PER_FRAME = 8000  # about 69888 T-states at roughly 8.7 T-states per instruction
LD_BYTES = 0x0556

KEYS = {  # key -> (row 0..7 by address bit A8..A15, bit)
    "CAPS": (0, 0), "Z": (0, 1), "X": (0, 2), "C": (0, 3), "V": (0, 4),
    "A": (1, 0), "S": (1, 1), "D": (1, 2), "F": (1, 3), "G": (1, 4),
    "Q": (2, 0), "W": (2, 1), "E": (2, 2), "R": (2, 3), "T": (2, 4),
    "1": (3, 0), "2": (3, 1), "3": (3, 2), "4": (3, 3), "5": (3, 4),
    "0": (4, 0), "9": (4, 1), "8": (4, 2), "7": (4, 3), "6": (4, 4),
    "P": (5, 0), "O": (5, 1), "I": (5, 2), "U": (5, 3), "Y": (5, 4),
    "ENTER": (6, 0), "L": (6, 1), "K": (6, 2), "J": (6, 3), "H": (6, 4),
    "SPACE": (7, 0), "SYM": (7, 1), "M": (7, 2), "N": (7, 3), "B": (7, 4),
}

PALETTE = [(0, 0, 0), (0, 0, 0xD7), (0xD7, 0, 0), (0xD7, 0, 0xD7),
           (0, 0xD7, 0), (0, 0xD7, 0xD7), (0xD7, 0xD7, 0), (0xD7, 0xD7, 0xD7),
           (0, 0, 0), (0, 0, 0xFF), (0xFF, 0, 0), (0xFF, 0, 0xFF),
           (0, 0xFF, 0), (0, 0xFF, 0xFF), (0xFF, 0xFF, 0), (0xFF, 0xFF, 0xFF)]


def tap_blocks(data: bytes) -> list[bytes]:
    blocks, pos = [], 0
    while pos + 2 <= len(data):
        n = data[pos] | (data[pos + 1] << 8)
        blocks.append(data[pos + 2:pos + 2 + n])
        pos += 2 + n
    return blocks


class Spectrum48:
    def __init__(self, rom: bytes) -> None:
        if len(rom) != 16384:
            raise ValueError("48K ROM must be 16384 bytes")
        self.mem = bytearray(0x10000)
        self.mem[:0x4000] = rom
        self.cpu = Z80(self.mem)
        self.cpu.rom_top = 0x4000
        self.cpu.halt_di_error = False
        self.hung = False  # HALT with interrupts disabled: a real Spectrum hangs too
        self.cpu.port_in = self.port_in
        self.cpu.pc = 0
        self.cpu.im = 0
        self.pressed: set[str] = set()
        self.tape: list[bytes] = []
        self.tape_pos = 0
        self.frames = 0
        self.loaded_blocks = 0

    # ---- I/O ---------------------------------------------------------------
    def port_in(self, port: int) -> int:
        if port & 1 == 0:
            v = 0x1F
            hi = port >> 8
            for k in self.pressed:
                row, bit = KEYS[k]
                if not hi & (1 << row):
                    v &= ~(1 << bit)
            return v | 0xA0
        if port & 0xFF == 0x1F:
            return 0x00  # Kempston: nothing pressed
        return 0xFF

    # ---- tape trap ---------------------------------------------------------
    def _ld_bytes(self) -> None:
        c = self.cpu
        want_flag, length, dest = c.a, c.de, c.ix  # A = flag byte, DE = length, IX = dest
        ok = False
        while self.tape_pos < len(self.tape):
            blk = self.tape[self.tape_pos]
            self.tape_pos += 1
            if not blk or blk[0] != want_flag:
                continue
            payload = blk[1:-1]
            n = min(length, len(payload))
            for i in range(n):
                c.wr(dest + i, payload[i])
            c.ix = (dest + n) & 0xFFFF
            c.de = length - n
            ok = n == length
            self.loaded_blocks += 1
            break
        c.f = (c.f | FLAG_C) if ok else (c.f & ~FLAG_C)
        c.pc = c.pop()

    # ---- running -----------------------------------------------------------
    def run_frames(self, frames: int) -> None:
        c = self.cpu
        for _ in range(frames):
            target = c.steps + INSTR_PER_FRAME
            while c.steps < target:
                if c.halted:
                    if not c.iff1:
                        self.hung = True
                        return
                    c.steps = target
                    break
                if c.pc == LD_BYTES:
                    self._ld_bytes()
                    continue
                c.step()
            c.interrupt()
            self.frames += 1

    def type_keys(self, keys: list[list[str]], hold: int = 4, gap: int = 4) -> None:
        for combo in keys:
            self.pressed = set(combo)
            self.run_frames(hold)
            self.pressed = set()
            self.run_frames(gap)

    def load_snapshot(self, s: Snapshot) -> None:
        c = self.cpu
        self.mem[0x4000:] = s.ram
        c.a, c.f, c.bc, c.de, c.hl = s.a, s.f, s.bc, s.de, s.hl
        c.a_, c.f_ = s.a_, s.f_
        c.b_, c.c_ = s.bc_ >> 8, s.bc_ & 0xFF
        c.d_, c.e_ = s.de_ >> 8, s.de_ & 0xFF
        c.h_, c.l_ = s.hl_ >> 8, s.hl_ & 0xFF
        c.ix, c.iy, c.i, c.im = s.ix, s.iy, s.i, s.im
        c.sp = s.sp
        c.pc = c.pop()  # PC sits on the stack, like .sna
        c.iff1 = c.iff2 = 1 if s.iff else 0

    def boot_and_load_tap(self, tap: bytes, boot_frames: int = 120, run_frames: int = 150) -> None:
        self.tape = tap_blocks(tap)
        self.tape_pos = 0
        self.run_frames(boot_frames)            # ROM init + RAM test
        # LOAD "" ENTER  (J = LOAD keyword, Symbol Shift+P = ")
        self.type_keys([["J"], ["SYM", "P"], ["SYM", "P"], ["ENTER"]])
        self.run_frames(run_frames)

    # ---- screen ------------------------------------------------------------
    def screen_png(self, path: str | Path, scale: int = 2) -> None:
        m = self.mem
        rows = []
        for y in range(192):
            line = bytearray()
            base = 0x4000 | ((y & 0xC0) << 5) | ((y & 0x07) << 8) | ((y & 0x38) << 2)
            abase = 0x5800 + (y >> 3) * 32
            for cx in range(32):
                bits, attr = m[base + cx], m[abase + cx]
                bright = 8 if attr & 0x40 else 0
                ink, paper = PALETTE[(attr & 7) | bright], PALETTE[((attr >> 3) & 7) | bright]
                for b in range(7, -1, -1):
                    line += bytes(ink if bits & (1 << b) else paper) * scale
            raw = b"\x00" + bytes(line)
            rows.extend([raw] * scale)
        w, h = 256 * scale, 192 * scale

        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b"")
        Path(path).write_bytes(png)
