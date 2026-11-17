"""Run the .d80 dot command in ZEsarUX (TBBlue / ZX Spectrum Next) and take screenshots.

    python tools/zesarux_next_check.py OUTDIR --mdos MDOS.rom --image disk.d80
        [--image-b disk2.d80] [--command ".d80 {image} {image_b}"] [--steps "wait:25,shot:boot,keys:R,ascii:13,wait:20,shot:run"]
        [--rom /sys/d80/gama.rom=Didaktik_Gama_1989.rom ...]

A working copy of emulators/ZEsarUX/tbblue.mmc (NextZXOS) gets
/dot/D80 (dot/build/D80), /sys/d80/mdos10.rom and /d80/<image>, and its
/nextzxos/autoexec.bas is replaced by one line that runs the dot command
(--command), so NextZXOS boots straight into it. ZEsarUX runs headless and
is driven through ZRCP. Steps:

    wait:N        sleep N seconds
    keys:TEXT     send-keys-string (no spaces; use ascii:32)
    ascii:N+N     send-keys-ascii with these codes (32 = space, 13 = ENTER)
    shot:NAME     save-screen to OUTDIR/NAME.png (BMP of the whole display)
    cmd:ZRCP      run a ZRCP command and print the answer
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fat16 import Fat16  # noqa: E402
from zesarux_check import ZDIR, Zrcp, bmp_to_png  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PORT = 10124
KEY_MS = 250
CR = bytes([13])


def plus3_basic(lines: list[tuple[int, bytes]], autostart: int) -> bytes:
    """A +3DOS BASIC file; each line body is stored as given (dot commands are plain text)."""
    prog = b"".join(n.to_bytes(2, "big") + (len(t) + 1).to_bytes(2, "little") + t + CR
                    for n, t in lines)
    h = bytearray(128)
    h[0:8] = b"PLUS3DOS"
    h[8:11] = bytes([0x1A, 1, 0])
    h[11:15] = (128 + len(prog)).to_bytes(4, "little")
    h[15] = 0                                   # BASIC program
    h[16:18] = len(prog).to_bytes(2, "little")
    h[18:20] = autostart.to_bytes(2, "little")
    h[20:22] = len(prog).to_bytes(2, "little")  # no variables
    h[127] = sum(h[:127]) & 0xFF
    return bytes(h) + prog


def put_image(fs: Fat16, image: Path, used: set[str]) -> str:
    name = image.stem[:8].upper().replace("-", "_") + ".D80"
    while name in used:                         # the same image twice
        name = name[:7] + chr(ord(name[7]) + 1) + ".D80" if len(name) == 12 else "X" + name
    used.add(name)
    fs.put(f"/d80/{name}", image.read_bytes())
    return f"/d80/{name}"


def prepare_sd(out: Path, mdos: Path, image: Path, command: str,
               image_b: Path | None = None, roms: dict[str, Path] | None = None) -> tuple[Path, str]:
    sd = out / "sd.mmc"
    shutil.copyfile(ZDIR / "tbblue.mmc", sd)
    fs = Fat16(sd)
    # timing=8 means "video mode not chosen yet" and shows the test screen
    cfg = fs.get("/machines/next/CONFIG.INI").replace(b"timing=8", b"timing=0")
    fs.put("/machines/next/CONFIG.INI", cfg)
    fs.put("/dot/D80", (ROOT / "dot" / "build" / "D80").read_bytes())
    fs.put("/sys/d80/mdos10.rom", mdos.read_bytes())
    for card_path, local in (roms or {}).items():     # e.g. the Didaktik ROMs of the machine menu
        fs.put(card_path, local.read_bytes())
    used: set[str] = set()
    a = put_image(fs, image, used)
    b = put_image(fs, image_b, used) if image_b else ""
    line = command.format(image=a, image_b=b).strip()
    fs.put("/nextzxos/AUTOEXEC.BAS", plus3_basic([(10, line.encode())], 10))
    return sd, line


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--mdos", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--image-b", help="second image for drive B: ({image_b} in --command)")
    ap.add_argument("--command", default=".d80 {image} {image_b}")
    ap.add_argument("--steps", default="wait:25,shot:boot")
    ap.add_argument("--rom", action="append", default=[], metavar="CARDPATH=FILE",
                    help="put FILE on the card as CARDPATH (8.3 names)")
    a = ap.parse_args()
    out = Path(a.outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    roms = {c: Path(f) for c, _, f in (r.partition("=") for r in a.rom)}
    sd, line = prepare_sd(out, Path(a.mdos), Path(a.image), a.command,
                          Path(a.image_b) if a.image_b else None, roms)
    print(f"autoexec: {line}")

    proc = subprocess.Popen(
        [str(ZDIR / "zesarux.exe"), "--noconfigfile", "--vo", "null", "--ao", "null",
         "--nowelcomemessage", "--quickexit", "--tbblue-autoconfigure-sd-already-asked",
         "--enable-remoteprotocol", "--remoteprotocol-port", str(PORT),
         "--machine", "tbblue", "--mmc-file", str(sd), "--enable-mmc", "--enable-divmmc-ports"],
        cwd=ZDIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        z = Zrcp(PORT)
        for step in a.steps.split(","):
            kind, _, arg = step.partition(":")
            if kind == "wait":
                time.sleep(float(arg))
            elif kind == "keys":
                z.cmd(f"send-keys-string {KEY_MS} {arg}")
            elif kind == "ascii":
                z.cmd(f"send-keys-ascii {KEY_MS} " + arg.replace("+", " "))
            elif kind == "shot":
                bmp = out / f"{arg}.bmp"
                z.cmd(f"save-screen {bmp}")
                time.sleep(0.5)
                if bmp.exists():
                    bmp_to_png(bmp, out / f"{arg}.png")
                    bmp.unlink()
                    print(f"shot {out / (arg + '.png')}")
                else:
                    print(f"shot {arg}: no file")
            elif kind == "cmd":
                print(z.cmd(arg))
        try:
            z.cmd("exit-emulator")
        except OSError:
            pass
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
