"""BMP encoding."""

from __future__ import annotations

import re
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

__all__ = ["HeaderVersion", "Mode", "encode", "encode_embedded", "rle_encode"]

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


#: Runs of three or more equal pixels; everything between them is a literal.
_LONG_RUN = re.compile(rb"(.)\1{2,}", re.S)
_MAX_RUN = 255


def _rle_literal(lit: bytes, four: bool, out: list[bytes]) -> None:
    """Append a literal stretch of pixels as absolute runs (or short runs)."""
    if four:
        _rle4_literal(lit, out)
        return
    for s in range(0, len(lit), _MAX_RUN):
        chunk = lit[s : s + _MAX_RUN]
        if len(chunk) >= 3:
            out.append(bytes((0, len(chunk))) + chunk + bytes(len(chunk) & 1))
        else:
            out.extend(bytes((1, v)) for v in chunk)


def _rle4_literal(lit: bytes, out: list[bytes]) -> None:
    """RLE4 literals use only even-length absolute runs.

    An odd count is valid, but Pillow before 13.0 (and some other decoders)
    drop the last pixel of one, so a trailing odd pixel becomes a 1-pixel run.
    """
    for s in range(0, len(lit), _MAX_RUN - 1):
        chunk = lit[s : s + _MAX_RUN - 1]
        tail = b""
        if len(chunk) & 1:
            chunk, tail = chunk[:-1], chunk[-1:]
        if len(chunk) >= 4:
            data = _pack_pixels(chunk, "P", 4, len(chunk), 1)
            out.append(bytes((0, len(chunk))) + data + bytes(len(data) & 1))
        elif chunk:  # two pixels: one encoded run alternating both nibbles
            out.append(bytes((2, (chunk[0] << 4) | chunk[1])))
        if tail:
            out.append(bytes((1, tail[0] << 4)))


def _rle_run(value: int, n: int, four: bool, out: list[bytes]) -> None:
    byte = (value << 4) | value if four else value
    full, rest = divmod(n, _MAX_RUN)
    if full:
        out.append(bytes((_MAX_RUN, byte)) * full)
    if rest:
        out.append(bytes((rest, byte)))


def rle_encode(indices: bytes, width: int, height: int, bits: int) -> bytes:
    """Encode top-down palette indices as a bottom-up ``BI_RLE8``/``BI_RLE4`` stream.

    Every row ends with an end-of-line escape except the last, which ends with
    end-of-bitmap. Runs of three or more equal pixels become encoded runs;
    everything else becomes word-aligned absolute runs. Delta escapes are not
    emitted.
    """
    if bits not in (4, 8):
        raise UnsupportedFormatError("RLE compression needs 4 or 8 bits per pixel")
    four = bits == 4
    out: list[bytes] = []
    mv = memoryview(indices)
    for y in range(height - 1, -1, -1):
        row = mv[y * width : (y + 1) * width].tobytes()
        pos = 0
        for m in _LONG_RUN.finditer(row):
            start, end = m.span()
            if start > pos:
                _rle_literal(row[pos:start], four, out)
            _rle_run(row[start], end - start, four, out)
            pos = end
        if pos < width:
            _rle_literal(row[pos:], four, out)
        out.append(b"\x00\x00" if y else b"\x00\x01")
    return b"".join(out)


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
    rle: bool = False,
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
        rle: Run-length compress the pixels: ``BI_RLE8`` for 8-bit and
            ``BI_RLE4`` for 4-bit indexed images. Needs mode ``"P"``, a
            non-core header and bottom-up rows.

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

    if rle:
        if mode != "P" or bits not in (4, 8):
            raise UnsupportedFormatError(
                "RLE compression needs mode 'P' with 4 or 8 bits per pixel"
            )
        if header == "core":
            raise UnsupportedFormatError("BITMAPCOREHEADER cannot store RLE data")
        if top_down:
            raise UnsupportedFormatError("RLE-compressed BMPs must be bottom-up")

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
    if rle:
        compression = Compression.BI_RLE8 if bits == 8 else Compression.BI_RLE4
        return _assemble(
            header,
            width,
            height,
            bits,
            compression,
            rle_encode(pixels, width, height, bits),
            pal,
            mode,
            top_down=False,
            pixels_per_meter=pixels_per_meter,
        )
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
    return _assemble(
        header,
        width,
        height,
        bits,
        compression,
        pixel_data,
        pal,
        mode,
        top_down=top_down,
        pixels_per_meter=pixels_per_meter,
    )


def _assemble(
    header: str,
    width: int,
    height: int,
    bits: int,
    compression: int,
    pixel_data: bytes,
    pal: Sequence[tuple[int, int, int]],
    mode: str,
    *,
    top_down: bool,
    pixels_per_meter: int,
) -> bytes:
    """Prepend the file header, DIB header and palette to ``pixel_data``."""
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


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
#: JPEG start-of-frame markers that carry the image size (not DHT/JPG/DAC).
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def embedded_kind(data: bytes) -> str | None:
    """Return ``"png"`` or ``"jpeg"`` from the stream's magic bytes, else ``None``."""
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise BMPError("PNG stream has no IHDR chunk")
    width, height = struct.unpack_from(">II", data, 16)
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int]:
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            raise BMPError(f"corrupt JPEG stream: expected a marker at byte {i}")
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:  # standalone markers
            i += 2
            continue
        (length,) = struct.unpack_from(">H", data, i + 2)
        if marker in _SOF_MARKERS:
            if i + 9 > n:
                break
            height, width = struct.unpack_from(">HH", data, i + 5)
            return width, height
        i += 2 + length
    raise BMPError("JPEG stream has no start-of-frame marker")


def encode_embedded(
    data: bytes | bytearray | memoryview,
    *,
    width: int | None = None,
    height: int | None = None,
    header: HeaderVersion = "v5",
    pixels_per_meter: int = DEFAULT_PPM,
) -> bytes:
    """Wrap a PNG or JPEG stream in a ``BI_PNG`` / ``BI_JPEG`` BMP file.

    The format is detected from the stream's magic bytes. ``width`` and
    ``height`` default to the size recorded in the PNG ``IHDR`` chunk or the
    JPEG start-of-frame marker. Such files are mostly used by printer drivers;
    many viewers (Pillow included) cannot open them.

    Raises:
        BMPError: if ``data`` is not PNG or JPEG, or its size can't be read.
        UnsupportedFormatError: for ``header="core"``.
    """
    stream = bytes(data)
    kind = embedded_kind(stream)
    if kind is None:
        raise BMPError("embedded image must be a PNG or JPEG stream")
    if header not in _HEADER_SIZES:
        raise BMPError(f"unknown header version {header!r}")
    if header == "core":
        raise UnsupportedFormatError("BITMAPCOREHEADER cannot embed PNG or JPEG data")
    if width is None or height is None:
        w, h = _png_size(stream) if kind == "png" else _jpeg_size(stream)
        width = w if width is None else width
        height = h if height is None else height
    if width <= 0 or height <= 0:
        raise BMPError(f"width and height must be positive, got {width}x{height}")
    compression = Compression.BI_PNG if kind == "png" else Compression.BI_JPEG
    return _assemble(
        header,
        width,
        height,
        0,
        compression,
        stream,
        (),
        "RGB",
        top_down=False,
        pixels_per_meter=pixels_per_meter,
    )
