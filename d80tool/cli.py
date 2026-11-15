"""Command line: list / extract / convert Didaktik D40/D80 images."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import basic, snapshot, tape
from .image import DirEntry, MdosError, MdosImage

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f-\xff]')


def safe_name(name: str) -> str:
    s = INVALID.sub("_", name).strip().rstrip(".")
    return s or "_"


def unique(path: Path, used: set[str]) -> Path:
    stem, suffix = path.stem, path.suffix
    candidate = path
    n = 1
    while candidate.name.lower() in used:
        candidate = path.with_name(f"{stem}~{n}{suffix}")
        n += 1
    used.add(candidate.name.lower())
    return candidate


def cmd_list(args) -> int:
    for p in args.images:
        img = MdosImage.open(p)
        print(f"== {img.name}  disk '{img.disk_name}'  {img.tracks} tracks x {img.sides} sides x "
              f"{img.sectors_per_track} sectors{'' if img.signature_ok else '  (no SDOS signature!)'}")
        for e in img.entries():
            err = img.check(e)
            extra = ""
            if e.type == "P":
                extra = f"LINE {e.param1}" if e.param1 < 10000 else ""
            elif e.type in "BNC":
                extra = f"@{e.param1}"
            print(f"  {e.type} {e.name:<10} {e.length:>6}  {extra:<10} {'H' if e.hidden else ' '}"
                  f"{'  BROKEN: ' + err if err else ''}")
    return 0


def cmd_extract(args) -> int:
    rc = 0
    for p in args.images:
        img = MdosImage.open(p)
        out = Path(args.output) / safe_name(Path(p).stem)
        out.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        for e in img.entries():
            try:
                data = img.read(e)
            except MdosError as ex:
                print(f"  skip {e.name!r}: {ex}", file=sys.stderr)
                rc = 1
                continue
            target = unique(out / f"{safe_name(e.name)}.{e.type if e.type.isalnum() else 'bin'}", used)
            target.write_bytes(data)
        print(f"{img.name}: extracted to {out}")
    return rc


LOAD_NAME = re.compile(rb'\xEF\*"([^"]{1,10})"')


def referenced_names(prog: bytes) -> list[str]:
    names = []
    for m in LOAD_NAME.finditer(prog):
        raw = m.group(1)
        if len(raw) > 2 and raw[1:2] == b":":
            raw = raw[2:]
        n = raw.decode("latin-1")
        if n not in names:
            names.append(n)
    return names


MDOS_HINTS = [
    (re.compile(rb"\xDF ?1[45]3"), "OUT to D40 ports (145/153)"),
    (re.compile(rb"\xCF"), "CAT"),
    (re.compile(rb"[\xF8\xD6\xD5\xEF\xF7]\*"), "remaining MDOS '*' command"),
]


def convert_image(path: Path, outroot: Path, write_sna: bool) -> dict:
    img = MdosImage.open(path)
    out = outroot / safe_name(path.stem)
    out.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    report = [f"# {img.name}", "", f"Disk name: `{img.disk_name}`", ""]
    stats = {"snapshots": 0, "programs": 0, "broken": 0, "failed": 0}

    files: dict[str, tuple[DirEntry, bytes]] = {}
    all_tap = bytearray()
    report.append("## Files\n")
    for e in img.entries():
        try:
            data = img.read(e)
        except MdosError as ex:
            stats["broken"] += 1
            report.append(f"- `{e.type} {e.name}`: **broken** ({ex})")
            continue
        files.setdefault(e.name, (e, data))
        note = ""
        if e.type == "S":
            try:
                snap = snapshot.parse(data)
                base = safe_name(e.name)
                z80 = unique(out / f"{base}.z80", used)
                z80.write_bytes(snap.to_z80())
                if write_sna:
                    unique(out / f"{base}.sna", used).write_bytes(snap.to_sna())
                note = f"snapshot → `{z80.name}` (PC={snap.pc:#06x}, IM{snap.im}, {'packed' if snap.packed else 'raw'})"
                stats["snapshots"] += 1
            except snapshot.SnapshotError as ex:
                note = f"snapshot **not converted**: {ex}"
                stats["failed"] += 1
        elif e.type == "P":
            new, plen, _ = basic.rewrite_mdos_loader(data, e.param2)
            all_tap += tape.program(e.name, new, e.param1, plen)
            note = "BASIC"
        elif e.type == "B":
            all_tap += tape.code(e.name, data, e.param1)
            note = f"CODE {e.param1},{e.length}"
        elif e.type in ("N", "C"):
            kind = tape.TAPE_NUM_ARRAY if e.type == "N" else tape.TAPE_CHAR_ARRAY
            all_tap += tape.file_blocks(kind, e.name, data, e.param1, e.param2)
            note = "array"
        else:
            raw = unique(out / f"{safe_name(e.name)}.{e.type if e.type.isalnum() else 'bin'}", used)
            raw.write_bytes(data)
            note = f"type {e.type!r} saved raw as `{raw.name}`"
        report.append(f"- `{e.type} {e.name}` ({e.length} B): {note}")

    # one tape per BASIC program: the rewritten loader + the files it names
    report.append("\n## Programs\n")
    for name, (e, data) in files.items():
        if e.type != "P":
            continue
        new, plen, changes = basic.rewrite_mdos_loader(data, e.param2)
        refs = referenced_names(data[:e.param2])
        tap = bytearray(tape.program(e.name, new, e.param1, plen))
        missing = []
        for r in refs:
            if r in files and files[r][0].type == "B":
                fe, fd = files[r]
                tap += tape.code(fe.name, fd, fe.param1)
            elif r in files and files[r][0].type == "P":
                fe, fd = files[r]
                n2, p2, _ = basic.rewrite_mdos_loader(fd, fe.param2)
                tap += tape.program(fe.name, n2, fe.param1, p2)
            else:
                missing.append(r)
        tap_path = unique(out / f"{safe_name(e.name)}.tap", used)
        tap_path.write_bytes(tap)
        stats["programs"] += 1
        hints = sorted({h for rx, h in MDOS_HINTS if rx.search(new[:plen])})
        report.append(f"### {e.name} → `{tap_path.name}`\n")
        report.append(f"- `LOAD *` rewritten: {changes}; files on tape: {', '.join(refs) or 'none'}")
        if missing:
            report.append(f"- not found on disk / not static: {', '.join(missing)}")
        if hints:
            report.append(f"- needs MDOS at runtime? {'; '.join(hints)}")
        report.append("\n```\n" + basic.listing(data, e.param2) + "\n```\n")

    if all_tap:
        unique(out / "_all_files.tap", used).write_bytes(all_tap)
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return stats


def cmd_convert(args) -> int:
    total = {"snapshots": 0, "programs": 0, "broken": 0, "failed": 0}
    for p in args.images:
        try:
            st = convert_image(Path(p), Path(args.output), args.sna)
        except MdosError as ex:
            print(f"{p}: {ex}", file=sys.stderr)
            continue
        print(f"{Path(p).name}: {st['snapshots']} snapshots, {st['programs']} programs, "
              f"{st['broken']} broken files, {st['failed']} unconverted snapshots")
        for k in total:
            total[k] += st[k]
    print("total:", total)
    return 0


def cmd_snap(args) -> int:
    """Convert standalone MDOS snapshot files (raw 49280-byte dumps or SNAPSHOT-PACKER files)."""
    rc = 0
    for f in args.files:
        f = Path(f)
        data = f.read_bytes()
        try:
            s = snapshot.parse(data)
        except snapshot.SnapshotError as ex:
            print(f"{f}: {ex}", file=sys.stderr)
            rc = 1
            continue
        out = Path(args.output) if args.output else f.parent
        out.mkdir(parents=True, exist_ok=True)
        z80 = out / (f.stem + ".z80")
        z80.write_bytes(s.to_z80())
        if args.sna:
            (out / (f.stem + ".sna")).write_bytes(s.to_sna())
        print(f"{f.name}: {'packed' if s.packed else 'raw'}, PC={s.pc:#06x} SP={s.sp:#06x} "
              f"I={s.i:#04x} IM{s.im} {'EI' if s.iff else 'DI'} -> {z80}")
    return rc


def cmd_basic(args) -> int:
    img = MdosImage.open(args.image)
    for e in img.entries():
        if e.type == "P" and (args.name is None or e.name == args.name):
            print(f"== {e.name} (LINE {e.param1})")
            print(basic.listing(img.read(e), e.param2))
    return 0


def cmd_new(args) -> int:
    import os
    from .image import blank_image
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
    s = sub.add_parser("list", help="show directory")
    s.add_argument("images", nargs="+")
    s.set_defaults(func=cmd_list)
    s = sub.add_parser("extract", help="extract raw files")
    s.add_argument("images", nargs="+")
    s.add_argument("-o", "--output", default="out")
    s.set_defaults(func=cmd_extract)
    s = sub.add_parser("convert", help="convert to .z80/.tap for emulators and ZX Spectrum Next")
    s.add_argument("images", nargs="+")
    s.add_argument("-o", "--output", default="out")
    s.add_argument("--sna", action="store_true", help="also write .sna snapshots")
    s.set_defaults(func=cmd_convert)
    s = sub.add_parser("snap", help="convert standalone MDOS snapshot (SNAP button) files to .z80/.sna")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output")
    s.add_argument("--sna", action="store_true")
    s.set_defaults(func=cmd_snap)
    s = sub.add_parser("basic", help="list BASIC programs")
    s.add_argument("image")
    s.add_argument("name", nargs="?")
    s.set_defaults(func=cmd_basic)
    s = sub.add_parser("new", help="create a blank (formatted) image: *.d40 = 360K D40, else 720K D80")
    s.add_argument("image")
    s.add_argument("--name", help="disk name (default: file name, max 10 characters)")
    s.set_defaults(func=cmd_new)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
