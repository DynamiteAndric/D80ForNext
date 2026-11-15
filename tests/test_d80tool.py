import unittest
from pathlib import Path

from d80tool import basic, snapshot, tape
from d80tool.image import MdosImage, MdosError
from d80tool.z80mini import Z80

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "images"
have_images = (IMAGES / "021.d80").exists()


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


class TestTape(unittest.TestCase):
    def test_block_checksums(self):
        t = tape.code("test", b"\x01\x02\x03", 32768)
        pos = 0
        while pos < len(t):
            n = t[pos] | (t[pos + 1] << 8)
            blk = t[pos + 2:pos + 2 + n]
            x = 0
            for b in blk:
                x ^= b
            self.assertEqual(x, 0)
            pos += 2 + n
        self.assertEqual(t[2], 0x00)            # header flag
        self.assertEqual(t[4:14], b"test      ")


class TestBasic(unittest.TestCase):
    def test_rewrite_load_star(self):
        # 10 LOAD *"game" CODE
        body = b'\xEF*"game"\xAF\x0D'
        prog = b"\x00\x0A" + len(body).to_bytes(2, "little") + body
        new, plen, changes = basic.rewrite_mdos_loader(prog, len(prog))
        self.assertEqual(changes, 1)
        self.assertIn(b'\xEF "game"\xAF', new)
        # lengths must not change: loaders keep machine code at fixed USR addresses behind the program
        self.assertEqual((plen, len(new)), (len(prog), len(prog)))
        self.assertEqual(basic.listing(new), '  10 LOAD  "game" CODE')

    def test_rewrite_drive_prefix(self):
        body = b'\xEF*"b:game"\x0D'
        prog = b"\x00\x0A" + len(body).to_bytes(2, "little") + body
        new, _, changes = basic.rewrite_mdos_loader(prog, len(prog))
        self.assertEqual(changes, 1)
        self.assertIn(b'\xEF "game"  \x0D', new)
        self.assertEqual(len(new), len(prog))

    def test_blank_poke_hash(self):
        # 2 POKE #247,79: PRINT "x"
        num247 = b"247\x0E\x00\x00\xF7\x00\x00"
        num79 = b"79\x0E\x00\x00\x4F\x00\x00"
        body = b"\xF4#" + num247 + b"," + num79 + b':\xF5"x"\x0D'
        prog = b"\x00\x02" + len(body).to_bytes(2, "little") + body
        new, _, changes = basic.rewrite_mdos_loader(prog, len(prog))
        self.assertEqual(changes, 1)
        self.assertEqual(len(new), len(prog))
        self.assertNotIn(b"\xF4", new)
        lst = basic.listing(new)
        self.assertTrue(lst.endswith('PRINT "x"') and 'POKE' not in lst, lst)



@unittest.skipUnless(have_images, "sample images not present")
class TestImages(unittest.TestCase):
    def test_all_chains_match_lengths(self):
        ok = bad = 0
        for p in sorted(IMAGES.glob("*.d80")):
            img = MdosImage.open(p)
            self.assertTrue(img.signature_ok)
            self.assertEqual((img.tracks, img.sides, img.sectors_per_track), (80, 2, 9))
            for e in img.entries():
                if img.check(e) is None:
                    ok += 1
                else:
                    bad += 1
        self.assertGreater(ok, 1500)
        self.assertLessEqual(bad, 3)  # a few entries are genuinely corrupt on the sample disks

    def test_directory(self):
        img = MdosImage.open(IMAGES / "021.d80")
        e = img.entries()[0]
        self.assertEqual((e.type, e.name, e.length, e.param1, e.first_sector), ("P", "run", 4041, 10, 14))

    def test_broken_chain_raises(self):
        img = MdosImage.open(IMAGES / "022.d80")
        snaps = [e for e in img.entries() if e.type == "S"]
        with self.assertRaises(MdosError):
            img.read(snaps[0])

    def test_packed_snapshot(self):
        img = MdosImage.open(IMAGES / "029-GAMES.d80")
        e = next(e for e in img.entries() if e.name == "TURRICAN1+")
        s = snapshot.parse(img.read(e))
        self.assertTrue(s.packed)
        self.assertEqual((s.pc, s.sp, s.i, s.im, s.iy), (0x822D, 0xFFF8, 0x3F, 1, 0x5C3A))
        z80 = s.to_z80()
        self.assertEqual(len(z80), 30 + 49152)
        self.assertEqual(z80[6] | (z80[7] << 8), 0x822D)
        self.assertEqual(len(s.to_sna()), 27 + 49152)

    def test_raw_snapshot(self):
        img = MdosImage.open(IMAGES / "041-games128.d80")
        e = next(e for e in img.entries() if e.name == "FALINGDOWN")
        s = snapshot.parse(img.read(e))
        self.assertFalse(s.packed)
        self.assertEqual((s.pc, s.i, s.im, s.iff), (0xD6E7, 0xAC, 2, True))


if __name__ == "__main__":
    unittest.main()
