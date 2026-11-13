"""Pixel-array decoding.

All hot paths work on whole buffers with C-level operations
(``bytes.translate``, extended slice assignment, ``bytes.join``,
``array``/``memoryview`` and big-integer bit operations) rather than per-pixel
Python loops. Only RLE decoding, which is inherently sequential, and arbitrary
non byte-aligned 32-bit bit fields without numpy fall back to Python loops.
"""

from __future__ import annotations

import sys
from array import array
from functools import lru_cache
from typing import TYPE_CHECKING

from ._constants import Compression
from ._errors import InvalidBMPError, TruncatedFileError, UnsupportedFormatError
from ._util import or_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._header import BMPHeader

__all__ = [
    "decode_indices",
    "decode_rgb",
    "effective_masks",
    "has_alpha",
    "pixel_array",
    "rgb_to_rgba",
]

try:  # optional speed-up for arbitrary bit-field layouts
    import numpy as _np
except ImportError:  # pragma: no cover - exercised in CI without numpy
    _np = None  # type: ignore[assignment]

#: Value of a channel whose mask is empty: black for colour, opaque for alpha.
_EMPTY = (0, 0, 0, 255)

_DEFAULT_MASKS: dict[int, tuple[int, int, int, int]] = {
    16: (0x7C00, 0x03E0, 0x001F, 0),
    32: (0x00FF0000, 0x0000FF00, 0x000000FF, 0),
}


def _uses_bitfields(header: BMPHeader) -> bool:
    return not header.is_os2 and header.compression in (
        Compression.BI_BITFIELDS,
        Compression.BI_ALPHABITFIELDS,
    )


def effective_masks(header: BMPHeader) -> tuple[int, int, int, int]:
    """Return the ``(red, green, blue, alpha)`` masks used for 16/32-bit pixels."""
    if _uses_bitfields(header):
        return (header.red_mask, header.green_mask, header.blue_mask, header.alpha_mask)
    return _DEFAULT_MASKS.get(header.bits_per_pixel, (0, 0, 0, 0))


def has_alpha(header: BMPHeader) -> bool:
    """``True`` when the pixel format carries a real alpha channel."""
    return header.bits_per_pixel in (16, 32) and effective_masks(header)[3] != 0


def _check_compression(header: BMPHeader) -> None:
    comp, bpp = header.compression, header.bits_per_pixel
    if header.is_os2 and comp in (3, 4):
        raise UnsupportedFormatError(
            "OS/2 Huffman 1D and RLE24 compression are not supported"
        )
    if comp == Compression.BI_RGB:
        return
    if comp == Compression.BI_RLE8 and bpp == 8:
        return
    if comp == Compression.BI_RLE4 and bpp == 4:
        return
    if _uses_bitfields(header) and bpp in (16, 32):
        return
    try:
        name = Compression(comp).name
    except ValueError:
        name = f"compression {comp}"
    raise UnsupportedFormatError(f"{name} with {bpp} bits per pixel is not supported")


def pixel_array(data: bytes, header: BMPHeader) -> bytes:
    """Return the raw stored pixel array, read from ``header.pixel_offset``.

    For uncompressed images this is exactly ``stride * abs(height)`` bytes; for
    compressed images it is ``image_size`` bytes (or the rest of the file).
    """
    start = header.pixel_offset
    if header.compression in (Compression.BI_RGB,) or (
        _uses_bitfields(header) and header.bits_per_pixel in (16, 32)
    ):
        length = header.stride * abs(header.height)
        end = start + length
        if end > len(data):
            raise TruncatedFileError(
                f"pixel array needs {length} bytes from offset {start}, "
                f"but only {max(0, len(data) - start)} are present"
            )
        return data[start:end]
    if start > len(data):
        raise TruncatedFileError(f"pixel data offset {start} is past end of file")
    end = start + header.image_size if header.image_size else len(data)
    if end > len(data):
        raise TruncatedFileError("compressed pixel data is truncated")
    return data[start:end]


def _packed_rows(data: bytes, header: BMPHeader) -> bytes:
    """Return unpadded rows in top-down order."""
    raw = pixel_array(data, header)
    stride = header.stride
    row_bytes = (header.bits_per_pixel * header.width + 7) // 8
    height = abs(header.height)
    if stride == row_bytes and header.top_down:
        return raw
    mv = memoryview(raw)
    starts = range(0, stride * height, stride)
    if not header.top_down:
        starts = starts[::-1]
    return b"".join([mv[s : s + row_bytes] for s in starts])


@lru_cache(maxsize=8)
def _unpack_tables(bpp: int) -> tuple[bytes, ...]:
    """``translate`` tables extracting each sub-byte pixel from a packed byte."""
    per_byte = 8 // bpp
    mask = (1 << bpp) - 1
    return tuple(
        bytes((b >> (8 - bpp * (k + 1))) & mask for b in range(256))
        for k in range(per_byte)
    )


def _expand_indices(packed: bytes, bpp: int, width: int, height: int) -> bytes:
    if bpp == 8:
        return packed
    per_byte = 8 // bpp
    out = bytearray(len(packed) * per_byte)
    for k, table in enumerate(_unpack_tables(bpp)):
        out[k::per_byte] = packed.translate(table)
    padded_width = ((bpp * width + 7) // 8) * per_byte
    if padded_width == width:
        return bytes(out)
    mv = memoryview(out)
    return b"".join(
        [mv[s : s + width] for s in range(0, padded_width * height, padded_width)]
    )


def _decode_rle(data: bytes, header: BMPHeader) -> bytes:
    """Decode BI_RLE8 / BI_RLE4 into one index per pixel, top-down."""
    src = pixel_array(data, header)
    width, height = header.width, abs(header.height)
    four = header.compression == Compression.BI_RLE4
    out = bytearray(width * height)
    x = y = i = 0
    n = len(src)
    while i + 1 < n and y < height:
        count, value = src[i], src[i + 1]
        i += 2
        if count:  # encoded run
            run = min(count, width - x)
            if run > 0:
                row = y * width + x
                if four:
                    hi, lo = value >> 4, value & 0x0F
                    out[row : row + run] = bytes((hi, lo)) * (run // 2) + (
                        bytes((hi,)) if run & 1 else b""
                    )
                else:
                    out[row : row + run] = bytes((value,)) * run
            x += count
        elif value == 0:  # end of line
            x, y = 0, y + 1
        elif value == 1:  # end of bitmap
            break
        elif value == 2:  # delta
            if i + 1 >= n:
                raise TruncatedFileError("RLE delta escape is truncated")
            x += src[i]
            y += src[i + 1]
            i += 2
        else:  # absolute run of `value` pixels
            nbytes = (value + 1) // 2 if four else value
            chunk = src[i : i + nbytes]
            if len(chunk) < nbytes:
                raise TruncatedFileError("RLE absolute run is truncated")
            if four:
                pix = bytearray(nbytes * 2)
                pix[0::2] = chunk.translate(_unpack_tables(4)[0])
                pix[1::2] = chunk.translate(_unpack_tables(4)[1])
                del pix[value:]
            else:
                pix = bytearray(chunk)
            run = min(value, width - x)
            if run > 0:
                row = y * width + x
                out[row : row + run] = pix[:run]
            x += value
            i += nbytes + (nbytes & 1)  # runs are word aligned
    # RLE bitmaps are stored bottom-up; flip to top-down.
    if header.height > 0:
        mv = memoryview(out)
        return b"".join(
            [mv[s : s + width] for s in range(width * (height - 1), -1, -width)]
        )
    return bytes(out)


def decode_indices(data: bytes, header: BMPHeader) -> bytes:
    """Return one palette index per pixel (top-down rows) for <= 8-bit images."""
    if header.bits_per_pixel > 8:
        raise UnsupportedFormatError(
            f"{header.bits_per_pixel}-bit images have no palette indices"
        )
    _check_compression(header)
    if header.compression in (Compression.BI_RLE8, Compression.BI_RLE4):
        return _decode_rle(data, header)
    packed = _packed_rows(data, header)
    return _expand_indices(
        packed, header.bits_per_pixel, header.width, abs(header.height)
    )


def _palette_tables(palette: Sequence[tuple[int, int, int]]) -> tuple[bytes, ...]:
    entries = list(palette[:256]) + [(0, 0, 0)] * (256 - min(len(palette), 256))
    return tuple(bytes(e[c] for e in entries) for c in range(3))


def _apply_palette(indices: bytes, palette: Sequence[tuple[int, int, int]]) -> bytes:
    out = bytearray(len(indices) * 3)
    for c, table in enumerate(_palette_tables(palette)):
        out[c::3] = indices.translate(table)
    return bytes(out)


def _mask_shift_bits(mask: int) -> tuple[int, int]:
    if mask == 0:
        return 0, 0
    shift = (mask & -mask).bit_length() - 1
    return shift, (mask >> shift).bit_length()


def _scale(value: int, bits: int) -> int:
    """Scale an n-bit channel value to 0..255, truncating like Pillow."""
    if bits == 8:
        return value
    return (value * 255) // ((1 << bits) - 1)


@lru_cache(maxsize=16)
def _table16(masks: tuple[int, int, int, int], alpha: bool) -> list[bytes]:
    """Map every 16-bit pixel value to its RGB(A) bytes."""
    channels = [_mask_shift_bits(m) for m in masks[: 4 if alpha else 3]]
    return [
        bytes(
            _scale((v >> s) & ((1 << b) - 1), b) if b else _EMPTY[i]
            for i, (s, b) in enumerate(channels)
        )
        for v in range(1 << 16)
    ]


def _byte_aligned(mask: int) -> int | None:
    """Return the byte index of an 8-bit byte-aligned mask, else ``None``."""
    for k in range(4):
        if mask == 0xFF << (8 * k):
            return k
    return None


def _decode16_bytewise(packed: bytes, masks: tuple[int, ...], channels: int) -> bytes:
    """Decode 16-bit pixels whose channels are <= 8 bits without a Python loop.

    Each channel is assembled from the low and high byte of every pixel with
    ``bytes.translate`` and combined with a big-integer OR, then scaled to
    0..255 with one more ``translate``.
    """
    lo, hi = packed[0::2], packed[1::2]
    npix = len(lo)
    out = bytearray(npix * channels)
    for c, m in enumerate(masks):
        shift, bits = _mask_shift_bits(m)
        if bits == 0:
            out[c::channels] = bytes((_EMPTY[c],)) * npix
            continue
        maxval = (1 << bits) - 1
        lo_t = bytes(((v >> shift) & maxval) if shift < 8 else 0 for v in range(256))
        hi_t = bytes((((v << 8) >> shift) & maxval) for v in range(256))
        if any(lo_t) and any(hi_t):
            raw = or_bytes(lo.translate(lo_t), hi.translate(hi_t))
        elif any(hi_t):
            raw = hi.translate(hi_t)
        else:
            raw = lo.translate(lo_t)
        scale = bytes(_scale(v, bits) if v <= maxval else 0 for v in range(256))
        out[c::channels] = raw.translate(scale)
    return bytes(out)


def _decode_bitfields(packed: bytes, header: BMPHeader, alpha: bool) -> bytes:
    bpp = header.bits_per_pixel
    masks = effective_masks(header)
    channels = 4 if alpha else 3
    npix = len(packed) // (bpp // 8)
    used = masks[:channels]

    if bpp == 32 and all(_byte_aligned(m) is not None for m in used):
        out = bytearray(npix * channels)
        for c, m in enumerate(used):
            k = _byte_aligned(m)
            out[c::channels] = packed[k::4]
        return bytes(out)

    if _np is not None:
        dtype = "<u2" if bpp == 16 else "<u4"
        wide = _np.uint32 if bpp == 16 else _np.uint64
        values = _np.frombuffer(packed, dtype=dtype).astype(wide)
        result = _np.empty((npix, channels), dtype=_np.uint8)
        for c, m in enumerate(used):
            shift, bits = _mask_shift_bits(m)
            if bits == 0:
                result[:, c] = _EMPTY[c]
                continue
            maxval = (1 << bits) - 1
            result[:, c] = ((values >> shift) & maxval) * 255 // maxval
        return bytes(result.tobytes())

    if bpp == 16 and all(_mask_shift_bits(m)[1] <= 8 for m in used):
        return _decode16_bytewise(packed, used, channels)

    if bpp == 16:
        values16 = array("H", packed)
        if sys.byteorder == "big":  # pragma: no cover - big-endian hosts only
            values16.byteswap()
        return b"".join(map(_table16(masks, alpha).__getitem__, values16))

    values32 = array("I", packed)
    if values32.itemsize != 4:  # pragma: no cover - exotic platforms only
        values32 = array("L", packed)
    if sys.byteorder == "big":  # pragma: no cover - big-endian hosts only
        values32.byteswap()
    out = bytearray(npix * channels)
    for c, m in enumerate(used):
        shift, bits = _mask_shift_bits(m)
        if bits == 0:
            out[c::channels] = bytes((_EMPTY[c],)) * npix
            continue
        maxval = (1 << bits) - 1
        out[c::channels] = bytes(
            ((v >> shift) & maxval) * 255 // maxval for v in values32
        )
    return bytes(out)


def decode_rgb(data: bytes, header: BMPHeader, *, alpha: bool = False) -> bytes:
    """Decode to packed 8-bit RGB (or RGBA when ``alpha``), top-down rows."""
    _check_compression(header)
    bpp = header.bits_per_pixel
    if bpp <= 8:
        if not header.palette:
            raise InvalidBMPError("indexed image has no palette")
        rgb = _apply_palette(decode_indices(data, header), header.palette)
        return rgb_to_rgba(rgb) if alpha else rgb
    packed = _packed_rows(data, header)
    if bpp == 24:
        out = bytearray(packed)
        out[0::3] = packed[2::3]
        out[2::3] = packed[0::3]
        return rgb_to_rgba(bytes(out)) if alpha else bytes(out)
    real_alpha = alpha and has_alpha(header)
    result = _decode_bitfields(packed, header, real_alpha)
    if alpha and not real_alpha:
        return rgb_to_rgba(result)
    return result


def rgb_to_rgba(rgb: bytes) -> bytes:
    """Append an opaque alpha channel to packed RGB data."""
    n = len(rgb) // 3
    out = bytearray(b"\xff" * (n * 4))
    out[0::4] = rgb[0::3]
    out[1::4] = rgb[1::3]
    out[2::4] = rgb[2::3]
    return bytes(out)
