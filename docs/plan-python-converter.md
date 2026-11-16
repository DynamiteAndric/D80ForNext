# Plan: Option 1, part 1 — Python converter (status 2026-11-16: removed; kept as history)

> The converter CLI (`list`/`basic`/`extract`/`convert`/`snap`), `d80tool.basic`, `d80tool.tape` and the converter check tools (`batch_check`, `zesarux_batch`, `preview_tap`, `preview_snapshots`) were removed on 2026-11-16. `d80tool.image`, `snapshot`, `emu48`, `z80mini` and `z80dis` stay because `.d80` and its tests use them.

## Goal
Use the sample images in `images/` to learn the real MDOS structure. Then write Python that extracts MDOS files and converts them into formats the ZX Spectrum Next loads, and check that the results run.

## Steps
1. [done] Reverse-engineer the format from the 25 sample `.d80` images: FAT with 341 entries per sector, directory, and a check that all file chains match their lengths (1541 of 1544 OK).
2. [done] `d80tool.image`: image reader with geometry, FAT, directory and checked file reads.
3. [done] `d80tool.snapshot`: MDOS `S` file → `.z80`/`.sna`. The register layout comes from the MDOS 2.1 source (labels `NMI` and `RUNSNAP2`). SNAPSHOT-PACKER files are unpacked with `d80tool.z80mini`.
4. [done] `d80tool.basic` + `d80tool.tape`: BASIC listing, rewriting `LOAD *"x"` → `LOAD "x"`, and TAP output (one tape per program plus `_all_files.tap`).
5. [done] `d80tool.cli`: `list` / `basic` / `extract` / `convert`, and a `report.md` per disk.
6. [done] Verification: Spectaculator's trial has expired, and running the downloaded ZEsarUX was not permitted. Instead `d80tool.emu48` (a Python 48K harness using the 48K ROM as data) renders the screen.
   - Snapshots: Turrican, Saboteur 1 and 2 (all packed) and Falling Down (raw) run correctly.
   - TAP: HEXAGONIA boots to its menu. EXPEDICE needs real tape loading because it copies the ROM loader into RAM. *(Wrong — see step 11.)*
7. [done] Unit tests in `tests/` (9 tests).
8. [done] ZEsarUX moved to `emulators/ZEsarUX`. Headless checks run through `tools/zesarux_check.py`:
   - Snapshots: all 4 real game snapshots run.
   - Tapes: HEXAGONIA and TOTALRECAL reach their title screens; DUCK OUT shows its intro.
   - Failures: EXPEDICE resets and MAH JONGG shows a black screen; both still need investigation. *(Fixed in step 11.)*
9. [done] MDOS ROMs (1.0 1991/1992, 2.0 1993) downloaded to `emulators/roms/`. Fuse with the Didaktik 80 interface and MDOS 1.0 boots the original images; reference captures come from `tools/fuse_check.py`. EXPEDICE and MAH JONGG run on the original, so their conversions fail because the Proxima loaders need MDOS at runtime. *(Wrong — the real cause was the converter bug fixed in step 11.)*
10. [done] MDOS 1.0 disassembly (`d80tool.z80dis`, notes in `docs/mdos10-notes.md`):
    - Snapshot restore at `#034D` and `#0970` (= `RET`) confirm the converter.
    - MDOS has no separate machine-code API; it is entered through the RST 8 error trap of BASIC statements.
11. [done] Bug fix: the `LOAD *` rewrite now preserves lengths, so machine code behind the BASIC program stays in place. EXPEDICE and MAH JONGG now match the originals.
12. [done] Bulk check of 314 program tapes:
    - **Python harness, all 314:** a rough screen only. It has no real timing, so many "blank" results are false alarms.
    - **ZEsarUX (48K, 35 s per program), 299 of 314:** the run was stopped by the system for low memory with 10 parallel instances; the 15 programs from 042/043 were not run. Results are in `out/_zx/summary.md` with contact sheets.

      | Class | Count | Notes |
      |---|---|---|
      | running | 209 | |
      | stopped-ok | 8 | |
      | basic-error | 16 | MDOS commands `CAT`, `MOVE`, `SAVE *` in menus and utilities |
      | reset | 31 | MDOS menus and tools, and 128K programs run on a 48K machine |
      | blank | 35 | |
    - Fixes found along the way:
      - `POKE #` statements (MDOS) are blanked; "Nonsense in BASIC" dropped from 33 to 2.
      - Harness: undocumented IXh/IXl instructions; `HALT` with interrupts disabled is recorded as a hang.

## Status: no further development (decided 2026-11-16)
The `.d80` dot command ([plan-d80-dot-command.md](plan-d80-dot-command.md)) runs disk images with the real MDOS on the Next, including what the converter cannot handle (MDOS menus, multi-load games, `CAT`/`MOVE`/`SAVE *`). It is now the main way to run D40/D80 disks on the Next.

The PC converter stays as it is and is kept working, but gets no new features. It is still useful as a fallback:
- on a Next with too little free RAM for `.d80` (a 720K image needs 90 free 8K pages);
- for 128K programs (`.d80` is 48K only);
- for files that open straight from the NextZXOS browser, or in emulators without Didaktik support;
- for listing and extracting files on a PC.

The rest of the `d80tool` package stays in active use, now as `tools/d80tool/`: `image.py` (`blank_image`), `z80mini`, `nextmmu.py` and `mdospatch.py` are the model and patch builder behind `.d80`, its build (`tools/build_dot.py`) and its tests. The `new` command became `tools/new_image.py`.

Dropped (were optional):
- finishing the ZEsarUX bulk check (the 15 programs from 042/043, the 128K programs on `--machine 128k`);
- checking a sample of the "blank" and "reset" programs against Fuse + MDOS;
- batch-classifying all 314 program tapes with the harness.
