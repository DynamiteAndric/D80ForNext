"""Build the SD card package and publish it as a GitHub release.

    python tools/make_release.py v1.0.0              # check, build, test, tag, push, release
    python tools/make_release.py v1.0.0 --dry-run    # only build out/d80-v1.0.0.zip
    python tools/make_release.py v1.0.1 --draft --notes "Fixes ..."

Steps:
1. checks: version looks like vX.Y.Z, on branch main, working tree clean,
   in sync with origin/main, tag not used yet;
2. rebuilds dist/dot/D80 (tools/build_dot.py) and dist/d80/demo.d80
   (tools/demo_image.py) and stops if that changes a committed file in dist/
   or dot/build/, so the package always matches the tagged commit;
3. runs the tests (skip with --skip-tests);
4. zips dist/ as committed at HEAD (git archive, so ignored files such as
   the MDOS ROM can never get in) to out/d80-<version>.zip and checks it
   holds no ROM or third-party disk;
5. creates an annotated tag, pushes it and runs ``gh release create`` with
   the zip (release notes generated from the commits unless --notes or
   --notes-file is given).

--dry-run stops after step 4 and allows a dirty tree and any branch.

--package-only is for the GitHub workflow (.github/workflows/release.yml),
which runs on an existing tag without sjasmplus or the ROMs: it skips step 1,
rebuilds only the demo disk in step 2 (the committed dist/dot/D80 is used),
and stops after step 4; the workflow creates the release itself.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
EXPECTED = {"dot/D80", "d80/demo.d80", "README.txt", "browser-d80.cfg"}


def run(*cmd: str, capture: bool = False) -> str:
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)
    if r.returncode:
        detail = (r.stderr or r.stdout or "").strip() if capture else ""
        sys.exit(f"failed: {' '.join(cmd)}\n{detail}".rstrip())
    return (r.stdout or "").strip() if capture else ""


def git(*args: str) -> str:
    return run("git", *args, capture=True)


def check_repo(version: str, dry_run: bool) -> None:
    if git("tag", "--list", version):
        sys.exit(f"tag {version} already exists")
    if dry_run:
        return
    branch = git("branch", "--show-current")
    if branch != "main":
        sys.exit(f"releases are made from main (you are on {branch!r})")
    if git("status", "--porcelain"):
        sys.exit("the working tree has uncommitted changes; commit or stash them first")
    run("git", "fetch", "-q", "origin")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        sys.exit("main is not in sync with origin/main; pull or push first")
    if git("ls-remote", "--tags", "origin", f"refs/tags/{version}"):
        sys.exit(f"tag {version} already exists on origin")


def rebuild(dry_run: bool, demo_only: bool = False) -> None:
    print("== build", flush=True)
    if not demo_only:
        run(sys.executable, "tools/build_dot.py")
    run(sys.executable, "tools/demo_image.py", "dist/d80/demo.d80")
    changed = git("status", "--porcelain", "--", "dist", "dot/build")
    if changed and not dry_run:
        sys.exit("the build changed committed files - commit them, then run again:\n" + changed)


def build_zip(version: str) -> Path:
    print("== package", flush=True)
    OUT.mkdir(exist_ok=True)
    prefix = f"d80-{version}/"
    path = OUT / f"d80-{version}.zip"
    run("git", "archive", "--format=zip", f"--prefix={prefix}", "-o", str(path), "HEAD:dist")
    with zipfile.ZipFile(path) as z:
        names = {n[len(prefix):] for n in z.namelist() if not n.endswith("/")}
    bad = [n for n in names if n.lower().endswith((".rom", ".z80", ".sna", ".tap", ".tzx"))
           or (n.lower().endswith((".d80", ".d40")) and n != "d80/demo.d80")]
    if bad:
        path.unlink()
        sys.exit(f"refusing to package copyrighted-looking files: {bad}")
    missing = EXPECTED - names
    if missing:
        sys.exit(f"the package lacks {sorted(missing)} (are they committed?)")
    print(f"{path.relative_to(ROOT)}: {', '.join(sorted(names))}")
    return path


def publish(version: str, zip_path: Path, a: argparse.Namespace) -> None:
    print("== release", flush=True)
    run("gh", "--version", capture=True)                 # fail early if gh is missing
    run("git", "tag", "-a", version, "-m", f"Release {version}")
    run("git", "push", "origin", version)
    cmd = ["gh", "release", "create", version, str(zip_path), "--title", f"D80 {version}"]
    if a.notes:
        cmd += ["--notes", a.notes]
    elif a.notes_file:
        cmd += ["--notes-file", a.notes_file]
    else:
        cmd += ["--generate-notes"]
    if a.draft:
        cmd.append("--draft")
    print(run(*cmd, capture=True))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", help="release version, e.g. v1.0.0")
    ap.add_argument("--dry-run", action="store_true", help="only build the zip in out/")
    ap.add_argument("--package-only", action="store_true",
                    help="for CI: check the demo disk, test and zip an existing tag")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--draft", action="store_true", help="create the release as a draft")
    notes = ap.add_mutually_exclusive_group()
    notes.add_argument("--notes", help="release notes text")
    notes.add_argument("--notes-file", help="release notes from a file")
    a = ap.parse_args()

    if not re.fullmatch(r"v\d+\.\d+\.\d+", a.version):
        sys.exit("version must look like v1.2.3")
    if not a.package_only:
        check_repo(a.version, a.dry_run)
    rebuild(a.dry_run, demo_only=a.package_only)
    if not a.skip_tests:
        print("== tests (a few minutes)", flush=True)
        run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
    zip_path = build_zip(a.version)
    if a.package_only:
        return
    if a.dry_run:
        print("dry run: no tag, no release")
        return
    publish(a.version, zip_path, a)


if __name__ == "__main__":
    main()
