"""Apply the .d80 patches (dot/mdospatch.asm) to a user-supplied MDOS ROM.

The patch data comes from ``dot/build/patches.json``, written by
``tools/build_dot.py``. It contains only the new bytes, so the copyrighted
MDOS ROM is never stored with the tool.

``build_pages`` returns what the dot command sets up on the Next:

* MDOS A (#0000-#1FFF) for DivMMC bank 3, which MAPRAM makes read-only and
  automaps at #0000-#1FFF on an opcode fetch from #0000/#0008;
* MDOS B (#2000-#37FF plus the 2K RAM at #3800) for a second DivMMC bank;
* the disk image in 8K RAM pages, with the sector count, the page table and
  the slot 2/7 page numbers filled in.

The 48K ROM is used unchanged (it must be the standard Sinclair ROM).
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from pathlib import Path

PATCHES = Path(__file__).resolve().parent.parent / "dot" / "build" / "patches.json"

# CRC32 of the ROMs the patches were written against
MDOS10_CRC = 0x545531FA       # Didaktik_40-80_MDOS_v1_91.rom (14336 bytes)
ROM48_CRC = 0xDDEE531F        # standard Sinclair 48K ROM (16384 bytes)

SECTOR = 512
SECTORS_PER_PAGE = 0x2000 // SECTOR
MAX_IMAGE_PAGES = 104


class PatchError(Exception):
    pass


@dataclass
class PageMap:
    image: list[int]                    # Next 8K pages for the disk image
    mdb_bank: int = 4                   # DivMMC bank for MDOS B (MDOS A is always bank 3)
    pg2: int = 10                       # page normally in MMU slot 2 (48K mode: bank 5)
    pg7: int = 1                        # page normally in MMU slot 7 (48K mode: bank 0)


@dataclass
class SdMap:
    """What DISK_FILEMAP reports for the image file (the -w option)."""
    extents: list[tuple[int, int]]      # (card address, sector count)
    card_flags: int = 2                 # bit 0 = card 1, bit 1 = block addressing


@dataclass
class Built:
    mda: bytearray                      # DivMMC bank 3 (read-only)
    mdb: bytearray                      # DivMMC bank mdb_bank
    image_pages: dict[int, bytearray] = field(default_factory=dict)
    n_secs: int = 0


def load_patches(path: Path = PATCHES) -> dict:
    if not path.exists():
        raise PatchError(f"{path} missing - run: python tools/build_dot.py")
    return json.loads(path.read_text())


def check_rom(data: bytes, crc: int, size: int, what: str) -> None:
    if len(data) != size:
        raise PatchError(f"{what}: expected {size} bytes, got {len(data)}")
    got = zlib.crc32(data) & 0xFFFFFFFF
    if got != crc:
        raise PatchError(f"{what}: CRC32 {got:#010x}, expected {crc:#010x}")


def build_pages(mdos_rom: bytes, image: bytes, pages: PageMap,
                patches: dict | None = None, sd: SdMap | None = None) -> Built:
    check_rom(mdos_rom, MDOS10_CRC, 14336, "MDOS 1.0 ROM")
    if len(image) % SECTOR:
        raise PatchError("image size is not a multiple of 512")
    n_secs = len(image) // SECTOR
    n_pages = -(-n_secs // SECTORS_PER_PAGE)
    if n_pages > MAX_IMAGE_PAGES or n_pages > len(pages.image):
        raise PatchError(f"image needs {n_pages} pages")
    p = patches or load_patches()

    mdos = mdos_rom + b"\x00" * (0x4000 - len(mdos_rom))  # 2K RAM at #3800 starts cleared
    img = {"mda": bytearray(mdos[:0x2000]), "mdb": bytearray(mdos[0x2000:])}
    for name, recs in p["images"].items():
        for off, hx in recs:
            blk = bytes.fromhex(hx)
            img[name][off:off + len(blk)] = blk
    mdb, sym = img["mdb"], {k: v - 0x2000 for k, v in p["symbols"].items()}
    mdb[sym["img_secs"]:sym["img_secs"] + 2] = n_secs.to_bytes(2, "little")
    mdb[sym["fix_pg2"]] = pages.pg2
    mdb[sym["fix_pg7"]] = pages.pg7
    mdb[sym["page_table"]:sym["page_table"] + n_pages] = bytes(pages.image[:n_pages])
    if sd is not None:
        if not 0 < len(sd.extents) <= p["symbols"]["SD_MAX"]:
            raise PatchError("image not mappable on SD card")
        if sum(n for _, n in sd.extents) < n_secs:
            raise PatchError("SD extents do not cover the image")
        mdb[sym["sd_on"]] = 1
        mdb[sym["sd_n"]] = len(sd.extents)
        mdb[sym["sd_cs"]] = 0xFD if sd.card_flags & 1 else 0xFE
        mdb[sym["sd_blk"]] = sd.card_flags & 2
        m = sym["SD_MAP"]
        for addr, n in sd.extents:
            mdb[m:m + 6] = addr.to_bytes(4, "little") + n.to_bytes(2, "little")
            m += 6

    built = Built(img["mda"], mdb, n_secs=n_secs)
    for i in range(n_pages):
        chunk = image[i * 0x2000:(i + 1) * 0x2000]
        built.image_pages[pages.image[i]] = bytearray(chunk + b"\x00" * (0x2000 - len(chunk)))
    return built
