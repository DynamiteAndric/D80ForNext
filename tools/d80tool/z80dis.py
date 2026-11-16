"""Small Z80 disassembler (documented opcodes plus IXh/IXl and SLL).

disasm(mem, addr) -> (length, text, info), where info is a dict with
optional keys: 'jump' (target), 'call' (target), 'end' (True after
unconditional JP/JR/RET/RETI/RETN/JP (HL)).
"""

from __future__ import annotations

R = ["B", "C", "D", "E", "H", "L", "(HL)", "A"]
RP = ["BC", "DE", "HL", "SP"]
RP2 = ["BC", "DE", "HL", "AF"]
CC = ["NZ", "Z", "NC", "C", "PO", "PE", "P", "M"]
ALU = ["ADD A,", "ADC A,", "SUB ", "SBC A,", "AND ", "XOR ", "OR ", "CP "]
ROT = ["RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SRL"]
BLI = {(4, 0): "LDI", (4, 1): "CPI", (4, 2): "INI", (4, 3): "OUTI",
       (5, 0): "LDD", (5, 1): "CPD", (5, 2): "IND", (5, 3): "OUTD",
       (6, 0): "LDIR", (6, 1): "CPIR", (6, 2): "INIR", (6, 3): "OTIR",
       (7, 0): "LDDR", (7, 1): "CPDR", (7, 2): "INDR", (7, 3): "OTDR"}


def h8(v): return f"#{v & 0xFF:02X}"
def h16(v): return f"#{v & 0xFFFF:04X}"


def disasm(mem, addr: int):
    pos = addr
    info: dict = {}

    def b():
        nonlocal pos
        v = mem[pos & 0xFFFF]
        pos += 1
        return v

    def w():
        lo = b()
        return lo | (b() << 8)

    def sd():
        v = b()
        return v - 256 if v & 0x80 else v

    op = b()
    xy = None
    if op in (0xDD, 0xFD):
        xy = "IX" if op == 0xDD else "IY"
        op = b()
        if op in (0xDD, 0xFD, 0xED):
            return 1, f"DEFB {h8(mem[addr & 0xFFFF])}", info

    def idx_mem(d):
        return f"({xy}{'+' if d >= 0 else '-'}{h8(abs(d))})"

    def reg(i, d=None):
        if xy and i == 6:
            return idx_mem(d)
        if xy and i in (4, 5):
            return xy + ("H" if i == 4 else "L")
        return R[i]

    def rp(i):
        return xy if (xy and i == 2) else RP[i]

    if op == 0xCB:
        if xy:
            d = sd()
            op2 = b()
            x, y, z = op2 >> 6, (op2 >> 3) & 7, op2 & 7
            m = idx_mem(d)
            if x == 0: t = f"{ROT[y]} {m}"
            elif x == 1: t = f"BIT {y},{m}"
            elif x == 2: t = f"RES {y},{m}"
            else: t = f"SET {y},{m}"
            if x != 1 and z != 6:
                t += f",{R[z]}"
            return pos - addr, t, info
        op2 = b()
        x, y, z = op2 >> 6, (op2 >> 3) & 7, op2 & 7
        t = [f"{ROT[y]} {R[z]}", f"BIT {y},{R[z]}", f"RES {y},{R[z]}", f"SET {y},{R[z]}"][x]
        return pos - addr, t, info

    if op == 0xED:
        op2 = b()
        x, y, z = op2 >> 6, (op2 >> 3) & 7, op2 & 7
        p, q = y >> 1, y & 1
        t = None
        if x == 1:
            if z == 0: t = f"IN {R[y]},(C)" if y != 6 else "IN (C)"
            elif z == 1: t = f"OUT (C),{R[y]}" if y != 6 else "OUT (C),0"
            elif z == 2: t = f"{'SBC' if q == 0 else 'ADC'} HL,{RP[p]}"
            elif z == 3:
                nn = w()
                t = f"LD ({h16(nn)}),{RP[p]}" if q == 0 else f"LD {RP[p]},({h16(nn)})"
            elif z == 4: t = "NEG"
            elif z == 5:
                t = "RETI" if y == 1 else "RETN"
                info["end"] = True
            elif z == 6: t = f"IM {[0, 0, 1, 2, 0, 0, 1, 2][y]}"
            else: t = ["LD I,A", "LD R,A", "LD A,I", "LD A,R", "RRD", "RLD", "NOP", "NOP"][y]
        elif x == 2 and (y, z) in BLI:
            t = BLI[(y, z)]
        if t is None:
            t = f"DEFB #ED,{h8(op2)}"
        return pos - addr, t, info

    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    t = ""
    if x == 0:
        if z == 0:
            if y == 0: t = "NOP"
            elif y == 1: t = "EX AF,AF'"
            else:
                d = sd()
                tgt = (pos + d) & 0xFFFF
                info["jump"] = tgt
                if y == 2: t = f"DJNZ {h16(tgt)}"
                elif y == 3:
                    t = f"JR {h16(tgt)}"
                    info["end"] = True
                else: t = f"JR {CC[y - 4]},{h16(tgt)}"
        elif z == 1:
            t = f"LD {rp(p)},{h16(w())}" if q == 0 else f"ADD {rp(2)},{rp(p)}"
        elif z == 2:
            if p == 0: t = "LD (BC),A" if q == 0 else "LD A,(BC)"
            elif p == 1: t = "LD (DE),A" if q == 0 else "LD A,(DE)"
            elif p == 2:
                nn = w()
                t = f"LD ({h16(nn)}),{rp(2)}" if q == 0 else f"LD {rp(2)},({h16(nn)})"
            else:
                nn = w()
                t = f"LD ({h16(nn)}),A" if q == 0 else f"LD A,({h16(nn)})"
        elif z == 3: t = f"{'INC' if q == 0 else 'DEC'} {rp(p)}"
        elif z in (4, 5):
            d = sd() if (xy and y == 6) else None
            t = f"{'INC' if z == 4 else 'DEC'} {reg(y, d)}"
        elif z == 6:
            d = sd() if (xy and y == 6) else None
            t = f"LD {reg(y, d)},{h8(b())}"
        else:
            t = ["RLCA", "RRCA", "RLA", "RRA", "DAA", "CPL", "SCF", "CCF"][y]
    elif x == 1:
        if op == 0x76:
            t = "HALT"
        else:
            d = sd() if (xy and (y == 6 or z == 6)) else None
            if xy and (y == 6 or z == 6):
                dst = reg(y, d) if y == 6 else R[y]
                src = reg(z, d) if z == 6 else R[z]
            else:
                dst, src = reg(y), reg(z)
            t = f"LD {dst},{src}"
    elif x == 2:
        d = sd() if (xy and z == 6) else None
        t = f"{ALU[y]}{reg(z, d)}"
    else:
        if z == 0:
            t = f"RET {CC[y]}"
        elif z == 1:
            if q == 0: t = f"POP {xy if (xy and p == 2) else RP2[p]}"
            else:
                t = ["RET", "EXX", f"JP ({rp(2)})", f"LD SP,{rp(2)}"][p]
                if p in (0, 2):
                    info["end"] = True
        elif z == 2:
            nn = w()
            info["jump"] = nn
            t = f"JP {CC[y]},{h16(nn)}"
        elif z == 3:
            if y == 0:
                nn = w()
                info["jump"] = nn
                info["end"] = True
                t = f"JP {h16(nn)}"
            elif y == 2: t = f"OUT ({h8(b())}),A"
            elif y == 3: t = f"IN A,({h8(b())})"
            else: t = ["", "", "", "", f"EX (SP),{rp(2)}", "EX DE,HL", "DI", "EI"][y]
        elif z == 4:
            nn = w()
            info["call"] = nn
            t = f"CALL {CC[y]},{h16(nn)}"
        elif z == 5:
            if q == 0: t = f"PUSH {xy if (xy and p == 2) else RP2[p]}"
            else:
                nn = w()
                info["call"] = nn
                t = f"CALL {h16(nn)}"
        elif z == 6:
            t = f"{ALU[y]}{h8(b())}"
        else:
            info["call"] = y * 8
            t = f"RST {h8(y * 8)}"
    return pos - addr, t, info


def listing(mem, start: int, end: int, labels: dict[int, str] | None = None) -> str:
    out = []
    a = start
    labels = labels or {}
    while a < end:
        n, t, _ = disasm(mem, a)
        if a in labels:
            out.append(f"{labels[a]}:")
        raw = " ".join(f"{mem[(a + i) & 0xFFFF]:02X}" for i in range(n))
        out.append(f"  {a:04X}  {raw:<12} {t}")
        a += n
    return "\n".join(out)
