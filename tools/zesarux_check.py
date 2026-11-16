"""Run converted .z80/.sna/.tap files in headless ZEsarUX and save screenshots.

Usage:
    python tools/zesarux_check.py [--machine 48k] [--seconds 15] OUTDIR FILE...

ZEsarUX is expected in emulators/ZEsarUX. It runs with no video and no audio
and is driven through its ZRCP remote protocol: smartload FILE, wait, then
save-screen. The SCR screenshot is also written as PNG so it can be viewed
easily.
"""
from __future__ import annotations

import argparse
import re
import socket
import struct
import subprocess
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZDIR = ROOT / "emulators" / "ZEsarUX"
PORT = 10123


class Zrcp:
    def __init__(self, port: int) -> None:
        deadline = time.time() + 30
        while True:
            try:
                self.s = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.3)
        self.s.settimeout(5)
        self.cmd("")

    def cmd(self, c: str) -> str:
        self.s.sendall((c + "\n").encode())
        out = b""
        try:
            while not re.search(rb"command(@[\w-]+)?> ?$", out):
                d = self.s.recv(65536)
                if not d:
                    break
                out += d
        except (socket.timeout, ConnectionResetError):
            pass
        return re.sub(r"command(@[\w-]+)?> ?", "", out.decode("latin-1")).strip()


def bmp_to_png(bmp: Path, png: Path) -> None:
    d = bmp.read_bytes()
    off, = struct.unpack_from("<I", d, 10)
    w, h, _, bpp = struct.unpack_from("<iiHH", d, 18)
    flip = h > 0
    h = abs(h)
    if bpp not in (24, 32):
        raise ValueError(f"unsupported BMP depth {bpp}")
    bpr = ((w * bpp // 8) + 3) & ~3
    rows = []
    for y in range(h):
        sy = h - 1 - y if flip else y
        row = d[off + sy * bpr: off + sy * bpr + w * bpp // 8]
        step = bpp // 8
        rgb = bytearray()
        for x in range(0, len(row), step):
            rgb += bytes((row[x + 2], row[x + 1], row[x]))
        rows.append(b"\x00" + bytes(rgb))

    def chunk(t, c):
        return struct.pack(">I", len(c)) + t + c + struct.pack(">I", zlib.crc32(t + c) & 0xFFFFFFFF)
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def scr_to_png(scr: Path, png: Path) -> None:
    """Render a 6912-byte .scr (Spectrum screen memory) using the emu48 renderer."""
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from d80tool.emu48 import Spectrum48
    z = Spectrum48(bytes(16384))
    z.mem[0x4000:0x4000 + 6912] = scr.read_bytes()[:6912]
    z.screen_png(png)


def run_one(file: Path, outdir: Path, machine: str, seconds: float, keys: str | None,
            port: int = PORT, keep_scr: bool = False) -> Path:
    proc = subprocess.Popen(
        [str(ZDIR / "zesarux.exe"), "--noconfigfile", "--vo", "null", "--ao", "null",
         "--nowelcomemessage", "--quickexit", "--fastautoload",
         "--enable-remoteprotocol", "--remoteprotocol-port", str(port), "--machine", machine,
         str(file.resolve())],  # loaded at startup (smartload: snapshot, or tape with autoload)
        cwd=ZDIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        z = Zrcp(port)
        time.sleep(seconds)
        if keys:
            z.cmd(f"send-keys-string 100 {keys}")
            time.sleep(3)
        scr = (outdir / re.sub(r"[^\w.+-]", "_", f"{file.parent.name}_{file.stem}.scr")).resolve()
        z.cmd(f"save-screen {scr}")
        time.sleep(0.5)
        try:
            z.cmd("exit-emulator")
        except OSError:
            pass
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    png = scr.with_suffix(".png")
    if scr.exists():
        scr_to_png(scr, png)
        if not keep_scr:
            scr.unlink()
    return png


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="48k")
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--keys", help="keys to send after waiting (send-keys-string)")
    ap.add_argument("outdir")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        png = run_one(Path(f), out, a.machine, a.seconds, a.keys)
        print(f"{f} -> {png if png.exists() else 'NO SCREENSHOT'}")


if __name__ == "__main__":
    main()
