# MDOS 1.0 (1991) — disassembly notes

ROM: `Didaktik_40-80_MDOS_v1_91.rom` (14 336 bytes, from cygnus.speccy.cz; kept in `emulators/roms/`, not in git). Disassembled with `d80tool.z80dis`:

```sh
python -c "from d80tool.z80dis import listing; m=bytearray(65536); r=open('emulators/roms/Didaktik_40-80_MDOS_v1_91.rom','rb').read(); m[:len(r)]=r; print(listing(m,0x0000,0x0400))"
```

## Paging and entry points

| Address | Contents | Meaning |
|---|---|---|
| `0000` | `NOP` / `JR #0068` | Reset and snapshot entry. The snapshot button (Fuse injects `RST 0` at `0x0066`) arrives here. |
| `0008` | `LD HL,(CH_ADD)` / `JP #0215` | RST 8 error hook: entry for the BASIC syntax extensions (`LOAD *`, `CAT`, …) |
| `0010`–`0020` | `RST #28` + `DEFW` | RST 10/18/20 forwarded to the 48K ROM |
| `0028` → `003B` | — | **"Call 48K ROM" mechanism:** `RST #28` followed by `DEFW addr`. The ROM pages out via `JP #1700`. |
| `0038` | `JP #25CE` | IM 1 interrupt while MDOS is paged in |
| `0066` | `JP (IX)` | NMI: FDC DRQ/INTRQ byte transfer. The read/write loops set IX to their handler. |
| `0068` | — | Reset/snapshot handler. It checks a warm-start signature at `#3EEF` (8 bytes `H XOR L`). It then dispatches on the return address through the table at `#019A`; a `*` byte after the call leads to `#01B0` (a debug "print number" helper). |
| `1700` | `RET` | Page-out point: fetching `#1700` disables the MDOS ROM, so the `RET` executes from the 48K ROM side. |

## Tables

`#019A`: (return address → handler) for entries through `0000`:

| Return address | Handler | Notes |
|---|---|---|
| `22C3`, `27A6` | `0DD9` | |
| `25AC` | `0E23` | |
| `27AD` | `0E1E` | |
| `0067` | `02E7` | Snapshot NMI: saves registers, then shows the save menu |

`#05FF`: 8-byte records `(T_ADDR, RST 8 return address, stack depth, handler)`. MDOS matches the state of the 48K ROM interpreter at the moment it reports an error, and so recognises which statement failed syntax or run-time checks. For example, `T_ADDR=#1AB2` leads to `#06C1`; with return `#1C8B` (CLASS-xx checks) the handlers are `#06F0`, `#086F`, `#0A50`, and so on. **There is no separate machine-code API.** Machine code reaches MDOS by running BASIC statements (or by calling ROM routines directly).

## Snapshot save and restore (confirms the converter)

`#02E7`, the save path:
1. `LD (#3FFE),SP` / `LD SP,#3FFE`.
2. Push AF, BC, DE, HL, then AF', BC', DE', HL' (after `EXX`/`EX AF,AF'`), then IX, IY.
3. Push `(#3EEC)`, which holds I and F from `LD A,I` (stored at `#0070`).
4. Save `#3F80`–`#FFFF` (49 280 bytes) as type `S`.

`#034D`, the restore (also the jump target of SNAPSHOT-PACKER):

```
DI ; LD SP,#3FE8 ; POP AF        ; A = I, F = flags from LD A,I
JP PE,#0376                      ; IFF2 set -> variant that ends with EI
LD I,A ; CP #3F ; JR Z,+2 ; IM 2 ; IM 2 only when I != #3F
POP IY ; POP IX ; POP HL ; POP DE ; POP BC ; POP AF ; EX AF,AF' ; EXX
POP HL ; POP DE ; POP BC ; POP AF
LD SP,(#3FFE) ; JP #1700         ; page out, RET from the 48K ROM -> PC from the stack
```

`#0970` is a lone `RET` (the end of the version-text printer). SNAPSHOT-PACKER uses `CALL #0970` / `DEC SP` ×2 / `POP HL` to find its own address, which is why `d80tool.snapshot` treats it as a plain `RET`.

## System variables in D40 RAM (#3800–#3FFF)

| Address | Meaning |
|---|---|
| `#3E60` | Debug flag |
| `#3E61` | Snapshot counter (the "SNAPSHOTnn" name) |
| `#3E66` | Saved DE |
| `#3E74` | Save start address |
| `#3E80` / `#3E8A` | Current file name buffers |
| `#3EEC` | I/F from `LD A,I` at the NMI |
| `#3EEE` | "Snapshot in progress" flag (non-zero → `#034A`) |
| `#3EEF` | 8-byte warm-start signature |
| `#3EF7` | Flag byte used by the error path |
| `#3F80`–`#3FFF` | Register stack saved into snapshots |

## Results verified against the original (Fuse + MDOS 1.0)

- **Snapshots:** FALINGDOWN and 027 SNAPSHOT00 look the same as the converted `.z80` files.
- **TAPs:** EXPEDICE and MAH JONGG failed only because of a converter bug. Removing `*` from `LOAD *"x"` shortened the BASIC program by one byte and shifted the machine code stored after it, so `USR` addresses missed by one. The converter now replaces `*` with a space (the ROM skips spaces), and both reach the same Proxima intro screens as the originals.

## Driver interface and patch points (for the `.d80` dot command)

Found while building `dot/mdospatch.asm`; all addresses are MDOS 1.0 (1991).

**FDC driver.** All WD2797 and control-port access (ports `#81`–`#89`, `#91`) is in `#2216`–`#25E9`, and the code ends at `#25EF`. `#2608`–`#37FF` is unprogrammed EPROM (an FF/00 noise pattern) that no code references, which leaves room for new code.

| Entry | Called from | Meaning |
|---|---|---|
| `#2216` | `#0125` (cold init) | Drive init: steps to track 0, sets descriptor bit 0 ("present"), (IX+3)/(IX+6) = 40/80 |
| `#2296` / `#229C` / `#22A2` | many | Multi-sector write / format / read. They set `#3E63` = `JP op` and loop at `#22B2`: `HL` = buffer, `B` = logical track (cyl·2+side), `C` = sector 0..spt−1, `D` = count, `IX` = drive descriptor (`#3E00` + 12·drive). After each sector, `C` += 1 and wraps at (IX+3) = sectors per track, and `B` += 1. |
| `#236A` / `#23BE` / `#23D8` | `#3E63` | Per-sector read / write / format. They return `C` = 0 for OK, otherwise the WD status, with `B` = error class (4 = not ready). They end with `EI`. |
| `#256D` | `#1F31`, `#1F52` | "Disk in drive A?" (measures index pulses). Returns NZ when present. |
| `#2340` / `#234B` | init, `#1384` | Send an FDC command / restore. Returns the status in A (bit 2 = track 0). |
| `#25BC` | — | `OUT (#89),A` plus the shadow at `#3EE9` |
| `#25CE` | `#0038` | IM 1 handler while MDOS is paged in (motor time-out counter `#3EE2`) |

Logical sector = `B`·spt + `C`, which is the linear sector order of the `.d80` images (see `d80tool/image.py`).

**Paging points.** There are 12 sites with `JP #1700`: `#005D` (end of the "call 48K ROM" helper at `#003B`), `#012C` (cold-init exit through `LD SP,#1019` — a stack inside the 48K ROM that "returns" to 48K `#0001`), `#0182`, `#01C5`, `#02C8`, `#02E4`, `#0373`, `#0391` (snapshot restore), `#0E09`, `#0E1B`, `#1061` and `#1968`. `#1700` itself is a `RET`, and `#1701+` is a data table. Some disk software (for example disk 022) calls MDOS routines directly and leaves with its own `JP #1700`.

**MDOS RAM.** All of `#3800`–`#3FFF` is in use: buffers at `#3800`/`#3A00`/`#3C00`, drive descriptors at `#3E00`, and system variables at `#3E60`–`#3EFF`. There is no RETN anywhere in MDOS.

**Drive in file names.** `#10E2` looks at the part of a name before `:` (copied to `#3E80`). A single letter A–D selects drive 0–3 (`#3E6B`); anything else is matched against the disk names in the drives (`#1F16` scans drives 0–3). So `LOAD *"b:name"` and `CAT "b:"` use drive B:.

**FORMAT (`FORMAT "a:name"`, handler `#1345`).** It asks `(Proceed = P)`, copies descriptor bytes 5–7 to 1–3, then calls the format op `#229C` once per track (`#1394`: B = track 0…tracks·sides−1, C = that count, D = 1); the op at `#23D8` writes a whole track (WD Write Track, track image built at `#4000`). In `.d80` this op is replaced by `sec_format`, which fills every sector of track B with `#E5` (and, with `-w`, writes them to the card); see [plan-d80-sd-write.md](plan-d80-sd-write.md). It then verifies every sector with a direct `CALL #236A` (`#13B8`), which must return B = 2 (class "read"); C bits `#18` mark a bad block. `#13E4`–`#147F` builds the boot sector in the buffer at `#3C00`:
- zeros; at 128, the 48 bytes from `#3E00` (drive descriptors); at 176, the 12-byte descriptor of the drive being formatted;
- the name from `#3E8A` at 192; two `LD A,R` bytes at 202–203 (disk ID; there is a `HALT` between them); `SDOS` from `#0F10` at 204.

It writes the boot sector, then FAT sectors 1–5 filled with `#DD`, and marks the data sectors free through `#1D1E` (set a FAT entry). Directory and data keep the `#E5` format fill. `d80tool.image.blank_image` and `.d80 -n` reproduce this. MDOS 1.0 initialises only drives 0 and 1 (`#2273 CP #02`); the default descriptors at `#0EF8` are 2 × 12 bytes.

**SNAP patch points (`.d80`).**
- `#0066` `JP (IX)` becomes `RST 0`; there is no FDC NMI any more.
- `#0000` `NOP/JR #0068` becomes `JP snap_entry0`.
- `#000B` `JP #0215` becomes `JP snap_entry8`.
- The page-out sites now go to `PAGE_OUT`, which turns the DRIVE NMI on and then does `JP #1FF8`.
- The new code sits in the unused EPROM area at `#3300`, after the SD extent table. See [plan-d80-snap.md](plan-d80-snap.md).
- The snapshot handler at `#0068` uses 8 bytes below the program's SP: `EX (SP),HL`, `PUSH BC`, `PUSH AF`, then `PUSH AF/POP BC` after `LD A,I`.

**`#1FF8`–`#1FFF` holds live code** (the tail of a loop, reached only by `JR NZ,#1FF8` at `#1FEE`). `.d80` relocates it, because that range is the DivMMC page-out trap.

## Compatibility findings (from running real disks in `d80tool.nextmmu`)

- **Protections check the 48K ROM.** EXPEDICE (Proxima) XORs 48K `#0001`–`#0007` and `#0066`–`#006C` and expects `#B8`. If the check fails, it wipes memory. The 48K ROM must stay byte-identical, so the Didaktik's page-on-fetch is reproduced with DivMMC automap and the ROM is not patched.
- **The ROM byte at `#0000` is data.** HEXAGONIA's IM 2 handler at `#FFFF` is `JR`, and its displacement is the ROM byte at `#0000` (`#F3` → `#FFF4`). Paging must react only to opcode fetches.
- **Writes to the ROM area must be ignored.** The 48K calculator writes to `#0000`–`#0004` at `#33E1`, and loaders run with SP inside the ROM.
- **The R register.** Exact R counting (two M1 cycles for prefixed opcodes) is needed for Proxima's R-based wipe loop to behave as on real hardware.

**SD write-through (`.d80 -w`).** After the RAM copy is updated, the replaced sector ops write the same sector to the card (CMD24, `dot/sdspi.asm`). They return `BC = #0340` if the card refuses the write. In the error table at `#22B2`, class 3 with WD bit 6 is `Disk is write protected (Retry = R)`. Class 4 bit 1 (`#0402`) would show `Bad device type`, and class 2 bit 0 would show `Internal error`.
