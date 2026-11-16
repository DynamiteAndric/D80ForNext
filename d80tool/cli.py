"""Command line: create blank Didaktik D40/D80 images."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .image import blank_image


def cmd_new(args) -> int:
    out = Path(args.image)
    if out.exists():
        print(f"{out}: file exists", file=sys.stderr)
        return 1
    name = args.name if args.name is not None else out.stem
    d40 = out.suffix.lower() == ".d40"                  # as .d80 -n: by the extension
    out.write_bytes(blank_image(name, os.urandom(2), tracks=40 if d40 else 80))
    print(f"{out}: blank {'360K D40' if d40 else '720K D80'} image, disk name {name[:10]!r}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="d80tool", description="Didaktik D40/D80 (MDOS) image tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new", help="create a blank (formatted) image: *.d40 = 360K D40, else 720K D80")
    s.add_argument("image")
    s.add_argument("--name", help="disk name (default: file name, max 10 characters)")
    s.set_defaults(func=cmd_new)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
