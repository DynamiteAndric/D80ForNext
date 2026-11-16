# D40onNext — Didaktik D40/D80 images on the ZX Spectrum Next

The **`.d80` dot command** boots Didaktik D40/D80 (MDOS) disk images (`.d40`/`.d80`) on the ZX Spectrum Next with the real MDOS 1.0.

## Running images directly on the Next: `.d80`

The `.d80` dot command boots a disk image on the Next with the real **MDOS 1.0**. Disk menus, multi-load games and `CAT`/`LOAD *`/`RUN` work as they do on a Didaktik 80.

```
.d80 /d80/021.d80                       ; then RUN, CAT, LOAD *"name" ...
.d80 -r /my/mdos.rom -4 /my/48.rom game.d80
.d80 "c:/my disks/game.d80"             ; quotes allow spaces and ':'
.d80 -w /d80/021.d80                    ; disk writes go back to the image file on SD
.d80 -w -n /d80/new.d80                 ; create a blank formatted disk, then use it
.d80 -w /d80/021.d80 /d80/data.d80      ; second image in drive B:
.d80 -w /d80/021.d80 -n /d80/data.d80   ; ... created blank first
```

While loading, `.d80` clears the screen and shows a window in the style of the 128 menu. It reports each step: the ROM checks, then each image by name with a progress bar, and `New disk …` when `-n` creates one. When all is ready it shows `Press any key` and starts MDOS on the next key press.

**Writing to the SD card (`-w`).** Without `-w`, disk writes change only the RAM copy. With `-w`:
- `.d80` asks esxDOS where the image file lies on the card (`DISK_FILEMAP`).
- It then checks that map with its own SPI code: the first sector of each file fragment and the last image sector must read back exactly as loaded.
- At run time, every sector MDOS writes or formats is also written to the card (CMD24), into the file's own sectors only. The FAT and the file size never change.
- If the card refuses a write, MDOS shows `Disk is write protected (Retry = R)`.
- An image in more than 128 fragments is refused.


To start images from the NextZXOS browser, add these lines to the end of `/nextzxos/browser.cfg` (the file `dist/browser-d80.cfg` holds them). Don't replace the existing file:
```
D80:.d80 -w "|"
D40:.d80 -w "|"
```
Programs started from the browser then save to the image (`-w`). Leave out `-w` for read-only starts. If the file already has `D80`/`D40` lines, replace them.

**Drive B: (second image).** A second image name goes into drive B:. MDOS 1.0 has exactly two drives, so a third name is a usage error. MDOS addresses B: by the letter before a colon, for example `CAT "b:"`, `LOAD *"b:name"` and `SAVE *"b:name" CODE 16384,6912`. Without a drive letter it uses the current drive (A: after the start). With `-w`, writes go to the image file of the drive they are for. A 720K image needs 90 pages, so two images need 180 pages of free RAM (a 2 MB Next).

**Blank disk (`-n`).** `-n` creates the image file as a freshly formatted disk, laid out as MDOS 1.0 FORMAT writes it: a 360K D40 disk (40 tracks) for a `*.d40` name, otherwise a 720K D80 disk. The disk name is the file name without its extension, up to 10 characters. If the file already exists, `.d80` stops with `File exists` and changes nothing. `-n` applies to the image name that follows it. Use it together with `-w`, otherwise the saves are lost at reset. `python tools/new_image.py` writes the same image on a PC.

**SNAP button and D80 menu.** The Next's **DRIVE** button (DivMMC NMI, hotkey F10) works as the Didaktik SNAP button. A short press saves a snapshot. Holding DRIVE for about half a second, or pressing it with CAPS SHIFT held, opens the **D80 menu** instead:

| Item | Key | Action |
|---|---|---|
| Swap A: and B: | `X` | swap the disks in the two drives |
| Snapshot | `S` | as a short press |
| Reset | `R` | cold start of MDOS and the 48K ROM; the disks stay |
| Back | `SPACE` | back to the program, which continues unchanged |

The menu looks like the ZX Spectrum 128 / NextZXOS menu: a window with the rainbow title bar, the disk names in A: and B:, and the items with a cyan selection bar. Choose an item with the cursor keys (`7`/`6` or `Q`/`A`) and `ENTER`, or press its key. The menu saves and restores the part of the screen it uses, and keeps the program's registers in MDOS RAM. A swap is refused while MDOS still holds an unwritten FAT, which cannot happen between commands. MDOS reads FAT and directory again after a change. Disks addressed by their *name* (`LOAD *"DiskName:file"`) are not looked up again; use the drive letter.

What a short press does:
- MDOS saves the running program as `SNAPSHOTnn` (type `S`, 49,280 bytes) to the current drive, and the program continues.
- Without `-w`, the file goes only to the RAM copy of the image. With `-w`, it is written to the image on the SD card.
- As on the Didaktik, the button is ignored while MDOS itself runs (for example during `LOAD *` or `CAT`).
- `LOAD *"SNAPSHOT00"` loads the snapshot back.

Details: [docs/plan-d80-snap.md](docs/plan-d80-snap.md).

Install:
1. Build with `python tools/build_dot.py` (it needs `tools/sjasmplus/`). Copy `dot/build/D80` to `C:/dot/`.
2. Put the MDOS 1.0 ROM (`Didaktik_40-80_MDOS_v1_91.rom`, 14,336 bytes, CRC32 `545531FA`) at `C:/sys/d80/mdos10.rom`. The ROM is not distributed.
3. The standard 48K ROM is taken from `C:/machines/next/48.rom`, which is part of the Next distribution.

How it works:
- MDOS sits in DivMMC banks 3 and 4.
- Automap on opcode fetches from `#0000`/`#0008` and the `#1FF8` off-trap reproduce the Didaktik paging.
- The standard 48K ROM goes, unmodified, into the alternate ROM.
- The FDC driver is replaced by a copy from the image, which is loaded into RAM pages.
- SNAP: the DRIVE NMI automaps DivMMC instantly at `#0066` (NextReg `#BB` bit 1), where MDOS now holds `RST 0`. NextReg `#06` bit 4 (DRIVE NMI) is set only while MDOS is paged out.
- With `-w`, sector writes also go to the card through the shared SPI code in `dot/sdspi.asm` (plan: [docs/plan-d80-sd-write.md](docs/plan-d80-sd-write.md)).

Details are in [docs/plan-d80-dot-command.md](docs/plan-d80-dot-command.md) and [docs/mdos10-notes.md](docs/mdos10-notes.md).

Limits:
- Without `-w`, disk writes change only the RAM copy.
- 48K only, with MDOS 1.0. 128K mode and MDOS 2.0 are not planned.
- At most two drives (A:, B:), as in MDOS 1.0.
- The DRIVE button no longer opens the NextZXOS NMI menu.
- A 720K image needs 90 free 8K pages.
- Leave with a hard reset.
- NextReg `#7F` holds the last progress marker: `#07` = waiting for the key, `#E3` = MDOS started; bit 7 set = `.d80` failed at step `marker & #7F` (`#20`–`#22` are the `-w` steps).

Checking without hardware:
```sh
python tools/preview_d80.py MDOS.rom 48.rom out/_d80 images/021.d80 --keys R,ENTER,WAIT6,D   # Python model
python tools/zesarux_next_check.py out/_next --mdos MDOS.rom --image images/021.d80           # ZEsarUX TBBlue
```

ZEsarUX 13 runs the dot command up to `JP 0`, but it does not emulate the programmable DivMMC entry points (NextReg `#B8`–`#BB`). Checked on a real Next: it works, and so does writing with `-w`.

## Tools (`tools/`)

Python helpers for building, testing and checking `.d80`. Pure Python 3.10+ with no dependencies. Run the scripts from the project root as `python tools/<script>.py`; the modules import each other directly from `tools/`.

| File | Purpose |
|---|---|
| `build_dot.py` | Assembles `dot/*.asm` with sjasmplus into `dot/build/D80`, `menu.bin` and the patch tables |
| `new_image.py` | Creates a blank formatted image on a PC, as `.d80 -n` does: `python tools/new_image.py blank.d80 [--name X]` |
| `image.py` | Reader for MDOS disk images (geometry, FAT, directory, files) and `blank_image` |
| `mdospatch.py` | Applies the `.d80` patches to a user-supplied MDOS ROM and lays out the RAM pages |
| `nextmmu.py` | Python model of the `.d80` runtime on the Next (DivMMC automap, NextRegs, SD card), used by the tests |
| `emu48.py`, `z80mini.py` | Minimal 48K Spectrum harness and the Z80 core it runs on |
| `snapshot.py` | Parses MDOS `S` snapshots (raw or SNAPSHOT-PACKER) and writes `.z80`/`.sna` |
| `z80dis.py` | Small Z80 disassembler (used for the MDOS notes) |
| `fat16.py` | Minimal FAT16 access to an SD card image (`ls`/`put`/`get`) |
| `preview_d80.py` | Boots an image in the Python model and saves screens as PNG |
| `zesarux_check.py`, `zesarux_next_check.py` | Headless ZEsarUX runs with screenshots; the second one runs `.d80` on the Next machine (TBBlue) |
| `fuse_check.py`, `fuse_snap_roundtrip.py` | Reference runs of the original images with real MDOS in Fuse, and a SNAP round trip |

The model and the emulator scripts need a standard 48K ROM and the MDOS ROM, which are not included. ZEsarUX 13.0 (Windows build) lives in `emulators/ZEsarUX/`, which git ignores.

### Reference runs with real MDOS (Fuse)

Fuse 1.10.1 in `emulators/fuse/` emulates the Didaktik 80 interface. The MDOS ROMs downloaded from cygnus.speccy.cz are kept in `emulators/roms/`, which git ignores; they are copyrighted, so they are not distributed with the tool. Fuse expects the 14 KB MDOS 1.0 ROM as `emulators/fuse/roms/didaktik80.rom`.

`tools/fuse_check.py` boots an original image, types keys into the Fuse window only, and captures that window (not the desktop). Its captures are the reference for `.d80`:

```sh
python tools/fuse_check.py --disk images/021.d80 --keys "R,ENTER" --seconds 12 out/_fuse              # disk menu
python tools/fuse_check.py --disk images/021.d80 --keys "R,ENTER,WAIT4,D" --seconds 20 out/_fuse      # HEXAGONIA
```

## Tests

```sh
python -m unittest discover -s tests -t .
```

## Format notes

See [docs/research-report.md](docs/research-report.md) [docs/mdos10-notes.md](docs/mdos10-notes.md) (MDOS 1.0 disassembly) and [docs/snap-button.md](docs/snap-button.md) (how the SNAP button works). The MDOS facts that were verified on the sample images are:

- **Image layout:** a linear dump of 512-byte logical sectors (80 tracks × 2 sides × 9 sectors). The boot sector holds the `SDOS` signature.
- **FAT:** sectors 1–5, with **341 entries per sector**. Each sector holds 170 triplets `(loA, hiA<<4|hiB, loB)`, plus one extra entry in its last two bytes `(lo, hi<<4|0xD)`. Values: 0xDDD = reserved, 0xE00+n = end of file with n bytes in the last sector (n = 0 means 512).
- **Directory:** sectors 6–13, 128 × 32-byte entries.

| Offset | Field |
|---|---|
| 0 | Type |
| 1–10 | Name |
| 11–12, 21 | Length |
| 13–14 | Start address or autostart line |
| 15–16 | BASIC program length |
| 17–18 | First sector |
| 20 | Attributes |

- **Snapshot (`S`):** a dump of memory 0x3F80–0xFFFF. The first 128 bytes are the top of the D40's 2K RAM and hold the MDOS NMI register stack:

| Address | Register |
|---|---|
| 0x3FFE | SP |
| 0x3FFC | AF |
| 0x3FFA | BC |
| 0x3FF8 | DE |
| 0x3FF6 | HL |
| 0x3FF4 | AF' |
| 0x3FF2 | BC' |
| 0x3FF0 | DE' |
| 0x3FEE | HL' |
| 0x3FEC | IX |
| 0x3FEA | IY |
| 0x3FE8 | F/I from `LD A,I` (P/V = IFF2) |

  PC is on the program's stack. IM is 1 if I = 0x3F, otherwise IM 2. Compressed snapshots (SNAPSHOT-PACKER v1.2, R. Kralovic 1992) are unpacked by running their own stub in the Z80 core.
