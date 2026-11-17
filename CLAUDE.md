# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`.d80` is a ZX Spectrum Next dot command (Z80 assembly, sjasmplus) that boots Didaktik D40/D80 (MDOS) disk images with the real MDOS 1.0 ROM. Python 3.10+ tooling in `tools/` (no dependencies) builds it, models it and tests it. User docs: `docs/usage.md`; internals: `docs/development.md`; disk format: `docs/disk-format.md`; design history: `docs/plan-*.md`.

## Commands

Run everything from the repo root.

```sh
python tools/build_dot.py                      # assemble dot/*.asm -> dot/build/ (D80, menu.bin, patches.json/.inc); copies D80 to dist/dot/
python -m unittest discover -s tests -t .      # all tests (~4 min; the Z80 model is slow)
python -m unittest tests.test_d80dot.TestSnap.test_snap_saves_running_program   # one test
python tools/demo_image.py dist/d80/demo.d80   # rebuild the demo disk after changing the generator
python tools/make_release.py v1.0.0 --dry-run # build out/d80-v1.0.0.zip; without --dry-run also tag + GitHub release
python tools/preview_d80.py MDOS.rom 48.rom out/x dist/d80/demo.d80 --keys R,ENTER,WAIT3,A   # boot in the Python model, save PNGs
python tools/zesarux_next_check.py out/x --mdos MDOS.rom --image dist/d80/demo.d80 --steps "wait:40,shot:boot"   # ZEsarUX (Next), loader only
```

`tests/__init__.py` puts `tools/` on `sys.path`, so tests and tools import modules directly (`from image import ...`). Tool scripts do the same with `sys.path.insert`.

## Files that are never in git (copyright)

- `tools/sjasmplus/` — the assembler (`sjasmplus-1.24.0.win/sjasmplus.exe`), needed by `build_dot.py`.
- `emulators/roms/Didaktik_40-80_MDOS_v1_91.rom` (CRC32 `545531FA`) and `emulators/fuse/roms/48.rom` — tests that need them skip without them.
- `emulators/images/` — real third-party disks for manual testing; no test uses them.
- `emulators/ZEsarUX/`, `emulators/fuse/` — emulators.

Never commit ROMs, third-party disk images or anything holding long runs of ROM bytes. `test_build_is_rom_free` guards `patches.json`. Test/demo disk content must be generated (see below).

## Architecture

**ROM-free patching.** `dot/mdospatch.asm` describes the patched MDOS layout but contains no ROM bytes: `build_dot.py` assembles it twice (fill `#00` and `#FF`) and keeps only bytes that agree — those are the patches. They go to `dot/build/patches.json` (read by `tools/mdospatch.py`) and `patches.inc` (assembled into the dot command, with `MDB_*` symbol addresses). At run time the user's ROM is CRC-checked and patched. Symbols needed by the loader and tests are listed in `DATA_SYMBOLS` in `build_dot.py`; add new ones there.

**Runtime on the Next.** MDOS lives in DivMMC banks (MDA = `#0000-#1FFF`, MDB = `#2000-#37FF` + 2K RAM). DivMMC automap on opcode fetch from `#0000`/`#0008` plus the `#1FF8` off-trap reproduce Didaktik paging, so the 48K ROM stays unmodified (alternate ROM). The floppy driver is replaced by one that reads/writes the image held in 8K RAM pages; values known only at load time (`img_secs`, `page_table`, `fix_pg2/7`) are data bytes at fixed MDB addresses filled in by the loader. The DRIVE button NMI maps to MDOS `#0066` = SNAP; a long press opens the D80 menu (`dot/menu.asm`, its own page at `#E000` with a copy of the ROM font).

**Assembly sources** (`dot/`): `d80.asm` = the dot command/loader (argument parsing, ROM/image loading via esxDOS, `-n` blank image, `-w` card map check, then point of no return); `mdospatch.asm` = MDOS patches + replacement driver; `menu.asm` = D80 menu; `sdspi.asm` = raw SD SPI access shared by the loader (reads) and the driver (`-w` writes, only into the image file's own sectors, never the FAT).

**Python model.** `tools/nextmmu.py` (`DidaktikNext`) emulates the Next as `.d80` leaves it (DivMMC automap, NextRegs, SPI SD card) on top of `z80mini.py`, and asserts paging invariants. `mdospatch.build_pages` builds the same pages the dot command does. Most tests drive it: `type_keys([["CAPS","SYM"], ...])`, `run_frames(n)`, `press_snap(hold=...)`, `screen_text()`, `image_bytes(drive)`. ZEsarUX does not emulate NextReg `#B8-#BB`, so it only checks the loader up to `JP 0`; MDOS behaviour is checked in the model (and on a real Next).

**Disk images.** `tools/image.py` reads MDOS images (FAT of 12-bit entries, 341 per sector, sectors 1–5; directory sectors 6–13) and writes them (`blank_image`, `add_file`). `tools/basic.py` tokenizes 48K BASIC. `tools/demo_image.py` builds the "D80 Demo" disk the tests use (built in memory) and `dist/d80/demo.d80`; its IM 2 machine-code demo (I = `#80`, busy-waits, no `HALT`) stands in for a running game in the SNAP/menu tests, and its 28 files make `CAT` scroll. Tests assert on exact screen text (e.g. `Directory of D80 Demo`, `B data10 ... 10270`), so changing the demo disk means updating those assertions.

`dist/` is the SD card package (`dot/D80`, `d80/demo.d80`, `browser-d80.cfg`, `README.txt`); keep `dist/README.txt` in sync with `docs/usage.md`.
