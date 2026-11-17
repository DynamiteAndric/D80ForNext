"""Does a 16K ROM keep every 48K ROM address MDOS relies on?

    python tools/romcompat.py MDOS.rom 48.rom CANDIDATE.rom [MORE.rom ...]

MDOS reaches the 48K ROM in three ways (docs/mdos10-notes.md):

- ``RST #28`` + ``DEFW addr``: call a 48K ROM routine (also the RST 10/18/20
  forwards at #0010-#0020);
- the error table at #05FF: 8-byte records (T_ADDR, return address of the
  48K ROM's RST 8, stack depth, handler), by which MDOS recognises which BASIC
  statement failed and takes it over;
- ``JP #1700``: the page-out, which runs the RET at 48K ROM #1700.

A Didaktik ROM (Gama, M, Kompakt) is usable when it has the same bytes as the
48K ROM at all of these places.  Only the addresses that differ are printed,
never ROM bytes.  Exit status 1 if any candidate differs.
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from z80dis import disasm  # noqa: E402

ERROR_TABLE = 0x05FF
CODE_WINDOW = 8          # bytes compared from a routine entry
RET_WINDOW = 3           # bytes compared before a return address (the CALL)


def rst28_targets(mdos: bytes) -> set[int]:
    """DEFW targets after every RST #28 found by a linear sweep of the MDOS code."""
    mem = bytearray(0x10000)
    mem[:len(mdos)] = mdos
    out, pc = set(), 0
    while pc < len(mdos):
        if mem[pc] == 0xEF:
            out.add(mem[pc + 1] | mem[pc + 2] << 8)
            pc += 3
            continue
        pc += disasm(mem, pc)[0]
    return {a for a in out if a < 0x4000}


def error_table(mdos: bytes) -> tuple[set[int], set[int]]:
    """(T_ADDR values, return addresses) from the #05FF table (ends with T_ADDR 0)."""
    t_addr, rets = set(), set()
    for rec in range(ERROR_TABLE, len(mdos) - 8, 8):
        t = mdos[rec] | mdos[rec + 1] << 8
        if t == 0:
            break
        t_addr.add(t)
        rets.add(mdos[rec + 2] | mdos[rec + 3] << 8)
    return t_addr, rets


def ranges(mdos_roms: list[bytes]) -> dict[str, list[tuple[int, int]]]:
    """Byte ranges of the 48K ROM that MDOS depends on, by kind."""
    calls, t_addrs, rets = set(), set(), set()
    for mdos in mdos_roms:
        calls |= rst28_targets(mdos)
        t, r = error_table(mdos)
        t_addrs |= t
        rets |= r
    calls |= {0x0010, 0x0018, 0x0020}
    return {
        "routine": sorted((a, min(a + CODE_WINDOW, 0x4000)) for a in calls),
        "syntax table": sorted((a, a + 1) for a in t_addrs),
        "return address": sorted((a - RET_WINDOW, a + 1) for a in rets),
        "page-out RET": [(0x1700, 0x1701)],
    }


def check(rom48: bytes, cand: bytes, deps: dict[str, list[tuple[int, int]]]) -> list[str]:
    bad = []
    for kind, rs in deps.items():
        for lo, hi in rs:
            if rom48[lo:hi] != cand[lo:hi]:
                bad.append(f"{kind} #{lo:04X}")
    return bad


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    mdos = Path(sys.argv[1]).read_bytes()
    rom48 = Path(sys.argv[2]).read_bytes()
    deps = ranges([mdos])
    n = sum(len(r) for r in deps.values())
    print(f"{n} places in the 48K ROM ({', '.join(f'{len(r)} {k}' for k, r in deps.items())})")
    status = 0
    for name in sys.argv[3:]:
        cand = Path(name).read_bytes()
        crc = zlib.crc32(cand) & 0xFFFFFFFF
        if len(cand) != 16384:
            print(f"{name}: {len(cand)} bytes, not a 16K ROM")
            status = 1
            continue
        bad = check(rom48, cand, deps)
        print(f"{name}: CRC32 {crc:08X}: " + ("compatible" if not bad else f"{len(bad)} differ: " + ", ".join(bad)))
        status |= bool(bad)
    return status


if __name__ == "__main__":
    sys.exit(main())
