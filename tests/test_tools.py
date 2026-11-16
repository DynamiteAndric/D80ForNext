import unittest
from pathlib import Path

import snapshot
from basic import tokenize
from demo_image import build as build_demo
from image import MdosError, MdosImage, add_file, blank_image, set_fat
from z80mini import Z80

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "emulators" / "images"     # optional third-party disks, not in git
have_samples = (SAMPLES / "029-GAMES.d80").exists()


class TestZ80(unittest.TestCase):
    def test_ldir_djnz_and_flags(self):
        mem = bytearray(0x10000)
        # LD HL,#8000 ; LD DE,#9000 ; LD BC,4 ; LDIR ; LD B,3 ; XOR A ; loop: INC A ; DJNZ loop ; CP 3 ; HALT
        code = bytes.fromhex("210080 110090 010400 EDB0 0603 AF 3C 10FD FE03 76".replace(" ", ""))
        mem[0x100:0x100 + len(code)] = code
        mem[0x8000:0x8004] = b"ABCD"
        cpu = Z80(mem)
        cpu.pc = 0x100
        cpu.iff1 = 1
        while not cpu.halted:
            cpu.step()
        self.assertEqual(mem[0x9000:0x9004], b"ABCD")
        self.assertEqual(cpu.a, 3)
        self.assertTrue(cpu.f & 0x40)  # Z flag set by CP 3


class TestBasic(unittest.TestCase):
    def test_tokenize(self):
        prog = tokenize("""
        10 PRINT AT 2,4;"GO TO 10": GO TO 10
        20 IF k$="a" THEN LOAD *"demo"
        30 REM GO TO stays text
        """)
        def num(n):
            return str(n).encode() + bytes([0x0E, 0, 0, n, 0, 0])
        body = (b"\xF5\xAC" + num(2) + b"," + num(4) + b';"GO TO 10":\xEC' + num(10) + b"\x0D")
        self.assertEqual(prog[:4], bytes([0, 10]) + len(body).to_bytes(2, "little"))
        self.assertEqual(prog[4:4 + len(body)], body)
        self.assertIn(b'\xFAk$="a"\xCB\xEF*"demo"\x0D', prog)
        self.assertTrue(prog.endswith(b"\xEAGO TO stays text\x0D"))


class TestImages(unittest.TestCase):
    """The generated demo disk (tools/demo_image.py)."""

    def test_demo_disk(self):
        img = MdosImage(build_demo())
        self.assertTrue(img.signature_ok)
        self.assertEqual((img.tracks, img.sides, img.sectors_per_track), (80, 2, 9))
        self.assertEqual(img.disk_name, "D80 Demo")              # zero-padded, as MDOS FORMAT
        entries = img.entries()
        self.assertEqual(len(entries), 28)
        self.assertTrue(all(img.check(e) is None for e in entries))
        e = entries[0]
        self.assertEqual((e.type, e.name, e.param1, e.first_sector), ("P", "run", 10, 14))
        self.assertEqual(e.param2, e.length)                       # no variables
        code = next(e for e in entries if e.name == "democode")
        self.assertEqual((code.type, code.param1, code.param2), ("B", 0x8000, 0x8000))

    def test_add_file_chain(self):
        data = bytearray(blank_image("T"))
        body = bytes(range(256)) * 5                               # 1280 bytes: 3 sectors
        add_file(data, "B", "x", body, param1=0x4000)
        img = MdosImage(bytes(data))
        e = img.entries()[0]
        self.assertEqual(img.chain(e.first_sector), ([14, 15, 16], 256))
        self.assertEqual(img.read(e), body)
        with self.assertRaises(MdosError):
            add_file(data, "B", "x", body)                        # exists

    def test_broken_chain_raises(self):
        data = bytearray(build_demo())
        img = MdosImage(bytes(data))
        e = next(e for e in img.entries() if e.name == "screen1")
        set_fat(data, e.first_sector, 0)                           # chain ends in a free sector
        with self.assertRaises(MdosError):
            MdosImage(bytes(data)).read(e)

    def test_raw_snapshot(self):
        mem = bytearray(0x10000)
        regs = {0x3FFE: 0xFF00, 0x3FFC: 0x1234, 0x3FFA: 0x5678, 0x3FEC: 0xABCD,
                0x3FEA: 0x5C3A, 0x3FE8: 0x8004}                    # SP AF BC IX IY, I=#80 P/V=1
        for a, v in regs.items():
            mem[a:a + 2] = v.to_bytes(2, "little")
        mem[0xFF00:0xFF02] = (0x8122).to_bytes(2, "little")        # PC on the program's stack
        s = snapshot.parse(bytes(mem[0x3F80:]))
        self.assertFalse(s.packed)
        self.assertEqual((s.pc, s.bc, s.ix, s.iy, s.i, s.im, s.iff), (0x8122, 0x5678, 0xABCD,
                                                                   0x5C3A, 0x80, 2, True))
        self.assertEqual(len(s.to_z80()), 30 + 49152)


@unittest.skipUnless(have_samples, "third-party sample disks not present (emulators/images/)")
class TestSampleDisks(unittest.TestCase):
    """Regression checks on real disks; they are not distributed."""

    def test_all_chains_match_lengths(self):
        bad = 0
        for p in sorted(SAMPLES.glob("*.d80")):
            img = MdosImage.open(p)
            self.assertTrue(img.signature_ok)
            bad += sum(img.check(e) is not None for e in img.entries())
        self.assertLessEqual(bad, 3)  # a few entries are genuinely corrupt on the sample disks

    def test_packed_snapshot(self):
        img = MdosImage.open(SAMPLES / "029-GAMES.d80")
        e = next(e for e in img.entries() if e.name == "TURRICAN1+")
        s = snapshot.parse(img.read(e))
        self.assertTrue(s.packed)
        self.assertEqual((s.pc, s.sp, s.i, s.im, s.iy), (0x822D, 0xFFF8, 0x3F, 1, 0x5C3A))
        self.assertEqual(len(s.to_sna()), 27 + 49152)


if __name__ == "__main__":
    unittest.main()
