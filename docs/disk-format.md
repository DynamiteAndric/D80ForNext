# MDOS disk and snapshot format

Facts verified on real MDOS disks. See also [mdos10-notes.md](mdos10-notes.md) (MDOS 1.0 disassembly), [snap-button.md](snap-button.md) and [research-report.md](research-report.md).

## Image layout

A linear dump of 512-byte logical sectors (80 tracks × 2 sides × 9 sectors for D80; 40 tracks for D40). The boot sector holds the `SDOS` signature.

## FAT

Sectors 1–5, with **341 entries per sector**. Each sector holds 170 triplets `(loA, hiA<<4|hiB, loB)`, plus one extra entry in its last two bytes `(lo, hi<<4|0xD)`.

Values: `0xDDD` = reserved, `0xE00+n` = end of file with n bytes in the last sector (n = 0 means 512).

## Directory

Sectors 6–13, 128 × 32-byte entries:

| Offset | Field |
|---|---|
| 0 | Type |
| 1–10 | Name |
| 11–12, 21 | Length |
| 13–14 | Start address or autostart line |
| 15–16 | BASIC program length |
| 17–18 | First sector |
| 20 | Attributes |

## Snapshot (`S`)

A dump of memory `0x3F80`–`0xFFFF`. The first 128 bytes are the top of the D40's 2K RAM and hold the MDOS NMI register stack:

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

PC is on the program's stack. IM is 1 if I = `0x3F`, otherwise IM 2. Compressed snapshots (SNAPSHOT-PACKER v1.2, R. Kralovic 1992) are unpacked by running their own stub in the Z80 core.
