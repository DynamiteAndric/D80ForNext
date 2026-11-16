# Plan: Didaktik Gama, Didaktik M and Didaktik Kompakt on the Next

## Context

`.d80` runs a 48K Spectrum with a D40/D80 drive: the Sinclair 48K ROM goes into the Next's alternate ROM, and MDOS 1.0 sits in DivMMC with a replacement driver. The question is what it takes to run the Czechoslovak Didaktik machines themselves:

| Machine | What it is | What changes compared with today |
|---|---|---|
| **Didaktik Gama** (1987–89) | 48K clone with its own ROM, an 8255 PPI (ports `#1F/#3F/#5F/#7F`) and 80K RAM: `#8000-#FFFF` has 2 banks, selected by 8255 PC0 (`OUT #5F,n`; MAME/Fuse notes) | Different 16K ROM; the 80K bank switch |
| **Didaktik M** (1990–92) | 48K clone with its own ROM, its own ULA (timing differs from Sinclair), and a built-in 8255 and joystick | Different 16K ROM; maybe the timing |
| **Didaktik Kompakt** (1991–94) | Didaktik M plus a built-in 3.5" 720K drive using **MDOS 2.0** (WD37C65/8272-class FDC, no FDC NMIs, `RST 0` at `#0066`) | Didaktik M ROM, plus MDOS 2.0 in place of 1.0 |

### Findings from this investigation

1. **The BASIC ROM can be swapped.** `emulators/specy/DIDAKTIK.ROM` ("1989 DIDAKTIK SKALICA", CRC `45C29401`, 8255 code at `#386E`, which looks like Gama '89) differs from the 48K ROM in only 924 bytes. The changes are a few small patches (`#04AB`, `#11D0`, `#153E`, …), the font and the spare area at `#386E-#3CFF`. The routine addresses MDOS relies on (the `RST #28` targets and the T_ADDR/return-address table at MDOS `#05FF`, see `docs/mdos10-notes.md`) appear to be unchanged. MDOS was built for these machines. The loader only blocks this today because it hard-checks `ROM48_CRC` (`dot/d80.asm:51`, `:111`).
2. **MDOS 2.0 is closer to 1.0 than expected.** Both ROMs are in `emulators/roms/`. 2.0 (`D4A6B86A`, and the 16K version `B5A18F73` whose first 14K are the same) differs from 1.0 in 3524 bytes. MDA has the **same 12 `JP #1700` sites** (`#005D … #1968`), the same `#0000/#000B/#0038/#1700/#1FE8` code, and only small changes apart from `#1519-#16A8`. Most of the difference is in the FDC code in MDB (`#2217-#27FF`). The sector-op entry points `#236A/#23BE/#23D8` and `DESC_SEL #21AC` are the same. At `#0066`, 2.0 already holds `RST 0`.
3. **The Gama's 80K banking cannot be emulated on the Next.** The Next cannot trap `OUT #5F`: the I/O traps in NextReg `#D8` cover only the +3 FDC ports. Writes to `#1F/#3F/#5F/#7F` do nothing harmful on the Next (none of them is the ULA, `#7FFD` or a Next port). Reads of `#1F` return the Kempston joystick, which matches the Didaktik joystick.
4. **Timing is not settled.** I found no source that documents the Didaktik M ULA timing or contention. The Next offers 48K, 128K, +3 and Pentagon timing (NextReg `#03`). Keep 48K timing unless measurements show otherwise.

## Approach

### Phase 1: a choice of BASIC ROM (Gama and Didaktik M; the Kompakt with MDOS 1.0)

**Status: done.** What was built:

- `rom48_known` and the `rom48_crcs` table in `dot/d80.asm`, with `ROMS16` in `tools/mdospatch.py`. The table holds the Sinclair 48K ROM, Gama 80k '89 (`45C29401`), M 1992 (`57264D4F`) and Kompakt 1993 (`34752ABA`). The Didaktik ROMs come from cygnus.speccy.cz and were checked against the CRC32/MD5 published there. They go in `emulators/roms/`, which git ignores.
- `tools/romcompat.py`. It checks 58 places: 32 RST #28 targets, 21 syntax-table T_ADDRs, 4 return addresses and the RET at `#1700`.
- `TestDidaktikRom`: romcompat, boot, CAT and SAVE in the model, plus a test of `rom48_known` in the loader.
- Docs.

Changes from the plan below:

- The `-m` machine option was dropped. `-4 file` already chooses the ROM, and the ROM list covers the machines.
- The Didaktik ROMs need 100–150 frames (M and Kompakt) or about 200 frames (Gama) to show the copyright message.
- When this ROM writes to ROM space, the writes are ignored, as on real hardware.


- `dot/d80.asm`:
  - Replace the single `ROM48_CRC` check with a table of known CRCs: Sinclair 48K, `45C29401` (Gama '89), and the Gama '87/'88, M '90–'93 and Kompakt dumps once the user supplies them.
  - Keep the `-4 file.rom` option.
  - Add a machine option, for example `-m gama|m|kompakt`, that picks the default ROM paths (`c:/sys/d80/gama.rom`, …). An unknown CRC still stops the load, as it does today.
  - Leave the font copy for the menu (`pg_r1`, ROM `#3D00`) as it is. It then shows the Didaktik font, which is fine.
- New `tools/romcompat.py`: lists every 48K ROM address MDOS 1.0 (and 2.0) uses (`RST #28` `DEFW` targets, the `#05FF` T_ADDR and return-address table, the `#0010-#0020` forwards, `#1700` RET), and checks that a given ROM has the same bytes there as the 48K ROM. This is how a new ROM gets added to the whitelist. It prints offsets only and never ROM bytes.
- `tools/nextmmu.py` / `mdospatch.build_pages`: take any 16K ROM, not only `48.rom`.
- Docs: `docs/usage.md`, `dist/README.txt` (keep the two in sync) and `docs/development.md`.
  - Say which ROMs work, that Gama 80K bank 1 is not supported, and that the 8255 printer (LPRINT) does nothing.
  - Users have to supply the ROMs. Never commit them.

### Phase 2: MDOS 2.0 (the real Kompakt, also the D80 v2)

- New `dot/mdos20patch.asm`, written alongside `dot/mdospatch.asm`.
  - Reuse the MDA part unchanged where the bytes match: page-out sites, `#1FE8` move, `#0038`/`#1700` and SNAP entries.
  - `#0066` is already `RST 0`, so that patch is a no-op.
  - Re-target the MDB patches to the 2.0 FDC code. Disassemble it with `tools/z80dis.py` and use the MDOS 2.1 source (`emulators/roms/mdos21-source.wri`) to find:
    - the 765 equivalents of the force-interrupt and `#87` writes;
    - the 8255 detection at `#2278`;
    - the motor and disk-ready code (`#2556`, `#256D`, `#25BC`);
    - the `#2340`/`#234B` sector-op setup.
  - Put the replacement driver, which reads and writes the image in RAM, over the 765 code (`#25EA-#27FF`).
  - Check that the MDB space used for `SD_MAP` (`#3000-#377F`) is unused in 2.0 as well.
  - Check the RAM variables the driver and menu use (`DRIVE #3E6B`, `SAVED_IX #3EE7`, `FAT_DIRTY #3E6C`, `FAT_DRIVE`, `DIR_DRIVE`, `DESC_A/B` in `dot/menu.asm:47-51`) against the 2.0 code. Where they differ, export them as `MDB_*` symbols.
- `tools/build_dot.py`: assemble both patch sets (the same 0/FF ROM-free method) into `patches.json`/`patches.inc`, keyed by MDOS CRC, with `DATA_SYMBOLS` for each version. `tools/mdospatch.py` picks the set by CRC.
- `dot/d80.asm`: replace the single `MDOS_CRC` with a table: 1.0 `545531FA` → patch set 1; 2.0 `D4A6B86A` (14K, or the first 14K of a 16K file) → patch set 2. Check whether 1.0+ `26E613D2` is a plain variant that set 1 covers. The dot command must still fit within its size limit with two patch tables (check that first).
- `test_build_is_rom_free` covers both sets.

### Out of scope / later

- **Gama 80K bank 1.** It cannot be trapped. The only other route is to patch the Gama ROM's own bank routines, which only covers BASIC use, so leave it for now.
- **Exact Didaktik M timing.** Revisit only if a reference (MAME or measurements) shows that software breaks under 48K timing.

## Critical files

- `dot/d80.asm`: ROM CRC tables, the `-m` option, and choosing the patch set
- `dot/mdospatch.asm` (MDOS 1.0, kept as it is) and the new `dot/mdos20patch.asm`
- `dot/menu.asm`: MDOS RAM addresses become symbols for each version
- `tools/build_dot.py`, `tools/mdospatch.py`, `tools/nextmmu.py`, the new `tools/romcompat.py`
- `tests/test_d80dot.py` and the other tests: run them for each ROM/MDOS combination
- `docs/usage.md`, `dist/README.txt`, `docs/development.md`, `docs/research-report.md` (which now says "MDOS 2.0 not planned")

## Verification

- `python tools/build_dot.py`, then `python -m unittest discover -s tests -t .`. Parametrize the existing boot/CAT/SNAP/menu tests over (48K ROM, the three Didaktik ROMs in `emulators/roms/`) × (MDOS 1.0, MDOS 2.0). They skip when a ROM is missing.
- `python tools/romcompat.py MDOS.rom 48.rom emulators/roms/Didaktik_*.rom`: no differences at the addresses MDOS uses.
- `python tools/preview_d80.py MDOS20.rom emulators/roms/Didaktik_Kompakt_93.rom out/x dist/d80/demo.d80 --keys R,ENTER,WAIT3,A`: the Didaktik copyright screen and the demo menu appear, and `CAT` lists the disk.
- Write test with MDOS 2.0: SAVE a file, then `image_bytes()` and `tools/image.py` read it back.
- `tools/zesarux_next_check.py` for the loader path; a final check on a real Next.
