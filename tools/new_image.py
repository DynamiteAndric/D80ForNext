"""Create a blank (formatted) Didaktik image, as MDOS 1.0 FORMAT and `.d80 -n` write it.

    python tools/new_image.py blank.d80 [--name X]     # *.d40: 360K D40, else 720K D80
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from image import blank_image  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--name", help="disk name (default: file name, max 10 characters)")
    args = ap.parse_args(argv)
    out = Path(args.image)
    if out.exists():
        print(f"{out}: file exists", file=sys.stderr)
        return 1
    name = args.name if args.name is not None else out.stem
    d40 = out.suffix.lower() == ".d40"                  # as .d80 -n: by the extension
    out.write_bytes(blank_image(name, os.urandom(2), tracks=40 if d40 else 80))
    print(f"{out}: blank {'360K D40' if d40 else '720K D80'} image, disk name {name[:10]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
