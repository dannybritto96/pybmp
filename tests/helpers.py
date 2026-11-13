"""Hand-rolled BMP builder used to craft files independently of pybmp.encode."""

from __future__ import annotations

import random
import struct

__all__ = ["build_bmp", "pad_rows", "random_bytes"]


def random_bytes(n: int, seed: int = 0, limit: int = 256) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.randrange(limit) for _ in range(n))


def pad_rows(rows: list[bytes]) -> bytes:
    """Pad each stored row to a multiple of 4 bytes and concatenate."""
    return b"".join(r + bytes(-len(r) % 4) for r in rows)


def build_bmp(
    *,
    header_size: int = 40,
    width: int,
    height: int,
    bpp: int,
    pixel_data: bytes,
    compression: int = 0,
    palette: list[tuple[int, int, int]] | None = None,
    masks: tuple[int, ...] | None = None,
    colors_used: int | None = None,
    image_size: int | None = None,
    signature: bytes = b"BM",
    offset_adjust: int = 0,
) -> bytes:
    """Build a BMP byte string with an arbitrary header version.

    ``masks`` go inside the header for V2+ headers and after a 40-byte header.
    """
    palette = palette or []
    if header_size == 12:
        dib = struct.pack("<IHHHH", 12, width, height, 1, bpp)
        pal = b"".join(bytes((b, g, r)) for r, g, b in palette)
        extra = b""
    elif header_size == 16:
        dib = struct.pack("<IiiHH", 16, width, height, 1, bpp)
        pal = b"".join(bytes((b, g, r, 0)) for r, g, b in palette)
        extra = b""
    else:
        dib = struct.pack(
            "<IiiHHIIiiII",
            header_size,
            width,
            height,
            1,
            bpp,
            compression,
            len(pixel_data) if image_size is None else image_size,
            2835,
            2835,
            len(palette) if colors_used is None else colors_used,
            0,
        )
        extra = b""
        if header_size == 40 and masks:
            extra = struct.pack(f"<{len(masks)}I", *masks)
        elif header_size >= 52 and header_size != 64:
            m = tuple(masks or ()) + (0,) * (4 - len(masks or ()))
            dib += struct.pack("<III", *m[:3])
            if header_size >= 56:
                dib += struct.pack("<I", m[3])
        dib += bytes(header_size - len(dib))
        if header_size >= 108:
            dib = dib[:56] + struct.pack("<I", 0x73524742) + dib[60:]
        pal = b"".join(bytes((b, g, r, 0)) for r, g, b in palette)
    offset = 14 + len(dib) + len(extra) + len(pal) + offset_adjust
    body = dib + extra + pal + bytes(max(0, offset_adjust)) + pixel_data
    head = struct.pack("<2sIHHI", signature, 14 + len(body), 0, 0, offset)
    return head + body
