"""Tests for the .d80 dot command: patch table, FAT16 helper and the Next runtime model.

The model tests need the MDOS 1.0 ROM (emulators/roms/), a standard 48K ROM
(emulators/fuse/roms/48.rom) and the generated patch data (python
tools/build_dot.py); they are skipped otherwise. They run on the demo disk
from tools/demo_image.py, which is built in memory. A few regression tests
use third-party disks from emulators/images/ (not in git) when present.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from demo_image import DEMO_I, build as build_demo
from mdospatch import PATCHES, PageMap, PatchError, build_pages, check_rom
from z80mini import Z80

ROOT = Path(__file__).resolve().parents[1]
MDOS = ROOT / "emulators" / "roms" / "Didaktik_40-80_MDOS_v1_91.rom"
ROM48 = ROOT / "emulators" / "fuse" / "roms" / "48.rom"
# Didaktik BASIC ROMs from cygnus.speccy.cz (optional): file, boot frames, copyright line
DIDAKTIK_ROMS = [(ROOT / "emulators" / "roms" / f, frames, text) for f, frames, text in (
    ("Didaktik_Gama_1989.rom", 220, "1989 DIDAKTIK SKALICA"),
    ("Didaktik_M_1992.rom", 150, "1992 DIDAKTIK M BASIC"),
    ("Didaktik_Kompakt_93.rom", 150, "1993 DIDAKTIK COMPUTER"))]
IMAGE = build_demo()
SAMPLES = ROOT / "emulators" / "images"                # optional third-party disks
SDCARD = ROOT / "emulators" / "ZEsarUX" / "tbblue.mmc"
have_all = all(p.exists() for p in (MDOS, ROM48, PATCHES))



class TestR(unittest.TestCase):
    def test_r_counts_m1_cycles(self):
        mem = bytearray(0x10000)
        mem[0:6] = bytes.fromhex("00 ED5F 00".replace(" ", "")) + b"\x76"  # NOP / LD A,R / NOP / HALT
        cpu = Z80(mem)
        cpu.step()
        cpu.step()
        self.assertEqual(cpu.a, 3)                  # NOP + ED + 5F


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestPatches(unittest.TestCase):
    def setUp(self):
        self.mdos = MDOS.read_bytes()
        self.pages = PageMap(image=list(range(0x40, 0x40 + 104)))

    def test_rom_checks(self):
        with self.assertRaises(PatchError):
            check_rom(self.mdos[:-1] + bytes([self.mdos[-1] ^ 1]), 0x545531FA, 14336, "MDOS")
        with self.assertRaises(PatchError):
            build_pages(self.mdos, b"\x00" * 1000, self.pages)

    def test_patched_bytes(self):
        import json
        b = build_pages(self.mdos, IMAGE, self.pages)
        page_out = json.loads(PATCHES.read_text())["symbols"]["page_out_j"] - 4
        self.assertEqual(b.mda[0x005D:0x0060], bytes([0xC3]) + page_out.to_bytes(2, "little"))
        self.assertEqual(b.mdb[page_out - 0x2000:page_out - 0x2000 + 7],     # SNAP on, JP #1FF8
                         bytes([0xED, 0x91, 0x06, 0x10, 0xC3, 0xF8, 0x1F]))
        self.assertEqual(b.mda[0x1FF8], 0xC9)                                # RET in the off-trap
        self.assertEqual(b.mda[0x1700], 0xFF)                                # RST #38 catch-all
        self.assertEqual(b.mda[0x0000], 0xC3)                                # JP snap_entry0
        self.assertEqual(b.mda[0x0008:0x000C], self.mdos[0x0008:0x000C])     # LD HL,(CH_ADD) kept
        self.assertEqual(b.mda[0x000B], 0xC3)                                # JP snap_entry8
        self.assertEqual(b.mda[0x0066], 0xC7)                                # NMI: RST 0 (SNAP)
        self.assertEqual(b.mda[0x0068:0x0080], self.mdos[0x0068:0x0080])     # snapshot code untouched
        self.assertEqual(b.n_secs, 1440)
        self.assertEqual(len(b.image_pages), 90)
        self.assertEqual(b.mdb[0x0800:0x0802], (1440).to_bytes(2, "little"))
        self.assertEqual(b.mdb[0x0804:0x0806], bytes([0x40, 0x41]))          # page table

    def test_build_is_rom_free(self):
        """patches.json must not carry long runs of the copyrighted ROM."""
        import json
        data = json.loads(PATCHES.read_text())
        for recs in data["images"].values():
            for off, hx in recs:
                self.assertLess(len(hx) // 2, 512, f"suspiciously long patch at {off:#x}")


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestNextModel(unittest.TestCase):
    def test_cat_lists_directory(self):
        from nextmmu import DidaktikNext
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE)
        m.run_frames(100)
        self.assertIn("1982 Sinclair Research Ltd", m.screen_text()[-1])
        m.type_keys([["CAPS", "SYM"], ["SYM", "9"], ["ENTER"]])     # CAT
        m.run_frames(60)
        text = m.screen_text()
        self.assertIn("Directory of D80 Demo", text)
        self.assertTrue(any(t.startswith("P run") and t.endswith("RWED") for t in text))
        self.assertEqual(m.fdc_access, [])
        self.assertEqual(m.cpu.mdos_rom_writes, [])
        self.assertEqual(m.cpu.rom_writes, 0)
        self.assertFalse(m.mdos_paged)


SAVE_TEST = [["S"], ["SYM", "B"], ["SYM", "P"], ["T"], ["E"], ["S"], ["T"], ["SYM", "P"],
             ["CAPS", "SYM"], ["I"], ["1"], ["6"], ["3"], ["8"], ["4"], ["SYM", "N"],
             ["6"], ["9"], ["1"], ["2"], ["ENTER"]]          # SAVE *"test" CODE 16384,6912


CAT = [["CAPS", "SYM"], ["SYM", "9"], ["ENTER"]]
FORMAT_TESTIK = [["CAPS", "SYM"], ["SYM", "0"], ["SYM", "P"], ["A"], ["SYM", "Z"],   # FORMAT "a:testik"
                 ["T"], ["E"], ["S"], ["T"], ["I"], ["K"], ["SYM", "P"], ["ENTER"]]
D80_BIN = ROOT / "dot" / "build" / "D80"
D80_SYM = ROOT / "dot" / "build" / "d80.sym"


@unittest.skipUnless(have_all and all(r.exists() for r, _, _ in DIDAKTIK_ROMS),
                     "Didaktik ROMs not present")
class TestDidaktikRom(unittest.TestCase):
    """Didaktik Gama/M/Kompakt ROMs in place of the 48K ROM, as with .d80 -4 rom."""

    def test_romcompat(self):
        from romcompat import check, ranges
        deps = ranges([MDOS.read_bytes()])
        for rom, _, _ in DIDAKTIK_ROMS:
            self.assertEqual(check(ROM48.read_bytes(), rom.read_bytes(), deps), [], rom.name)

    def test_known_crc(self):
        import zlib
        from mdospatch import ROMS16
        for rom, _, _ in DIDAKTIK_ROMS:
            self.assertIn(zlib.crc32(rom.read_bytes()), ROMS16, rom.name)

    def test_cat_and_save(self):
        from image import MdosImage
        from nextmmu import DidaktikNext
        for rom, frames, text in DIDAKTIK_ROMS:
            with self.subTest(rom.name):
                m = DidaktikNext(MDOS.read_bytes(), rom.read_bytes(), IMAGE)
                m.run_frames(frames)                        # Didaktik ROMs boot slower
                self.assertIn(text, m.screen_text()[-1])
                m.type_keys(CAT)
                m.run_frames(60)
                self.assertIn("Directory of D80 Demo", m.screen_text())
                m.type_keys([["SPACE"]])                    # scroll? -> no
                m.run_frames(20)
                m.type_keys(SAVE_TEST)
                m.run_frames(150)
                names = [e.raw_name.rstrip(bytes(1)) for e in MdosImage(bytes(m.image_bytes(0))).entries()]
                self.assertIn(b"test", names)
                self.assertEqual(m.cpu.mdos_rom_writes, [])
                self.assertFalse(m.mdos_paged)


class TestBlank(unittest.TestCase):
    """-n / tools/new_image.py: a blank image as MDOS 1.0 FORMAT writes it."""

    def test_layout(self):
        from image import MdosImage, blank_image
        b = blank_image("NoNameDisk", bytes([0x25, 0x25]))
        im = MdosImage(b)
        self.assertEqual(len(b), 737280)
        self.assertEqual((im.tracks, im.sectors_per_track, im.sides), (80, 9, 2))
        self.assertEqual(im.entries(), [])
        self.assertEqual(im.disk_name, "NoNameDisk")
        self.assertEqual([im.fat(n) for n in (0, 13)], [0xDDD, 0xDDD])
        self.assertTrue(all(im.fat(n) == 0 for n in range(14, 1440)))
        self.assertTrue(all(im.fat(n) == 0xDDD for n in range(1440, 1705)))
        kompakt = SAMPLES / "036-KOMPAKT.d80"
        if kompakt.exists():                    # formatted by MDOS, same disk id
            self.assertEqual(b[:512], kompakt.read_bytes()[:512])

    def test_layout_d40(self):
        from image import MdosImage, blank_image
        b = blank_image("Small", tracks=40)
        im = MdosImage(b)
        self.assertEqual(len(b), 368640)                    # 360K
        self.assertEqual((im.tracks, im.sectors_per_track, im.sides), (40, 9, 2))
        self.assertEqual(im.entries(), [])
        self.assertTrue(all(im.fat(n) == 0 for n in range(14, 720)))
        self.assertTrue(all(im.fat(n) == 0xDDD for n in list(range(14)) + list(range(720, 1705))))

    @unittest.skipUnless(D80_BIN.exists() and D80_SYM.exists(), "dot command not built")
    def test_dot_command_writes_the_same(self):
        """blank_sector in the dot command, run in the Z80 model, gives the
        same sectors as blank_image (apart from the random disk id)."""
        from image import blank_image
        sym = {}
        for line in D80_SYM.read_text().splitlines():
            name, _, val = line.partition(": EQU ")
            if val:
                sym[name] = int(val, 16)
        for path, name, tracks in (("c:/d80/My Disk.d80", "My Disk", 80),
                                   ("verylongdiskname.d80", "verylongdi", 80),
                                   ("/x/.d80", "NoNameDisk", 80), ("new", "new", 80),
                                   ("c:/d80/Small.D40", "Small", 40)):
            mem = bytearray(0x10000)
            dot = D80_BIN.read_bytes()
            mem[0x2000:0x2000 + len(dot)] = dot
            raw = path.encode() + b"\0"
            mem[sym["name_img"]:sym["name_img"] + len(raw)] = raw
            mem[sym["blk_d40"]] = tracks == 40          # (set by make_blank)
            ref = blank_image(name, tracks=tracks)
            for sec in list(range(16)) + [tracks * 18 - 1]:
                cpu = Z80(mem)
                cpu.sp = 0xFF00
                cpu.push(0x0000)                # return to a HALT at 0
                mem[0] = 0x76
                cpu.pc, cpu.h, cpu.l = sym["blank_sector"], sec >> 8, sec & 0xFF
                while cpu.pc != 0:
                    cpu.step()
                got = bytearray(mem[sym["sd_buf"]:sym["sd_buf"] + 512])
                want = bytearray(ref[sec * 512:(sec + 1) * 512])
                if sec == 0:
                    got[202:204] = want[202:204] = b"??"
                self.assertEqual(got, want, f"{path}: sector {sec}")

    @unittest.skipUnless(D80_BIN.exists() and D80_SYM.exists() and MDOS.exists() and ROM48.exists(),
                         "dot command or ROMs not present")
    def test_dot_command_crc(self):
        """crc_init + crc_add (table-driven) in the Z80 model give zlib's CRC32,
        also when the data comes in several pieces (as read_page adds it)."""
        import time
        import zlib
        sym = {}
        for line in D80_SYM.read_text().splitlines():
            name, _, val = line.partition(": EQU ")
            if val:
                sym[name] = int(val, 16)
        for data, pieces in ((MDOS.read_bytes(), (0x2000, 0x1800)),
                             (ROM48.read_bytes(), (0x2000, 0x2000)), (b"123456789", (9,))):
            mem = bytearray(0x10000)
            dot = D80_BIN.read_bytes()
            mem[0x2000:0x2000 + len(dot)] = dot
            mem[0x8000:0x8000 + len(data)] = data
            mem[0] = 0x76

            def call(addr, hl=0, bc=0):
                cpu = Z80(mem)
                cpu.sp = 0xFF00
                cpu.push(0x0000)
                cpu.pc, cpu.hl, cpu.bc = addr, hl, bc
                while cpu.pc != 0:
                    cpu.step()
                return cpu.steps
            call(sym["crc_init"])
            pos, steps = 0x8000, 0
            for n in pieces:
                steps += call(sym["crc_add"], pos, n)
                pos += n
            got = int.from_bytes(mem[sym["crc"]:sym["crc"] + 4], "little") ^ 0xFFFFFFFF
            self.assertEqual(got, zlib.crc32(data), data[:4])
            if len(data) > 100:
                self.assertLess(steps / len(data), 25)      # instructions per byte

    @unittest.skipUnless(D80_BIN.exists() and D80_SYM.exists(), "dot command not built")
    def test_dot_command_rom48_known(self):
        """rom48_known accepts exactly the 16K ROMs in mdospatch.ROMS16."""
        from mdospatch import ROMS16
        sym = {}
        for line in D80_SYM.read_text().splitlines():
            name, _, val = line.partition(": EQU ")
            if val:
                sym[name] = int(val, 16)
        for crc in (*ROMS16, 0x545531FA, 0x98B1320B, 0):
            mem = bytearray(0x10000)
            dot = D80_BIN.read_bytes()
            mem[0x2000:0x2000 + len(dot)] = dot
            mem[sym["crc"]:sym["crc"] + 4] = (crc ^ 0xFFFFFFFF).to_bytes(4, "little")
            mem[0] = 0x76
            cpu = Z80(mem)
            cpu.sp = 0xFF00
            cpu.push(0x0000)
            cpu.pc = sym["rom48_known"]
            while cpu.pc != 0:
                cpu.step()
            self.assertEqual(bool(cpu.f & 0x40), crc in ROMS16, f"{crc:08X}")

    @unittest.skipUnless(D80_BIN.exists() and D80_SYM.exists(), "dot command not built")
    def test_dot_command_progress_bar(self):
        """bar_init + bar_step: the bar fills cell by cell and is full after
        exactly the given number of steps."""
        sym = {}
        for line in D80_SYM.read_text().splitlines():
            name, _, val = line.partition(": EQU ")
            if val:
                sym[name] = int(val, 16)
        # img_steps: the bar length by extension, *.d40 = 360K
        for path, steps in (("c:/d80/game.d40", 45), ("GAME.D40", 45), ("./dir/x.D40", 45),
                            ("/d80/021.D80", 90), ("noext", 90), ("a.d40x/b.d80", 90)):
            mem = bytearray(0x10000)
            dot = D80_BIN.read_bytes()
            mem[0x2000:0x2000 + len(dot)] = dot
            raw = path.encode() + b"\0"
            mem[sym["name_img"]:sym["name_img"] + len(raw)] = raw
            mem[0] = 0x76
            cpu = Z80(mem)
            cpu.sp = 0xFF00
            cpu.push(0x0000)
            cpu.pc = sym["img_steps"]
            while cpu.pc != 0:
                cpu.step()
            self.assertEqual(cpu.a, steps, path)

        row, col, width = 9, sym["BAR_C"], sym["BAR_W"]

        def cells(mem):
            """filled cells: pixel line 3 of each bar cell is #FF"""
            base = 0x4000 | ((row & 0x18) << 8) | ((row & 7) << 5)
            return sum(mem[base + 3 * 256 + col + i] == 0xFF for i in range(width))

        for total in (90, 45, 7, 104):
            mem = bytearray(0x10000)
            dot = D80_BIN.read_bytes()
            mem[0x2000:0x2000 + len(dot)] = dot
            mem[sym["line"]] = row
            mem[0] = 0x76

            def call(addr, a=0):
                cpu = Z80(mem)
                cpu.sp = 0xFF00
                cpu.push(0x0000)
                cpu.pc, cpu.a = addr, a
                while cpu.pc != 0:
                    cpu.step()
            call(sym["bar_init"], total)
            self.assertEqual(cells(mem), 0)
            base = 0x4000 | ((row & 0x18) << 8) | ((row & 7) << 5)
            top = base + 256                                          # pixel line 1
            self.assertEqual(bytes(mem[top + col:top + col + width]), b"\xFF" * width)
            self.assertEqual(bytes(mem[base + col:base + col + width]), bytes(width))  # gap
            seen = []
            for _ in range(total):
                call(sym["bar_step"])
                seen.append(cells(mem))
            self.assertEqual(seen, sorted(seen))                     # never goes back
            self.assertEqual(seen[-1], width, total)                  # full at the end
            self.assertEqual(seen[total // 2 - 1], width * (total // 2) // total)

    @unittest.skipUnless(have_all, "ROMs or patches.json not present")
    def test_mdos_uses_blank_image(self):
        from image import MdosImage, blank_image
        t = TestSdWrite()
        m = t.machine(image=blank_image("Empty"))       # with -w
        m.type_keys(CAT)
        m.run_frames(60)
        text = [s for s in m.screen_text() if s.strip()]
        self.assertIn("Directory of Empty", text)
        self.assertEqual(text[-1], "0 OK, 0:1")
        m.type_keys(SAVE_TEST)
        m.run_frames(150)
        self.assertEqual([s for s in m.screen_text() if s.strip()][-1], "0 OK, 0:1")
        im = MdosImage(m.image_bytes())
        self.assertEqual([(e.name.strip(), e.type, e.length) for e in im.entries()],
                         [("test", "B", 6912)])
        self.assertIsNone(im.check(im.entries()[0]))
        t.check_card(m)



def snapshots(m):
    from image import MdosImage
    img = MdosImage(m.image_bytes())
    return {e.name.strip(): img.read(e) for e in img.entries() if e.type == "S"}


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestSnap(unittest.TestCase):
    """The DRIVE button (DivMMC NMI) as the Didaktik SNAP button."""

    running = None

    @classmethod
    def demo(cls):
        """A machine running the IM 2 demo (RUN menu, key A), built once."""
        import copy
        from nextmmu import DidaktikNext
        if cls.running is None:
            m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE)
            m.run_frames(150)
            m.type_keys([["R"], ["ENTER"]])
            m.run_frames(300)
            m.type_keys([["A"]])
            m.run_frames(500)
            cls.running = m
        return copy.deepcopy(cls.running)

    def check_clean(self, m):
        c = m.cpu
        self.assertFalse(c.mapped)
        self.assertFalse(c.nmi_active)
        self.assertEqual(c.nr06, 0x10)                      # SNAP enabled again
        self.assertEqual(c.mdos_rom_writes, [])
        self.assertFalse(m.hung)

    def test_snap_saves_running_program(self):
        m = self.demo()
        c = m.cpu
        self.assertEqual((c.im, c.i), (2, DEMO_I))            # the game is running
        for _ in range(3000):                               # somewhere inside a frame
            c.step()
        regs = dict(a=c.a, f=c.f, bc=c.bc, de=c.de, hl=c.hl, a_=c.a_, f_=c.f_,
                    bc_=(c.b_ << 8) | c.c_, de_=(c.d_ << 8) | c.e_, hl_=(c.h_ << 8) | c.l_,
                    ix=c.ix, iy=c.iy, i=c.i)
        pc, sp, iff, ram = c.pc, c.sp, bool(c.iff1), bytes(m.mem[0x4000:])
        self.assertTrue(m.press_snap())
        self.assertFalse(m.press_snap())                    # held: a second press is lost
        m.run_frames(300)
        self.check_clean(m)
        snaps = snapshots(m)
        self.assertEqual(list(snaps), ["SNAPSHOT00"])
        self.assertEqual(len(snaps["SNAPSHOT00"]), 49280)

        from snapshot import parse
        s = parse(snaps["SNAPSHOT00"])
        for k, v in regs.items():
            self.assertEqual(getattr(s, k), v, k)
        self.assertEqual((s.pc, s.sp, s.iff, s.im), (pc, (sp - 2) & 0xFFFF, iff, 2))
        low = s.sp - 8 - 0x4000                             # MDOS #0068 uses 8 bytes below SP
        self.assertEqual(s.ram[:low], ram[:low])
        self.assertEqual(s.ram[s.sp + 2 - 0x4000:], ram[s.sp + 2 - 0x4000:])

        # the game goes on, and SNAP works again
        m.run_frames(50)
        self.assertEqual((c.im, c.i), (2, DEMO_I))
        self.assertTrue(m.press_snap())
        m.run_frames(300)
        self.check_clean(m)
        self.assertEqual(sorted(snapshots(m)), ["SNAPSHOT00", "SNAPSHOT01"])

    def test_snap_takes_a_free_name(self):
        """MDOS 2.0 fix: after a reset the counter starts at 00 again. MDOS 1.0
        then overwrote SNAPSHOT00; now SNAP counts up to a free name."""
        m = self.demo()
        self.assertTrue(m.press_snap())
        m.run_frames(300)
        m.cpu.mdb[0x3E61 - 0x2000] = 0                      # the counter, as after a reset
        m.run_frames(50)
        self.assertTrue(m.press_snap())
        m.run_frames(300)
        self.check_clean(m)
        self.assertEqual(sorted(snapshots(m)), ["SNAPSHOT00", "SNAPSHOT01"])

    def test_snap_ignored_while_mdos_runs(self):
        import json
        from nextmmu import DidaktikNext
        sym = json.loads(PATCHES.read_text())["symbols"]
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE)
        m.run_frames(100)

        # CAT enters MDOS through #0008 and re-enters it through #0000 after
        # every 48K ROM call.  A plain press while MDOS reads a sector is lost
        # (NextReg #06 bit 4 is off).  NMIs latched in the race windows (entering
        # or leaving MDOS) are taken, but snap_entry0 sees MDOS paged in and
        # returns.  The Next holds further NMIs until DivMMC unmaps, so each
        # window is tested in a separate MDOS entry.
        entry0_x = sym["snap_entry0_x"]
        m.snap_at = [(0x000B, True), (0x236A, False), (sym["page_out_j"], True),
                     (entry0_x, True),                      # the NMI's own RST 0: held, lost
                     (entry0_x, True),                      # next entry through #0000
                     (sym["page_out_j"], True),             # still held: lost
                     (0x1FF8, True),                        # the same page-out: lost
                     (0x1FF8, True)]                        # a later one
        m.type_keys(CAT)
        m.run_frames(60)
        self.assertEqual(m.snap_at, [])
        self.assertEqual(m.snap_results, [True, False, True, False, True, False, False, True])
        text = m.screen_text()
        self.assertEqual(text[-1], "scroll?")
        self.assertIn("B data10         10270 ----RWED", text)  # the listing is intact
        m.type_keys([["N"]])
        m.run_frames(20)
        m.snap_at = [(sym["snap_entry8_j"], True)]
        m.type_keys(CAT)
        m.run_frames(60)
        self.assertEqual(m.snap_results[-1], True)
        self.assertEqual(m.screen_text()[-1], "scroll?")
        m.type_keys([["N"]])
        m.run_frames(20)
        self.assertEqual(m.snaps, 5)
        self.assertEqual(snapshots(m), {})
        self.assertEqual(m.fdc_access, [])
        self.check_clean(m)

    def test_snap_written_to_sd(self):
        t = TestSdWrite()
        t.setUp = None
        m = t.machine()
        m.run_frames(10)
        self.assertTrue(m.press_snap())                     # at the BASIC prompt
        m.run_frames(300)
        self.check_clean(m)
        self.assertIn("SNAPSHOT00", snapshots(m))
        t.check_card(m)
        self.assertIn("1982 Sinclair Research Ltd", m.screen_text()[-1])   # BASIC goes on


CAT_B = [["CAPS", "SYM"], ["SYM", "9"], ["SYM", "P"], ["B"], ["SYM", "Z"], ["SYM", "P"],
         ["ENTER"]]                                    # CAT "b:"
CAT_A = CAT_B[:3] + [["A"]] + CAT_B[4:]                # CAT "a:"
SAVE_B = SAVE_TEST[:3] + [["B"], ["SYM", "Z"]] + SAVE_TEST[3:]   # SAVE *"b:test" CODE ...
LOAD_B = [["J"]] + SAVE_B[1:]                          # LOAD *"b:test" CODE 16384,6912


def lines(m):
    return [t for t in m.screen_text() if t.strip()]


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestMdos20Fixes(unittest.TestCase):
    """MOVE between volumes, and the MDOS 2.0 fixes ported to the 1.0 patches."""

    def machine(self, program, free_b=None, frames=1500):
        """Boot with a "run" program on SrcDisk (A:, files data0-2 of 3000 bytes)
        and DstDisk in B: (with only free_b sectors free), RUN it."""
        from basic import tokenize
        from image import MdosImage, add_file, blank_image
        from nextmmu import DidaktikNext
        a = bytearray(blank_image("SrcDisk"))
        prog = tokenize(program)
        add_file(a, "P", "run", prog, param1=10, param2=len(prog))
        for n in range(3):
            add_file(a, "B", f"data{n}", bytes([n + 1]) * 3000, param1=0x8000)
        b = bytearray(blank_image("DstDisk"))
        if free_b is not None:
            add_file(b, "B", "filler", bytes(512 * (self.free(MdosImage(bytes(b))) - free_b)))
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), bytes(a), image_b=bytes(b))
        m.run_frames(150)
        m.type_keys([["R"], ["ENTER"]])
        m.run_frames(frames)
        return m

    @staticmethod
    def free(im):
        return sum(1 for s in range(14, im.total_sectors) if im.fat(s) == 0)

    def files(self, m, drive):
        from image import MdosImage
        im = MdosImage(m.image_bytes(drive))
        for e in im.entries():
            self.assertIsNone(im.check(e))
        return [e.name.strip() for e in im.entries()], self.free(im)

    def test_move_keeps_program_memory(self):
        """Volume names match (zero-padded disk names); MOVE no longer writes
        #C000 (MDOS 1.0 stored BC there)."""
        m = self.machine('10 POKE 49152,85: POKE 49153,170: MOVE "SrcDisk:data*","DstDisk:*"\n'
                         '20 PRINT PEEK 49152,PEEK 49153')
        self.assertEqual(lines(m), ["3 File(s) copied.", "85              170", "0 OK, 20:1"])
        self.assertEqual(self.files(m, 1), (["data0", "data1", "data2"], 1426 - 18))
        self.assertEqual(m.image_bytes(1)[192:202], b"DstDisk\0\0\0")

    def test_move_disk_full_leaves_no_entry(self):
        """MDOS 1.0 left the file that did not fit with an empty FAT chain."""
        m = self.machine('10 MOVE "SrcDisk:data*","DstDisk:*"', free_b=8)
        self.assertEqual(lines(m)[-1], "U Disk full, 10:1")
        self.assertEqual(self.files(m, 1), (["filler", "data0"], 2))

    def test_save_disk_full_leaves_no_entry(self):
        m = self.machine('10 SAVE *"DstDisk:big" CODE 32768,3000', free_b=3, frames=800)
        self.assertEqual(lines(m)[-1], "U Disk full, 10:1")
        self.assertEqual(self.files(m, 1), (["filler"], 3))


MENU_TITLE = "Swap A: and B:"                    # shown while the menu is open
HOLD = 400_000                                         # CPU steps: DRIVE held (> 0.4 s)


def regs(c):
    return (c.a, c.f, c.bc, c.de, c.hl, c.a_, c.f_, c.b_, c.c_, c.d_, c.e_, c.h_, c.l_,
            c.ix, c.iy, c.i, c.sp, c.pc, c.iff1)


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestMenu(unittest.TestCase):
    """DRIVE held (or CAPS SHIFT + DRIVE): the D80 menu."""

    def basic(self, image_b=None):
        from nextmmu import DidaktikNext
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE,
                         image_b=image_b)
        m.run_frames(100)
        return m

    def menu(self, m, keys, hold=HOLD):
        """Open the menu, check it is shown, press keys, wait until MDOS is paged out."""
        self.assertTrue(m.press_snap(hold=hold))
        m.run_frames(30)
        self.assertIn(MENU_TITLE, " ".join(m.screen_text()))
        for k in keys[:-1]:
            m.type_keys([[k]])
        m.pressed = {keys[-1]}                          # the last key: stop right after
        for _ in range(2_000_000):                      # MDOS has paged out
            m.cpu.step()
            if not m.cpu.mapped:
                break
        m.pressed = set()

    def clean(self, m, game=False):
        c = m.cpu
        self.assertFalse(c.mapped)
        self.assertFalse(c.nmi_active)
        self.assertEqual(c.nr06, 0x10)
        self.assertEqual((c.mmu[6], c.mmu[7]), (0, 1))
        self.assertEqual(c.mdos_rom_writes, [])
        if not game:                                    # a running program may use the ports
            self.assertEqual(m.fdc_access, [])

    def cat(self, m, keys=CAT):
        m.type_keys([["V"], ["ENTER"]])                 # CLS
        m.run_frames(10)
        m.type_keys(keys)
        m.run_frames(60)
        text = m.screen_text()
        if text[-1] == "scroll?":
            m.type_keys([["N"]])
            m.run_frames(10)
        return text

    def test_back_leaves_program_untouched(self):
        m = TestSnap.demo()
        c = m.cpu
        for _ in range(3000):
            c.step()
        before, state = bytes(m.mem[0x4000:]), regs(c)
        self.menu(m, ["SPACE"])
        self.assertEqual(regs(c), state)                 # back at the interrupted PC
        self.assertEqual(bytes(m.mem[0x4000:0x5B00]), before[:0x1B00])   # screen restored
        low = c.sp - 10 - 0x4000                         # NMI 2 + 8 (as MDOS #0068)
        self.assertEqual(bytes(m.mem[0x4000:0x4000 + low]), before[:low])
        self.assertEqual(bytes(m.mem[c.sp:]), before[c.sp - 0x4000:])
        self.clean(m, game=True)
        m.run_frames(50)
        self.assertEqual((c.im, c.i), (2, DEMO_I))         # the game goes on
        self.assertEqual(snapshots(m), {})

    def test_short_press_is_still_snap(self):
        m = self.basic()
        self.assertTrue(m.press_snap())
        m.run_frames(200)
        self.assertNotIn(MENU_TITLE, " ".join(m.screen_text()))
        self.assertEqual(list(snapshots(m)), ["SNAPSHOT00"])

    def test_caps_shift_opens_menu(self):
        m = self.basic()
        m.pressed = {"CAPS"}
        self.assertTrue(m.press_snap())                  # short press
        m.run_frames(10)
        m.pressed = set()
        m.run_frames(20)
        self.assertIn(MENU_TITLE, " ".join(m.screen_text()))
        m.type_keys([["SPACE"]])
        m.run_frames(5)
        self.clean(m, game=True)

    def test_snapshot_from_menu(self):
        m = TestSnap.demo()
        c = m.cpu
        for _ in range(3000):
            c.step()
        ram, pc = bytes(m.mem[0x4000:]), c.pc
        self.menu(m, ["S"])
        m.run_frames(300)
        self.clean(m, game=True)
        from snapshot import parse
        s = parse(snapshots(m)["SNAPSHOT00"])
        self.assertEqual(s.pc, pc)
        low = s.sp - 8 - 0x4000
        self.assertEqual(s.ram[:low], ram[:low])         # the screen without the menu
        self.assertEqual((c.im, c.i), (2, DEMO_I))

    def test_swap(self):
        from image import blank_image
        m = self.basic(image_b=blank_image("DiskB"))
        self.menu(m, ["X", "SPACE"])                     # hot key
        self.clean(m)
        self.assertIn("Directory of DiskB", " ".join(self.cat(m, CAT_A)))
        self.assertIn("Directory of D80 Demo", " ".join(self.cat(m, CAT_B)))
        self.menu(m, ["ENTER", "6", "6", "6", "ENTER"])  # "Swap A: and B:", then "Back"
        self.assertIn("Directory of D80 Demo", " ".join(self.cat(m, CAT_A)))
        self.assertIn("Directory of DiskB", " ".join(self.cat(m, CAT_B)))
        m.type_keys(SAVE_B)                              # B: still writable
        m.run_frames(150)
        self.assertEqual(lines(m)[-1], "0 OK, 0:1")
        self.clean(m)

    def test_cursor_keys(self):
        m = self.basic()
        self.menu(m, ["6", "6", "7", "ENTER"])           # down, down, up: "Snapshot"
        m.run_frames(200)
        self.assertEqual(list(snapshots(m)), ["SNAPSHOT00"])
        self.clean(m)

    def test_swap_into_empty_drive(self):
        m = self.basic()                                 # no image for B:
        self.menu(m, ["X", "SPACE"])
        self.assertNotIn("Directory of", " ".join(self.cat(m, CAT_A)))
        self.assertIn("Directory of D80 Demo", " ".join(self.cat(m, CAT_B)))
        self.clean(m)

    def test_reset(self):
        m = TestSnap.demo()
        self.menu(m, ["R"])
        m.run_frames(150)
        self.assertIn("1982 Sinclair Research Ltd", m.screen_text()[-1])
        self.clean(m, game=True)
        self.assertIn("Directory of D80 Demo", " ".join(self.cat(m, CAT_A)))


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestDriveB(unittest.TestCase):
    """A second image in drive B: (.d80 a.d80 b.d80)."""

    def test_cat_save_load_on_b_with_sd(self):
        from image import MdosImage, blank_image
        t = TestSdWrite()
        a = IMAGE
        m = t.machine(image_b=blank_image("DiskB"))
        m.type_keys(CAT_B)
        m.run_frames(60)
        self.assertEqual(lines(m), ["Directory of DiskB", "0 File(s),   730112 Bytes free.",
                                    "0 OK, 0:1"])
        m.type_keys(SAVE_B)
        m.run_frames(150)
        self.assertEqual(lines(m)[-1], "0 OK, 0:1")
        b = MdosImage(m.image_bytes(1))
        self.assertEqual([(e.name.strip(), e.type, e.length) for e in b.entries()],
                         [("test", "B", 6912)])
        self.assertIsNone(b.check(b.entries()[0]))
        self.assertEqual(m.image_bytes(0), a)               # A: untouched
        t.check_card(m)
        m.type_keys(LOAD_B)
        m.run_frames(150)
        self.assertEqual(lines(m)[-1], "0 OK, 0:1")
        m.type_keys(CAT)                                   # A: is still the default
        m.run_frames(60)
        self.assertIn("Directory of D80 Demo", m.screen_text())

    def test_blank_d40_in_b(self):
        from image import MdosImage, blank_image
        t = TestSdWrite()
        m = t.machine(image_b=blank_image("Small", tracks=40))
        m.type_keys(CAT_B)
        m.run_frames(60)
        self.assertEqual(lines(m), ["Directory of Small", "0 File(s),   361472 Bytes free.",
                                    "0 OK, 0:1"])
        m.type_keys(SAVE_B)
        m.run_frames(150)
        self.assertEqual(lines(m)[-1], "0 OK, 0:1")
        b = MdosImage(m.image_bytes(1))
        self.assertEqual([(e.name.strip(), e.length) for e in b.entries()], [("test", 6912)])
        self.assertIsNone(b.check(b.entries()[0]))
        self.assertTrue(all(s < 720 for s in b.chain(b.entries()[0].first_sector)[0]))
        t.check_card(m)

    def test_no_image_in_b(self):
        from nextmmu import DidaktikNext
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE)
        m.run_frames(100)
        m.type_keys(CAT_B)
        m.run_frames(60)
        text = lines(m)
        self.assertNotIn("Directory of", " ".join(text))
        self.assertNotEqual(text[-1], "0 OK, 0:1")
        self.assertEqual(m.fdc_access, [])
        m.type_keys(CAT)                                   # A: still works
        m.run_frames(60)
        self.assertIn("Directory of D80 Demo", m.screen_text())

    @unittest.skipUnless((SAMPLES / "035-X-MAGAZIN.d80").exists(), "035-X-MAGAZIN.d80 missing")
    def test_sector_ops_follow_active_drive(self):
        """X-MAGAZIN reaches the sector loop with IX = #3E0C (drive 1's descriptor)
        while A: is active. MDOS's own ops select the drive from #3E6B, so must ours:
        selecting by IX gave "Device unavailable" (B: is empty)."""
        from nextmmu import DidaktikNext
        img = (SAMPLES / "035-X-MAGAZIN.d80").read_bytes()
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), img)
        m.run_frames(150)
        m.type_keys([["R"], ["ENTER"]])
        m.run_frames(600)
        self.assertNotIn("Device unavailable", m.screen_text())
        self.assertEqual(m.fdc_access, [])


@unittest.skipUnless(have_all, "ROMs or patches.json not present")
class TestSdWrite(unittest.TestCase):
    """-w: every sector MDOS writes goes through to the model SD card."""

    EXTENTS = [(100, 300), (2000, 600), (5000, 540)]     # a fragmented file (card sectors)
    EXTENTS_B = [(6000, 700), (7000, 740)]                # image B: on the same card

    def machine(self, block=True, pipelined=False, write_protect=False, image=None,
                image_b=None, busy=0):
        from mdospatch import SdMap
        from nextmmu import DidaktikNext, SpiSdCard
        image = image or IMAGE
        card = bytearray(b"\xAA" * 8192 * 512)
        unit = 1 if block else 512
        maps = []
        for img, extents in ((image, self.EXTENTS), (image_b, self.EXTENTS_B)):
            if img is None:
                maps.append(None)
                continue
            pos = 0
            for s, n in extents:
                card[s * 512:(s + n) * 512] = img[pos * 512:(pos + n) * 512]
                pos += n
            maps.append(SdMap([(s * unit, n) for s, n in extents], 2 if block else 0))
        self.card = SpiSdCard(card, block_addr=block, pipelined=pipelined,
                              write_protect=write_protect, busy=busy)
        self.has_b = image_b is not None
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), image, sd=maps[0], card=self.card,
                         image_b=image_b, sd_b=maps[1])
        m.run_frames(100)
        return m

    def check_card(self, m):
        extents = self.EXTENTS + (self.EXTENTS_B if getattr(self, "has_b", False) else [])
        inside = {s for b, n in extents for s in range(b, b + n)}
        self.assertEqual([w for w in self.card.writes if w not in inside], [])
        self.assertEqual(m.card_image(), m.image_bytes())
        if getattr(self, "has_b", False):
            self.assertEqual(m.card_image(1), m.image_bytes(1))
        self.assertEqual(m.fdc_access, [])
        self.assertEqual(m.cpu.mdos_rom_writes, [])

    def save(self, m):
        m.type_keys(SAVE_TEST)
        m.run_frames(150)
        return [t for t in m.screen_text() if t.strip()]

    def test_save_block_addressed(self):
        m = self.machine()
        self.assertEqual(self.save(m)[-1], "0 OK, 0:1")
        self.assertNotEqual(m.image_bytes(), IMAGE)
        self.assertGreater(len(self.card.writes), 10)          # FAT, directory, data
        self.check_card(m)

    def test_save_byte_addressed_pipelined_port(self):
        m = self.machine(block=False, pipelined=True)
        self.assertEqual(self.save(m)[-1], "0 OK, 0:1")
        self.check_card(m)

    def test_write_error_then_retry(self):
        m = self.machine(write_protect=True)
        self.assertEqual(self.save(m)[-2:], ["Disk is write protected (Retry =", " R)"])
        self.card.write_protect = False
        m.type_keys([["R"]])
        m.run_frames(150)
        self.assertEqual([t for t in m.screen_text() if t.strip()][-1], "0 OK, 0:1")
        self.check_card(m)

    def test_format_command(self):
        """FORMAT "a:testik": MDOS calls the format op once per track (B = track,
        C = track count) and verifies with a direct read that must return B = 2."""
        self.format_and_save(self.machine())

    def test_format_busy_card_pipelined_port(self):
        """Back-to-back writes on the Next's SPI port (a read returns the byte of
        the previous exchange) to a card that stays busy after each write: the
        driver must not send CMD24 before the card is ready."""
        self.format_and_save(self.machine(pipelined=True, busy=300))

    def format_and_save(self, m):
        from image import MdosImage
        m.type_keys(FORMAT_TESTIK)
        m.run_frames(100)
        m.type_keys([["P"]])                                # Proceed
        for _ in range(20):
            m.run_frames(100)
            if "0 OK, 0:1" in m.screen_text()[-1] or "Retry" in "".join(m.screen_text()):
                break
        screen = [t for t in m.screen_text() if t.strip()]
        self.assertEqual(screen[-1], "0 OK, 0:1", screen)
        self.assertIn("Total capacity is  730112 Bytes.", screen)
        img = m.image_bytes()
        self.assertEqual(img[192:198], b"testik")
        self.assertEqual(img[14 * 512:], b"\xE5" * (len(img) - 14 * 512))
        self.assertEqual(MdosImage(img).entries(), [])
        self.check_card(m)
        self.assertEqual(self.save(m)[-1], "0 OK, 0:1")     # the new disk is usable
        self.check_card(m)

    def test_format_writes_e5(self):
        """sd_put with op = 2 (sec_format) writes a #E5-filled sector."""
        import json
        sym = json.loads(PATCHES.read_text())["symbols"]
        m = self.machine()
        c = m.cpu
        c.mapped = True
        c.mdb[sym["op"] - 0x2000] = 2
        c.mdb[sym["cur_lsn"] - 0x2000:sym["cur_lsn"] - 0x1FFE] = (305).to_bytes(2, "little")
        c.wr(0x8000, 0x76)                                  # HALT as the return address
        c.sp = 0x9000
        c.push(0x8000)
        c.pc = sym["sd_put"]
        c.iff1 = c.iff2 = 0
        for _ in range(200_000):
            c.step()
            if c.pc == 0x8000:                              # returned
                break
        self.assertEqual(c.pc, 0x8000)
        self.assertFalse(c.f & 1)                           # NC = written
        self.assertEqual(self.card.writes, [2005])          # sector 305 = extent 2, offset 5
        self.assertEqual(bytes(self.card.data[2005 * 512:2006 * 512]), b"\xE5" * 512)


@unittest.skipUnless(SDCARD.exists(), "ZEsarUX tbblue.mmc not present")
class TestFat16(unittest.TestCase):
    def test_put_get_roundtrip(self):
        from fat16 import Fat16
        with tempfile.TemporaryDirectory() as d:
            sd = Path(d) / "sd.mmc"
            shutil.copyfile(SDCARD, sd)
            fs = Fat16(sd)
            data = bytes(range(256)) * 300
            fs.put("/d80test/sub/FILE.BIN", data)
            fs.f.close()
            fs = Fat16(sd)
            self.assertEqual(fs.get("/d80test/sub/FILE.BIN"), data)
            self.assertIn("FILE.BIN", "".join(fs.ls("/d80test/sub")))
            fs.f.close()


if __name__ == "__main__":
    unittest.main()
