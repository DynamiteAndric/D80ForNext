# Didaktik D40/D80 disk images on the ZX Spectrum Next — research report

*Date: 2026-11-14*

## 1. Verdict

- **No existing solution.** No Next core, dot command or port that handles D40/D80 images has been published.
- **Transparent hardware emulation is not possible on the stock Next core.** The Next has no WD2797 or µPD765 floppy controller. Its I/O traps (NextReg 0xD8) cover only the +3 FDC ports 0x2FFD/0x3FFD, not the Didaktik ports 0x81–0x89.
- **The image format is simple and well documented.** A `.d40`/`.d80` file is a raw sector dump of an MS-DOS-like filesystem (12-bit FAT plus directory). Extracting files is easy.
- **Most practical route:** convert image content into formats the Next already loads (snapshots → `.z80`/`.sna`, P/B files → `.tap`). A later step is an on-Next `.D80` browser dot command.
- **Hardest route, best compatibility:** run a patched MDOS ROM in Next RAM, with its sector routines redirected to the image file on the SD card. MDOS3 for divIDE is the closest prior art. This is the only route that supports software which calls MDOS at runtime, such as multi-load games and disk utilities.

## 2. Didaktik D40/D80 hardware

| | D40 | D80 (MDOS 1) | D80 v2 |
|---|---|---|---|
| Drive | 5.25" DD | 3.5" DD | 3.5" DD |
| FDC | WD2797 | WD2797 | WD37C65 / GM82C765 (8272-class) |
| ROM | MDOS 1.0 (1991) | MDOS 1.0 | MDOS 2.0 (1993) |
| FDC ports | 0x81–0x87 | same | MSR 0x81/0x83, FIFO 0x85/0x87 |
| Control | 0x89 (drive select, motor, NMI on INTRQ/DRQ) | same | 0x89 = DOR |

- **Port decoding:** mask 0xF9. The 8255 PPI sits at 0x1F/0x3F/0x5F/0x7F and is enabled through 0x91/0x99.
- **Memory:** a 14 KB ROM at 0x0000–0x37FF and 2 KB RAM at 0x3800–0x3FFF.
- **Paging:** the ROM pages in on opcode fetch at **0x0000, 0x0008 and 0x0066**, and pages out on fetch at **0x1700**.
- **Snapshot button:** generates an NMI, and MDOS saves the whole machine as an `S` file.
- **Compatibility:** a D40 disk is readable on a D80, but not always the other way round. Programs written for the WD controller may break on the 8272-based D80 v2.

Sources: MAME `src/devices/bus/spectrum/d40.cpp`; Fuse patch #331.

## 3. Image and MDOS filesystem format

**Image files**
- `.d40` / `.d80` are headerless raw dumps of logical sectors in order.
- Standard geometry is 40 or 80 tracks × 2 sides × 9 sectors × 512 B, giving 360 KB or 720 KB. Variants with 10 sectors per track or up to 82 tracks exist.
- x128 also accepts a `.000` directory form, with one file per MDOS file.

**Boot sector (logical sector 0)**

| Offset | Content |
|---|---|
| 177 | Flags: bit 3 = double-step, bit 4 = double-sided |
| 178 | Tracks |
| 179 | Sectors per track |
| 181–183 | Copy of 177–179 |
| 192–201 | Disk name |
| 202–203 | Random ID |
| 204–207 | Signature `SDOS` |

**FAT**
- 12-bit entries packed 2 per 3 bytes, indexed by logical sector. Each entry holds the next sector of the file.
- Special values: 0 = free, 0xC00 = empty file, 0xDDD = reserved (boot, FAT, directory), 0xDFF = bad, 0xE00 + n = end of file with n bytes used in the last sector.

**Directory**
- Logical sectors 7–14. George K.'s ROM guide gives 6–13, so this needs checking against a real image.
- 128 entries of 32 bytes each.

| Offset | Field |
|---|---|
| 0 | Type: `P` BASIC, `B` bytes, `N`/`C` arrays, `S` snapshot, `Q` sequential |
| 1–10 | Name, padded with 0x00 |
| 11–12 (+21) | Length |
| 13–14 | Start address, or autostart line for BASIC |
| 15–16 | BASIC program length without variables |
| 17–18 | First sector |
| 20 | Attributes (HSPARWED) |
| 22–31 | Filled with 0xE5 |

**To verify against real images:** byte order, the mapping of logical sector to (track, side, sector) (probably side-interleaved), the exact FAT start sector, and the internal layout of `S` snapshot files.

Sources: x128 file-format notes; cygnus.speccy.cz "Formát systému MDOS"; George K. "Rutiny ROM D40".

## 4. ZX Spectrum Next capabilities and limits

**Native loaders.** NextZXOS loads `.tap`, `.z80`, `.sna` and `.nex` directly. Everything that can be converted into these formats runs with no new software on the Next.

**I/O traps** (NextReg 0xD8–0xDA, experimental)
- The only trappable ports are the +3 FDC ports 2FFD and 3FFD; a trap raises a Multiface NMI.
- The Didaktik ports cannot be trapped, so unmodified MDOS cannot drive an "emulated" controller.

**Memory and paging**
- The MMU (NextReg 0x50/0x51) can map RAM into 0x0000–0x3FFF, so a patched MDOS plus a copy of the 48K ROM can run from RAM.
- DivMMC automap entry points (NextReg 0xB8–0xBB) can trigger on 0x0000–0x0038 and 0x0066, matching the Didaktik paging points. However, DivMMC is owned by NextZXOS/esxDOS, so the cleaner design is ROM-in-RAM with patched hooks.

**Physical hardware.** Connecting a real D40/D80 to the expansion bus is theoretically possible through NextReg 0x80/0x86–0x89 decoding and ROMCS. Port conflicts and 48K-only behaviour make it unattractive.

Sources: SpectrumNext FPGA `cores/zxnext/nextreg.txt`; Klive IDE book, appendices B and C.

## 5. Options, ranked

| # | Approach | Effort | Runs what | Notes |
|---|---|---|---|---|
| 1 | **PC converter (Python):** `.d40/.d80` → `.z80/.sna` + `.tap` + raw/+3DOS files | Low (about 300–500 LOC) | Snapshots and most single-load BASIC + CODE programs | BASIC loaders using `LOAD *"name"` must be rewritten to tape `LOAD ""` |
| 2 | **`.D80` dot command on the Next** (z88dk/asm): browse an image on SD, load S/P/B files directly | Medium | Same as #1, with no PC step | Uses the esxDOS F_OPEN/F_SEEK/F_READ API |
| 3 | **High-level MDOS emulation:** patched MDOS in RAM, sector I/O redirected to the image file | High (reverse engineering) | Almost everything, including multi-load and MDOS tools | Prior art: MDOS3 for divIDE (SWEET; source not public). MDOS 2.1 source is published. ROM licensing is unclear |
| 4 | **FPGA:** custom Next core with an emulated WD2797 backed by SD | Very high | Everything | Needs VHDL work and replaces the standard core |

**Existing tools**
- SAMdisk reads D80 images at sector level.
- No ready-made MDOS file extractor was found.
- MAME, Fuse and x128 emulate the D40/D80 and are useful as test references.

## 6. Recommended path

1. **Python converter.** Parse the boot sector, FAT and directory, then extract files. Convert `S` → `.z80`, convert P/B → `.tap`, and offer an optional BASIC loader rewrite. Validate against images run in Fuse or MAME.
2. **`.D80` dot command** for direct use on the Next, reusing the knowledge gained in step 1.
3. **Optional research spike:** take the MDOS 2.1 source, identify the sector read/write entry points, and prototype ROM-in-RAM with esxDOS-backed sector I/O.

## 7. Agent skills found

- `z88dk/z88dk@target-zxn`, `@cpu-z80n`, `@tool-z80asm` and `@target-zx` from the official z88dk repository. They are new, with about 1 install each, and are relevant to option 2.
- Install with `npx skills add z88dk/z88dk@target-zxn`.
- No Didaktik- or disk-image-specific skills exist.

## 8. Open questions (updated after analysing the sample images)

- **Resolved: layout.** The directory occupies logical sectors **6–13**. Images are linear in logical sector order. The FAT holds **341 entries per sector**: 170 triplets plus one entry in the last 2 bytes, with filler nibble 0xD. See README.md.
- **Resolved: snapshot format.** An `S` file is a memory dump of 0x3F80–0xFFFF. The register block sits at 0x3FE8–0x3FFF, following the MDOS 2.1 `NMI` routine, and PC is on the stack. Compressed snapshots (SNAPSHOT-PACKER v1.2) are self-extracting stubs.
- **Resolved: multi-load software.** It is common on the sample disks: game loaders that call machine code using MDOS, and disk menus. Option 3 (below) runs it.
- **Option 3 implemented (2026-11-15):** the `.d80` dot command runs the real MDOS 1.0 using DivMMC automap (NextReg `#B8`–`#BB`), with the unmodified 48K ROM in the alternate ROM and the disk image in RAM pages. See [plan-d80-dot-command.md](plan-d80-dot-command.md). It works on a real Next (confirmed 2026-11-15). Since then it also has:
  - SD write-through (`-w`, [plan-d80-sd-write.md](plan-d80-sd-write.md));
  - the SNAP button on the Next's DRIVE button ([plan-d80-snap.md](plan-d80-snap.md));
  - blank images (`-n`), drive B: and the D80 menu on a held DRIVE button ([plan-d80-drives-menu.md](plan-d80-drives-menu.md)).
- **Option 1 (PC converter) removed (2026-11-16):** with `.d80` working, the converter (`list`/`basic`/`extract`/`convert`/`snap`) was removed; see [plan-python-converter.md](plan-python-converter.md) for its history.
- **Open:** loading only the used sectors on 1 MB machines. 128K mode and MDOS 2.0 (D80 v2) are not planned. See [plan-d80-dot-command.md](plan-d80-dot-command.md).

## Sources

- [Spectrum Computing — Didaktik 40/80](https://spectrumcomputing.co.uk/entry/1000931)
- [x128 file formats](https://x128.speccy.cz/x128wip/instructions/fileformats.htm)
- [MAME d40.cpp](https://github.com/mamedev/mame/blob/master/src/devices/bus/spectrum/d40.cpp)
- [Fuse patch #331 — Didaktik 40/80](https://sourceforge.net/p/fuse-emulator/patches/331)
- [Formát systému MDOS (cygnus.speccy.cz)](https://cygnus.speccy.cz/popis_mdos-format.php)
- [George K. — Rutiny ROM D40](https://docplayer.cz/19362550-George-k-s-rutiny-rom-d40-prirucka-pro-uzivatele-disketovych-jednotek-didaktik-40-didaktik-80-a-didaktik-kompakt.html)
- [MDOS3 for divIDE (velesoft)](https://velesoft.speccy.cz/zx/divide/divide-mdos3.htm)
- [SpectrumNext nextreg.txt](https://gitlab.com/SpectrumNext/ZX_Spectrum_Next_FPGA/-/blob/master/cores/zxnext/nextreg.txt)
- [Klive IDE — I/O ports reference](https://dotneteer.github.io/kliveide/book/app-C-io-ports-reference/)
- [SAMdisk formats](https://simonowen.com/samdisk/formats)
- [MTs — ZX Spectrum & Didaktik, MDOS](https://mts.speccy.cz/info_zxs/infozxs.htm)
- [skills.sh — z88dk target-zxn](https://skills.sh/z88dk/z88dk/target-zxn)
