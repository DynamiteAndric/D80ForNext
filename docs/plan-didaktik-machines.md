# Plan: Didaktik Gama, Didaktik M and Didaktik Kompakt on the Next (status 2026-11-17: done; verified on a real Next)

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

Added afterwards: without `-4` the loader shows a **machine menu**.
- The choices are 48K, Gama, M and Kompakt, picked with keys 1–4 or the cursor keys and ENTER. ENTER alone takes the 48K.
- The files are `c:/machines/next/48.rom` and `c:/sys/d80/{gama,didm,kompakt}.rom`. The names are 8.3 so the ZEsarUX test card, written by `fat16.py`, can hold them.
- The items are the first lines of the progress window. The bar stays on the choice, and the progress report continues below it (rows 11–16, enough for the 6 lines of `-n` on both drives).
- The menu code sits after `once` at the end of the binary. The CRC table and `sd_buf` overlay it once it has run, so the dot command still fits below `#3E00` (6,683 bytes; `once` may grow to `#3A00` before the CRC table has to move).
- Tested in ZEsarUX with `tools/zesarux_next_check.py --rom`.
- After the real Next check (2026-11-17), at the user's request: `probe_roms` opens each `c:/sys/d80/*.rom` and the menu lists only the machines found. With none there is no menu. The items are numbered 1–n without gaps (the user's choice). `TestBlank.test_dot_command_machine_menu` runs `choose_rom` in the Z80 model with a fake card and keys. The dot command is 6,971 bytes.

Changes from the plan below:

- The `-m` machine option was dropped. `-4 file` already chooses the ROM, and the ROM list covers the machines.
- The Didaktik ROMs need 100–150 frames (M and Kompakt) or about 200 frames (Gama) to show the copyright message.
- When this ROM writes to ROM space, the writes are ignored, as on real hardware.

The original Phase 1 plan, kept for reference:

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

### Phase 2: MDOS 2.0 — dropped; its fixes go into the 1.0 patches

**Status: done (2026-11-16). MDOS 2.0 is not supported and is not needed.** The Kompakt ROM already runs with MDOS 1.0 (Phase 1). A byte-by-byte comparison of `Didaktik_40-80_MDOS_v1_91.rom` and `v2_93.rom` (3,524 bytes differ, 130 regions), with every MDA change disassembled, showed that 2.0 brings nothing the Next needs:

| What changed in 2.0 | Where | On the Next |
|---|---|---|
| Driver for the Kompakt's WD37C65/765 FDC; `OUT #97/#99` to block the D80 v2's 8255 | MDB `#2217-#27FF` | Replaced by our RAM-image driver anyway |
| Unused EPROM filled with `#FF` (1.0: `#FF`/`#00` noise) | `#2800-#37FF` | Nothing |
| `RST 0` at `#0066` (written at `#2792`) | | We patch `#0066` the same way |
| FORMAT shows track/side, runs a VERIFY pass, asks "New volume:" | MDA `#1519-#16A8`, `#130F-#13E6`, `#1493-#14E0` | Not needed: FORMAT of a RAM image is instant |
| Only drives A: and B: (1.0 accepts A:-D:) | `#08AE`, `#08DD`, `#08FA`, `#1106-#110C`, `#1658` | A restriction, not a feature |
| Boot border colour, version text, a free-memory off-by-one (`#0940`), the debug flag test at `#0221` | | Cosmetic |
| **SNAP looks for a free SNAPSHOTnn name** (`#033A` → `#1620`) | MDA | **Ported** |
| **MOVE: stray `LD (#C000),BC` removed** (`#1AAB`) | MDA | **Ported** |
| **MOVE counts matching files before copying** (`#1ACD` → `#1680/#1699`, RAM `#3EFB`) | MDA | **Ported** |
| **Disk full: delete the half-made file** (`#20BC` → `#166C`; `#0CDE/#0EB7` go to the plain error) | MDA/MDB | **Ported** |

The routines the fixes call (`#217B`, `#1C8F`, `#212B/#212D`, `#1F88`, `#1D9D`, `#1C06`) are the same bytes in both versions, and so are the addresses that software calls directly (MDA up to `#1493`, `#236A/#23BE/#23D8`, `#21AC`). The disk format is the same.

What was built:

- `dot/mdospatch.asm`: the fixes as patches at `#033A`, `#0CDE`, `#0EB7`, `#1AAB`, `#1ACD-#1AD4` and `#20BC`, with the new code (`fix_*`, the same logic as 2.0 `#1620-#16A8`) at `FIXES` = `#2E00` in unused MDB EPROM. The one change from 2.0: the disk-full clean-up only erases the entry if it is found. The dot command grew to 6,811 bytes (patch table).
- Found along the way: **volume names (`MOVE "SrcDisk:x","DstDisk:"`, `CAT "name:"`) never matched on images we create.** MDOS FORMAT pads the disk name with zeros and compares all 10 bytes; `blank_image` (`tools/image.py`), `.d80 -n` (`dot/d80.asm`) and the demo disk padded it with spaces. All now pad with zeros. MOVE takes only volume names, so it did not work at all on those images.
- Tests: `TestSnap.test_snap_takes_a_free_name`; `TestMdos20Fixes` (wildcard MOVE between volumes keeps `#C000`; MOVE and SAVE onto a full disk leave no broken entry).

Verified behaviour of MDOS 1.0 before the fixes (in the model): MOVE turned `#C000-#C001` into `00 00`; MOVE onto a full disk left the file that did not fit with an empty FAT chain; SAVE onto a full disk left the file with a short chain and the disk at 0 free sectors.

The original Phase 2 plan, kept for reference:

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

## Files

- `dot/d80.asm`: `rom48_crcs` (48K, Gama '89, M '92, Kompakt '93), `rom48_known`, the machine menu (after `once`), `-4` skips it
- `dot/mdospatch.asm`: the MDOS 2.0 fixes (`fix_*` at `FIXES` = `#2E00`)
- `tools/romcompat.py`, `tools/mdospatch.py` (`ROMS16`), `tools/nextmmu.py` (any 16K ROM), `tools/image.py` (zero-padded volume names)
- `tests/test_d80dot.py`: `TestDidaktikRom`, `TestMdos20Fixes`, `TestSnap.test_snap_takes_a_free_name`
- `docs/usage.md`, `dist/README.txt`, `docs/development.md`

## Verification

- [done] `python tools/build_dot.py`, then `python -m unittest discover -s tests -t .`. The Didaktik tests skip when the ROMs are missing from `emulators/roms/`.
- [done] `python tools/romcompat.py MDOS.rom 48.rom emulators/roms/Didaktik_*.rom`: no differences at the 58 addresses MDOS uses.
- [done] `tools/zesarux_next_check.py --rom c:/sys/d80/gama.rom=…` for the loader path and the machine menu.
- [done 2026-11-17, the user: all steps pass] **Real Next.** Card layout: `/dot/D80` (from `dist/dot/`), `/sys/d80/mdos10.rom`, `/sys/d80/{gama,didm,kompakt}.rom`, `/d80/demo.d80`, and a scratch copy `/d80/test.d80` of the demo disk.
  1. **Menu, 48K:** `.d80 /d80/demo.d80`. The menu lists 48K, Gama, M, Kompakt. ENTER alone → the Sinclair copyright, then MDOS boots the demo. The bar and the progress report below it are drawn cleanly.
  2. **Menu keys:** `.d80 /d80/demo.d80`, move the bar with `6`/`7`, ENTER on Didaktik M → the Didaktik M copyright (after 2–3 s). Repeat with the digit keys `2` (Gama, about 4 s to the copyright) and `4` (Kompakt).
  3. **Each Didaktik ROM, MDOS works:** for each of `2`, `3`, `4`: `CAT` lists `Directory of D80 Demo` and scrolls; `LOAD *"…"` of a BASIC program from the demo runs it; the Didaktik font shows in BASIC.
  4. **`-4` skips the menu:** `.d80 -4 /sys/d80/kompakt.rom /d80/demo.d80` → no menu, straight to the progress window and the Kompakt.
  5. **Unknown ROM:** `.d80 -4 /some/other.rom /d80/demo.d80` (e.g. a 128K ROM half) → `Unknown machine ROM`, back to NextZXOS. (Since the menu probing: a missing ROM is not listed, see below.)
  6. **Write + SNAP free name (MDOS 2.0 fix):** `.d80 -w /d80/test.d80`, choose `3`. Start the demo program, press DRIVE twice (two short presses, a few seconds apart). `CAT` shows `SNAPSHOT00` and `SNAPSHOT01` (1.0 overwrote `00`). Reset, run `.d80 /d80/test.d80` again: both snapshots are still there, and `LOAD *"SNAPSHOT01"` resumes the program.
  7. **Volume names + MOVE fix:** `.d80 -w /d80/test.d80 -n /d80/dst.d80`, choose `4`. `POKE 49152,85: POKE 49153,170: MOVE "D80 Demo:data*","dst:*"`, then `PRINT PEEK 49152,PEEK 49153` → `85 170` (1.0 gave `0 0`). `CAT "dst:"` (or `CAT "b:"`) lists the copied `data*` files.
  8. **Disk full:** `.d80 -w -n /d80/full.d40` (a 360K disk), choose `1`. `SAVE *"big1" CODE 0,65535`, `SAVE *"big2" CODE 0,65535`, … until `U Disk full`. `CAT` shows no entry for the file that failed, and a smaller `SAVE *"s" CODE 16384,100` still fits. Reset and load the image again: the same files are there.
  9. **Hold DRIVE** on each machine opens the D80 menu (with the chosen ROM's font). Swap A:/B: and continue.
  Then delete `/d80/test.d80`, `/d80/dst.d80` and `/d80/full.d40`.
- [done 2026-11-17, the user] **Real Next, menu probing:** with all three Didaktik ROMs the menu shows 4 items as before. Rename `gama.rom`: the menu shows `1 ZX Spectrum 48K`, `2 Didaktik M`, `3 Didaktik Kompakt`; `3` takes the Kompakt, `4` does nothing. Rename all three: no menu, `.d80 /d80/demo.d80` goes straight to the 48K. Rename them back.
