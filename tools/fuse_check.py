"""Run files in Fuse (emulators/fuse) and capture only the Fuse window as PNG.

Typical use: boot an original D40/D80 image with real MDOS for reference:

    python tools/fuse_check.py --disk images/021.d80 --seconds 20 out/_fuse
    python tools/fuse_check.py --snapshot out/029-GAMES/TURRICAN1+.z80 out/_fuse

The window is captured with the Win32 PrintWindow API (only the emulator
window, not the desktop). Fuse settings are not saved (--no-autosave-settings).
"""
from __future__ import annotations

import argparse
import ctypes
import re
import struct
import subprocess
import time
import zlib
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUSE = ROOT / "emulators" / "fuse" / "fuse.exe"
MDOS_ROM = ROOT / "emulators" / "roms" / "Didaktik_40-80_MDOS_v1_91.rom"

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


def find_window(pid: int) -> int | None:
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append(((r.right - r.left) * (r.bottom - r.top), hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return max(found)[1] if found else None


def capture(hwnd: int, png: Path) -> None:
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 1 | 2)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(bi)
    bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -h, 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    raw = buf.raw
    rows = []
    for y in range(h):
        line = raw[y * w * 4:(y + 1) * w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows.append(b"\x00" + bytes(rgb))

    def chunk(t, c):
        return struct.pack(">I", len(c)) + t + c + struct.pack(">I", zlib.crc32(t + c) & 0xFFFFFFFF)
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def menu_items(hwnd: int) -> dict[str, int]:
    """Map 'Top/Sub/Item' paths of the Fuse window menu to command IDs."""
    user32.GetMenu.restype = wintypes.HMENU
    user32.GetSubMenu.restype = wintypes.HMENU
    user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
    user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
    user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
    user32.GetMenuItemID.restype = wintypes.UINT
    user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
    result: dict[str, int] = {}

    def walk(hm, prefix):
        for i in range(user32.GetMenuItemCount(hm)):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetMenuStringW(hm, i, buf, 256, 0x400)  # MF_BYPOSITION
            name = buf.value.replace("&", "").split("	")[0].strip().rstrip(".").strip()
            sub = user32.GetSubMenu(hm, i)
            path = f"{prefix}/{name}" if prefix else name
            if sub:
                walk(sub, path)
            elif name:
                result[path] = user32.GetMenuItemID(hm, i)

    hm = user32.GetMenu(hwnd)
    if hm:
        walk(hm, "")
    return result


def menu_command(hwnd: int, path: str) -> None:
    items = menu_items(hwnd)
    key = next((k for k in items if k.lower() == path.lower()), None)
    if key is None:
        raise SystemExit(f"menu item {path!r} not found; available: {sorted(items)[:40]} ...")
    user32.PostMessageW(hwnd, 0x0111, items[key], 0)  # WM_COMMAND


VK = {"ENTER": 0x0D, "SPACE": 0x20, "SYM": 0x11, "CAPS": 0x10}
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101


def post_keys(hwnd: int, spec: str) -> None:
    """Post key presses to the Fuse window only.

    spec: comma separated steps; a step is KEY or KEY+KEY (held together) or
    WAIT<seconds>. Keys: letters, digits, ENTER, SPACE, SYM (Symbol Shift =
    Ctrl in Fuse), CAPS (Caps Shift = Shift). Example: "R,ENTER" or
    "J,SYM+B,SYM+P,H,I,SYM+P,ENTER".
    """
    for step in spec.split(","):
        step = step.strip()
        if not step:
            continue
        if step.upper().startswith("MENU:"):
            menu_command(hwnd, step[5:])
            time.sleep(0.3)
            continue
        if step.upper().startswith("WAIT"):
            time.sleep(float(step[4:]))
            continue
        vks = [VK[k.upper()] if k.upper() in VK else ord(k.upper()) for k in step.split("+")]
        for vk in vks:
            sc = user32.MapVirtualKeyW(vk, 0)
            user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 1 | (sc << 16))
            time.sleep(0.03)
        time.sleep(0.12)
        for vk in reversed(vks):
            sc = user32.MapVirtualKeyW(vk, 0)
            user32.PostMessageW(hwnd, WM_KEYUP, vk, 1 | (sc << 16) | (0xC0 << 24))
            time.sleep(0.03)
        time.sleep(0.15)


def run(args: list[str], seconds: float, png: Path, keys: str | None = None,
        boot: float = 4.0) -> bool:
    proc = subprocess.Popen([str(FUSE), "--no-autosave-settings", "--no-sound", "--no-confirm-actions", *args],
                            cwd=FUSE.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if keys:
            time.sleep(boot)
            hwnd = find_window(proc.pid)
            if hwnd:
                post_keys(hwnd, keys)
        time.sleep(seconds)
        hwnd = find_window(proc.pid)
        if not hwnd:
            return False
        capture(hwnd, png)
        return True
    finally:
        proc.kill()
        proc.wait(10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--disk", help="D40/D80 image to boot with MDOS")
    ap.add_argument("--snapshot")
    ap.add_argument("--tape")
    ap.add_argument("--rom", default=str(MDOS_ROM), help="14K MDOS 1.x ROM for the Didaktik 80 interface")
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--keys", help='keys to type after boot, e.g. "R,ENTER" (see post_keys)')
    ap.add_argument("--name", help="output PNG name (without extension)")
    ap.add_argument("outdir")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    args = ["--machine", "48"]
    src = a.disk or a.snapshot or a.tape
    if a.disk:
        args += ["--didaktik80", "--rom-didaktik80", str(Path(a.rom).resolve()),
                 "--didaktik80disk", str(Path(a.disk).resolve())]
    if a.snapshot:
        args += ["--snapshot", str(Path(a.snapshot).resolve())]
    if a.tape:
        args += ["--tape", str(Path(a.tape).resolve())]
    name = a.name or re.sub(r"[^\w.+-]", "_", Path(src).stem if src else "boot")
    png = out / f"{name}.png"
    ok = run(args, a.seconds, png, a.keys)
    print(f"{src} -> {png if ok else 'NO WINDOW'}")


if __name__ == "__main__":
    main()
