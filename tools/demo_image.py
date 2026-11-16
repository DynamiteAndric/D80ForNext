"""Build the demo disk: an original D80 image used by the tests, the
screenshots and dist/d80/. Everything on it is generated here, so it can be
published freely.

    python tools/demo_image.py dist/d80/demo.d80

Contents (``RUN`` starts the menu):

    P run        menu: A = demo, B = counter, C = CAT
    P demo       BASIC loader: prints a title, loads ``democode``, starts it
    B democode   machine code at #8000: IM 2 (I = #80), the interrupt counts
                 frames and the main loop waits for each frame, then paints
                 moving colour bands into the bottom third of the screen; it
                 never returns
    P counter    a BASIC FOR loop that counts on screen
    B screen1-4  SCREEN$ files (6912 bytes) with generated patterns
    B data01-20  CODE files of different lengths (enough for CAT to scroll)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from basic import tokenize  # noqa: E402
from image import add_file, blank_image  # noqa: E402

DISK_NAME = "D80 Demo"
DISK_ID = b"D8"

CODE_START = 0x8000
DEMO_I = 0x80                    # IM 2 table at #8000-#8100, all #82 -> handler at #8282
MAIN = 0x8110
HANDLER = 0x8282
COUNTER = 0x8300

RUN = '''
10 BORDER 1: PAPER 7: INK 0: CLS
20 PRINT AT 0,0; PAPER 1; INK 7; BRIGHT 1;"        D80 DEMO DISK           "
30 PRINT AT 4,4;"A  Machine code demo (IM 2)"
40 PRINT AT 6,4;"B  BASIC counter"
50 PRINT AT 8,4;"C  Catalogue (CAT)"
60 PRINT AT 21,0; PAPER 1; INK 7;" Press A, B or C                "
70 LET k$=INKEY$: IF k$="" THEN GO TO 70
80 IF k$="a" OR k$="A" THEN LOAD *"demo"
90 IF k$="b" OR k$="B" THEN LOAD *"counter"
100 IF k$="c" OR k$="C" THEN CLS: CAT: STOP
110 GO TO 70
'''

DEMO = f'''
10 CLEAR {CODE_START - 1}: BORDER 0: PAPER 0: INK 7: CLS
20 PRINT AT 2,12; BRIGHT 1;"D80 DEMO"
30 PRINT AT 6,3;"Machine code with IM 2 paints"
40 PRINT AT 7,3;"the colour bands below."
50 PRINT AT 10,3;"Short DRIVE press: snapshot"
60 PRINT AT 11,3;"Hold DRIVE: the D80 menu"
70 LOAD *"democode" CODE
80 RANDOMIZE USR {MAIN}
'''

COUNTER_PRG = '''
10 BORDER 2: PAPER 7: INK 0: CLS
20 PRINT AT 2,6;"Counting - BREAK stops"
30 FOR i=1 TO 9999: PRINT AT 10,13;i: NEXT i
'''


def democode() -> bytes:
    """IM 2 demo, assembled by hand (addresses above)."""
    mem = bytearray(COUNTER + 1 - CODE_START)

    def put(addr: int, code: bytes) -> None:
        mem[addr - CODE_START:addr - CODE_START + len(code)] = code

    put(CODE_START, bytes([HANDLER & 0xFF]) * 257)                 # vector table
    cl, ch = COUNTER & 0xFF, COUNTER >> 8
    anim = MAIN + 23
    code = bytes([              # busy-waits for the next frame (no HALT), like a game
        0xF3,                   # DI
        0x3E, DEMO_I,           # LD A,#80
        0xED, 0x47,             # LD I,A
        0xED, 0x5E,             # IM 2
        0xFB,                   # EI
        0x3A, cl, ch,           # loop: LD A,(counter)
        0x47,                   # LD B,A
        0x3A, cl, ch,           # wait: LD A,(counter)
        0xB8,                   # CP B
        0x28, 0xFA,             # JR Z,wait
        0xCD, anim & 0xFF, anim >> 8,   # CALL anim
        0x18, 0xF1,             # JR loop
    ]) + bytes([
        0x3A, cl, ch,           # anim: LD A,(counter)
        0xCB, 0x3F,             # SRL A          (one step every 2 frames)
        0x4F,                   # LD C,A
        0x21, 0x00, 0x5A,       # LD HL,#5A00    (attributes of the bottom third)
        0x06, 0x00,             # LD B,0         (256 cells)
        0x7D,                   # l: LD A,L
        0x81,                   # ADD A,C
        0xE6, 0x38,             # AND #38        (paper colour)
        0x77,                   # LD (HL),A
        0x23,                   # INC HL
        0x10, 0xF8,             # DJNZ l
        0xC9,                   # RET
    ])
    put(MAIN, code)
    put(HANDLER, bytes([
        0xF5,                   # PUSH AF
        0x3A, cl, ch,           # LD A,(counter)
        0x3C,                   # INC A
        0x32, cl, ch,           # LD (counter),A
        0xF1,                   # POP AF
        0xFB,                   # EI
        0xED, 0x4D,             # RETI
    ]))
    assert MAIN + len(code) < HANDLER
    return bytes(mem)


def screen(n: int) -> bytes:
    """A SCREEN$ with a generated pattern: stripes, checks, diagonals, bands."""
    pix = bytearray(6144)
    for y in range(192):
        addr = ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
        for x in range(32):
            pix[addr + x] = [0xAA if y & 1 else 0x55,
                             0xFF if (x ^ (y >> 3)) & 1 else 0x00,
                             (0x80 >> (y & 7)) | (0x01 << (y & 7)),
                             0xF0 if (y >> 2) & 1 else 0x0F][n % 4]
    attr = bytes(((x + y + n) % 7 + 1) << 3 | 7 * ((x + y) % 2 == 0)
                 for y in range(24) for x in range(32))
    return bytes(pix) + attr


def data(n: int) -> bytes:
    length = 300 + 997 * n
    return bytes((i * 7 + n) & 0xFF for i in range(length))


def build() -> bytes:
    img = bytearray(blank_image(DISK_NAME, DISK_ID))
    for name, src, line in (("run", RUN, 10), ("demo", DEMO, 10), ("counter", COUNTER_PRG, 10)):
        prog = tokenize(src)
        add_file(img, "P", name, prog, param1=line, param2=len(prog))
    add_file(img, "B", "democode", democode(), param1=CODE_START)
    for n in range(1, 5):
        add_file(img, "B", f"screen{n}", screen(n), param1=0x4000)
    for n in range(1, 21):
        add_file(img, "B", f"data{n:02}", data(n), param1=0x8000)
    return bytes(img)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build())
    print(f"{out}: {DISK_NAME!r}, {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
