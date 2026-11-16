"""Tokenize ZX Spectrum 48K BASIC source text into a program (as SAVE stores it).

    from basic import tokenize
    prog = tokenize('''
    10 BORDER 0: CLS
    20 PRINT AT 2,4;"Hello"
    ''')

Enough for small, hand-written programs: keywords are written in upper case,
spaces outside strings and REM are dropped (LIST puts them back), and every
number outside a string gets its hidden 5-byte form (integers 0-65535 only).
Variable names must not start with or contain a keyword (``cat``, ``total``).
"""

from __future__ import annotations

KEYWORDS = [
    "RND", "INKEY$", "PI", "FN", "POINT", "SCREEN$", "ATTR", "AT", "TAB", "VAL$",
    "CODE", "VAL", "LEN", "SIN", "COS", "TAN", "ASN", "ACS", "ATN", "LN", "EXP",
    "INT", "SQR", "SGN", "ABS", "PEEK", "IN", "USR", "STR$", "CHR$", "NOT", "BIN",
    "OR", "AND", "<=", ">=", "<>", "LINE", "THEN", "TO", "STEP", "DEF FN", "CAT",
    "FORMAT", "MOVE", "ERASE", "OPEN #", "CLOSE #", "MERGE", "VERIFY", "BEEP",
    "CIRCLE", "INK", "PAPER", "FLASH", "BRIGHT", "INVERSE", "OVER", "OUT", "LPRINT",
    "LLIST", "STOP", "READ", "DATA", "RESTORE", "NEW", "BORDER", "CONTINUE", "DIM",
    "REM", "FOR", "GO TO", "GO SUB", "INPUT", "LOAD", "LIST", "LET", "PAUSE", "NEXT",
    "POKE", "PRINT", "PLOT", "RUN", "SAVE", "RANDOMIZE", "IF", "CLS", "DRAW", "CLEAR",
    "RETURN", "COPY",
]
TOKENS = {k: 0xA5 + i for i, k in enumerate(KEYWORDS)}
BY_LENGTH = sorted(KEYWORDS, key=len, reverse=True)


class BasicError(ValueError):
    pass


def _number(text: str) -> bytes:
    n = int(text)
    if not 0 <= n <= 0xFFFF:
        raise BasicError(f"only integers 0-65535 are supported: {text}")
    return text.encode() + bytes([0x0E, 0, 0, n & 0xFF, n >> 8, 0])


def tokenize_line(body: str) -> bytes:
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c == '"':                                    # string literal, as is
            j = body.index('"', i + 1)
            while j + 1 < len(body) and body[j + 1] == '"':   # "" inside a string
                j = body.index('"', j + 2)
            out += body[i:j + 1].encode("latin-1")
            i = j + 1
            continue
        if c == " ":
            i += 1
            continue
        prev = body[i - 1] if i else " "
        if c.isdigit() and not (prev.isalnum() or prev == "$"):
            j = i
            while j < len(body) and body[j].isdigit():
                j += 1
            out += _number(body[i:j])
            i = j
            continue
        if not prev.isalpha():
            for k in BY_LENGTH:
                end = i + len(k)
                if body[i:end] != k:
                    continue
                if k[-1].isalpha() and end < len(body) and body[end].isalpha():
                    continue                            # e.g. a variable "TOTAL"
                out.append(TOKENS[k])
                i = end
                if k == "REM":                          # the rest of the line, as is
                    out += body[i:].lstrip(" ").encode("latin-1")
                    i = len(body)
                break
            else:
                out += c.encode("latin-1")
                i += 1
            continue
        out += c.encode("latin-1")
        i += 1
    return bytes(out)


def tokenize(source: str) -> bytes:
    """A whole program: lines ``<number> <statements>``, blank lines ignored."""
    prog = bytearray()
    last = 0
    for raw in source.strip().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        num, _, body = raw.partition(" ")
        n = int(num)
        if not last < n <= 9999:
            raise BasicError(f"bad line number order: {n}")
        last = n
        line = tokenize_line(body) + b"\x0D"
        prog += n.to_bytes(2, "big") + len(line).to_bytes(2, "little") + line
    return bytes(prog)
