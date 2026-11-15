"""Batch-run converted program tapes in the Python 48K harness and classify them.

    python tools/batch_check.py ROM48 OUTDIR [--frames 500] [--jobs N] TAP...

For each tape it boots the ROM, types LOAD "" and runs the given number of
frames. It then records:
  - tape blocks loaded vs. present
  - the CPU state (exception / halted)
  - the BASIC report on the bottom screen line (OCR against the ROM font)
  - how "busy" the screen is
and saves a PNG plus contact sheets, summary.csv and summary.md.
"""
from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d80tool.emu48 import Spectrum48, tap_blocks, PALETTE  # noqa: E402


def ocr_line(mem: bytes, row: int) -> str:
    """Read one character row of the screen using the ROM font (0x3D00, chars 32..127)."""
    font = {bytes(mem[0x3D00 + (c - 32) * 8:0x3D00 + (c - 31) * 8]): chr(c) for c in range(32, 128)}
    out = []
    for col in range(32):
        cell = bytes(mem[0x4000 | ((row & 0x18) << 8) | (line << 8) | ((row & 7) << 5) | col] for line in range(8))
        inv = bytes(b ^ 0xFF for b in cell)
        out.append(font.get(cell) or font.get(inv) or "?")
    return "".join(out).rstrip()


def busy(mem: bytes) -> float:
    """Fraction of 8x8 cells that are not blank (ink pixels or non-default paper)."""
    n = 0
    for row in range(24):
        for col in range(32):
            attr = mem[0x5800 + row * 32 + col]
            pix = any(mem[0x4000 | ((row & 0x18) << 8) | (line << 8) | ((row & 7) << 5) | col] for line in range(8))
            if pix and (attr & 7) != ((attr >> 3) & 7):
                n += 1
    return n / 768


def check(job):
    rom, tap_path, outdir, frames, press = job
    tap = Path(tap_path)
    data = tap.read_bytes()
    z = Spectrum48(rom)
    status = "ran"
    try:
        if press:
            third = frames // 3
            z.boot_and_load_tap(data, run_frames=third)
            z.type_keys([["SPACE"]], hold=6, gap=third)
            z.type_keys([["ENTER"]], hold=6, gap=third)
        else:
            z.boot_and_load_tap(data, run_frames=frames)
    except Exception as ex:  # emulator-level failure: crash, halt with DI, etc.
        status = f"cpu: {ex}"[:80]
    if z.hung:
        status = "hung (HALT with interrupts disabled)"
    name = f"{tap.parent.name}__{tap.stem}".replace(" ", "_")
    png = Path(outdir) / f"{name}.png"
    z.screen_png(png, scale=1)
    nblocks = sum(1 for b in tap_blocks(data) if b and b[0] == 0xFF)
    m = z.mem
    report = ocr_line(m, 23)
    return {
        "disk": tap.parent.name, "program": tap.stem, "status": status,
        "data_blocks": nblocks, "loaded": z.loaded_blocks // 2 if z.loaded_blocks else 0,
        "loaded_raw": z.loaded_blocks, "tape_left": len(z.tape) - z.tape_pos,
        "pc": f"{z.cpu.pc:04X}", "busy": round(busy(m), 3), "bottom": report, "png": png.name,
    }


def classify(r) -> str:
    b = r["bottom"]
    if r["status"].startswith("hung"):
        return "hung"
    if r["status"] != "ran":
        return "crash"
    if r["loaded_raw"] < 2:
        return "not-loaded"
    if b[:2] in ("C ", "R ") or "Nonsense" in b or "loading error" in b:
        return "basic-error"
    if len(b) > 2 and b[0].isalnum() and b[1] == " " and "," in b and ":" in b:
        return "basic-error" if not b.startswith("0 OK") else "stopped-ok"
    if r["busy"] < 0.02:
        return "blank"
    return "running"


def contact_sheet(pngs: list[Path], out: Path, cols: int = 6) -> None:
    """Combine 256x192 PNGs (written by screen_png scale=1) into one grid image."""
    def read_png(p: Path):
        d = p.read_bytes()
        pos, idat, w, h = 8, b"", 0, 0
        while pos < len(d):
            n = struct.unpack(">I", d[pos:pos + 4])[0]
            t = d[pos + 4:pos + 8]
            c = d[pos + 8:pos + 8 + n]
            if t == b"IHDR":
                w, h = struct.unpack(">II", c[:8])
            elif t == b"IDAT":
                idat += c
            pos += 12 + n
        raw = zlib.decompress(idat)
        stride = w * 3 + 1
        return w, h, [raw[y * stride + 1:(y + 1) * stride] for y in range(h)]
    W, H, gap = 256, 192, 4
    rows = (len(pngs) + cols - 1) // cols
    sw, sh = cols * (W + gap), rows * (H + gap)
    canvas = [bytearray(b"\x40\x40\x40" * sw) for _ in range(sh)]
    for i, p in enumerate(pngs):
        _, _, lines = read_png(p)
        ox, oy = (i % cols) * (W + gap), (i // cols) * (H + gap)
        for y, line in enumerate(lines):
            canvas[oy + y][ox * 3:ox * 3 + len(line)] = line
    raw = b"".join(b"\x00" + bytes(r) for r in canvas)

    def chunk(t, c):
        return struct.pack(">I", len(c)) + t + c + struct.pack(">I", zlib.crc32(t + c) & 0xFFFFFFFF)
    out.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", sw, sh, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("outdir")
    ap.add_argument("taps", nargs="+")
    ap.add_argument("--frames", type=int, default=500)
    ap.add_argument("--press", action="store_true", help="press SPACE and ENTER during the run")
    ap.add_argument("--jobs", type=int, default=max(1, mp.cpu_count() - 1))
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rom = Path(a.rom).read_bytes()
    jobs = [(rom, t, str(out), a.frames, a.press) for t in sorted(a.taps)]
    with mp.Pool(a.jobs) as pool:
        results = []
        for i, r in enumerate(pool.imap_unordered(check, jobs), 1):
            r["class"] = classify(r)
            results.append(r)
            print(f"[{i}/{len(jobs)}] {r['class']:<12} {r['disk']}/{r['program']}  {r['bottom'][:40]}", flush=True)
    results.sort(key=lambda r: (r["class"], r["disk"], r["program"]))
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    md = ["# Batch check of converted program tapes", "",
          f"Harness: Python 48K, {a.frames} frames after LOAD \"\".", "",
          "| class | count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(counts.items())]
    md += ["", "| class | disk | program | blocks loaded | bottom line |", "|---|---|---|---|---|"]
    md += [f"| {r['class']} | {r['disk']} | {r['program']} | {r['loaded_raw']}/{r['data_blocks'] * 2} | `{r['bottom']}` |"
           for r in results]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    for cls in counts:
        pngs = [out / r["png"] for r in results if r["class"] == cls]
        for k in range(0, len(pngs), 36):
            contact_sheet(pngs[k:k + 36], out / f"_sheet_{cls}_{k // 36 + 1}.png")
    print(counts)


if __name__ == "__main__":
    main()
