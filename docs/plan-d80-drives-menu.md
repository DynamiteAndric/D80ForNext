# Plan: `.d80` — blank image, drive B:, NMI menu (status 2026-11-15: done; all phases, including the 128-style menu, verified on a real Next)

## Context
`.d80` handled one disk (A:), writing to SD (`-w`) and SNAP on the DRIVE button, all verified on a real Next. The user wanted:
1. to create a blank (formatted) image that can be written to;
2. to use more than one virtual drive at a time;
3. an NMI menu with D80 controls.

User decisions:
- a short press of DRIVE = SNAP (as before), holding it = menu;
- at most **2 disks** (A: + B:), loaded at start;
- the Next has 2 MB.

### Feasibility (checked in the ROM and the sample images)
- **Blank image: yes, easy.** FORMAT in MDOS 1.0 (`#13E4`–`#147F`) writes:
  - boot sector: zeros; at offset 128 the drive descriptors (`#3E00`, 48 B); at 176 the descriptor of the current drive (12 B); at 192 the name (10 B); at 202–203 two random bytes (`LD A,R`); at 204 `SDOS` (from `#0F10`);
  - FAT (sectors 1–5): filled with `#DD`, entries for data sectors 14…1439 = 0;
  - directory (sectors 6–13) and data: `#E5`.

  The boot sectors of the samples (021, 036, 040) match this.
- **More drives: yes, but the limit is 2.** MDOS 1.0 initialises only drives 0 and 1 (`#2273 CP #02`), and the default descriptor table at `#0EF8` has 24 B, i.e. two drives. More drives would mean rewriting MDOS, which is not needed. 2 × 90 pages + 4 + menu fit into 2 MB.
- **NMI menu: yes.**
  - It starts from the same path as SNAP (`snap_entry0`; the NMI is enabled only outside MDOS).
  - The length of the press comes from NextReg `#10` bit 1 (DRIVE held).
  - The menu code runs from its own 8K page mapped into slot 7, with interrupts off and its own stack (the same trick as `sec_op`).
  - No NextZXOS API is needed at run time.

## Phase 1 — blank image (`-n`)
**Plan**
- **CLI:** `.d80 -n new.d80` creates a 720K D80 image (80 tracks, 2 sides, 9 sectors) and starts it.
  - Disk name = file name without extension, at most 10 characters.
  - If the file exists, the command stops with an error and overwrites nothing.
  - Combines with `-w` (without it a blank image is of little use, but it is allowed).
- **`dot/d80.asm`:** a new routine `make_blank`: `F_OPEN` creating a new file, then the boot sector, 5 FAT sectors, 8 directory sectors and `#E5` data; then `F_CLOSE` and the normal path (open → `get_map` → load), so `-w` works unchanged. New messages: "File exists", "Write error".
- **`d80tool`:** `python -m d80tool new name.d80 [--name X]` with the same logic (`d80tool/image.py`: `blank_image()`), as the reference for the tests.

**Result**
- `d80tool.image.blank_image` and `python -m d80tool new` are done. The boot sector is byte-identical with disk 036, formatted by MDOS (given the same disk ID).
- `.d80 -n`: `make_blank` (`F_OPEN` with `#06` = write + create new only; error 18 prints "File exists"). System sectors are written one at a time, the `#E5` data in 8K blocks from a temporary page; `blank_sector` generates the sector contents.
- A `*.d40` name creates a 360K D40 disk (40 tracks), see [plan-d80-dot-command.md](plan-d80-dot-command.md).
- Tests `TestBlank`: layout; the asm `blank_sector` run in the Z80 model gives the same sectors as Python; MDOS in the model does `CAT` and `SAVE` on a blank image with `-w`, the file reads back and the card matches the RAM copy.
- [done 2026-11-15] Verified by the user on a real Next.
- Not done (optional): compare with a disk formatted by the real MDOS FORMAT in Fuse.

## Phase 2 — drive B:
**Plan**
- **CLI:** `.d80 [-w] [-n] a.d80 [b.d80]`; the second positional argument is B:.
- **Driver data in MDOS B (`dot/mdospatch.asm`):** the tables are split per drive (`img_secs`, `page_table`, `sd_n`, `sd_cs`, `sd_blk`). B: gets its own tables at `#2608`–`#26FF` and its extent map (`SD_MAP_B`, 768 B) at `#3400`–`#36FF`. `ASSERT`s guard every boundary.
- **Driver:** `sec_op`, `disk_ready`, `#234B` (track 0) and `sd_put` use the tables of the selected drive; a drive without an image still returns `#0401` (not ready).
- **Loader:** the image load loop runs again for B:; `MAX_PAGES` stays 104 per drive.

**Result**
- Syntax in MDOS 1.0: routine `#10E2` turns a single letter A–D before `:` into the drive number (`#3E6B`); otherwise it looks for a disk by name. So it is `CAT "b:"` or `LOAD *"b:name"`.
- Deviation from the plan: the driver does not use an `IY` pointer, it swaps tables. The current set (`img_secs`, `fix_pg2/7`, `page_table`; `sd_n/cs/blk`; the pointer `sd_mapp`) belongs to drive `cur_drv`. The other set is at `oth_tab`/`oth_sd`/`oth_mapp` (`#2610`). `drv_sel` swaps them when the drive changes (113 B, about 2 ms); the extent maps stay in place (`SD_MAP` `#3000`, `SD_MAP_B` `#3400`).
- The drive for sector ops is the active drive `#3E6B` (`act_sel`), not the incoming IX, just like the original `DRWSU` (`#2493`), which sets IX from `#3E6B` through `DRVCMP`. (Fixed 2026-11-15: selecting by IX gave "Device unavailable, 3:1" in 035-X-MAGAZIN, which calls the sector loop with IX = `#3E0C` while A: is active. `disk_ready` was fixed at the same time: it passed the remainder `H or L` to `DESC_SEL` instead of the drive number.) Only `#234B` (init, IX walks the descriptors) still selects by IX.
- `drv_present` is used by `#234B` and `disk_ready`. A drive without an image reports "not ready".
- Loader: `load_drive`/`store_drive` for A: and B:. Without a second image, B: gets `img_secs` = 0, because the area at `#2610` otherwise holds EPROM noise.
- Deviation from the plan: `-n` applies to the image name that follows it (`.d80 -w a.d80 -n b.d80`), so "File exists" keeps working.
- Tests `TestDriveB`: `CAT "b:"`, `SAVE` and `LOAD` on B: with `-w` (A: unchanged, both cards match their RAM copies); a blank D40 in B:; without B:, `CAT "b:"` reports an error and A: keeps working; sector ops follow the active drive.
- ZEsarUX (`tools/zesarux_next_check.py --image-b`): `.d80 -w 021.d80 diskb.d80` reaches `E3` with correct B: tables; `.d80 -w 021.d80 -n /d80/newdisk.d80` creates a file identical to `blank_image` and loads it into B:. ZEsarUX also found a bug (marker `#81`): the parser overwrote the command-line pointer at the second name. Fixed.
- [done 2026-11-15] Verified by the user on a real Next.

## Phase 3 — NMI menu (hold DRIVE)
**Plan**
- **Press detection** in `snap_entry0`: read NextReg `#10` bit 1 in a timed loop of about 0.5 s (interrupts are off). Released early → SNAP (`jp #0068`); still held → menu.
- **Pages** (allocated and filled by the loader): MENU (menu code + 768 B font copied from the 48K ROM `#3D00`, which is not visible while MDOS is mapped) and SCR (screen backup). The page numbers go into MDOS B.
- **Menu entry** (code in MDOS B): save the program's registers, map the menu page into slot 7, switch SP, `call #E000`; on return map the program's page back, restore the registers and IFF, or continue into SNAP.
- **Disk change:** MDOS may keep the FAT or directory in its buffers at `#3800`/`#3A00`/`#3C00`. After a swap it must re-read them. This was the main risk of the phase.

**Result**
- Press detection in `snap_entry0` (MDOS B): with CAPS SHIFT held, the menu opens at once; otherwise NextReg `#10` bit 1 (the physical DRIVE button, `i_SPKEY_BUTTONS`) is read for about 0.4 s. Release → SNAP. 10 B are written below the program's SP, as with MDOS `#0068` (2 B NMI + 8 B).
- `menu_entry` (MDOS B, `#338F`):
  - the program's registers go into variables in MDOS B (`m_af` … `m_hl2`), not onto the program's stack; IFF comes from `LD A,I`;
  - the menu page goes into slot 7, SP to its top, `call #E000`;
  - back: `EI` according to IFF2, then `JP PAGE_OUT`; snapshot as for a short press (`#0067` + `#0068`); reset (corrupt the signature at `#3EEF`, `JP #0000`).
- `dot/menu.asm` (829 B, `build/menu.bin`; the loader copies it into its own page through `INCBIN`):
  - font copy at `#EC00`, backup of screen rows 6–17 at `#F000`;
  - disk names from the boot sector (the image page is mapped into slot 6 for a moment);
  - swap = `cur_drv xor 1` (the tables stay in place);
  - after a change: `#3E6E` = `#3E71` = `#FF` and bit 0 of the descriptors (`#3E00`/`#3E0C`) set by whether the drive has an image, so MDOS re-reads the disk;
  - a change is refused while `#3E6C` (unsaved FAT) is set.
- Look: like the ZX Spectrum 128 / NextZXOS menu. A window in columns 8–23 (16 characters) and rows 7–15, title "D80" (like "128"), black title bar with the rainbow stripes (diagonal-glyph cells, ink = left colour, paper = right colour), blue rows with the disk names, white body with a frame, cyan selection bar.
- Controls: cursor (`7`/`6`, `Q`/`A`) and `ENTER`; shortcuts `X` (swap A: ↔ B:), `S` (snapshot), `R` (reset), `SPACE` (back).
- Deviations from the plan:
  - CAPS SHIFT + DRIVE always opens the menu, as a fallback in case bit 1 of NextReg `#10` does not report the F10 hotkey;
  - the border is not changed, so it needs no restoring;
  - the NextReg select port `#243B` is not restored (48K programs don't use NextRegs);
  - eject/insert (`1`/`2`) and the `-w` line were removed after the hardware test at the user's request: with two images loaded at start they are pointless.
- Tests `TestMenu`: back leaves the program untouched (registers, PC, screen, RAM); a short press is still SNAP; CAPS SHIFT opens the menu; snapshot from the menu; swap by shortcut and cursor, with `CAT` on both drives showing the swapped directories and `SAVE` on B: afterwards; cursor keys; swap into an empty drive; reset.
- ZEsarUX: the loader allocates the menu page and fills it with exactly `menu.bin` + the font; NextReg `#BB` = `#42`.
- [done 2026-11-15] Verified by the user on a real Next (holding DRIVE opens the menu).

## Model and tests
- `d80tool/nextmmu.py`: two drives (`PageMap` for A: and B:); NextReg `#10` bit 1 (`drive_held` with a step count) and port `#243B`; the MENU/SCR pages; `press_snap(hold_steps=…)`.
- `tests/test_d80dot.py`: `TestBlank`, `TestDriveB`, `TestMenu`. The whole suite (43 tests) passes.
- Menu screens can be previewed with `tools/preview_d80.py` (`--keys` with the `HOLD` action).

## End-to-end check on a real Next
- `.d80 -w -n /d80/new.d80` → `SAVE *"x"` → reset → `.d80 /d80/new.d80` → `CAT` shows `x`.
- `.d80 -w /d80/021.d80 /d80/new.d80` → `LOAD` from A:, `SAVE` to B:, `CAT` on both drives.
- Short press of DRIVE → `SNAPSHOTnn` as before. Hold → menu → `X` → `CAT` shows the swapped disks → `SPACE` → the program continues with the same screen.

The user confirmed each phase on the Next (blank image, B:, menu). Individual results of the steps above were not recorded separately.
