"""Tests for the .d80 dot command: patch table, FAT16 helper and the Next runtime model.

The model tests need the MDOS 1.0 ROM (emulators/roms/), a standard 48K ROM
(emulators/fuse/roms/48.rom), the sample image 021.d80 and the generated
patch data (python tools/build_dot.py); they are skipped otherwise.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from d80tool.mdospatch import PATCHES, PageMap, PatchError, build_pages, check_rom
from d80tool.z80mini import Z80

ROOT = Path(__file__).resolve().parents[1]
MDOS = ROOT / "emulators" / "roms" / "Didaktik_40-80_MDOS_v1_91.rom"
ROM48 = ROOT / "emulators" / "fuse" / "roms" / "48.rom"
IMAGE = ROOT / "images" / "021.d80"
SDCARD = ROOT / "emulators" / "ZEsarUX" / "tbblue.mmc"
have_all = all(p.exists() for p in (MDOS, ROM48, IMAGE, PATCHES))

sys.path.insert(0, str(ROOT / "tools"))


class TestR(unittest.TestCase):
    def test_r_counts_m1_cycles(self):
        mem = bytearray(0x10000)
        mem[0:6] = bytes.fromhex("00 ED5F 00".replace(" ", "")) + b"\x76"  # NOP / LD A,R / NOP / HALT
        cpu = Z80(mem)
        cpu.step()
        cpu.step()
        self.assertEqual(cpu.a, 3)                  # NOP + ED + 5F


@unittest.skipUnless(have_all, "ROMs, sample image or patches.json not present")
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
        b = build_pages(self.mdos, IMAGE.read_bytes(), self.pages)
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


@unittest.skipUnless(have_all, "ROMs, sample image or patches.json not present")
class TestNextModel(unittest.TestCase):
    def test_cat_lists_directory(self):
        from d80tool.nextmmu import DidaktikNext
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE.read_bytes())
        m.run_frames(100)
        self.assertIn("1982 Sinclair Research Ltd", m.screen_text()[-1])
        m.type_keys([["CAPS", "SYM"], ["SYM", "9"], ["ENTER"]])     # CAT
        m.run_frames(60)
        text = m.screen_text()
        self.assertIn("Directory of NoNameDisk", text)
        self.assertTrue(any(t.startswith("P run") and t.endswith("RWED") for t in text))
        self.assertEqual(m.fdc_access, [])
        self.assertEqual(m.cpu.mdos_rom_writes, [])
        self.assertEqual(m.cpu.rom_writes, 0)
        self.assertFalse(m.mdos_paged)


SAVE_TEST = [["S"], ["SYM", "B"], ["SYM", "P"], ["T"], ["E"], ["S"], ["T"], ["SYM", "P"],
             ["CAPS", "SYM"], ["I"], ["1"], ["6"], ["3"], ["8"], ["4"], ["SYM", "N"],
             ["6"], ["9"], ["1"], ["2"], ["ENTER"]]          # SAVE *"test" CODE 16384,6912


CAT = [["CAPS", "SYM"], ["SYM", "9"], ["ENTER"]]


def snapshots(m):
    from d80tool.image import MdosImage
    img = MdosImage(m.image_bytes())
    return {e.name.strip(): img.read(e) for e in img.entries() if e.type == "S"}


@unittest.skipUnless(have_all, "ROMs, sample image or patches.json not present")
class TestSnap(unittest.TestCase):
    """The DRIVE button (DivMMC NMI) as the Didaktik SNAP button."""

    running = None

    @classmethod
    def hexagonia(cls):
        """A machine running HEXAGONIA (disk 021 menu, key D), built once."""
        import copy
        from d80tool.nextmmu import DidaktikNext
        if cls.running is None:
            m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE.read_bytes())
            m.run_frames(150)
            m.type_keys([["R"], ["ENTER"]])
            m.run_frames(300)
            m.type_keys([["D"]])
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
        m = self.hexagonia()
        c = m.cpu
        self.assertEqual((c.im, c.i), (2, 0x3A))            # the game is running
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

        from d80tool.snapshot import parse
        s = parse(snaps["SNAPSHOT00"])
        for k, v in regs.items():
            self.assertEqual(getattr(s, k), v, k)
        self.assertEqual((s.pc, s.sp, s.iff, s.im), (pc, (sp - 2) & 0xFFFF, iff, 2))
        low = s.sp - 8 - 0x4000                             # MDOS #0068 uses 8 bytes below SP
        self.assertEqual(s.ram[:low], ram[:low])
        self.assertEqual(s.ram[s.sp + 2 - 0x4000:], ram[s.sp + 2 - 0x4000:])

        # the game goes on, and SNAP works again
        m.run_frames(50)
        self.assertEqual((c.im, c.i), (2, 0x3A))
        self.assertTrue(m.press_snap())
        m.run_frames(300)
        self.check_clean(m)
        self.assertEqual(sorted(snapshots(m)), ["SNAPSHOT00", "SNAPSHOT01"])

    def test_snap_ignored_while_mdos_runs(self):
        import json
        from d80tool.nextmmu import DidaktikNext
        sym = json.loads(PATCHES.read_text())["symbols"]
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), IMAGE.read_bytes())
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
        self.assertIn("B level 2b       18120 ----RWED", text)  # the listing is intact
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


@unittest.skipUnless(have_all, "ROMs, sample image or patches.json not present")
class TestSdWrite(unittest.TestCase):
    """-w: every sector MDOS writes goes through to the model SD card."""

    EXTENTS = [(100, 300), (2000, 600), (5000, 540)]     # a fragmented file (card sectors)

    def machine(self, block=True, pipelined=False, write_protect=False):
        from d80tool.mdospatch import SdMap
        from d80tool.nextmmu import DidaktikNext, SpiSdCard
        image = IMAGE.read_bytes()
        card = bytearray(b"\xAA" * 8192 * 512)
        pos = 0
        for s, n in self.EXTENTS:
            card[s * 512:(s + n) * 512] = image[pos * 512:(pos + n) * 512]
            pos += n
        unit = 1 if block else 512
        sd = SdMap([(s * unit, n) for s, n in self.EXTENTS], 2 if block else 0)
        self.card = SpiSdCard(card, block_addr=block, pipelined=pipelined,
                              write_protect=write_protect)
        m = DidaktikNext(MDOS.read_bytes(), ROM48.read_bytes(), image, sd=sd, card=self.card)
        m.run_frames(100)
        return m

    def check_card(self, m):
        inside = {s for b, n in self.EXTENTS for s in range(b, b + n)}
        self.assertEqual([w for w in self.card.writes if w not in inside], [])
        self.assertEqual(m.card_image(), m.image_bytes())
        self.assertEqual(m.fdc_access, [])
        self.assertEqual(m.cpu.mdos_rom_writes, [])

    def save(self, m):
        m.type_keys(SAVE_TEST)
        m.run_frames(150)
        return [t for t in m.screen_text() if t.strip()]

    def test_save_block_addressed(self):
        m = self.machine()
        self.assertEqual(self.save(m)[-1], "0 OK, 0:1")
        self.assertNotEqual(m.image_bytes(), IMAGE.read_bytes())
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
