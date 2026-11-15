"""Python model of the .d80 dot-command runtime on the ZX Spectrum Next.

It runs the patched MDOS 1.0 with the unmodified 48K ROM the way the Next
will after ``.d80`` has set it up:

* DivMMC automap on an opcode fetch from #0000/#0008 (NextReg #B8-#BA,
  instant), off-trap on a fetch from #1FF8-#1FFF (unmapped right after that
  opcode fetch), RETN also unmaps;
* while mapped, #0000-#1FFF is DivMMC bank 3 (MDOS A, read-only through
  MAPRAM) and #2000-#3FFF is the MDOS B bank (read/write);
* the disk image lives in 8K RAM pages; the replaced sector driver maps one
  into MMU slot 7 or 2 with the Z80N ``NEXTREG`` instructions (ED 91/ED 92).

It also checks the invariants the design relies on:

* the 48K ROM is never written (writes are ignored, as on the real ROM);
* no code accesses the WD2797 / Didaktik ports any more;
* writes into the MDOS ROM area are counted (they hit read-only bank 3 or
  the patched code in bank MDB);
* with an ``SpiSdCard`` (the -w option) the SPI ports #E7/#EB reach a model
  SD card; every card write must land inside the image's extents;
* page-outs through MDOS #1700 (user code leaving MDOS, handled by the
  RST #38 at #1700) are counted in ``user_pageouts``;
* the DRIVE button (``press_snap``) raises the DivMMC NMI when NextReg #06
  bit 4 is set, even while DivMMC is mapped (as in zxnext.vhd).  The opcode
  fetch from #0066 then automaps instantly; the NMI stays held (further
  presses are lost) until DivMMC unmaps and the button flag is clear.
"""

from __future__ import annotations

from .emu48 import INSTR_PER_FRAME, Spectrum48
from .mdospatch import PageMap, SdMap, build_pages
from .z80mini import Z80

FDC_PORTS = {0x81, 0x83, 0x85, 0x87, 0x89, 0x91, 0x99}
RETN = {0x45, 0x55, 0x65, 0x75, 0x5D, 0x6D, 0x7D}
STD_PAGES = {2: 10, 3: 11, 4: 4, 5: 5, 6: 0, 7: 1}  # 48K mode MMU slots 2..7

DEFAULT_PAGES = PageMap(image=list(range(0x40, 0x40 + 104)),
                        image_b=list(range(0x12, 0x40)) + list(range(0xA8, 0xE0)))


class InvariantError(Exception):
    pass


class SpiSdCard:
    """An SD card in SPI mode behind the Next ports #E7 (chip select) and #EB.

    Only CMD17 (read block) and CMD24 (write block) are needed; NextZXOS has
    initialised the card already.  ``pipelined`` selects how a read of port
    #EB behaves: True returns the byte of the previous exchange (and starts a
    new one), False returns the byte of the exchange the read starts.  The
    driver must work with both.
    """

    def __init__(self, data: bytearray, block_addr: bool = True, card: int = 0,
                 pipelined: bool = False, write_protect: bool = False) -> None:
        self.data = data
        self.block_addr = block_addr
        self.cs_value = 0xFD if card else 0xFE
        self.pipelined = pipelined
        self.write_protect = write_protect
        self.selected = False
        self.cmd: list[int] = []
        self.out: list[int] = []
        self.rx: list[int] | None = None    # CMD24 data being received
        self.wr_sector = 0
        self.last = 0xFF
        self.writes: list[int] = []
        self.reads: list[int] = []

    def chip_select(self, v: int) -> None:
        self.selected = v == self.cs_value
        if not self.selected:
            self.cmd, self.out, self.rx = [], [], None

    def _sector(self, arg: int) -> int:
        if self.block_addr:
            return arg
        if arg % 512:
            raise InvariantError(f"unaligned byte address {arg:#x}")
        return arg // 512

    def exchange(self, b: int) -> int:
        if not self.selected:
            return 0xFF
        reply = self.out.pop(0) if self.out else 0xFF
        if self.rx is not None:                 # CMD24: token, data, CRC
            if not self.rx and b == 0xFF and len(self.cmd) == 0:
                return reply
            self.rx.append(b)
            if self.rx[0] != 0xFE:
                raise InvariantError(f"bad start token {self.rx[0]:#x}")
            if len(self.rx) == 1 + 512 + 2:
                if self.write_protect:
                    self.out = [0xFF, 0x0D]     # write error
                else:
                    s = self.wr_sector
                    self.data[s * 512:(s + 1) * 512] = bytes(self.rx[1:513])
                    self.writes.append(s)
                    self.out = [0xFF, 0x05, 0x00, 0x00, 0x00]
                self.rx = None
            return reply
        if self.cmd or (b & 0xC0) == 0x40:
            self.cmd.append(b)
            if len(self.cmd) == 6:
                c, arg = self.cmd[0] & 0x3F, int.from_bytes(bytes(self.cmd[1:5]), "big")
                self.cmd = []
                if c == 17:
                    s = self._sector(arg)
                    self.reads.append(s)
                    self.out = [0xFF, 0x00, 0xFF, 0xFE, *self.data[s * 512:(s + 1) * 512], 0x12, 0x34]
                elif c == 24:
                    self.wr_sector = self._sector(arg)
                    self.out = [0xFF, 0x00]
                    self.rx = []
                else:
                    self.out = [0xFF, 0x04]     # illegal command
        return reply

    def port_out(self, port: int, v: int) -> None:
        if port & 0xFF == 0xE7:
            self.chip_select(v)
        elif port & 0xFF == 0xEB:
            self.last = self.exchange(v)

    def port_in(self, port: int) -> int:
        if self.pipelined:
            v, self.last = self.last, self.exchange(0xFF)
            return v
        self.last = self.exchange(0xFF)
        return self.last


class NextZ80(Z80):
    """Z80 with the 48K ROM, DivMMC automap and MMU slots 2..7 (NEXTREG ED 91/92)."""

    def __init__(self, rom48: bytes, mda: bytearray, mdb: bytearray,
                 pages: dict[int, bytearray], ram: bytearray) -> None:
        super().__init__(ram)
        self.rom48 = rom48
        self.mda, self.mdb = mda, mdb
        self.pages = pages
        self.mmu = dict(STD_PAGES)
        self.mapped = False
        self.unmap_after_fetch = False
        self.rom_writes = 0
        self.mdos_rom_writes: list[tuple[int, int]] = []
        self.nr06 = 0
        self.button_nmi = False         # divmmc.vhd button_nmi
        self.nmi_active = False         # zxnext.vhd nmi_divmmc (until the hold ends)

    def _page(self, a):
        """Return (buffer, offset) for an address in slots 2..7."""
        slot = a >> 13
        p = self.mmu[slot]
        if p == STD_PAGES[slot]:
            return self.m, a
        return self.pages[p], a & 0x1FFF

    def rd(self, a):
        a &= 0xFFFF
        if a < 0x2000:
            return self.mda[a] if self.mapped else self.rom48[a]
        if a < 0x4000:
            return self.mdb[a - 0x2000] if self.mapped else self.rom48[a]
        buf, off = self._page(a)
        return buf[off]

    def wr(self, a, v):
        a &= 0xFFFF
        if a < 0x4000:
            if not self.mapped:
                self.rom_writes += 1            # ignored, as on the real ROM
            elif a < 0x2000:
                self.mdos_rom_writes.append((self.pc, a))   # bank 3 is read-only
            else:
                if a < 0x3800 and not 0x2600 <= a < 0x2900:   # driver data
                    self.mdos_rom_writes.append((self.pc, a))
                self.mdb[a - 0x2000] = v & 0xFF
            return
        buf, off = self._page(a)
        buf[off] = v & 0xFF

    def rd16(self, a):
        return self.rd(a) | (self.rd(a + 1) << 8)

    def fetch(self):
        v = self.rd(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        if self.unmap_after_fetch:
            # off-trap: the opcode comes from DivMMC, everything after it from
            # normal memory (automap_held drops when MREQ goes high again)
            self.unmap_after_fetch = False
            self.mapped = False
        return v

    def nmi(self) -> None:
        """DivMMC NMI from the DRIVE button (call at an instruction boundary)."""
        if self.halted:
            self.halted = False
            self.pc = (self.pc + 1) & 0xFFFF
        self.iff1 = 0
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        self.push(self.pc)
        self.pc = 0x0066

    def step(self):
        pc = self.pc
        if not self.mapped and (pc in (0x0000, 0x0008) or (pc == 0x0066 and self.button_nmi)):
            self.mapped = True                  # instant automap
        if self.mapped:
            self.button_nmi = False             # cleared once automap is held
        if self.mapped and 0x1FF8 <= pc <= 0x1FFF:
            self.unmap_after_fetch = True
        retn = self.mapped and self.rd(pc) == 0xED and self.rd(pc + 1) in RETN
        super().step()
        if retn:
            self.mapped = False
            self.button_nmi = False
        if self.nmi_active and not self.mapped and not self.button_nmi:
            self.nmi_active = False             # divmmc_nmi_hold dropped: S_NMI_END

    def exec_ed(self):
        op = self.rd(self.pc)
        if op in (0x91, 0x92):
            self.pc = (self.pc + 1) & 0xFFFF
            reg = self.fetch()
            val = self.fetch() if op == 0x91 else self.a
            self.nextreg(reg, val)
            return
        return super().exec_ed()

    def nextreg(self, reg: int, val: int) -> None:
        if reg == 0x06:
            self.nr06 = val
            return
        slot = reg - 0x50
        if slot in (2, 6, 7) and (val == STD_PAGES[slot] or val in self.pages):
            self.mmu[slot] = val
        else:
            raise InvariantError(f"unexpected NEXTREG {reg:#x},{val:#x} at pc={self.pc:#06x}")


class DidaktikNext(Spectrum48):
    """48K Spectrum + Didaktik 80 as the .d80 dot command sets it up."""

    def __init__(self, mdos_rom: bytes, rom48: bytes, image: bytes,
                 pages: PageMap = DEFAULT_PAGES, sd: SdMap | None = None,
                 card: SpiSdCard | None = None, image_b: bytes | None = None,
                 sd_b: SdMap | None = None) -> None:
        if len(rom48) != 16384:
            raise ValueError("48K ROM must be 16384 bytes")
        self.pagemap = pages
        self.mem = bytearray(0x10000)
        built = build_pages(mdos_rom, image, pages, sd=sd, image_b=image_b, sd_b=sd_b,
                            rom48=rom48)
        self.sd, self.sd_b, self.card = sd, sd_b, card
        self.n_secs, self.n_secs_b = built.n_secs, built.n_secs_b
        self.cpu = NextZ80(rom48, built.mda, built.mdb, built.image_pages, self.mem)
        self.cpu.halt_di_error = False
        self.cpu.port_in = self.port_in
        self.cpu.port_out = self.port_out
        self.cpu.pc = 0
        self.cpu.sp = 0x5B00            # the dot command starts with SP in RAM
        self.cpu.im = 0
        self.hung = False
        self.pressed: set[str] = set()
        self.tape: list[bytes] = []
        self.tape_pos = 0
        self.frames = 0
        self.loaded_blocks = 0
        self.fdc_access: list[tuple[int, int]] = []
        self.user_pageouts = 0
        # press SNAP when PC reaches each (address, force) in turn; force: as if
        # pressed just before NextReg #06 changed (see press_snap)
        self.snap_at: list[tuple[int, bool]] = []
        self.snap_results: list[bool] = []
        self.snaps = 0                      # NMIs the button actually raised
        self.nr_select = 0                  # port #243B
        self.drive_release = 0              # CPU step at which DRIVE is let go

    def port_in(self, port: int) -> int:
        if port & 0xFFFF == 0x253B:
            if self.nr_select == 0x10:          # bit 1: DRIVE button held
                return 0x02 if self.cpu.steps < self.drive_release else 0x00
            raise InvariantError(f"NextReg {self.nr_select:#x} read at pc={self.cpu.pc:#06x}")
        if port & 0xFF in FDC_PORTS:
            self.fdc_access.append((self.cpu.pc, port))
        if self.card is not None and port & 0xFF == 0xEB:
            return self.card.port_in(port)
        return super().port_in(port)

    def port_out(self, port: int, v: int) -> None:
        if port & 0xFFFF == 0x243B:
            self.nr_select = v
            return
        if port & 0xFF in FDC_PORTS:
            self.fdc_access.append((self.cpu.pc, port))
        if self.card is not None and port & 0xFF in (0xE7, 0xEB):
            if self.cpu.iff1:
                raise InvariantError(f"SD access with interrupts on at pc={self.cpu.pc:#06x}")
            self.card.port_out(port, v)

    def card_image(self, drive: int = 0) -> bytes:
        """Image file A: (drive 0) or B: as it is on the model card (through its extents)."""
        unit = 1 if self.card.block_addr else 512
        sd, n_secs = (self.sd, self.n_secs) if drive == 0 else (self.sd_b, self.n_secs_b)
        out = b""
        for addr, n in sd.extents:
            s = addr // unit
            out += bytes(self.card.data[s * 512:(s + n) * 512])
        return out[:n_secs * 512]

    def press_snap(self, force: bool = False, hold: int = 50) -> bool:
        """Press the DRIVE button now.  Returns True if it raised the NMI.

        hotkey_drive is an edge: a press while NextReg #06 bit 4 is clear or
        while an NMI is still held is lost.  ``force`` ignores bit 4: the NMI
        was latched just before the instruction that cleared it (race test)."""
        c = self.cpu
        if not (force or c.nr06 & 0x10) or c.nmi_active:
            return False
        self.drive_release = c.steps + hold    # held for this many CPU steps
        c.nmi_active = c.button_nmi = True
        c.nmi()
        self.snaps += 1
        return True

    @property
    def mdos_paged(self) -> bool:
        return self.cpu.mapped

    def image_bytes(self, drive: int = 0) -> bytes:
        """The RAM copy of image A: (drive 0) or B: (shows what MDOS wrote)."""
        pages = self.cpu.pages
        if drive == 0:
            plist, n_secs = self.pagemap.image, self.n_secs
        else:
            plist, n_secs = self.pagemap.image_b, self.n_secs_b
        n = -(-n_secs // 16)
        return b"".join(bytes(pages[p]) for p in plist[:n])[:n_secs * 512]

    def screen_text(self) -> list[str]:
        """The 24x32 character screen, read back with the 48K ROM font (#3D00)."""
        font = {bytes(self.cpu.rom48[0x3D00 + i * 8:0x3D08 + i * 8]): chr(32 + i) for i in range(96)}
        rows = []
        for r in range(24):
            line = ""
            for col in range(32):
                base = 0x4000 | ((r & 0x18) << 8) | ((r & 7) << 5) | col
                cell = bytes(self.mem[base + k * 256] for k in range(8))
                line += font.get(cell) or font.get(bytes(255 - b for b in cell), "?")
            rows.append(line.rstrip())
        return rows

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
                if c.mapped and c.pc == 0x1700:
                    self.user_pageouts += 1
                if self.snap_at and c.pc == self.snap_at[0][0]:
                    self.snap_results.append(self.press_snap(self.snap_at.pop(0)[1]))
                if any(c.mmu[s] != STD_PAGES[s] for s in (2, 6, 7)):
                    if c.iff1:
                        raise InvariantError(f"image page mapped with interrupts on at pc={c.pc:#06x}")
                c.step()
            c.interrupt()
            self.frames += 1
