"""MDOS snapshot (type S) files -> .z80 / .sna.

An MDOS snapshot is a memory dump of 0x3F80..0xFFFF (49280 bytes): the top
128 bytes of the D40/D80's 2K RAM, then the 48K Spectrum RAM. The NMI handler
(MDOS 2.1 source, label ``NMI``) stores the interrupted program's SP at 0x3FFE
and pushes its registers below it:

    0x3FFC AF   0x3FFA BC   0x3FF8 DE   0x3FF6 HL
    0x3FF4 AF'  0x3FF2 BC'  0x3FF0 DE'  0x3FEE HL'
    0x3FEC IX   0x3FEA IY   0x3FE8 F/I from ``LD A,I`` (P/V = IFF2)

The PC is on the program's own stack, as in the .sna format. On restore
(``RUNSNAP2``) MDOS uses IM 1 when I == 0x3F, otherwise IM 2.

Shorter files are packed with SNAPSHOT-PACKER (R. Kralovic, 1992). They
contain a fake register block whose PC points to a self-extracting stub at
the end of the file. The stub returns to BASIC, then copies the real register
block to 0x3F80, moves the data and runs a backward RLE depacker from D40 RAM,
and finally jumps to the MDOS restore routine. :func:`unpack` runs the
part after BASIC in a small Z80 interpreter and stops at the jump into ROM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .z80mini import Z80, Trap, Z80Error

SNAP_BASE = 0x3F80
SNAP_SIZE = 0x10000 - SNAP_BASE  # 49280
RAM_BASE = 0x4000
D40_RAM_BASE = 0x3800

# Start of the SNAPSHOT-PACKER stage that runs after BASIC:
#   DI ; LD SP,nn ; LD HL,nn ; LD DE,#3F80 ; LD BC,#0080 ; LDIR
PACKER_STAGE = re.compile(rb"\xF3\x31..\x21..\x11\x80\x3F\x01\x80\x00\xED\xB0", re.S)


class SnapshotError(Exception):
    pass


@dataclass
class Snapshot:
    ram: bytes  # 49152 bytes, 0x4000..0xFFFF
    a: int; f: int; bc: int; de: int; hl: int
    a_: int; f_: int; bc_: int; de_: int; hl_: int
    ix: int; iy: int; sp: int; i: int
    iff: bool
    im: int
    r: int = 0
    packed: bool = False

    @property
    def pc(self) -> int:
        return self._mem16(self.sp)

    def _mem16(self, addr: int) -> int:
        def b(a):
            a &= 0xFFFF
            return self.ram[a - RAM_BASE] if a >= RAM_BASE else 0
        return b(addr) | (b(addr + 1) << 8)

    @property
    def border(self) -> int:
        return (self.ram[0x5C48 - RAM_BASE] >> 3) & 7  # BORDCR system variable

    def to_sna(self) -> bytes:
        def w(v): return bytes([v & 0xFF, (v >> 8) & 0xFF])
        hdr = bytes([self.i]) + w(self.hl_) + w(self.de_) + w(self.bc_) + bytes([self.f_, self.a_]) \
            + w(self.hl) + w(self.de) + w(self.bc) + w(self.iy) + w(self.ix) \
            + bytes([0x04 if self.iff else 0x00, self.r & 0xFF, self.f, self.a]) \
            + w(self.sp) + bytes([self.im, self.border])
        assert len(hdr) == 27
        return hdr + self.ram

    def to_z80(self) -> bytes:
        """Version 1 .z80 file, uncompressed, with PC taken from the stack."""
        def w(v): return bytes([v & 0xFF, (v >> 8) & 0xFF])
        pc, sp = self.pc, (self.sp + 2) & 0xFFFF
        flags1 = ((self.r >> 7) & 1) | (self.border << 1)  # bit 5 = 0: not compressed
        hdr = bytes([self.a, self.f]) + w(self.bc) + w(self.hl) + w(pc) + w(sp) \
            + bytes([self.i, self.r & 0x7F, flags1]) + w(self.de) + w(self.bc_) + w(self.de_) \
            + w(self.hl_) + bytes([self.a_, self.f_]) + w(self.iy) + w(self.ix) \
            + bytes([1 if self.iff else 0, 1 if self.iff else 0, self.im & 3])
        assert len(hdr) == 30
        return hdr + self.ram


def _from_memory(mem: bytes | bytearray, packed: bool) -> Snapshot:
    def w(a): return mem[a] | (mem[a + 1] << 8)
    flags_i = w(0x3FE8)
    i, f_from_ld_a_i = flags_i >> 8, flags_i & 0xFF
    return Snapshot(
        ram=bytes(mem[RAM_BASE:0x10000]),
        a=mem[0x3FFD], f=mem[0x3FFC], bc=w(0x3FFA), de=w(0x3FF8), hl=w(0x3FF6),
        a_=mem[0x3FF5], f_=mem[0x3FF4], bc_=w(0x3FF2), de_=w(0x3FF0), hl_=w(0x3FEE),
        ix=w(0x3FEC), iy=w(0x3FEA), sp=w(0x3FFE), i=i,
        iff=bool(f_from_ld_a_i & 0x04),
        im=1 if i == 0x3F else 2,
        packed=packed,
    )


def unpack(data: bytes) -> bytearray:
    """Run the SNAPSHOT-PACKER stub, return the 64K memory image."""
    mem = bytearray(0x10000)
    mem[SNAP_BASE:SNAP_BASE + len(data)] = data
    m = PACKER_STAGE.search(bytes(mem), SNAP_BASE + 128)
    if not m:
        raise SnapshotError("short snapshot without a known depacker (SNAPSHOT-PACKER) stub")
    cpu = Z80(mem)
    cpu.pc = m.start()
    cpu.trap_below = D40_RAM_BASE  # anything below D40 RAM is (MDOS or Spectrum) ROM
    while True:
        try:
            cpu.run()
        except Trap as t:
            if t.kind == "call":
                # 0x0052 is a RET in the 48K ROM (used to read the return address).
                # Other MDOS ROM calls in the stub (0x0970) only set up paging;
                # emulate them as plain RET.
                cpu.pc = cpu.pop()
                continue
            # A jump into ROM ends the stub (0x034D = MDOS "run snapshot").
            break
        except Z80Error as e:
            raise SnapshotError(f"depacker failed: {e}") from e
    return mem


def parse(data: bytes) -> Snapshot:
    """Parse an MDOS snapshot file (raw or SNAPSHOT-PACKER compressed)."""
    if len(data) == SNAP_SIZE:
        mem = bytearray(0x10000)
        mem[SNAP_BASE:] = data
        return _from_memory(mem, packed=False)
    if len(data) < 256 or len(data) > SNAP_SIZE:
        raise SnapshotError(f"unexpected snapshot length {len(data)}")
    return _from_memory(unpack(data), packed=True)
