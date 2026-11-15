"""Minimal FAT16 access to an SD-card image (first MBR partition).

Enough to put the .d80 dot command, the MDOS ROM and disk images onto the
ZEsarUX ``tbblue.mmc`` for testing, without hdfmonkey:

    python tools/fat16.py IMAGE ls [/path]
    python tools/fat16.py IMAGE put LOCALFILE /dir/NAME.EXT    (8.3 names, dirs created)
    python tools/fat16.py IMAGE get /dir/NAME.EXT LOCALFILE

Only short (8.3) names are written; long-name entries are skipped when reading.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


class Fat16:
    def __init__(self, path: str | Path) -> None:
        self.f = open(path, "r+b")
        mbr = self._read(0, 512)
        self.base = struct.unpack("<I", mbr[0x1C6:0x1CA])[0] * 512
        b = self._read(self.base, 512)
        if b[0x36:0x3E] != b"FAT16   ":
            raise ValueError("not FAT16")
        self.bps = struct.unpack("<H", b[11:13])[0]
        self.spc = b[13]
        res = struct.unpack("<H", b[14:16])[0]
        self.nfats = b[16]
        self.rootent = struct.unpack("<H", b[17:19])[0]
        self.fatsz = struct.unpack("<H", b[22:24])[0]
        tot = struct.unpack("<H", b[19:21])[0] or struct.unpack("<I", b[32:36])[0]
        self.fat_off = self.base + res * self.bps
        self.root_off = self.fat_off + self.nfats * self.fatsz * self.bps
        self.data_off = self.root_off + self.rootent * 32
        self.csize = self.spc * self.bps
        self.nclusters = (tot - (self.data_off - self.base) // self.bps) // self.spc + 2
        self.fat = bytearray(self._read(self.fat_off, self.fatsz * self.bps))

    # ---- low level ---------------------------------------------------------
    def _read(self, off: int, n: int) -> bytes:
        self.f.seek(off)
        return self.f.read(n)

    def _write(self, off: int, data: bytes) -> None:
        self.f.seek(off)
        self.f.write(data)

    def _next(self, c: int) -> int:
        return struct.unpack("<H", self.fat[c * 2:c * 2 + 2])[0]

    def _set(self, c: int, v: int) -> None:
        self.fat[c * 2:c * 2 + 2] = struct.pack("<H", v)

    def _chain(self, c: int) -> list[int]:
        out = []
        while 2 <= c < 0xFFF8:
            out.append(c)
            c = self._next(c)
        return out

    def _coff(self, c: int) -> int:
        return self.data_off + (c - 2) * self.csize

    def _alloc(self, n: int) -> list[int]:
        free = [c for c in range(2, self.nclusters) if self._next(c) == 0][:n]
        if len(free) < n:
            raise OSError("SD image full")
        for a, b in zip(free, free[1:] + [0xFFFF]):
            self._set(a, b)
        return free

    def flush(self) -> None:
        for i in range(self.nfats):
            self._write(self.fat_off + i * self.fatsz * self.bps, bytes(self.fat))
        self.f.flush()

    # ---- directories ---------------------------------------------------------
    def _dir_slots(self, cluster: int | None) -> list[int]:
        """Byte offsets of all 32-byte slots of a directory (None = root)."""
        if cluster is None:
            return [self.root_off + i * 32 for i in range(self.rootent)]
        return [self._coff(c) + i * 32 for c in self._chain(cluster) for i in range(self.csize // 32)]

    def entries(self, cluster: int | None):
        for off in self._dir_slots(cluster):
            e = self._read(off, 32)
            if e[0] == 0:
                break
            if e[0] == 0xE5 or e[11] == 0x0F or e[11] & 0x08:
                continue
            name = e[0:8].decode("latin-1").rstrip()
            ext = e[8:11].decode("latin-1").rstrip()
            yield (name + ("." + ext if ext else ""), e[11], struct.unpack("<H", e[26:28])[0],
                   struct.unpack("<I", e[28:32])[0], off)

    def _find(self, cluster: int | None, name: str):
        for ent in self.entries(cluster):
            if ent[0].upper() == name.upper():
                return ent
        return None

    def _resolve_dir(self, path: str, create: bool = False) -> int | None:
        cluster = None
        for part in [p for p in path.strip("/").split("/") if p]:
            ent = self._find(cluster, part)
            if ent is None:
                if not create:
                    raise FileNotFoundError(path)
                cluster = self._mkdir(cluster, part)
            elif not ent[1] & 0x10:
                raise NotADirectoryError(path)
            else:
                cluster = ent[2] or None
        return cluster

    def _free_slot(self, cluster: int | None) -> int:
        for off in self._dir_slots(cluster):
            if self._read(off, 1)[0] in (0x00, 0xE5):
                return off
        if cluster is None:
            raise OSError("root directory full")
        last = self._chain(cluster)[-1]
        new = self._alloc(1)[0]
        self._set(last, new)
        self._write(self._coff(new), bytes(self.csize))
        return self._coff(new)

    @staticmethod
    def _83(name: str) -> bytes:
        base, _, ext = name.upper().partition(".")
        if not 1 <= len(base) <= 8 or len(ext) > 3:
            raise ValueError(f"not an 8.3 name: {name}")
        return base.ljust(8).encode() + ext.ljust(3).encode()

    def _entry(self, name: str, attr: int, cluster: int, size: int) -> bytes:
        return self._83(name) + bytes([attr]) + bytes(14) + struct.pack("<HI", cluster, size)

    def _mkdir(self, parent: int | None, name: str) -> int:
        c = self._alloc(1)[0]
        blk = bytearray(self.csize)
        blk[0:32] = b".          " + bytes([0x10]) + bytes(14) + struct.pack("<HI", c, 0)
        blk[32:64] = b"..         " + bytes([0x10]) + bytes(14) + struct.pack("<HI", parent or 0, 0)
        self._write(self._coff(c), bytes(blk))
        self._write(self._free_slot(parent), self._entry(name, 0x10, c, 0))
        return c

    # ---- files ---------------------------------------------------------------
    def put(self, path: str, data: bytes) -> None:
        d, _, name = path.rpartition("/")
        cluster = self._resolve_dir(d, create=True)
        old = self._find(cluster, name)
        if old:
            for c in self._chain(old[2]):
                self._set(c, 0)
        n = max(1, -(-len(data) // self.csize))
        chain = self._alloc(n) if data else []
        for i, c in enumerate(chain):
            self._write(self._coff(c), data[i * self.csize:(i + 1) * self.csize].ljust(self.csize, b"\0"))
        slot = old[4] if old else self._free_slot(cluster)
        self._write(slot, self._entry(name, 0x20, chain[0] if chain else 0, len(data)))
        self.flush()

    def get(self, path: str) -> bytes:
        d, _, name = path.rpartition("/")
        ent = self._find(self._resolve_dir(d), name)
        if ent is None:
            raise FileNotFoundError(path)
        data = b"".join(self._read(self._coff(c), self.csize) for c in self._chain(ent[2]))
        return data[:ent[3]]

    def ls(self, path: str = "/") -> list[str]:
        return [f"{'<DIR>' if a & 0x10 else s:>10}  {n}" for n, a, _, s, _ in self.entries(self._resolve_dir(path))]


def main() -> None:
    img, cmd, *args = sys.argv[1:]
    fs = Fat16(img)
    if cmd == "ls":
        print("\n".join(fs.ls(args[0] if args else "/")))
    elif cmd == "put":
        fs.put(args[1], Path(args[0]).read_bytes())
    elif cmd == "get":
        Path(args[1]).write_bytes(fs.get(args[0]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
