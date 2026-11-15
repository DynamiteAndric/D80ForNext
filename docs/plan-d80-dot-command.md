# Plan: `.d80` dot command — MDOS 1.0 with a RAM-backed floppy on the ZX Spectrum Next (status 2026-11-15)

## Context
The Python converter (`d80tool`) handles snapshots and single-load programs. It cannot handle software that calls MDOS at runtime: disk menus, multi-load games, and `CAT`/`MOVE`/`SAVE *` utilities. In the converter's bulk check, 47 of 314 programs ended as "reset" or "basic-error" for this reason.

`.d80 image.d80` turns the Next into a 48K Spectrum with a Didaktik 80. It runs the real MDOS 1.0 ROM, with the FDC driver replaced by a copy from the disk image held in Next RAM.

Decisions:
- a NextZXOS dot command;
- **read-only v1**: writes change the RAM copy only;
- the sjasmplus assembler;
- MDOS **1.0** (`Didaktik_40-80_MDOS_v1_91.rom`), supplied by the user.

## Final architecture
The first design (patched 48K ROM in MMU-mapped RAM, MMU trampolines) was dropped after the prototype found three problems:
1. MMU RAM in slots 0–1 is writable (`zxnext.vhd`: `sram_pre_rdonly <= '0'`), and the 48K ROM writes to `#0000`–`#0004`.
2. Programs read the ROM byte at `#0000` as data (an IM 2 `JR` at `#FFFF`).
3. Proxima protections checksum 48K `#0001`–`#0007` and `#0066`–`#006C`.

The final design uses the Next's own hardware:

| Didaktik | Next |
|---|---|
| ROM pages in on an opcode fetch from `#0000`/`#0008` | DivMMC automap: NextReg `#B8` = `#03`, `#B9` = `#03` (always), `#BA` = `#03` (instant) |
| ROM pages out on a fetch from `#1700` | DivMMC off-trap `#1FF8`–`#1FFF` (NextReg `#BB` = `#40`, `#42` since SNAP; **bit 6 = 1 enables it**). Every `JP #1700` becomes `JP #1FF8` (`RET`); since SNAP, it becomes `JP PAGE_OUT`, which turns the DRIVE NMI on and then does `JP #1FF8`. MDOS `#1700` itself becomes `RST #38`, which handles user code that leaves with `JP #1700`. |
| 14K ROM `#0000`–`#37FF` | DivMMC bank 3 under MAPRAM (read-only at `#0000`) holds MDOS A. Bank 4 at `#2000` holds MDOS B. |
| 2K RAM `#3800`–`#3FFF` | the end of DivMMC bank 4 (writable) |
| 48K ROM | the standard ROM in the **alternate ROM** (NextReg `#8C` = `#B0`, ROM3 locked). It is unmodified and read-only. NextZXOS's ROM3 differs from it in 3,333 bytes. |
| WD2797 + disk | the sector ops `#236A`/`#23BE`/`#23D8` copy 512 bytes from the image pages. The page is mapped into MMU slot 7 (or slot 2) with interrupts off and no stack use. |

The patches are generated from `dot/mdospatch.asm`: `tools/build_dot.py` assembles it with fill bytes `#00` and `#FF` and keeps only the bytes that are the same in both builds. No ROM content is stored.

## Status
1. [done] **Driver interface and patch points.** See `docs/mdos10-notes.md`, sections "Driver interface" and "Compatibility findings".
2. [done] **Python model of the runtime.** `d80tool/nextmmu.py` models DivMMC automap and off-trap timing as in `zxnext.vhd`/`divmmc.vhd`, read-only bank 3, NEXTREG and exact R. `d80tool/mdospatch.py` builds the pages. `tools/preview_d80.py` renders the screens.
   - **Results:**
     - `CAT` works on disk 021.
     - The disk menus that failed as tapes now run: 020, 022, 024, 025, 026, 027, 031, 033 and 035.
     - HEXAGONIA, EXPEDICE and MAH JONGG reach the same screens as the original in Fuse.
   - In every run there was no FDC port access, no write to the 48K ROM and no write into the MDOS ROM area.
3. [done] **The dot command.** `dot/d80.asm` builds `dot/build/D80` (about 2.2K). It:
   - parses `[-r mdos] [-4 48rom] image`;
   - allocates pages with `IDE_BANK`;
   - checks CRC32 (MDOS `#545531FA`, 48K `#DDEE531F`);
   - applies the patches;
   - loads the image (up to 104 pages) and checks `SDOS`;
   - commits through a stub at `#5B00`: RETN, alt ROM, DivMMC banks, NextRegs, 48K paging lock, then `JP 0`.
4. [partly done] **Next emulation (ZEsarUX 13, TBBlue + NextZXOS SD image).** `tools/zesarux_next_check.py` and `tools/fat16.py` handle it.
   - Verified: loading, CRC checks, patching, the DivMMC bank contents and every NextReg value. Progress markers in NextReg `#7F` end at `#E3` (`JP 0`).
   - **Not verifiable:** ZEsarUX does not implement the programmable DivMMC entry points (its `TODO_machines`: "make triggering programmable via nextreg 0xB8 - 0xBB"). So the automap never fires there.
   - Two bugs were found and fixed on the way: the patch tables were assembled outside the binary, and `DISP` labels were patched at their run-time address. The NextZXOS interrupt handler crashing while slot 4 held a loader page was fixed by DI during loading.
5. [done 2026-11-15] **Real Next hardware:** the user confirmed that `.d80` works on a real Next.
6. [done 2026-11-15] **Browser association:** the `D80:.d80 "|"` / `D40:.d80 "|"` lines go in `/nextzxos/browser.cfg`. The argument parser accepts `"quoted"` paths, which may contain spaces and `:`. Checked in ZEsarUX with `.d80 "c:/d80/021.D80"`, which reached marker `#E3` and the 48K screen.
7. [done] **Docs:** README section, these notes, and the research report updated.

## Out of scope for v1
- write-back to SD (done since: `-w`, see [plan-d80-sd-write.md](plan-d80-sd-write.md));
- SNAP on the Next NMI button (DivMMC entry `#0066`). Done since: the DRIVE button, see [plan-d80-snap.md](plan-d80-snap.md);
- 128K mode;
- MDOS 2.0 (8272 FDC);
- loading only the used sectors on 1 MB machines;
- a table-driven CRC (the bitwise CRC takes about 0.6 s at 28 MHz).

## Verification
- `python -m unittest discover -s tests -t .`: 16 tests, including a model boot plus `CAT` on disk 021.
- `python tools/build_dot.py` writes `dot/build/patches.json`, `patches.inc` and `D80`.
- `python tools/preview_d80.py <mdos.rom> <48.rom> out/x images/021.d80 --keys R,ENTER,WAIT6,D`
- `python tools/zesarux_next_check.py out/_next --mdos <mdos.rom> --image images/021.d80 --steps "wait:40,shot:boot"`
