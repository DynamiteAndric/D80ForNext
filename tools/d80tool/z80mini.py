"""A small Z80 interpreter, just enough to run snapshot depacker stubs.

It covers the documented unprefixed, CB, ED and DD/FD (IX/IY) instruction
sets, with correct flags for the common arithmetic and logic ops. It has no
timing and no interrupts, and does not emulate the undocumented
IXh/IXl/DDCB-store forms. Execution stops when the program counter enters a
caller-defined "trap" region (for example the ROM), so the caller decides what
the ROM call means.
"""

from __future__ import annotations

FLAG_C, FLAG_N, FLAG_PV, FLAG_3, FLAG_H, FLAG_5, FLAG_Z, FLAG_S = (1 << i for i in range(8))

PARITY = [0] * 256
for _i in range(256):
    PARITY[_i] = FLAG_PV if bin(_i).count("1") % 2 == 0 else 0
SZ = [(i & 0xA8) | (FLAG_Z if i == 0 else 0) for i in range(256)]
SZP = [SZ[i] | PARITY[i] for i in range(256)]


class Z80Error(Exception):
    pass


class Trap(Exception):
    """Raised when execution reaches a trapped address."""

    def __init__(self, pc: int, kind: str) -> None:
        super().__init__(f"{kind} to {pc:#06x}")
        self.pc = pc
        self.kind = kind


class Z80:
    def __init__(self, mem: bytearray) -> None:
        self.m = mem
        self.a = self.f = self.b = self.c = self.d = self.e = self.h = self.l = 0
        self.a_ = self.f_ = self.b_ = self.c_ = self.d_ = self.e_ = self.h_ = self.l_ = 0
        self.ix = self.iy = 0
        self.sp = 0xFFFF
        self.pc = 0
        self.i = self.r = 0
        self.iff1 = self.iff2 = 0
        self.im = 1
        self.halted = False
        self.trap_below = 0x0000  # executing any address < trap_below raises Trap
        self.rom_top = 0x0000     # writes below this address are ignored (ROM)
        self.halt_di_error = True  # HALT with interrupts off: raise (else stay halted forever)
        self.port_in = lambda port: 0xFF
        self.port_out = lambda port, value: None
        self.steps = 0

    # ---- register pairs -------------------------------------------------
    def _get_bc(self): return (self.b << 8) | self.c
    def _set_bc(self, v): self.b, self.c = (v >> 8) & 0xFF, v & 0xFF
    def _get_de(self): return (self.d << 8) | self.e
    def _set_de(self, v): self.d, self.e = (v >> 8) & 0xFF, v & 0xFF
    def _get_hl(self): return (self.h << 8) | self.l
    def _set_hl(self, v): self.h, self.l = (v >> 8) & 0xFF, v & 0xFF
    def _get_af(self): return (self.a << 8) | self.f
    def _set_af(self, v): self.a, self.f = (v >> 8) & 0xFF, v & 0xFF
    bc = property(_get_bc, _set_bc)
    de = property(_get_de, _set_de)
    hl = property(_get_hl, _set_hl)
    af = property(_get_af, _set_af)

    # ---- memory ----------------------------------------------------------
    def rd(self, a): return self.m[a & 0xFFFF]
    def wr(self, a, v):
        a &= 0xFFFF
        if a >= self.rom_top:
            self.m[a] = v & 0xFF
    def rd16(self, a): return self.m[a & 0xFFFF] | (self.m[(a + 1) & 0xFFFF] << 8)

    def wr16(self, a, v):
        self.wr(a, v)
        self.wr(a + 1, v >> 8)

    def fetch(self):
        v = self.m[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch()
        return lo | (self.fetch() << 8)

    def disp(self):
        d = self.fetch()
        return d - 256 if d & 0x80 else d

    def push(self, v):
        self.sp = (self.sp - 2) & 0xFFFF
        self.wr16(self.sp, v)

    def pop(self):
        v = self.rd16(self.sp)
        self.sp = (self.sp + 2) & 0xFFFF
        return v

    # ---- 8-bit register access by index (B C D E H L (HL) A) ---------------
    def get_r(self, idx, xy=None, d=0):
        if idx == 0: return self.b
        if idx == 1: return self.c
        if idx == 2: return self.d
        if idx == 3: return self.e
        if idx == 4: return self.h
        if idx == 5: return self.l
        if idx == 6: return self.rd(self.hl if xy is None else (getattr(self, xy) + d) & 0xFFFF)
        return self.a

    def set_r(self, idx, v, xy=None, d=0):
        v &= 0xFF
        if idx == 0: self.b = v
        elif idx == 1: self.c = v
        elif idx == 2: self.d = v
        elif idx == 3: self.e = v
        elif idx == 4: self.h = v
        elif idx == 5: self.l = v
        elif idx == 6: self.wr(self.hl if xy is None else (getattr(self, xy) + d) & 0xFFFF, v)
        else: self.a = v

    # ---- ALU -------------------------------------------------------------
    def add8(self, v, carry=0):
        a = self.a
        r = a + v + carry
        f = SZ[r & 0xFF] | (FLAG_C if r > 0xFF else 0)
        f |= (a ^ v ^ r) & FLAG_H
        f |= FLAG_PV if ((a ^ ~v) & (a ^ r) & 0x80) else 0
        self.a = r & 0xFF
        self.f = f

    def sub8(self, v, carry=0, store=True):
        a = self.a
        r = a - v - carry
        f = SZ[r & 0xFF] | FLAG_N | (FLAG_C if r < 0 else 0)
        f |= (a ^ v ^ r) & FLAG_H
        f |= FLAG_PV if ((a ^ v) & (a ^ r) & 0x80) else 0
        if store:
            self.a = r & 0xFF
        else:  # CP: undocumented bits 3/5 come from the operand
            f = (f & ~0x28) | (v & 0x28)
        self.f = f

    def alu(self, op, v):
        if op == 0: self.add8(v)
        elif op == 1: self.add8(v, self.f & FLAG_C)
        elif op == 2: self.sub8(v)
        elif op == 3: self.sub8(v, self.f & FLAG_C)
        elif op == 4:
            self.a &= v
            self.f = SZP[self.a] | FLAG_H
        elif op == 5:
            self.a ^= v
            self.f = SZP[self.a]
        elif op == 6:
            self.a |= v
            self.f = SZP[self.a]
        else: self.sub8(v, store=False)

    def inc8(self, v):
        r = (v + 1) & 0xFF
        self.f = (self.f & FLAG_C) | SZ[r] | (FLAG_H if (v & 0x0F) == 0x0F else 0) | (FLAG_PV if v == 0x7F else 0)
        return r

    def dec8(self, v):
        r = (v - 1) & 0xFF
        self.f = (self.f & FLAG_C) | SZ[r] | FLAG_N | (FLAG_H if (v & 0x0F) == 0 else 0) | (FLAG_PV if v == 0x80 else 0)
        return r

    def add16(self, a, b):
        r = a + b
        self.f = (self.f & (FLAG_S | FLAG_Z | FLAG_PV)) | (FLAG_C if r > 0xFFFF else 0) \
            | (((a ^ b ^ r) >> 8) & FLAG_H) | ((r >> 8) & 0x28)
        return r & 0xFFFF

    def adc16(self, b):
        a = self.hl
        c = self.f & FLAG_C
        r = a + b + c
        f = (FLAG_C if r > 0xFFFF else 0) | (((a ^ b ^ r) >> 8) & FLAG_H)
        f |= FLAG_PV if ((a ^ ~b) & (a ^ r) & 0x8000) else 0
        r &= 0xFFFF
        f |= (FLAG_Z if r == 0 else 0) | ((r >> 8) & 0xA8)
        self.f = f
        self.hl = r

    def sbc16(self, b):
        a = self.hl
        c = self.f & FLAG_C
        r = a - b - c
        f = FLAG_N | (FLAG_C if r < 0 else 0) | (((a ^ b ^ r) >> 8) & FLAG_H)
        f |= FLAG_PV if ((a ^ b) & (a ^ r) & 0x8000) else 0
        r &= 0xFFFF
        f |= (FLAG_Z if r == 0 else 0) | ((r >> 8) & 0xA8)
        self.f = f
        self.hl = r

    def cond(self, cc):
        f = self.f
        return [not f & FLAG_Z, f & FLAG_Z, not f & FLAG_C, f & FLAG_C,
                not f & FLAG_PV, f & FLAG_PV, not f & FLAG_S, f & FLAG_S][cc]

    def rot(self, op, v):
        c = self.f & FLAG_C
        if op == 0: r = ((v << 1) | (v >> 7)) & 0xFF; nc = v >> 7          # RLC
        elif op == 1: r = ((v >> 1) | (v << 7)) & 0xFF; nc = v & 1         # RRC
        elif op == 2: r = ((v << 1) | c) & 0xFF; nc = v >> 7               # RL
        elif op == 3: r = (v >> 1) | (c << 7); nc = v & 1                  # RR
        elif op == 4: r = (v << 1) & 0xFF; nc = v >> 7                     # SLA
        elif op == 5: r = (v >> 1) | (v & 0x80); nc = v & 1                # SRA
        elif op == 6: r = ((v << 1) | 1) & 0xFF; nc = v >> 7               # SLL
        else: r = v >> 1; nc = v & 1                                       # SRL
        self.f = SZP[r] | (FLAG_C if nc else 0)
        return r

    # ---- pair tables -----------------------------------------------------
    def get_rp(self, p, xy=None):
        if p == 0: return self.bc
        if p == 1: return self.de
        if p == 2: return self.hl if xy is None else getattr(self, xy)
        return self.sp

    def set_rp(self, p, v, xy=None):
        v &= 0xFFFF
        if p == 0: self.bc = v
        elif p == 1: self.de = v
        elif p == 2:
            if xy is None: self.hl = v
            else: setattr(self, xy, v)
        else: self.sp = v

    def get_rp2(self, p, xy=None):
        return self.af if p == 3 else self.get_rp(p, xy)

    def set_rp2(self, p, v, xy=None):
        if p == 3: self.af = v
        else: self.set_rp(p, v, xy)

    # ---- execution -------------------------------------------------------
    def run(self, max_steps: int = 20_000_000) -> None:
        while self.steps < max_steps:
            if self.pc < self.trap_below:
                raise Trap(self.pc, "jump")
            self.step()
        raise Z80Error(f"step limit {max_steps} reached at pc={self.pc:#06x}")

    def step(self) -> None:
        self.steps += 1
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        op = self.fetch()
        if op in (0xCB, 0xED, 0xDD, 0xFD):  # the prefixed opcode is a second M1 cycle
            self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        if op == 0xCB: return self.exec_cb()
        if op == 0xED: return self.exec_ed()
        if op in (0xDD, 0xFD): return self.exec_xy("ix" if op == 0xDD else "iy")
        self.exec_main(op)

    def exec_main(self, op, xy=None):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        d = 0
        hreg = (lambda: getattr(self, xy)) if xy else (lambda: self.hl)

        if x == 1:
            if op == 0x76:
                if not self.iff1 and self.halt_di_error:
                    raise Z80Error(f"HALT with interrupts disabled at {self.pc - 1:#06x}")
                self.halted = True
                self.pc = (self.pc - 1) & 0xFFFF
                return
            if xy and (y == 6 or z == 6):
                d = self.disp()
                self.set_r(y, self.get_r(z, xy if z == 6 else None, d), xy if y == 6 else None, d)
            else:
                self.set_r(y, self.get_r(z))
            return
        if x == 2:
            if xy and z == 6:
                d = self.disp()
            self.alu(y, self.get_r(z, xy if z == 6 else None, d))
            return
        if x == 0:
            if z == 0:
                if y == 0: return
                if y == 1:
                    self.af, (self.a_, self.f_) = (self.a_ << 8) | self.f_, (self.a, self.f)
                    return
                e = self.disp()
                if y == 2:
                    self.b = (self.b - 1) & 0xFF
                    if self.b: self.pc = (self.pc + e) & 0xFFFF
                elif y == 3 or self.cond(y - 4):
                    self.pc = (self.pc + e) & 0xFFFF
                return
            if z == 1:
                if q == 0: self.set_rp(p, self.fetch16(), xy)
                else:
                    v = self.add16(hreg(), self.get_rp(p, xy))
                    self.set_rp(2, v, xy)
                return
            if z == 2:
                if p == 0:
                    if q == 0: self.wr(self.bc, self.a)
                    else: self.a = self.rd(self.bc)
                elif p == 1:
                    if q == 0: self.wr(self.de, self.a)
                    else: self.a = self.rd(self.de)
                elif p == 2:
                    nn = self.fetch16()
                    if q == 0: self.wr16(nn, hreg())
                    else: self.set_rp(2, self.rd16(nn), xy)
                else:
                    nn = self.fetch16()
                    if q == 0: self.wr(nn, self.a)
                    else: self.a = self.rd(nn)
                return
            if z == 3:
                self.set_rp(p, self.get_rp(p, xy) + (1 if q == 0 else -1), xy)
                return
            if z in (4, 5):
                if y == 6 and xy: d = self.disp()
                v = self.get_r(y, xy if y == 6 else None, d)
                v = self.inc8(v) if z == 4 else self.dec8(v)
                self.set_r(y, v, xy if y == 6 else None, d)
                return
            if z == 6:
                if y == 6 and xy: d = self.disp()
                self.set_r(y, self.fetch(), xy if y == 6 else None, d)
                return
            # z == 7
            a, c = self.a, self.f & FLAG_C
            keep = self.f & (FLAG_S | FLAG_Z | FLAG_PV)
            if y == 0:
                c = a >> 7; self.a = ((a << 1) | c) & 0xFF
                self.f = keep | c | (self.a & 0x28)
            elif y == 1:
                c = a & 1; self.a = (a >> 1) | (c << 7)
                self.f = keep | c | (self.a & 0x28)
            elif y == 2:
                self.a = ((a << 1) | c) & 0xFF
                self.f = keep | (a >> 7) | (self.a & 0x28)
            elif y == 3:
                self.a = (a >> 1) | (c << 7)
                self.f = keep | (a & 1) | (self.a & 0x28)
            elif y == 4:  # DAA
                corr, nc = 0, c
                if (self.f & FLAG_H) or (a & 0x0F) > 9: corr |= 0x06
                if c or a > 0x99: corr |= 0x60; nc = 1
                if self.f & FLAG_N:
                    h = 1 if (self.f & FLAG_H) and (a & 0x0F) < 6 else 0
                    r = (a - corr) & 0xFF
                else:
                    h = 1 if (a & 0x0F) > 9 else 0
                    r = (a + corr) & 0xFF
                self.a = r
                self.f = SZP[r] | (self.f & FLAG_N) | (FLAG_H if h else 0) | (FLAG_C if nc else 0)
            elif y == 5:
                self.a ^= 0xFF
                self.f = (self.f & (FLAG_S | FLAG_Z | FLAG_PV | FLAG_C)) | FLAG_H | FLAG_N | (self.a & 0x28)
            elif y == 6:
                self.f = keep | FLAG_C | (a & 0x28)
            else:
                self.f = keep | (FLAG_H if c else 0) | (0 if c else FLAG_C) | (a & 0x28)
            return
        # x == 3
        if z == 0:
            if self.cond(y): self.pc = self.pop()
            return
        if z == 1:
            if q == 0:
                self.set_rp2(p, self.pop(), xy)
            elif p == 0:
                self.pc = self.pop()
            elif p == 1:
                for r in "bcdehl":
                    s, t = getattr(self, r), getattr(self, r + "_")
                    setattr(self, r, t); setattr(self, r + "_", s)
            elif p == 2:
                self.pc = hreg()
            else:
                self.sp = hreg()
            return
        if z == 2:
            nn = self.fetch16()
            if self.cond(y): self.pc = nn
            return
        if z == 3:
            if y == 0: self.pc = self.fetch16()
            elif y == 1: raise Z80Error("CB prefix in main table")
            elif y == 2: self.port_out((self.a << 8) | self.fetch(), self.a)  # OUT (n),A
            elif y == 3:
                n = self.fetch()
                self.a = self.port_in((self.a << 8) | n) & 0xFF
            elif y == 4:
                v = self.rd16(self.sp)
                self.wr16(self.sp, hreg())
                self.set_rp(2, v, xy)
            elif y == 5: self.de, self.hl = self.hl, self.de
            elif y == 6: self.iff1 = self.iff2 = 0
            else: self.iff1 = self.iff2 = 1
            return
        if z == 4:
            nn = self.fetch16()
            if self.cond(y): self._call(nn)
            return
        if z == 5:
            if q == 0: self.push(self.get_rp2(p, xy))
            elif p == 0: self._call(self.fetch16())
            else: raise Z80Error(f"prefix {op:#04x} in main table")
            return
        if z == 6:
            self.alu(y, self.fetch())
            return
        self._call(y * 8)

    def interrupt(self) -> bool:
        """Accept a maskable interrupt if enabled. Returns True if taken."""
        if not self.iff1:
            return False
        if self.halted:
            self.halted = False
            self.pc = (self.pc + 1) & 0xFFFF
        self.iff1 = self.iff2 = 0
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)  # interrupt acknowledge is an M1 cycle
        self.push(self.pc)
        if self.im == 2:
            self.pc = self.rd16(((self.i << 8) | 0xFF) & 0xFFFF)
        else:
            self.pc = 0x0038
        return True

    def _call(self, nn):
        self.push(self.pc)
        self.pc = nn
        if nn < self.trap_below:
            raise Trap(nn, "call")

    def exec_cb(self, xy=None, d=0):
        op = self.fetch()
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        idx = 6 if xy else z
        v = self.get_r(idx, xy, d)
        if x == 0:
            r = self.rot(y, v)
        elif x == 1:
            f = (self.f & FLAG_C) | FLAG_H | (v & 0x28)
            if not v & (1 << y): f |= FLAG_Z | FLAG_PV
            if y == 7 and v & 0x80: f |= FLAG_S
            self.f = f
            return
        elif x == 2:
            r = v & ~(1 << y) & 0xFF
        else:
            r = v | (1 << y)
        self.set_r(idx, r, xy, d)
        if xy and z != 6:
            self.set_r(z, r)

    def exec_xy(self, xy):
        op = self.fetch()
        if op == 0xCB:
            d = self.disp()
            return self.exec_cb(xy, d)
        if op in (0xDD, 0xFD, 0xED):
            self.pc = (self.pc - 1) & 0xFFFF
            return
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        uses_hl = (op in (0x21, 0x22, 0x2A, 0x23, 0x2B, 0x09, 0x19, 0x29, 0x39, 0xE1, 0xE5,
                          0xE3, 0xE9, 0xF9, 0x34, 0x35, 0x36)
                   or (x == 1 and (y == 6 or z == 6) and op != 0x76)
                   or (x == 2 and z == 6))
        if not uses_hl:
            if (x == 1 and (y in (4, 5) or z in (4, 5))) or (x == 2 and z in (4, 5)) \
                    or op in (0x24, 0x25, 0x26, 0x2C, 0x2D, 0x2E):
                # undocumented IXh/IXl/IYh/IYl forms: run the H/L version on the index halves
                h, l = self.h, self.l
                v = getattr(self, xy)
                self.h, self.l = v >> 8, v & 0xFF
                self.exec_main(op)
                setattr(self, xy, (self.h << 8) | self.l)
                self.h, self.l = h, l
                return
            return self.exec_main(op)
        if x == 1:
            d = self.disp()
            if y == 6:
                self.wr((getattr(self, xy) + d) & 0xFFFF, self.get_r(z))
            else:
                self.set_r(y, self.rd((getattr(self, xy) + d) & 0xFFFF))
            return
        return self.exec_main(op, xy)

    def exec_ed(self):
        op = self.fetch()
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 1:
            if z == 0:  # IN r,(C)
                v = self.port_in(self.bc) & 0xFF
                if y != 6: self.set_r(y, v)
                self.f = (self.f & FLAG_C) | SZP[v]
            elif z == 1: self.port_out(self.bc, 0 if y == 6 else self.get_r(y))  # OUT (C),r
            elif z == 2:
                if q == 0: self.sbc16(self.get_rp(p))
                else: self.adc16(self.get_rp(p))
            elif z == 3:
                nn = self.fetch16()
                if q == 0: self.wr16(nn, self.get_rp(p))
                else: self.set_rp(p, self.rd16(nn))
            elif z == 4:
                v = self.a; self.a = 0; self.sub8(v)
            elif z == 5:
                self.pc = self.pop(); self.iff1 = self.iff2
            elif z == 6:
                self.im = [0, 0, 1, 2][y & 3]
            else:
                if y == 0: self.i = self.a
                elif y == 1: self.r = self.a
                elif y in (2, 3):
                    self.a = self.i if y == 2 else self.r
                    self.f = (self.f & FLAG_C) | SZ[self.a] | (FLAG_PV if self.iff2 else 0)
                elif y == 4:  # RRD
                    m = self.rd(self.hl)
                    self.wr(self.hl, ((self.a << 4) | (m >> 4)) & 0xFF)
                    self.a = (self.a & 0xF0) | (m & 0x0F)
                    self.f = (self.f & FLAG_C) | SZP[self.a]
                elif y == 5:  # RLD
                    m = self.rd(self.hl)
                    self.wr(self.hl, ((m << 4) | (self.a & 0x0F)) & 0xFF)
                    self.a = (self.a & 0xF0) | (m >> 4)
                    self.f = (self.f & FLAG_C) | SZP[self.a]
            return
        if x == 2 and z <= 3 and y >= 4:
            inc = 1 if y in (4, 6) else -1
            repeat = y >= 6
            if z == 0:  # LDI/LDD/LDIR/LDDR
                while True:
                    v = self.rd(self.hl)
                    self.wr(self.de, v)
                    self.hl = (self.hl + inc) & 0xFFFF
                    self.de = (self.de + inc) & 0xFFFF
                    self.bc = (self.bc - 1) & 0xFFFF
                    if not repeat or self.bc == 0:
                        break
                    self.steps += 1
                n = (v + self.a) & 0xFF
                self.f = (self.f & (FLAG_S | FLAG_Z | FLAG_C)) | (FLAG_PV if self.bc else 0) \
                    | (n & FLAG_3) | ((n << 4) & FLAG_5)
            elif z == 1:  # CPI/CPD/CPIR/CPDR
                c = self.f & FLAG_C
                while True:
                    v = self.rd(self.hl)
                    self.hl = (self.hl + inc) & 0xFFFF
                    self.bc = (self.bc - 1) & 0xFFFF
                    r = (self.a - v) & 0xFF
                    if not repeat or self.bc == 0 or r == 0:
                        break
                h = (self.a ^ v ^ r) & FLAG_H
                self.f = c | FLAG_N | SZ[r] & (FLAG_S | FLAG_Z) | h | (FLAG_PV if self.bc else 0)
            else:  # block I/O: INI/IND/INIR/INDR, OUTI/OUTD/OTIR/OTDR
                while True:
                    if z == 2:
                        self.wr(self.hl, self.port_in(self.bc) & 0xFF)
                        self.b = (self.b - 1) & 0xFF
                    else:
                        v = self.rd(self.hl)
                        self.b = (self.b - 1) & 0xFF
                        self.port_out(self.bc, v)
                    self.hl = (self.hl + inc) & 0xFFFF
                    if not repeat or self.b == 0:
                        break
                    self.steps += 1
                self.f = FLAG_N | (FLAG_Z if self.b == 0 else 0)
            return
        # undefined ED opcodes act as NOP
