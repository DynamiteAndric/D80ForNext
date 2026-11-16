"""Round-trip test of the Didaktik SNAP button in Fuse.

    python tools/fuse_snap_roundtrip.py IMAGE.d80 KEYS OUTDIR [--wait 15]

1. copies IMAGE to OUTDIR (the original is never modified),
2. boots it in Fuse (Didaktik 80 + MDOS 1.0) and types KEYS (see fuse_check.post_keys),
3. captures the screen, presses Machine/Didaktik SNAP, waits for MDOS to save,
4. saves the disk image (Media/Disk/Didaktik 80/Drive A/Save),
5. converts the new SNAPSHOTnn file with d80tool and lists the result.

Example (HEXAGONIA from disk 021):
    python tools/fuse_snap_roundtrip.py images/021.d80 "R,ENTER,WAIT4,D,WAIT15" out/_snapfuse
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuse_check as fc  # noqa: E402
from d80tool.image import MdosImage  # noqa: E402
from d80tool import snapshot  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("image")
ap.add_argument("keys")
ap.add_argument("outdir")
ap.add_argument("--wait", type=float, default=15, help="seconds for MDOS to write the snapshot")
a = ap.parse_args()
out = Path(a.outdir)
out.mkdir(parents=True, exist_ok=True)
work = out / (Path(a.image).stem + "_work.d80")
shutil.copyfile(a.image, work)
before = {e.name for e in MdosImage.open(work).entries()}

p = subprocess.Popen([str(fc.FUSE), "--no-autosave-settings", "--no-sound", "--no-confirm-actions",
                      "--machine", "48", "--didaktik80", "--rom-didaktik80", str(fc.MDOS_ROM),
                      "--didaktik80disk", str(work.resolve())], cwd=fc.FUSE.parent)
try:
    time.sleep(4)
    h = fc.find_window(p.pid)
    fc.post_keys(h, a.keys)
    fc.capture(h, out / "1_before_snap.png")
    fc.menu_command(h, "Machine/Didaktik SNAP")
    time.sleep(a.wait)
    fc.capture(h, out / "2_after_snap.png")
    fc.menu_command(h, "Media/Disk/Didaktik 80/Drive A/Save")
    time.sleep(3)
finally:
    p.kill()
    p.wait(10)

img = MdosImage.open(work)
new = [e for e in img.entries() if e.type == "S" and e.name not in before]
if not new:
    raise SystemExit("no new snapshot file on the disk")
for e in new:
    s = snapshot.parse(img.read(e))
    z80 = out / f"{e.name}.z80"
    z80.write_bytes(s.to_z80())
    print(f"{e.name}: {e.length} B, PC={s.pc:#06x} SP={s.sp:#06x} I={s.i:#04x} IM{s.im} "
          f"{'EI' if s.iff else 'DI'} -> {z80}")
