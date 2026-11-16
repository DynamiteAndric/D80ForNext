# Plan: SNAP button for the `.d80` dot command (status 2026-11-15: done)

## Goal
On the Didaktik, SNAP raises an NMI and MDOS saves `SNAPSHOTnn` (type `S`, 49 280 B) to the current drive, then the program continues (see [snap-button.md](snap-button.md)). The same should happen on the Next when the **DRIVE** button (DivMMC NMI, also the F10 hotkey) is pressed while `.d80` runs. The snapshot is written into the image: only to the RAM copy without `-w`, and to the SD card with `-w`.

## Next hardware (from `zxnext.vhd` / `divmmc.vhd` / `nextreg.txt`)
- NextReg `#06` bit 4 enables the DivMMC NMI from the DRIVE button. `hotkey_drive` is an edge, so a press while the bit is 0 is lost, not latched.
- NextReg `#BB` bit 1: on that NMI, DivMMC automaps **instantly** on the opcode fetch from `#0066`, so the opcode comes from DivMMC bank 3 (MDOS A).
- `nmi_divmmc` is set by the button **even while DivMMC is already mapped**, because only the Multiface path checks `divmmc_nmi_hold`. Without a guard, a press during `LOAD *`/`CAT` would run the snapshot code in the middle of MDOS. The real D40 ignores the button while its ROM is paged in.
- The NMI state machine holds until `divmmc_nmi_hold = automap or button_nmi` drops. Leaving MDOS through the `#1FF8` off-trap ends it, so **no RETN is needed**. RETN would also unmap DivMMC.

## Design
| Piece | Change |
|---|---|
| MDOS `#0066` | `JP (IX)` → `RST 0`, as on the D80 v2. The FDC NMI is gone because the driver is replaced. `RST 0` pushes `#0067` and enters the unchanged snapshot path `#0068` → `#02E7`. |
| MDOS `#0000` | `NOP / JR #0068` → `JP snap_entry0`: SNAP off (`NEXTREG #06`), then `#0068` |
| MDOS `#000B` | `JP #0215` → `JP snap_entry8`: SNAP off, then `#0215` |
| page-out | every `JP #1700` site (and the RST #38 catch-all) goes to `page_out`: SNAP on, then `JP #1FF8` (RET in the off-trap) |
| `.d80` | reads NextReg `#06`. Its value with bit 4 cleared and with bit 4 set is written into the three `NEXTREG #06,n` instructions in MDOS B. The stub turns SNAP off before it touches DivMMC and writes `#BB = #42`. MDOS's own cold-start page-out turns SNAP on. |

So SNAP is enabled only while MDOS is paged out. That is the Didaktik behaviour, including the case where MDOS calls the 48K ROM (`RST #28`).

**Race windows.** An NMI may still be accepted a few instructions after MDOS was entered or before it leaves: on the instruction at `#000B`, `snap_entry0`, `snap_entry0+4`, `snap_entry8`, `snap_entry8+4`, `page_out_j`, or the `RET` at `#1FF8`. `snap_entry0` sees `#0067` as its return address and checks the interrupted PC against these 7 addresses. On a match, the press is ignored:
- the registers are restored;
- IFF1 is set again from IFF2 (`LD A,I`, `EI` + `RET`, without RETN, which would unmap MDOS);
- an NMI inside the page-out window resumes at `PAGE_OUT`, so SNAP is turned on again.

A user program that happens to run 48K ROM code at one of these addresses at the moment of the press simply gets no snapshot, and the user can press again.

## Status
- [done] Patches (`dot/mdospatch.asm`), loader and stub (`dot/d80.asm`), model and tests (`TestSnap`; the whole suite passes).
- [done] Bug found on the way, in `-w` mode: `sd_put` ran on the caller's stack. The snapshot's first sector (`#3F80`–`#417F`) contains MDOS's stack, so the card got different bytes from the RAM copy. The SD write now runs on a private stack at `#2880`–`#28FF`, switched before the `CALL`.
- [done 2026-11-15] **Real Next hardware:** the user confirmed that SNAP works on a real Next, including:
  - with `-w`, the snapshot loads back after a reset;
  - a press during `CAT` / `LOAD *` is ignored.

## Verification
- `tools/nextmmu.py` models NextReg `#06`, the button NMI, the instant `#0066` automap and the NMI hold.
- Tests:
  - SNAP while HEXAGONIA runs → `SNAPSHOT00` (type `S`, 49 280 B) is in the image directory, the program continues, and the converted `.z80` holds the registers;
  - with `-w`, the snapshot also lands on the model SD card;
  - SNAP while MDOS is paged in is ignored, and a press in a race window is ignored.
- After the press, the Next holds further NMIs until DivMMC unmaps. The test also covers presses lost to that hold.
- Real Next: press DRIVE in a game, then `CAT`, then `LOAD *"SNAPSHOT00"`.
