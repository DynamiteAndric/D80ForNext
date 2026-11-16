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


# ---- blank (formatted) image -------------------------------------------------
# What MDOS 1.0 FORMAT (#13E4) writes: a zeroed boot sector with the drive
# descriptors from #3E00 at 128 (the most common state on the sample disks),
# the descriptor of the formatted drive at 176 (flags, 2 sides, 80 tracks,
# 9 sectors), the disk name at 192, two random bytes at 202 and "SDOS" at 204;
# the FAT filled with #DD and the data sectors marked free; everything else
# (directory and data) is the #E5 format fill.
BLANK_DESCRIPTORS = bytes.fromhex(
    "0118500900185e0900000000" "0118500900185e0900000000"
    "01185e0900185e0900000000" "01185e0900185e0900000000"
    "0118500900185e0900000000")
BLANK_SECTORS = 1440                     # D80: 80 tracks x 2 sides x 9 sectors
DATA_FIRST_SECTOR = DIR_FIRST_SECTOR + 8


def blank_name(name: str) -> bytes:
    """Disk name field: up to 10 characters, padded with spaces."""
    raw = name.encode("latin-1", "replace")[:10]
    return raw + b" " * (10 - len(raw))


def set_fat(data: bytearray, n: int, value: int) -> None:
    sec, k = divmod(n, FAT_ENTRIES_PER_SECTOR)
    base = (FAT_FIRST_SECTOR + sec) * SECTOR_SIZE
    if k == FAT_ENTRIES_PER_SECTOR - 1:
        data[base + 510] = value & 0xFF
        data[base + 511] = ((value >> 8) << 4) | (data[base + 511] & 0x0F)
        return
    o = base + (k // 2) * 3
    if k % 2 == 0:
        data[o] = value & 0xFF
        data[o + 1] = ((value >> 8) << 4) | (data[o + 1] & 0x0F)
    else:
        data[o + 2] = value & 0xFF
        data[o + 1] = (data[o + 1] & 0xF0) | (value >> 8)


def blank_image(name: str = "NoNameDisk", disk_id: bytes = b"\x00\x00",
                tracks: int = 80) -> bytes:
    """A freshly formatted image, as MDOS 1.0 FORMAT leaves it: 80 tracks =
    720K D80, 40 tracks = 360K D40 (2 sides, 9 sectors each)."""
    n_secs = tracks * 2 * 9
    data = bytearray(b"\xE5" * (n_secs * SECTOR_SIZE))
    data[:SECTOR_SIZE] = bytes(SECTOR_SIZE)
    data[128:188] = BLANK_DESCRIPTORS
    data[178] = tracks                   # the formatted drive's descriptor
    data[192:202] = blank_name(name)
    data[202:204] = disk_id[:2]
    data[204:208] = SIGNATURE
    fat = slice(FAT_FIRST_SECTOR * SECTOR_SIZE, DIR_FIRST_SECTOR * SECTOR_SIZE)
    data[fat] = b"\xDD" * (fat.stop - fat.start)
    for n in range(DATA_FIRST_SECTOR, n_secs):
        set_fat(data, n, FAT_FREE)
    return bytes(data)


# ---- writing files -------------------------------------------------------------

def add_file(data: bytearray, type_char: str, name: str, body: bytes,
             param1: int = 0, param2: int = 0x8000, attributes: int = 0x0F) -> None:
    """Add a file to an image in place, laid out as MDOS SAVE * writes it.

    ``param1`` is the start address (``B``) or autostart line (``P``);
    ``param2`` is the program length without variables (``P``) and #8000
    for the other types."""
    if not body:
        raise MdosError("empty files are not supported")
    im = MdosImage(bytes(data))
    raw_name = name.encode("latin-1")
    if not 0 < len(raw_name) <= 10:
        raise MdosError(f"bad file name {name!r}")
    used = {e.index for e in im.entries()}
    if any(e.raw_name.rstrip(b"\x00") == raw_name and e.type == type_char for e in im.entries()):
        raise MdosError(f"file exists: {name}")
    slot = next((i for i in range(DIR_ENTRIES) if i not in used), None)
    if slot is None:
        raise MdosError("directory full")
    n = -(-len(body) // SECTOR_SIZE)
    free = [s for s in range(DATA_FIRST_SECTOR, im.total_sectors) if im.fat(s) == FAT_FREE][:n]
    if len(free) < n:
        raise MdosError("disk full")
    for i, s in enumerate(free):
        chunk = body[i * SECTOR_SIZE:(i + 1) * SECTOR_SIZE]
        data[s * SECTOR_SIZE:(s + 1) * SECTOR_SIZE] = chunk + b"\x00" * (SECTOR_SIZE - len(chunk))
        set_fat(data, s, free[i + 1] if i + 1 < n else FAT_EOF_BASE + len(body) % SECTOR_SIZE)
    e = bytearray(b"\xE5" * DIR_ENTRY_SIZE)
    e[0] = ord(type_char)
    e[1:11] = raw_name + b"\x00" * (10 - len(raw_name))
    e[11:13] = (len(body) & 0xFFFF).to_bytes(2, "little")
    e[13:15] = param1.to_bytes(2, "little")
    e[15:17] = param2.to_bytes(2, "little")
    e[17:19] = free[0].to_bytes(2, "little")
    e[19] = 0
    e[20] = attributes
    e[21] = len(body) >> 16
    base = DIR_FIRST_SECTOR * SECTOR_SIZE + slot * DIR_ENTRY_SIZE
    data[base:base + DIR_ENTRY_SIZE] = e

