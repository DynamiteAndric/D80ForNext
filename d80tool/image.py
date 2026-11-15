"""Reader for Didaktik D40/D80 (MDOS) disk images.

Layout (verified on real images, see docs/research-report.md):

* The image is a headerless dump of 512-byte logical sectors, in MDOS
  logical order (sector 0 first).
* Sector 0 is the boot sector: geometry at 177..179, disk name at 192..201,
  signature ``SDOS`` at 204..207.
* Sectors 1..5 hold the FAT. Each FAT sector stores 341 twelve-bit entries:
  170 packed triplets ``(loA, hiA<<4 | hiB, loB)`` followed by one extra entry
  in the last two bytes ``(lo, hi<<4 | 0xD)``.
* Sectors 6..13 hold the directory: 128 entries x 32 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SECTOR_SIZE = 512
FAT_FIRST_SECTOR = 1
FAT_ENTRIES_PER_SECTOR = 341
DIR_FIRST_SECTOR = 6
DIR_ENTRIES = 128
DIR_ENTRY_SIZE = 32
SIGNATURE = b"SDOS"

FAT_FREE = 0x000
FAT_EMPTY_FILE = 0xC00
FAT_RESERVED = 0xDDD
FAT_BAD = 0xDFF
FAT_EOF_BASE = 0xE00

# MDOS file type letters
TYPE_NAMES = {
    "P": "program",
    "B": "bytes",
    "N": "number array",
    "C": "char array",
    "S": "snapshot",
    "Q": "sequential",
}


class MdosError(Exception):
    """Raised for malformed images or broken files."""


@dataclass(frozen=True)
class DirEntry:
    index: int
    type_code: int
    raw_name: bytes
    length: int
    param1: int  # start address (B) or autostart line (P)
    param2: int  # BASIC program length without variables (P)
    first_sector: int
    attributes: int

    @property
    def type(self) -> str:
        return chr(self.type_code) if 32 <= self.type_code < 127 else "?"

    @property
    def name(self) -> str:
        return self.raw_name.rstrip(b"\x00").decode("latin-1")

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type, "unknown")

    @property
    def hidden(self) -> bool:
        return bool(self.attributes & 0x80)


class MdosImage:
    def __init__(self, data: bytes, name: str = "") -> None:
        if len(data) < (DIR_FIRST_SECTOR + 8) * SECTOR_SIZE or len(data) % SECTOR_SIZE:
            raise MdosError(f"{name}: size {len(data)} is not a valid MDOS image")
        self.data = bytes(data)
        self.name = name
        boot = self.data[:SECTOR_SIZE]
        self.signature_ok = boot[204:208] == SIGNATURE
        self.flags = boot[177]
        self.tracks = boot[178]
        self.sectors_per_track = boot[179]
        self.sides = 2 if self.flags & 0x10 else 1
        self.total_sectors = len(self.data) // SECTOR_SIZE

    @classmethod
    def open(cls, path: str | Path) -> "MdosImage":
        path = Path(path)
        return cls(path.read_bytes(), path.name)

    @property
    def disk_name(self) -> str:
        return self.data[192:202].rstrip(b"\x00").decode("latin-1")

    def sector(self, n: int) -> bytes:
        if not 0 <= n < self.total_sectors:
            raise MdosError(f"sector {n} outside image ({self.total_sectors} sectors)")
        return self.data[n * SECTOR_SIZE:(n + 1) * SECTOR_SIZE]

    def fat(self, n: int) -> int:
        sec, k = divmod(n, FAT_ENTRIES_PER_SECTOR)
        base = (FAT_FIRST_SECTOR + sec) * SECTOR_SIZE
        if sec >= DIR_FIRST_SECTOR - FAT_FIRST_SECTOR:
            raise MdosError(f"FAT entry {n} out of range")
        d = self.data
        if k == FAT_ENTRIES_PER_SECTOR - 1:
            return d[base + 510] | ((d[base + 511] >> 4) << 8)
        o = base + (k // 2) * 3
        if k % 2 == 0:
            return d[o] | ((d[o + 1] >> 4) << 8)
        return d[o + 2] | ((d[o + 1] & 0x0F) << 8)

    def entries(self, include_deleted: bool = False) -> list[DirEntry]:
        result = []
        base = DIR_FIRST_SECTOR * SECTOR_SIZE
        for i in range(DIR_ENTRIES):
            e = self.data[base + i * DIR_ENTRY_SIZE: base + (i + 1) * DIR_ENTRY_SIZE]
            if not include_deleted and e[0] in (0x00, 0xE5):
                continue
            result.append(DirEntry(
                index=i,
                type_code=e[0],
                raw_name=bytes(e[1:11]),
                length=e[11] | (e[12] << 8) | (e[21] << 16),
                param1=e[13] | (e[14] << 8),
                param2=e[15] | (e[16] << 8),
                first_sector=e[17] | (e[18] << 8),
                attributes=e[20],
            ))
        return result

    def chain(self, first: int) -> tuple[list[int], int]:
        """Return (sectors, bytes used in last sector) for a FAT chain."""
        sectors: list[int] = []
        s = first
        seen = set()
        while True:
            if s in seen or not 0 < s < self.total_sectors:
                raise MdosError(f"broken FAT chain at sector {s} (start {first})")
            seen.add(s)
            sectors.append(s)
            v = self.fat(s)
            if v >= FAT_EOF_BASE:
                last = v - FAT_EOF_BASE
                return sectors, last if last else SECTOR_SIZE
            if v == FAT_EMPTY_FILE:
                return [], 0
            if v in (FAT_FREE, FAT_RESERVED, FAT_BAD) or v >= 0xC00:
                raise MdosError(f"broken FAT chain: sector {s} -> {v:#05x} (start {first})")
            s = v

    def read(self, entry: DirEntry) -> bytes:
        """Read a file's data. Raises MdosError if the chain does not match its length."""
        sectors, last = self.chain(entry.first_sector)
        size = (len(sectors) - 1) * SECTOR_SIZE + last if sectors else 0
        if size != entry.length:
            raise MdosError(
                f"{entry.name!r}: FAT chain holds {size} bytes, directory says {entry.length}")
        return b"".join(self.sector(s) for s in sectors)[:entry.length]

    def check(self, entry: DirEntry) -> str | None:
        """Return an error message if the file is unreadable, else None."""
        try:
            self.read(entry)
        except MdosError as e:
            return str(e)
        return None
