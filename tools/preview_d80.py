"""Boot a .d80 image in the Python model of the .d80 dot command and save screens.

    python tools/preview_d80.py MDOS.rom 48.rom OUTDIR IMAGE.d80 [--keys R,ENTER,WAIT4,D] [--frames 600]

Keys are typed after boot (150 frames). ``A+B`` presses keys together,
``WAITn`` waits n seconds (50 frames each), ``SNAP`` presses the DRIVE
button briefly and ``HOLD`` holds it (the D80 menu). Screens are written every
``--every`` frames as OUTDIR/<image>_<tag>_<n>.png. The run reports
invariant violations of the paging design (see nextmmu.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nextmmu import DidaktikNext, InvariantError  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mdos")
    ap.add_argument("rom48")
    ap.add_argument("outdir")
    ap.add_argument("image")
    ap.add_argument("--keys", default="R,ENTER")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--every", type=int, default=200)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.image).stem + (f"_{a.tag}" if a.tag else "")
    m = DidaktikNext(Path(a.mdos).read_bytes(), Path(a.rom48).read_bytes(), Path(a.image).read_bytes())
    status = "ok"
    try:
        m.run_frames(150)
        for k in a.keys.split(","):
            if k.upper().startswith("WAIT"):
                m.run_frames(int(k[4:]) * 50)
            elif k.upper() in ("SNAP", "HOLD"):
                m.press_snap(hold=400_000 if k.upper() == "HOLD" else 50)
                m.run_frames(30)
            else:
                m.type_keys([k.split("+")])
        n = 0
        while n * a.every < a.frames:
            m.run_frames(a.every)
            m.screen_png(out / f"{stem}_{n}.png")
            n += 1
    except InvariantError as e:
        status = f"INVARIANT: {e}"
        m.screen_png(out / f"{stem}_fail.png")
    c = m.cpu
    print(f"{stem}: {status}; frames={m.frames} pc={c.pc:#06x} hung={m.hung} "
          f"fdc_ports={len(m.fdc_access)} mdos_rom_writes={len(c.mdos_rom_writes)} "
          f"user_pageouts={m.user_pageouts}")


if __name__ == "__main__":
    main()
