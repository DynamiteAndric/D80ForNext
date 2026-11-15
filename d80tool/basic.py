"""ZX Spectrum BASIC listing and MDOS -> tape loader rewriting."""

from __future__ import annotations

TOKENS = {
    0xA3: "SPECTRUM", 0xA4: "PLAY", 0xA5: "RND", 0xA6: "INKEY$", 0xA7: "PI",
    0xA8: "FN", 0xA9: "POINT", 0xAA: "SCREEN$", 0xAB: "ATTR", 0xAC: "AT",
    0xAD: "TAB", 0xAE: "VAL$", 0xAF: "CODE", 0xB0: "VAL", 0xB1: "LEN",
    0xB2: "SIN", 0xB3: "COS", 0xB4: "TAN", 0xB5: "ASN", 0xB6: "ACS",
    0xB7: "ATN", 0xB8: "LN", 0xB9: "EXP", 0xBA: "INT", 0xBB: "SQR",
    0xBC: "SGN", 0xBD: "ABS", 0xBE: "PEEK", 0xBF: "IN", 0xC0: "USR",
    0xC1: "STR$", 0xC2: "CHR$", 0xC3: "NOT", 0xC4: "BIN", 0xC5: "OR",
    0xC6: "AND", 0xC7: "<=", 0xC8: ">=", 0xC9: "<>", 0xCA: "LINE",
    0xCB: "THEN", 0xCC: "TO", 0xCD: "STEP", 0xCE: "DEF FN", 0xCF: "CAT",
    0xD0: "FORMAT", 0xD1: "MOVE", 0xD2: "ERASE", 0xD3: "OPEN #",
    0xD4: "CLOSE #", 0xD5: "MERGE", 0xD6: "VERIFY", 0xD7: "BEEP",
    0xD8: "CIRCLE", 0xD9: "INK", 0xDA: "PAPER", 0xDB: "FLASH",
    0xDC: "BRIGHT", 0xDD: "INVERSE", 0xDE: "OVER", 0xDF: "OUT",
    0xE0: "LPRINT", 0xE1: "LLIST", 0xE2: "STOP", 0xE3: "READ", 0xE4: "DATA",
    0xE5: "RESTORE", 0xE6: "NEW", 0xE7: "BORDER", 0xE8: "CONTINUE",
    0xE9: "DIM", 0xEA: "REM", 0xEB: "FOR", 0xEC: "GO TO", 0xED: "GO SUB",
    0xEE: "INPUT", 0xEF: "LOAD", 0xF0: "LIST", 0xF1: "LET", 0xF2: "PAUSE",
    0xF3: "NEXT", 0xF4: "POKE", 0xF5: "PRINT", 0xF6: "PLOT", 0xF7: "RUN",
    0xF8: "SAVE", 0xF9: "RANDOMIZE", 0xFA: "IF", 0xFB: "CLS", 0xFC: "DRAW",
    0xFD: "CLEAR", 0xFE: "RETURN", 0xFF: "COPY",
}

TOK_LOAD = 0xEF
TOK_POKE = 0xF4
TOK_REM = 0xEA
NUMBER_MARK = 0x0E


def iter_lines(data: bytes, prog_len: int | None = None):
    """Yield (line_number, body, offset) for each BASIC line."""
    end = len(data) if prog_len is None else min(prog_len, len(data))
    pos = 0
    while pos + 4 <= end:
        num = (data[pos] << 8) | data[pos + 1]
        if num > 16383:
            break
        ln = data[pos + 2] | (data[pos + 3] << 8)
        body = data[pos + 4:pos + 4 + ln]
        yield num, body, pos
        pos += 4 + ln


def detokenize(body: bytes) -> str:
    out = []
    i = 0
    in_string = False
    in_rem = False
    while i < len(body):
        c = body[i]
        if c == 0x0D:
            break
        if not in_string and not in_rem and c == NUMBER_MARK:
            i += 6
            continue
        if c == 0x22:
            in_string = not in_string
            out.append('"')
        elif c >= 0xA3 and not in_string and not in_rem:
            word = TOKENS[c]
            if out and out[-1][-1:] not in (" ", ""):
                out.append(" ")
            out.append(word + " ")
            if c == TOK_REM:
                in_rem = True
        elif 32 <= c < 127:
            out.append(chr(c))
        elif 0x10 <= c <= 0x15:  # colour control codes take one parameter
            i += 1
        elif c in (0x16, 0x17):
            i += 2
        else:
            out.append(f"{{{c:02X}}}")
        i += 1
    return "".join(out).rstrip()


def listing(data: bytes, prog_len: int | None = None) -> str:
    return "\n".join(f"{n:>4} {detokenize(b)}" for n, b, _ in iter_lines(data, prog_len))


def rewrite_mdos_loader(data: bytes, prog_len: int) -> tuple[bytes, int, int]:
    """Turn MDOS disk syntax into tape syntax without changing any lengths.

    ``LOAD *"name"`` becomes ``LOAD  "name"`` (the ``*`` is replaced by a space)
    and ``LOAD *"a:name"`` becomes ``LOAD  "name"  `` (the drive prefix moves out
    of the string as two spaces). The ROM interpreter skips spaces, and keeping
    every byte in place matters: many loaders keep machine code behind the
    program (in the variables area) and call it with fixed ``USR`` addresses.
    Returns (new_data, prog_len, changes).
    """
    out = bytearray(data)
    changes = 0
    for _num, body, offset in iter_lines(data, prog_len):
        base = offset + 4
        i = 0
        in_string = False
        in_rem = False
        while i < len(body):
            c = body[i]
            if not in_string and not in_rem and c == NUMBER_MARK:
                i += 6
                continue
            if c == 0x22:
                in_string = not in_string
            elif not in_string and c == TOK_REM:
                in_rem = True
            elif not in_string and not in_rem and c == TOK_POKE and i + 1 < len(body)                     and body[i + 1:i + 2] == b"#":
                # MDOS "POKE #addr,val" writes into D40 RAM: meaningless without the
                # interface and a syntax error on a plain Spectrum. Blank the statement.
                k = i
                q = False
                while k < len(body) and not (not q and body[k] in (ord(":"), 0x0D)):
                    if body[k] == NUMBER_MARK and not q:
                        for m in range(6):
                            out[base + k + m] = 0x20
                        k += 6
                        continue
                    if body[k] == 0x22:
                        q = not q
                    out[base + k] = 0x20
                    k += 1
                changes += 1
                i = k
                continue
            elif not in_string and not in_rem and c == TOK_LOAD:
                j = i + 1
                if j < len(body) and body[j] == ord("*"):
                    out[base + j] = 0x20
                    changes += 1
                    q = j + 1
                    if (q + 3 < len(body) and body[q] == 0x22 and body[q + 2] == ord(":")
                            and chr(body[q + 1]).isalnum()):
                        end = body.find(b'"', q + 3)
                        if end > 0:
                            name = body[q + 3:end]
                            seg = b'"' + name + b'"  '
                            out[base + q:base + end + 1] = seg
                    i = j + 1
                    continue
            i += 1
    assert len(out) == len(data)
    return bytes(out), prog_len, changes
