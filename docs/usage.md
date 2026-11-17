# Using `.d80`

The `.d80` dot command boots a Didaktik D40/D80 disk image on the ZX Spectrum Next with the real **MDOS 1.0**. The Next becomes a 48K Spectrum with a Didaktik 80; disk menus, multi-load games and `CAT`/`LOAD *`/`RUN` work as they do on the original.

## Installation

Copy the contents of `dist/` to the root of the Next SD card:

| Path on the card | Contents |
|---|---|
| `/dot/D80` | the dot command |
| `/sys/d80/mdos10.rom` | the MDOS 1.0 ROM — **not included**, see below |
| `/sys/d80/gama.rom`, `didm.rom`, `kompakt.rom` | optional Didaktik ROMs for the machine menu — **not included**, see below |
| `/d80/demo.d80` | a demo disk (`RUN` starts its menu) |

The MDOS ROM is copyrighted and not distributed. Download `Didaktik_40-80_MDOS_v1_91.rom` (MDOS 1.0, 1991; 14,336 bytes, CRC32 `545531FA`) from the ROM page of [cygnus.speccy.cz](https://cygnus.speccy.cz/download_roms.php) and save it as `/sys/d80/mdos10.rom`.

The standard 48K ROM is taken from `/machines/next/48.rom`, which is part of the normal Next distribution.

## Command line

```
.d80 [-w] [-r mdos.rom] [-4 48.rom] [-n] a.d80 [[-n] b.d80]
```

| Option | Meaning |
|---|---|
| `-w` | write disk changes back to the image file on the SD card |
| `-n` | create the image name that follows it as a blank formatted disk |
| `-r file` | MDOS ROM to use instead of `/sys/d80/mdos10.rom` |
| `-4 file` | 16K ROM to use (the 48K ROM or a Didaktik ROM, see below) without the machine menu |

Examples:

```
.d80 /d80/demo.d80                      ; then RUN, CAT, LOAD *"name" ...
.d80 -r /my/mdos.rom -4 /my/48.rom game.d80
.d80 "c:/my disks/game.d80"             ; quotes allow spaces and ':'
.d80 -w /d80/demo.d80                   ; disk writes go back to the image file on SD
.d80 -w -n /d80/new.d80                 ; create a blank formatted disk, then use it
.d80 -w /d80/demo.d80 /d80/data.d80     ; second image in drive B:
.d80 -w /d80/demo.d80 -n /d80/data.d80  ; ... created blank first
```

Without `-4`, `.d80` first asks for the machine if any Didaktik ROM is on the card (see below). ENTER takes the ZX Spectrum 48K. While loading, `.d80` shows a window in the style of the 128 menu. It reports each step: the ROM checks, then each image with a progress bar, and `New disk …` when `-n` creates one. When everything is ready it shows `Press any key`; the next key starts MDOS.

## Machine menu: Didaktik Gama, M and Kompakt ROMs

Without `-4`, `.d80` first shows a machine menu. It lists only the machines whose ROM file is on the card; the 48K is always there. With no Didaktik ROM on the card there is no menu, and `.d80` starts the 48K.

| Key (all ROMs present) | Machine | ROM file |
|---|---|---|
| `1` | ZX Spectrum 48K | `/machines/next/48.rom` |
| `2` | Didaktik Gama | `/sys/d80/gama.rom` |
| `3` | Didaktik M | `/sys/d80/didm.rom` |
| `4` | Didaktik Kompakt | `/sys/d80/kompakt.rom` |

Press a digit, or move the bar with the cursor keys (`6`/`7`) and press ENTER. The items are numbered in the order of the table, without gaps: with only `kompakt.rom` on the card the menu shows `1 ZX Spectrum 48K` and `2 Didaktik Kompakt`. ENTER alone takes the ZX Spectrum 48K. `-4 file` skips the menu and uses that file. For example, `.d80 -4 /sys/d80/kompakt.rom /d80/demo.d80` starts a Didaktik Kompakt directly.

With a Didaktik ROM, the Next starts with the Didaktik copyright message, its font and its BASIC changes. MDOS works the same way, because these ROMs keep every 48K ROM address MDOS uses.

`.d80` checks the ROM by CRC32 and accepts:

| ROM | CRC32 |
|---|---|
| Sinclair 48K | `DDEE531F` |
| Didaktik Gama 80k '89 (`Didaktik_Gama_1989.rom`) | `45C29401` |
| Didaktik M 1992 (`Didaktik_M_1992.rom`) | `57264D4F` |
| Didaktik Kompakt 1993 (`Didaktik_Kompakt_93.rom`) | `34752ABA` |

Download the Didaktik ROMs from the same [cygnus.speccy.cz](https://cygnus.speccy.cz/download_roms.php) page as MDOS. Save them under the short names from the menu table: `Didaktik_Gama_1989.rom` as `gama.rom`, `Didaktik_M_1992.rom` as `didm.rom` and `Didaktik_Kompakt_93.rom` as `kompakt.rom`. Any other ROM stops with `Unknown machine ROM`. To add one, check it with `python tools/romcompat.py mdos10.rom 48.rom new.rom` and add its CRC to `rom48_crcs` in `dot/d80.asm` (see `docs/plan-didaktik-machines.md`). These ROMs are copyrighted and not included.

Differences from the real machines:

- **Gama 80K:** the second 32K bank (`OUT 95,1`) is not emulated. The Next cannot intercept that port, so programs see only bank 0.
- **8255 printer port:** there is none. `LPRINT`/`LLIST` through the 8255 do not print. `OUT 31` (`#1F`) also drives the Next's DAC A if the DACs are enabled.
- **Timing:** the Next runs with 48K Sinclair timing, not the Didaktik ULA timing.
- **Kompakt:** its built-in drive used MDOS 2.0. `.d80` runs MDOS 1.0 with the same 720K disks. The MDOS 2.0 fixes that matter are built in: SNAP picks a free `SNAPSHOTnn` name instead of overwriting one, MOVE no longer overwrites two bytes at 49152, and a file that does not fit on a full disk is deleted instead of left broken.

## Starting images from the NextZXOS browser

Add these lines to the **end** of `/nextzxos/browser.cfg` (they are also in `dist/browser-d80.cfg`). Do not replace the file — it holds the other associations. If it already has `D80`/`D40` lines, replace those.

```
D80:.d80 -w "|"
D40:.d80 -w "|"
```

Select a `.d80` or `.d40` file in the browser and press ENTER. Programs then save to the image (`-w`); leave out `-w` for read-only starts.

## Writing to the SD card (`-w`)

Without `-w`, disk writes change only the RAM copy and are lost on reset. With `-w`:

- `.d80` asks esxDOS where the image file lies on the card (`DISK_FILEMAP`).
- It checks that map with its own SPI code: the first sector of each file fragment and the last image sector must read back exactly as loaded.
- At run time, every sector MDOS writes or formats is also written to the card, into the file's own sectors only. The FAT and the file size never change.
- If the card refuses a write, MDOS shows `Disk is write protected (Retry = R)`.
- An image in more than 128 fragments is refused.

Keep a backup of images you care about.

## Drive B: (second image)

A second image name goes into drive B:. MDOS 1.0 has exactly two drives, so a third name is a usage error.

MDOS addresses B: by the letter before a colon: `CAT "b:"`, `LOAD *"b:name"`, `SAVE *"b:name" CODE 16384,6912`. Without a drive letter it uses the current drive (A: after the start). With `-w`, writes go to the image file of the drive they are for.

## Blank disks (`-n`)

`-n` creates the image file as a freshly formatted disk, laid out as MDOS 1.0 FORMAT writes it:

- a 360K D40 disk (40 tracks) for a `*.d40` name,
- otherwise a 720K D80 disk.

The disk name is the file name without its extension, up to 10 characters. If the file already exists, `.d80` stops with `File exists` and changes nothing. Use `-n` together with `-w`, otherwise saves are lost at reset.

On a PC, `python tools/new_image.py blank.d80 [--name X]` writes the same image.

## SNAP button and the D80 menu

The Next's **DRIVE** button (DivMMC NMI, hotkey F10) works as the Didaktik SNAP button.

**Short press** — snapshot:

- MDOS saves the running program as `SNAPSHOTnn` (type `S`, 49,280 bytes) to the current drive, and the program continues.
- Without `-w` the file goes only to the RAM copy; with `-w` it is written to the image on the card.
- As on the Didaktik, the button is ignored while MDOS itself runs (for example during `LOAD *` or `CAT`).
- `LOAD *"SNAPSHOT00"` loads the snapshot back.

**Long press** (about half a second, or DRIVE with CAPS SHIFT held) — the D80 menu:

| Item | Key | Action |
|---|---|---|
| Swap A: and B: | `X` | swap the disks in the two drives |
| Snapshot | `S` | same as a short press |
| Reset | `R` | cold start of MDOS and the 48K ROM; the disks stay |
| Back | `SPACE` | back to the program, which continues unchanged |

Choose an item with the cursor keys (`7`/`6` or `Q`/`A`) and `ENTER`, or press its key. The menu shows the disk names in A: and B: and restores the screen when it closes.

After a swap, MDOS reads the FAT and directory again. Disks addressed by *name* (`LOAD *"DiskName:file"`) are not looked up again — use the drive letter.

## Limits

- 48K mode and MDOS 1.0 only. 128K mode is not planned. MDOS 2.0 is not needed: its fixes are part of the patches (`docs/plan-didaktik-machines.md`).
- At most two drives (A:, B:).
- A 720K image needs 90 free 8K pages; two images need a 2 MB Next.
- `-w` needs an image in at most 128 fragments on the card.
- While `.d80` runs, the DRIVE button no longer opens the NextZXOS NMI menu.
- Leave with a hard reset.

## Troubleshooting

NextReg `#7F` holds the last progress marker:

| Value | Meaning |
|---|---|
| `#07` | waiting for the key press |
| `#E3` | MDOS started |
| bit 7 set | `.d80` failed at step `marker & #7F` (`#20`–`#22` are the `-w` steps) |
