"""Writing standard .tap files."""

from __future__ import annotations

TAPE_PROGRAM, TAPE_NUM_ARRAY, TAPE_CHAR_ARRAY, TAPE_CODE = 0, 1, 2, 3


def _block(flag: int, payload: bytes) -> bytes:
    body = bytes([flag]) + payload
    chk = 0
    for b in body:
        chk ^= b
    body += bytes([chk])
    return len(body).to_bytes(2, "little") + body


def tape_name(name: str | bytes) -> bytes:
    raw = name.encode("latin-1", "replace") if isinstance(name, str) else bytes(name)
    raw = raw.rstrip(b"\x00").replace(b"\x00", b" ")
    return raw[:10].ljust(10, b" ")


def file_blocks(kind: int, name: str | bytes, data: bytes, param1: int, param2: int) -> bytes:
    header = bytes([kind]) + tape_name(name) + len(data).to_bytes(2, "little") \
        + (param1 & 0xFFFF).to_bytes(2, "little") + (param2 & 0xFFFF).to_bytes(2, "little")
    return _block(0x00, header) + _block(0xFF, data)


def program(name, data: bytes, autostart: int | None, prog_len: int) -> bytes:
    line = 0x8000 if autostart is None or autostart > 9999 else autostart
    return file_blocks(TAPE_PROGRAM, name, data, line, prog_len)


def code(name, data: bytes, start: int) -> bytes:
    return file_blocks(TAPE_CODE, name, data, start, 0x8000)
