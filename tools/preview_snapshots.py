"""Run the snapshots of the given images in the Python 48K harness and save PNGs."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d80tool.image import MdosImage, MdosError  # noqa: E402
from d80tool.snapshot import parse, SnapshotError  # noqa: E402
from d80tool.emu48 import Spectrum48  # noqa: E402
from d80tool.cli import safe_name  # noqa: E402

rom = Path(sys.argv[1]).read_bytes()
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
for img_path in sys.argv[3:]:
    im = MdosImage.open(img_path)
    for e in im.entries():
        if e.type != "S":
            continue
        tag = f"{Path(img_path).stem}_{safe_name(e.name)}"
        try:
            s = parse(im.read(e))
        except (MdosError, SnapshotError) as ex:
            print(f"{tag}: not converted ({ex})")
            continue
        z = Spectrum48(rom)
        z.load_snapshot(s)
        z.screen_png(out / f"{tag}_start.png")
        t = time.time()
        try:
            z.run_frames(150)
            status = "ran 150 frames"
        except Exception as ex:  # report and keep going
            status = f"stopped: {ex}"
        z.screen_png(out / f"{tag}_run.png")
        print(f"{tag}: PC={s.pc:#06x} IM{s.im} {'packed' if s.packed else 'raw'} -> {status} "
              f"({time.time() - t:.1f}s, pc now {z.cpu.pc:#06x})")
