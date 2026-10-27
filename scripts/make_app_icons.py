#!/usr/bin/env python3
"""Draw the Internship Engine app icons using only the Python standard library."""

import struct
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PURPLE = (0x63, 0x5B, 0xFF)
WHITE = (255, 255, 255)
SCALE = 3


def _rounded_rect(pixels: bytearray, size: int, box: tuple[int, int, int, int], radius: int,
                  color: tuple[int, int, int]) -> None:
    left, top, right, bottom = box
    for y in range(max(0, top), min(size, bottom)):
        cy = min(max(y + 0.5, top + radius), bottom - radius)
        for x in range(max(0, left), min(size, right)):
            cx = min(max(x + 0.5, left + radius), right - radius)
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= radius * radius:
                offset = (y * size + x) * 4
                pixels[offset:offset + 4] = bytes((*color, 255))


def _chunk(kind: bytes, payload: bytes) -> bytes:
    data = kind + payload
    return struct.pack(">I", len(payload)) + data + struct.pack(">I", zlib.crc32(data) & 0xFFFFFFFF)


def make_png(size: int) -> bytes:
    """Return an antialiased RGBA PNG with a rounded purple tile and rising bars."""
    high = size * SCALE
    pixels = bytearray(high * high * 4)
    tile = int(high * 0.08)
    _rounded_rect(pixels, high, (tile, tile, high - tile, high - tile), int(high * 0.21), PURPLE)
    bar_width = int(high * 0.085)
    base = int(high * 0.77)
    for index, height in enumerate((0.19, 0.32, 0.45, 0.58)):
        center = int(high * (0.285 + index * 0.143))
        top = int(high * (0.77 - height))
        _rounded_rect(pixels, high, (center - bar_width // 2, top, center + (bar_width + 1) // 2, base),
                      bar_width // 2, WHITE)

    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            sums = [0, 0, 0, 0]
            for sy in range(SCALE):
                for sx in range(SCALE):
                    offset = (((y * SCALE + sy) * high) + x * SCALE + sx) * 4
                    for channel in range(4):
                        sums[channel] += pixels[offset + channel]
            rows.extend(value // (SCALE * SCALE) for value in sums)
    header = struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


def _self_check() -> None:
    png = make_png(16)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">2I", png[16:24]) == (16, 16)
    assert zlib.decompress(png[41:-16])[0] == 0


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        _self_check()
        print("app icon self-check passed")
        return 0
    if sys.argv[1:]:
        print("usage: make_app_icons.py [--self-check]", file=sys.stderr)
        return 2
    for size in (192, 512):
        path = ROOT / "site" / "app" / f"icon-{size}.png"
        path.write_bytes(make_png(size))
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
