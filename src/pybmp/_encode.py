"""BMP encoding."""

from __future__ import annotations

import struct
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from ._constants import (
    CORE_HEADER_SIZE,
    FILE_HEADER_SIZE,
    INFO_HEADER_SIZE,
    LCS_SRGB,
    V4_HEADER_SIZE,
    V5_HEADER_SIZE,
    Compression,
)
from ._errors import BMPError, UnsupportedFormatError
from ._header import row_stride
from ._util import or_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["HeaderVersion", "Mode", "encode"]

Mode = Literal["RGB", "RGBA", "P"]
HeaderVersion = Literal["core", "info", "v4", "v5"]

_HEADER_SIZES: dict[str, int] = {
    "core": CORE_HEADER_SIZE,
    "info": INFO_HEADER_SIZE,
    "v4": V4_HEADER_SIZE,
    "v5": V5_HEADER_SIZE,
}
_CHANNELS: dict[str, int] = {"RGB": 3, "RGBA": 4, "P": 1}
_DEFAULT_BITS: dict[str, int] = {"RGB": 24, "RGBA": 32, "P": 8}
_ALLOWED_BITS: dict[str, frozenset[int]] = {
    "RGB": frozenset({16, 24, 32}),
    "RGBA": frozenset({32}),
    "P": frozenset({1, 2, 4, 8}),
}
_RGBA_MASKS = (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
_LCS_GM_IMAGES = 4
#: 72 DPI expressed in pixels per metre.
DEFAULT_PPM = 2835


@lru_cache(maxsize=8)
def _pack_tables(bits: int) -> tuple[bytes, ...]:
    per_byte = 8 // bits
    mask = (1 << bits) - 1
    return tuple(
        bytes(((v & mask) << (8 - bits * (k + 1))) & 0xFF for v in range(256))
        for k in range(per_byte)
    )


_R_HI = bytes((v >> 3) << 2 for v in range(256))
_G_HI = bytes(v >> 6 for v in range(256))
_G_LO = bytes(((v >> 3) & 7) << 5 for v in range(256))
_B_LO = bytes(v >> 3 for v in range(256))


def _pack_pixels(pixels: bytes, mode: str, bits: int, width: int, height: int) -> bytes:
    """Return unpadded, top-down stored rows for the requested pixel format."""
    if mode == "P":
        if bits == 8:
            return pixels
        per_byte = 8 // bits
        padded = -(-width // per_byte) * per_byte
        if padded != width:
            mv = memoryview(pixels)
            fill = bytes(padded - width)
            pixels = b"".join(
                [
                    mv[s : s + width].tobytes() + fill
                    for s in range(0, width * height, width)
                ]
            )
        tables = _pack_tables(bits)
        packed = pixels[0::per_byte].translate(tables[0])
        for k in range(1, per_byte):
            packed = or_bytes(packed, pixels[k::per_byte].translate(tables[k]))
        return packed
    step = _CHANNELS[mode]
    r, g, b = pixels[0::step], pixels[1::step], pixels[2::step]
    n = width * height
    if bits == 24:
        out = bytearray(n * 3)
        out[0::3], out[1::3], out[2::3] = b, g, r
        return bytes(out)
    if bits == 32:
        out = bytearray(n * 4)
        out[0::4], out[1::4], out[2::4] = b, g, r
        if mode == "RGBA":
            out[3::4] = pixels[3::4]
        return bytes(out)
    # 16-bit X1R5G5B5
    out = bytearray(n * 2)
    out[0::2] = or_bytes(g.translate(_G_LO), b.translate(_B_LO))
    out[1::2] = or_bytes(r.translate(_R_HI), g.translate(_G_HI))
    return bytes(out)


def encode(
    width: int,
    height: int,
    pixels: bytes | bytearray | memoryview,
    *,
    mode: Mode = "RGB",
    bits: int | None = None,
    palette: Sequence[tuple[int, int, int]] | None = None,
    top_down: bool = False,
    header: HeaderVersion | None = None,
    pixels_per_meter: int = DEFAULT_PPM,
) -> bytes:
    """Encode raw pixels into a complete BMP file.

    Args:
        width: Image width in pixels.
        height: Image height in pixels (always positive; use ``top_down``).
        pixels: Packed top-down pixel data: 3 bytes per pixel for ``"RGB"``,
            4 for ``"RGBA"`` and one palette index per pixel for ``"P"``.
        mode: Layout of ``pixels``.
        bits: Stored bits per pixel. Defaults to 24 (RGB), 32 (RGBA) or 8 (P).
            RGB supports 16 (X1R5G5B5), 24 and 32; RGBA supports 32; P
            supports 1, 2, 4 and 8.
        palette: ``(r, g, b)`` tuples, required for mode ``"P"``.
        top_down: Store rows top-down (negative height). Not valid for
            ``header="core"``.
        header: DIB header version. Defaults to ``"v4"`` for RGBA (needed for
            the alpha mask) and ``"info"`` otherwise.
        pixels_per_meter: Horizontal and vertical resolution to record.

    Returns:
        The encoded BMP file.

    Raises:
        BMPError: for inconsistent arguments.
        UnsupportedFormatError: for a combination BMP cannot express.
    """
    if mode not in _CHANNELS:
        raise BMPError(f"unknown mode {mode!r}; expected 'RGB', 'RGBA' or 'P'")
    if width <= 0 or height <= 0:
        raise BMPError(f"width and height must be positive, got {width}x{height}")
    bits = _DEFAULT_BITS[mode] if bits is None else bits
    if bits not in _ALLOWED_BITS[mode]:
        raise UnsupportedFormatError(
            f"mode {mode} cannot be stored with {bits} bits per pixel "
            f"(allowed: {sorted(_ALLOWED_BITS[mode])})"
        )
    if header is None:
        header = "v4" if mode == "RGBA" else "info"
    if header not in _HEADER_SIZES:
        raise BMPError(f"unknown header version {header!r}")
    pixels = bytes(pixels)
    expected = width * height * _CHANNELS[mode]
    if len(pixels) != expected:
        raise BMPError(
            f"expected {expected} bytes of {mode} data for {width}x{height}, "
            f"got {len(pixels)}"
        )
    if mode == "RGBA" and header not in ("v4", "v5"):
        raise UnsupportedFormatError(
            "RGBA needs header='v4' or 'v5' to store the alpha mask"
        )
    if header == "core":
        if bits not in (1, 4, 8, 24):
            raise UnsupportedFormatError("BITMAPCOREHEADER supports 1, 4, 8 or 24 bits")
        if top_down:
            raise UnsupportedFormatError("BITMAPCOREHEADER cannot store top-down rows")
        if width > 0xFFFF or height > 0xFFFF:
            raise UnsupportedFormatError("BITMAPCOREHEADER is limited to 65535x65535")

    pal: list[tuple[int, int, int]] = []
    if mode == "P":
        if not palette:
            raise BMPError("mode 'P' requires a palette")
        pal = [(int(r), int(g), int(b)) for r, g, b in palette]
        if any(not 0 <= v <= 255 for entry in pal for v in entry):
            raise BMPError("palette components must be in the range 0..255")
        if len(pal) > 1 << bits:
            raise BMPError(
                f"palette has {len(pal)} colours; {bits}-bit allows {1 << bits}"
            )
        if pixels and max(pixels) >= len(pal):
            raise BMPError(f"pixel index {max(pixels)} is outside the palette")

    compression = Compression.BI_BITFIELDS if mode == "RGBA" else Compression.BI_RGB
    packed = _pack_pixels(pixels, mode, bits, width, height)
    row_bytes = len(packed) // height
    stride = row_stride(bits, width)
    pad = bytes(stride - row_bytes)
    if pad or not top_down:
        mv = memoryview(packed)
        starts = range(0, row_bytes * height, row_bytes)
        if not top_down:
            starts = starts[::-1]
        if pad:
            pixel_data = pad.join([mv[s : s + row_bytes] for s in starts]) + pad
        else:
            pixel_data = b"".join([mv[s : s + row_bytes] for s in starts])
    else:
        pixel_data = packed

    header_size = _HEADER_SIZES[header]
    if header == "core":
        dib = struct.pack("<IHHHH", header_size, width, height, 1, bits)
        pal_bytes = b"".join(struct.pack("<BBB", b, g, r) for r, g, b in pal)
    else:
        dib = struct.pack(
            "<IiiHHIIiiII",
            header_size,
            width,
            -height if top_down else height,
            1,
            bits,
            compression,
            len(pixel_data),
            pixels_per_meter,
            pixels_per_meter,
            len(pal),
            0,
        )
        if header_size >= V4_HEADER_SIZE:
            masks = _RGBA_MASKS if mode == "RGBA" else (0, 0, 0, 0)
            dib += struct.pack("<IIII", *masks)
            dib += struct.pack("<I36sIII", LCS_SRGB, bytes(36), 0, 0, 0)
        if header_size == V5_HEADER_SIZE:
            dib += struct.pack("<IIII", _LCS_GM_IMAGES, 0, 0, 0)
        pal_bytes = b"".join(struct.pack("<BBBB", b, g, r, 0) for r, g, b in pal)

    offset = FILE_HEADER_SIZE + len(dib) + len(pal_bytes)
    file_size = offset + len(pixel_data)
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, offset)
    return b"".join((file_header, dib, pal_bytes, pixel_data))
