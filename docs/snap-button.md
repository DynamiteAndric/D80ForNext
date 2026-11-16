# The SNAP button on the Didaktik D40/D80

Analysis from the ROM disassemblies of MDOS 1.0 (1991) and MDOS 2.0 (1993), the MDOS 2.1 source (`emulators/roms/mdos21-source.wri`, from velesoft.speccy.cz), and the MAME/Fuse emulations of the interface.

## 1. What the hardware does

The D40/D80 has a **SNAP** button connected to the Z80 **/NMI** line. The interface also watches opcode fetches. Its ROM pages in on fetches from `#0000`, `#0008` and `#0066`, and pages out on a fetch from `#1700`.

Pressing SNAP:

1. Raises an NMI. The CPU pushes the PC of the interrupted program **onto that program's own stack** (SP−2) and fetches the opcode at `#0066`. The ROM pages in. The NMI also clears IFF1, but IFF2 keeps the previous interrupt state.
2. The byte at `#0066` becomes `RST 0` (`#C7`):
   - **D40 / D80 with MDOS 1.x (WD2797):** the ROM holds `JP (IX)` at `#0066`, which the disk controller uses as its NMI handler for byte transfers. The interface therefore **forces `#C7` onto the data bus** while the snapshot flag is set; MAME and Fuse emulate this "RST 0 injection". The button works only while the MDOS ROM is not paged in, so it cannot interrupt a disk operation.
   - **D80 v2 with MDOS 2.x (Intel 8272-type FDC):** the ROM itself holds `RST 0` at `#0066`, since this controller does not use NMIs.
3. `RST 0` pushes `#0067` and jumps to `#0000` → `JR #0068`. The handler (identical in MDOS 1.0 and 2.0):
   - `#0068`: saves HL, BC and AF temporarily on the program's stack, using up to 8 bytes **below** its SP (`PUSH AF / POP BC` after `LD A,I`);
   - `LD A,I` / `DI`: the P/V flag now holds IFF2, the interrupt state before the NMI; I and F are stored at `#3EEC`;
   - checks the warm-start signature at `#3EEF`. With a cold machine, MDOS initialises instead;
   - looks up the return address `#0067` in the table at `#019A` → handler `#02E7`;
   - restores HL/BC/AF and DE. On entry to `#02E7`, **all registers hold the program's values and SP points at its PC**.

## 2. What MDOS saves (`#02E7` → `#0341`)

```
LD (#3FFE),SP ; LD SP,#3FFE          ; program SP -> #3FFE, stack in D40 RAM
PUSH AF,BC,DE,HL ; EXX ; EX AF,AF'
PUSH AF',BC',DE',HL' ; PUSH IX ; PUSH IY
PUSH (#3EEC)                         ; I (high byte) + F from LD A,I (low byte, P/V = IFF2)
IM 1 ; flag #3EEE = #FF              ; "snapshot in progress"
name := "SNAPSHOTnn", type S         ; nn = counter at #3E61 (00..99)
EI
save #3F80..#FFFF (DE = #C080 = 49280 bytes) via #1A00
```

- **No menu:** MDOS 1.0/2.0 save immediately to the current drive. MDOS 2.1 adds an NMI menu: snapshot, `FOTO` (the screen saved as a 6912-byte `B` file), return, and so on.
- **Errors:** if saving fails (full disk, no disk), the RST 8 handler sees `#3EEE` ≠ 0 and jumps to `#034A`, which returns to the program.
- **Afterwards:** `#034A` → `#034D` restores the registers and the program continues, so pressing SNAP doesn't stop the game.

### File layout (49280 bytes, type `S`)

| File offset | Address | Contents |
|---|---|---|
| 0–103 | `#3F80`–`#3FE7` | Rest of the top of D40 RAM (MDOS work area; MDOS 2.1 stores SYSFLAG at `#3FE7`) |
| 104 | `#3FE8` | F from `LD A,I`: bit 2 (P/V) = IFF2; MDOS 2.1 also uses bits 1 and 4 |
| 105 | `#3FE9` | **I** |
| 106–107 | `#3FEA` | IY |
| 108–109 | `#3FEC` | IX |
| 110–111 | `#3FEE` | HL' |
| 112–113 | `#3FF0` | DE' |
| 114–115 | `#3FF2` | BC' |
| 116–117 | `#3FF4` | AF' (F', A') |
| 118–119 | `#3FF6` | HL |
| 120–121 | `#3FF8` | DE |
| 122–123 | `#3FFA` | BC |
| 124–125 | `#3FFC` | AF (F, A) |
| 126–127 | `#3FFE` | **SP**, which points at the saved PC |
| 128–49279 | `#4000`–`#FFFF` | The whole 48K RAM |

## 3. Loading a snapshot (`#0394` → `#034D`)

```
LD SP,#3F80 ; IX=#3F80 ; DE=#C080 ; CALL #19AE    ; load the file back to #3F80
DI ; LD SP,#3FE8 ; POP AF                         ; A=I, F=flags
JP PE,...        ; IFF2 was set -> variant ending with EI
LD I,A ; CP #3F ; JR Z,+2 ; IM 2                  ; IM 2 only when I != #3F
POP IY,IX,HL,DE,BC,AF ; EX AF,AF' ; EXX ; POP HL,DE,BC,AF
LD SP,(#3FFE) ; [EI] ; JP #1700                   ; page out -> RET (48K ROM) -> PC from stack
```

## 4. Converting to a standard snapshot

This is exactly the .SNA convention: registers in a header, PC on the stack. Conversion is lossless, apart from information MDOS never saves:

| Item | MDOS | Conversion |
|---|---|---|
| A, F, BC, DE, HL and alternates, IX, IY, SP | saved | copied 1:1 |
| PC | on the stack at SP | `.sna`: left on the stack; `.z80`: read from the stack and SP+2 |
| I | saved | copied |
| IFF1/IFF2 | P/V of `LD A,I` = IFF2 before the NMI | IFF1 = IFF2 = P/V |
| IM | **not saved** | like MDOS: IM 1 if I = `#3F`, else IM 2 (MDOS 2.1 additionally lets the user override this with keys) |
| R | not saved | 0. It matters only for rare protections that decrypt using R |
| Border | not saved | taken from the BORDCR system variable (`#5C48`) |
| 128K state (7FFD, AY, other banks) | not saved | the file is 48K only. A 128K program snapshotted in its 128K mode cannot be restored by MDOS either |
| 8 bytes below SP | overwritten by the handler (`#0068`) | harmless: they lie below the stack top |

Compressed snapshots made by **SNAPSHOT-PACKER v1.2** (R. Kralovic 1992, `!KOMPRESOR` on disk 041) or **PACKSNAP** (on disk 027) are shorter `S` files. They contain a fake register block whose PC points at a self-extracting stub, followed by RLE data. The stub restores the real register block to `#3F80` and finally jumps to `#034D`. `d80tool` runs the stub in its Z80 core and so recovers the original 49280-byte snapshot.

### Conversion

The `convert` and `snap` commands that turned `S` files into `.z80`/`.sna` were removed together with the PC converter (2026-11-16). `d80tool.snapshot` (`parse`, `to_z80`, `to_sna`) is still there; the tests and `tools/fuse_snap_roundtrip.py` use it.

### Verification

Checked against the original disks in Fuse with MDOS 1.0 (`LOAD *"name"`): FALINGDOWN and 027 SNAPSHOT00 look the same. In ZEsarUX: Turrican, Saboteur 1 and Saboteur 2 (all packed) and Falling Down run.

### SNAP on the ZX Spectrum Next (`.d80`)

On the Next, the **DRIVE** button (DivMMC NMI) is the SNAP button. MDOS runs the same save code as above. The mechanism and its limits are in [plan-d80-snap.md](plan-d80-snap.md). In the Python model (`tests/test_d80dot.py`, `TestSnap`):
- SNAP in HEXAGONIA saves `SNAPSHOT00` with exactly the registers, PC, SP, IFF and RAM of the moment of the press;
- the game continues, and a second press gives `SNAPSHOT01`;
- the converted snapshot also runs in a plain 48K machine.

### Round trip on the emulated hardware (Fuse)

`tools/fuse_snap_roundtrip.py` repeats the full sequence on a copy of the disk:

1. MDOS boots in Fuse and the program starts (HEXAGONIA from disk 021).
2. **Machine › Didaktik SNAP** is pressed.
3. MDOS writes `SNAPSHOT00` (49 280 B) to the disk, and the game continues; the title scroller keeps moving.
4. The disk image is saved through **Media › Disk › Didaktik 80 › Drive A › Save**.
5. `d80tool.snapshot` converts the snapshot.

The snapshot caught the program at the entry of its IM 2 interrupt (PC=`#FFFF`, I=`#3A`, interrupts disabled because the interrupt had just been accepted). In ZEsarUX the converted `.z80` continues exactly where it was snapped: the HEXAGONIA title screen with its scroller running.
