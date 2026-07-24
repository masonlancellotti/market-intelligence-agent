"""Generate the PWA app icons (dark rounded square + blue meridian waveform).

Pure numpy + zlib PNG encoder (no Pillow dependency). Writes web/public/icon-*.png.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "web" / "public"


def _png(rgba: np.ndarray) -> bytes:
    h, w, _ = rgba.shape
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0
        raw.extend(rgba[y].tobytes())

    def chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def _rounded_mask(n: int, r: float) -> np.ndarray:
    ys, xs = np.mgrid[0:n, 0:n].astype(float)
    m = np.ones((n, n), bool)
    for cx, cy in [(r, r), (n - r, r), (r, n - r), (n - r, n - r)]:
        corner = ((xs < r) if cx == r else (xs > n - r)) & ((ys < r) if cy == r else (ys > n - r))
        m &= ~(corner & ((xs - cx) ** 2 + (ys - cy) ** 2 > r * r))
    return m


def make(n: int) -> np.ndarray:
    img = np.zeros((n, n, 4), np.uint8)
    # background: near-black
    img[..., :3] = (10, 10, 12)
    img[..., 3] = 255
    # meridian waveform (two lobes) in Apple blue
    blue = np.array([10, 132, 255], np.uint8)
    xs = np.arange(n)
    amp = n * 0.20
    mid = n * 0.52
    stroke = max(2, n // 40)
    ywave = mid - amp * np.sin(np.clip((xs - n * 0.16) / (n * 0.34), 0, np.pi) * 1.0) \
        + amp * np.sin(np.clip((xs - n * 0.5) / (n * 0.34), 0, np.pi) * 1.0)
    for x in range(int(n * 0.14), int(n * 0.86)):
        yc = int(ywave[x])
        img[max(0, yc - stroke):yc + stroke, x, :3] = blue
    mask = _rounded_mask(n, n * 0.22)
    img[~mask] = (0, 0, 0, 0)
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for size, name in [(180, "icon-180.png"), (512, "icon-512.png"), (32, "favicon.png")]:
        (OUT / name).write_bytes(_png(make(size)))
        print("wrote", OUT / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
