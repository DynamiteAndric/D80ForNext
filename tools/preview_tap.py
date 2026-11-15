"""Boot the 48K ROM in the Python harness, LOAD "" a .tap and save a PNG of the screen."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d80tool.emu48 import Spectrum48  # noqa: E402

rom = Path(sys.argv[1]).read_bytes()
out = Path(sys.argv[2])
frames = int(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
for tap in sys.argv[4:]:
    tap = Path(tap)
    z = Spectrum48(rom)
    t = time.time()
    try:
        z.boot_and_load_tap(tap.read_bytes(), run_frames=frames)
        status = "ok"
    except Exception as ex:
        status = f"stopped: {ex}"
    png = out / f"{tap.parent.name}_{tap.stem}.png"
    z.screen_png(png)
    print(f"{tap}: {status}; blocks loaded {z.loaded_blocks}/{len(z.tape)//2 * 2}, "
          f"pc={z.cpu.pc:#06x}, {time.time() - t:.1f}s -> {png.name}")
