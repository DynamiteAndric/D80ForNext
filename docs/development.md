# Development

How `.d80` works, how to build it and how to check it without hardware.

## Building

```sh
python tools/build_dot.py
```

It needs sjasmplus in `tools/sjasmplus/` (git ignores it) and writes `dot/build/D80`, `menu.bin` and the patch tables, and copies `D80` to `dist/dot/D80`, so `dist/` is ready to copy to the card.

## How it works

- MDOS sits in DivMMC banks 3 and 4.
- Automap on opcode fetches from `#0000`/`#0008` and the `#1FF8` off-trap reproduce the Didaktik paging.
- The standard 48K ROM goes, unmodified, into the alternate ROM.
- The FDC driver is replaced by a copy from the image, which is loaded into RAM pages.
- SNAP: the DRIVE NMI automaps DivMMC instantly at `#0066` (NextReg `#BB` bit 1), where MDOS holds `RST 0`. NextReg `#06` bit 4 (DRIVE NMI) is set only while MDOS is paged out.
- The yellow NMI button (Multiface, NextReg `#06` bit 3) is off from the start of the loader on: `nr06_fill` clears bit 3 in every `#06` value MDOS B and the stub write, and `restore` puts NextZXOS's value back if loading fails. The Multiface menu pages over `#0000-#3FFF` and froze the Next.
- With `-w`, sector writes also go to the card (CMD24) through the shared SPI code in `dot/sdspi.asm`.
- The D80 menu keeps the program's registers in MDOS RAM and saves/restores the part of the screen it uses. A disk swap is refused while MDOS still holds an unwritten FAT, which cannot happen between commands.

Design notes and history:

- [plan-d80-dot-command.md](plan-d80-dot-command.md) — the dot command itself
- [plan-d80-sd-write.md](plan-d80-sd-write.md) — writing to the SD card (`-w`)
- [plan-d80-snap.md](plan-d80-snap.md) — the SNAP button
- [plan-d80-drives-menu.md](plan-d80-drives-menu.md) — blank images, drive B:, the D80 menu
- [plan-didaktik-machines.md](plan-didaktik-machines.md) — Didaktik Gama/M/Kompakt ROMs; MDOS 2.0 compared and its fixes ported
- [plan-demo-disk.md](plan-demo-disk.md) — the generated demo disk that replaced the third-party samples
- [mdos10-notes.md](mdos10-notes.md) — MDOS 1.0 disassembly notes
- [snap-button.md](snap-button.md) — how the SNAP button works on the original hardware
- [research-report.md](research-report.md) — the original research
- [disk-format.md](disk-format.md) — the MDOS disk and snapshot format

## Tools (`tools/`)

Pure Python 3.10+ with no dependencies. Run the scripts from the project root as `python tools/<script>.py`; the modules import each other directly from `tools/`.

| File | Purpose |
|---|---|
| `build_dot.py` | Assembles `dot/*.asm` with sjasmplus into `dot/build/D80`, `menu.bin` and the patch tables, and copies `D80` to `dist/dot/` |
| `new_image.py` | Creates a blank formatted image on a PC, as `.d80 -n` does |
| `image.py` | Reader for MDOS disk images (geometry, FAT, directory, files), `blank_image` and `add_file` |
| `basic.py` | Tokenizes 48K BASIC source text into a program, as `SAVE` stores it |
| `make_release.py` | Builds the `dist/` zip and publishes a GitHub release |
| `demo_image.py` | Builds the demo disk `dist/d80/demo.d80` (BASIC menu, IM 2 machine-code demo, data files) |
| `romcompat.py` | Checks that a Didaktik (or other) 16K ROM keeps every 48K ROM address MDOS uses, before its CRC is added to `rom48_crcs` |
| `mdospatch.py` | Applies the `.d80` patches to a user-supplied MDOS ROM and lays out the RAM pages |
| `nextmmu.py` | Python model of the `.d80` runtime on the Next (DivMMC automap, NextRegs, SD card), used by the tests |
| `emu48.py`, `z80mini.py` | Minimal 48K Spectrum harness and the Z80 core it runs on |
| `snapshot.py` | Parses MDOS `S` snapshots (raw or SNAPSHOT-PACKER) and writes `.z80`/`.sna` |
| `z80dis.py` | Small Z80 disassembler (used for the MDOS notes) |
| `fat16.py` | Minimal FAT16 access to an SD card image (`ls`/`put`/`get`) |
| `preview_d80.py` | Boots an image in the Python model and saves screens as PNG |
| `zesarux_check.py`, `zesarux_next_check.py` | Headless ZEsarUX runs with screenshots; the second runs `.d80` on the Next machine (TBBlue) |
| `fuse_check.py`, `fuse_snap_roundtrip.py` | Reference runs of disk images with the real Didaktik 80 in Fuse, and a SNAP round trip |

The model and the emulator scripts need a standard 48K ROM and the MDOS ROM, which are not included.

## Releases

`tools/make_release.py` builds the SD card package and publishes it as a GitHub release (needs the `gh` CLI, logged in):

```sh
python tools/make_release.py v1.0.0 --dry-run    # only build out/d80-v1.0.0.zip
python tools/make_release.py v1.0.0              # tag, push the tag, create the release with the zip
```

It only releases from a clean `main` that matches `origin/main`. It rebuilds `dist/` and stops if that changes a committed file, runs the tests, and zips `dist/` from `HEAD` with `git archive`, so ignored files such as the MDOS ROM never get in. Release notes come from the commits, or from `--notes`/`--notes-file`; `--draft` creates a draft.

Alternatively, push only a tag and let GitHub build the release (`.github/workflows/release.yml`):

```sh
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

The workflow checks that the tag is on `main`, runs `make_release.py --package-only` (demo disk check, tests, zip) and creates the release with generated notes. The runner has neither sjasmplus nor the ROMs, so it packages the committed `dist/dot/D80` and skips the ROM tests: build and run the full tests locally before tagging.

## Tests

```sh
python -m unittest discover -s tests -t .
```

The tests run on the demo disk, which they build in memory with `tools/demo_image.py`; everything on it is generated, so no third-party software is needed or distributed. Rebuild the copy in `dist/` after changing the generator:

```sh
python tools/demo_image.py dist/d80/demo.d80
```

A few regression checks (the SNAPSHOT-PACKER unpacker, a disk that reaches the sector loop with the other drive's descriptor) need real third-party disks. Put them in `emulators/images/` (git ignores it) to run those checks; otherwise they are skipped.

## Checking without hardware

```sh
python tools/preview_d80.py MDOS.rom 48.rom out/_d80 dist/d80/demo.d80 --keys R,ENTER,WAIT3,A    # Python model
python tools/zesarux_next_check.py out/_next --mdos MDOS.rom --image dist/d80/demo.d80             # ZEsarUX TBBlue
```

ZEsarUX 13.0 (Windows build) lives in `emulators/ZEsarUX/`, which git ignores. It runs the dot command up to `JP 0`, but it does not emulate the programmable DivMMC entry points (NextReg `#B8`–`#BB`), so the rest has to be checked on a real Next (done: booting and writing with `-w` both work).

### Reference runs with real MDOS (Fuse)

Fuse 1.10.1 in `emulators/fuse/` emulates the Didaktik 80 interface. The MDOS ROMs (from [cygnus.speccy.cz](https://cygnus.speccy.cz/download_roms.php)) are kept in `emulators/roms/`, which git ignores; they are copyrighted and not distributed. Fuse expects the 14 KB MDOS 1.0 ROM as `emulators/fuse/roms/didaktik80.rom`.

`tools/fuse_check.py` boots an image with the original Didaktik 80, types keys into the Fuse window only, and captures that window. Its captures are the reference for `.d80`:

```sh
python tools/fuse_check.py --disk dist/d80/demo.d80 --keys "R,ENTER" --seconds 12 out/_fuse          # demo menu
python tools/fuse_check.py --disk dist/d80/demo.d80 --keys "R,ENTER,WAIT3,A" --seconds 20 out/_fuse  # IM 2 demo
```
