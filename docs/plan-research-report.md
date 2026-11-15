# Plan: Research report — running Didaktik D40/D80 images on ZX Spectrum Next

## Context
The user wants to know how Didaktik D40/D80 (MDOS) disk images could be opened and run on a ZX Spectrum Next.
They chose **"Research report only"** (no code yet; Python preferred if a PC tool is built later).
Deliverable: one written report (Claude Doc, or `d:\Project\D40onNext\REPORT.md` if preferred), with sources.

## Key findings (to go into the report)

### Didaktik D40/D80 hardware (MAME `d40.cpp`, Fuse patch #331)
- D40 (5.25" DD) and D80 (3.5" DD) use a WD2797 FDC with MDOS 1.0. The D80 v2 uses a WD37C65 (8272-class) FDC with MDOS 2.0.
- I/O: FDC at 0x81–0x87, control/DOR at 0x89, 8255 PPI at 0x1F/0x3F/0x5F/0x7F, enabled via 0x91/0x99. Ports are decoded with mask 0xF9.
- 14K ROM at 0x0000–0x37FF and 2K RAM at 0x3800. The ROM pages in on opcode fetch at 0x0000/0x0008/0x0066 and pages out at 0x1700. A SNAPSHOT button raises an NMI.
- A D40 disk is readable on a D80, but not always the other way round.

### Image + filesystem format (x128 docs, cygnus.speccy.cz, George K. "Rutiny ROM D40")
- `.d40`/`.d80` files are raw sector dumps with no header: 40 or 80 tracks × 2 sides × 9 sectors × 512 B (720 KB for a D80). 10 sectors per track or up to 82 tracks also occur. x128 also has a `.000` per-file directory variant.
- Sector 0 is the boot sector: geometry at offsets 177–183, disk name at 192–201, signature "SDOS" at 204–207.
- 12-bit FAT with logical sector chains. 0 = free, 0xDDD = reserved, 0xDFF = bad, 0xE00 + n = EOF with n bytes in the last sector.
- Directory in sectors 7–14 (some sources say 6–13): 128 entries of 32 B each. Type at 0 (P/B/N/C/S/Q), name at 1–10, length at 11–12 (+21), start/line at 13–14, BASIC length at 15–16, first sector at 17–18, attributes at 20.
- **S = snapshot files** (from the SNAPSHOT button) are common on game disks and are the easiest content to convert.
- Still to verify against real images: endianness, the logical sector → (track, side, sector) mapping, and the snapshot file layout.

### ZX Spectrum Next capabilities (nextreg.txt, Klive IDE book)
- The Next has no WD/µPD FDC. **I/O traps (NextReg 0xD8) cover only the +3 FDC ports 0x2FFD/0x3FFD**, so Didaktik ports 0x81–0x89 cannot be trapped. Transparent hardware emulation of the D40/D80 is impossible on the stock core.
- Useful features: MMU (RAM can be mapped into 0x0000–0x3FFF), DivMMC automap entry points (NextReg 0xB8–0xBB, which include 0x0000/0x0008/0x0066), the esxDOS/NextZXOS file API, and native loading of TAP, .z80, .sna and .nex files.
- Nobody has published a Next port, dot command or core for D40/D80.

### Options (ranked)
1. **Offline conversion (easy, high payoff).** Extract files from the image and turn S snapshots into .z80/.sna, P/B files into TAP or +3DOS-headed files. BASIC loaders need rewriting from `LOAD *"name"` to tape syntax. Existing tools: SAMdisk reads D80 at the sector level. No ready-made MDOS file extractor was found, so a ~300-line Python tool would be needed.
2. **On-Next `.D80` dot command (medium).** Browse an image on the SD card and load snapshots or BASIC/CODE files directly, using the esxDOS API. z88dk skills exist for this work (`z88dk/z88dk@target-zxn`, `@cpu-z80n`, `@tool-z80asm`; new, 1 install each, but from the official z88dk repo).
3. **High-level MDOS emulation (hard).** Run a patched MDOS ROM in Next RAM via the MMU, with ROM switching at the 0x0008 and 0x1700 hooks and FDC sector routines redirected to esxDOS F_SEEK/F_READ on the `.d80` file. Prior art is MDOS3 for divIDE (SWEET; virtual .D80 drives on a FAT partition), but MDOS3 source is not published and only the MDOS 2.1 source is. This is the only route that supports multi-load software. ROM licensing is unclear.
4. **Hardware/FPGA (very hard).** Plugging a real D40/D80 into the Next expansion bus would likely hit port conflicts and needs ROMCS. A custom Next core with an emulated WD2797 is the alternative.
- Skills search: no ZX/Didaktik-specific skills beyond the z88dk ones above.

## Steps after approval
1. Create the report doc with sections: Summary/verdict · Didaktik hardware · Image & MDOS filesystem format · Next capabilities and limits · Options ranked with effort and compatibility · Recommended path · Open questions · Sources.
2. Fill it from the findings above, with the source links listed below.
3. Reply with a one-line verdict and the link.

## Verification
- Every technical claim cites a source. Unverified items (sector mapping, snapshot layout, directory sector offset) are flagged as open questions.

## Sources
spectrumcomputing.co.uk/entry/1000931 · x128.speccy.cz fileformats · MAME d40.cpp · Fuse patch #331 · cygnus.speccy.cz/popis_mdos-format.php · George K. "Rutiny ROM D40" · velesoft divide-mdos3 · gitlab SpectrumNext nextreg.txt · Klive IDE book appendix B/C · simonowen.com/samdisk/formats · skills.sh z88dk
