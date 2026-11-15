"""Run many converted files in parallel headless ZEsarUX instances and classify them.

    python tools/zesarux_batch.py OUTDIR [--seconds 35] [--jobs 10] FILE...

Each instance gets its own ZRCP port. The saved .scr is rendered to PNG, the
bottom line is OCR'd against the 48K ROM font, and the result is classified
like tools/batch_check.py (summary.csv / summary.md / contact sheets).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zesarux_check import run_one, ZDIR  # noqa: E402
from batch_check import ocr_line, busy, contact_sheet  # noqa: E402


def png_to_mem(png: Path, rom: bytes) -> bytearray:
    """Rebuild screen memory (pixels + attributes) from a PNG made by scr_to_png (scale 1 or 2)."""
    import struct, zlib
    from d80tool.emu48 import PALETTE
    d = png.read_bytes(); pos = 8; idat = b""; w = h = 0
    while pos < len(d):
        n = struct.unpack(">I", d[pos:pos + 4])[0]; t = d[pos + 4:pos + 8]; c = d[pos + 8:pos + 8 + n]
        if t == b"IHDR": w, h = struct.unpack(">II", c[:8])
        elif t == b"IDAT": idat += c
        pos += 12 + n
    raw = zlib.decompress(idat); st = w * 3 + 1; sc = w // 256
    pal = {rgb: i for i, rgb in enumerate(PALETTE)}
    pal[(0, 0, 0)] = 0
    rows = []
    for y in range(192):
        line = raw[y * sc * st + 1:(y * sc + 1) * st]
        step = 3 * sc
        rows.append(list(zip(line[0::step], line[1::step], line[2::step])))
    mem = bytearray(0x10000)
    mem[:0x4000] = rom
    for row in range(24):
        for col in range(32):
            cell = [rows[row * 8 + y][col * 8:col * 8 + 8] for y in range(8)]
            counts: dict = {}
            for line in cell:
                for rgb in line:
                    counts[rgb] = counts.get(rgb, 0) + 1
            order = sorted(counts, key=counts.get, reverse=True)
            paper = order[0]
            ink = order[1] if len(order) > 1 else paper
            pi, ii = pal.get(paper, 7), pal.get(ink, 0)
            bright = 0x40 if (pi >= 8 or ii >= 8) else 0
            mem[0x5800 + row * 32 + col] = bright | ((pi & 7) << 3) | (ii & 7)
            if ink == paper:
                continue
            for y, line in enumerate(cell):
                v = 0
                for x, rgb in enumerate(line):
                    if rgb == ink:
                        v |= 0x80 >> x
                mem[0x4000 | ((row & 0x18) << 8) | (y << 8) | ((row & 7) << 5) | col] = v
    return mem


def classify(bottom: str, b: float, top: str = "") -> str:
    if "1982 Sinclair" in bottom or "1986 Sinclair" in bottom:
        return "reset"
    if (top.startswith("Program:") or top.startswith("Bytes:")) and b < 0.06:
        return "waiting-tape"  # only a tape header on screen: next file is not on the tape
    if len(bottom) > 2 and bottom[0].isalnum() and bottom[1] == " " and "," in bottom and ":" in bottom:
        return "stopped-ok" if bottom.startswith("0 OK") else "basic-error"
    if b < 0.02:
        return "blank"
    return "running"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--seconds", type=float, default=35)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--machine", default="48k")
    ap.add_argument("--resume", action="store_true", help="reuse existing screenshots, only run missing ones")
    ap.add_argument("--no-run", action="store_true", help="only classify existing screenshots, never start ZEsarUX")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rom = (ZDIR / "48.rom").read_bytes()
    files = sorted(set(a.files))

    def work(i_f):
        i, f = i_f
        f = Path(f)
        png = out / re.sub(r"[^\w.+-]", "_", f"{f.parent.name}_{f.stem}.png")
        if not png.exists() and a.no_run:
            r = {"disk": f.parent.name, "program": f.stem, "png": png.name, "bottom": "", "busy": 0.0,
                 "class": "not-run"}
            return r
        if not ((a.resume or a.no_run) and png.exists()):
            png = run_one(f, out, a.machine, a.seconds, None, port=10200 + (i % a.jobs))
        r = {"disk": f.parent.name, "program": f.stem, "png": png.name, "bottom": "", "busy": 0.0}
        if png.exists():
            mem = png_to_mem(png, rom)
            r["bottom"] = ocr_line(mem, 23)
            r["busy"] = round(busy(mem), 3)
            r["top"] = ocr_line(mem, 0)
            r["class"] = classify(r["bottom"], r["busy"], r["top"])
        else:
            r["class"] = "no-screen"
        print(f"{r['class']:<12} {r['disk']}/{r['program']}  {r['bottom'][:40]}", flush=True)
        return r

    results = []
    # ports are reused only after the previous instance on that slot has finished
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = []
        for slot in range(a.jobs):
            chunk = [(i, f) for i, f in enumerate(files) if i % a.jobs == slot]
            futs.append(ex.submit(lambda c: [work(x) for x in c], chunk))
        for fu in as_completed(futs):
            results.extend(fu.result())
    results.sort(key=lambda r: (r["class"], r["disk"], r["program"]))
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["class", "disk", "program", "busy", "top", "bottom", "png"], extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    md = ["# ZEsarUX batch check", "", f"{a.machine}, {a.seconds:.0f} s after autoload.", "",
          "| class | count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(counts.items())]
    md += ["", "| class | disk | program | bottom line |", "|---|---|---|---|"]
    md += [f"| {r['class']} | {r['disk']} | {r['program']} | `{r['bottom']}` |" for r in results]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    # contact sheets (downscaled 2x)
    import struct, zlib
    def down(p, q):
        d = p.read_bytes(); pos = 8; idat = b""; w = h = 0
        while pos < len(d):
            n = struct.unpack(">I", d[pos:pos + 4])[0]; t = d[pos + 4:pos + 8]; c = d[pos + 8:pos + 8 + n]
            if t == b"IHDR": w, h = struct.unpack(">II", c[:8])
            elif t == b"IDAT": idat += c
            pos += 12 + n
        raw = zlib.decompress(idat); st = w * 3 + 1
        rows = [b"\x00" + b"".join(raw[y * st + 1 + x * 3:y * st + 4 + x * 3] for x in range(0, w, 2)) for y in range(0, h, 2)]
        ch = lambda t, c: struct.pack(">I", len(c)) + t + c + struct.pack(">I", zlib.crc32(t + c) & 0xFFFFFFFF)
        q.write_bytes(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w // 2, h // 2, 8, 2, 0, 0, 0))
                      + ch(b"IDAT", zlib.compress(b"".join(rows))) + ch(b"IEND", b""))
    small_dir = out / "_small"
    small_dir.mkdir(exist_ok=True)
    for cls in counts:
        smalls = []
        for r in results:
            if r["class"] == cls and (out / r["png"]).exists():
                q = small_dir / r["png"]
                down(out / r["png"], q)
                smalls.append(q)
        for k in range(0, len(smalls), 36):
            contact_sheet(smalls[k:k + 36], out / f"_sheet_{cls}_{k // 36 + 1}.png")
    print(counts)


if __name__ == "__main__":
    main()
