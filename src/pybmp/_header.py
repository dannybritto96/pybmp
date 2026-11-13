"""Parsing of the BMP file header, DIB header, colour masks and palette."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ._constants import (
    CORE_HEADER_SIZE,
    FILE_HEADER_SIZE,
    HEADER_NAMES,
    SIGNATURES,
    Compression,
)
from ._errors import HeaderNotSupported, InvalidBMPError, TruncatedFileError

__all__ = ["BMPHeader", "parse_header", "row_stride"]

_FILE_HEADER = struct.Struct("<2sIHHI")
_CORE = struct.Struct("<HHHH")
_OS2_SHORT = struct.Struct("<iiHH")
_INFO = struct.Struct("<iiHHIIiiII")
_MASKS3 = struct.Struct("<III")
_MASKS4 = struct.Struct("<IIII")
_V4_TAIL = struct.Struct("<I36sIII")
_V5_TAIL = struct.Struct("<IIII")

_VALID_BPP = frozenset({1, 2, 4, 8, 16, 24, 32})


def row_stride(bits_per_pixel: int, width: int) -> int:
    """Return the size in bytes of one stored row, including padding to 4 bytes."""
    return ((bits_per_pixel * width + 31) // 32) * 4


@dataclass(frozen=True, slots=True)
class BMPHeader:
    """Every header field of a BMP file, decoded into plain Python values.

    ``height`` keeps its on-disk sign: negative means the rows are stored
    top-down. Fields a header version does not carry are ``0`` (or empty).
    """

    signature: str
    file_size: int
    reserved1: int
    reserved2: int
    pixel_offset: int
    header_size: int
    width: int
    height: int
    planes: int
    bits_per_pixel: int
    compression: int = Compression.BI_RGB
    image_size: int = 0
    x_pixels_per_meter: int = 0
    y_pixels_per_meter: int = 0
    colors_used: int = 0
    colors_important: int = 0
    red_mask: int = 0
    green_mask: int = 0
    blue_mask: int = 0
    alpha_mask: int = 0
    color_space_type: int = 0
    endpoints: bytes = b""
    gamma_red: int = 0
    gamma_green: int = 0
    gamma_blue: int = 0
    intent: int = 0
    profile_data: int = 0
    profile_size: int = 0
    palette: tuple[tuple[int, int, int], ...] = ()

    @property
    def header_name(self) -> str:
        """Name of the DIB header version, e.g. ``"BITMAPINFOHEADER"``."""
        return HEADER_NAMES[self.header_size]

    @property
    def compression_name(self) -> str:
        """Name of the compression method, e.g. ``"BI_RGB"``."""
        try:
            return Compression(self.compression).name
        except ValueError:
            return f"UNKNOWN({self.compression})"

    @property
    def top_down(self) -> bool:
        """``True`` when the first stored row is the top of the image."""
        return self.height < 0

    @property
    def stride(self) -> int:
        """Bytes per stored row, including padding."""
        return row_stride(self.bits_per_pixel, self.width)

    @property
    def is_os2(self) -> bool:
        """``True`` for OS/2 headers, whose compression codes 3 and 4 differ."""
        return self.header_size in (16, 64)


def _need(data: memoryview, end: int, what: str) -> None:
    if len(data) < end:
        raise TruncatedFileError(
            f"file is {len(data)} bytes but the {what} needs {end} bytes"
        )


def parse_header(data: bytes | bytearray | memoryview) -> BMPHeader:
    """Parse every header structure of a BMP held in ``data``.

    Raises:
        TruncatedFileError: if ``data`` ends inside a header or the palette.
        InvalidBMPError: if the signature or a field value is invalid.
        HeaderNotSupported: if the DIB header size is unknown.
    """
    mv = memoryview(data)
    _need(mv, FILE_HEADER_SIZE + 4, "file header")
    raw_sig, file_size, res1, res2, offset = _FILE_HEADER.unpack_from(mv, 0)
    signature = raw_sig.decode("latin-1")
    if signature not in SIGNATURES:
        raise InvalidBMPError(f"not a BMP file: bad signature {raw_sig!r}")
    (header_size,) = struct.unpack_from("<I", mv, FILE_HEADER_SIZE)
    if header_size not in HEADER_NAMES:
        raise HeaderNotSupported(f"DIB header size {header_size} not supported")
    _need(mv, FILE_HEADER_SIZE + header_size, HEADER_NAMES[header_size])
    base = FILE_HEADER_SIZE + 4
    comp = size = xres = yres = used = important = 0
    red = green = blue = alpha = 0
    cstype = gamma_r = gamma_g = gamma_b = intent = pdata = psize = 0
    endpoints = b""

    if header_size == CORE_HEADER_SIZE:
        width, height, planes, bpp = _CORE.unpack_from(mv, base)
    elif header_size == 16:
        width, height, planes, bpp = _OS2_SHORT.unpack_from(mv, base)
    else:
        (width, height, planes, bpp, comp, size, xres, yres, used, important) = (
            _INFO.unpack_from(mv, base)
        )

    after_header = FILE_HEADER_SIZE + header_size
    is_os2 = header_size in (16, 64)

    # Colour masks: inside V2+ headers, or straight after a 40-byte header.
    if header_size >= 52 and not is_os2:
        red, green, blue = _MASKS3.unpack_from(mv, FILE_HEADER_SIZE + 40)
        if header_size >= 56:
            (alpha,) = struct.unpack_from("<I", mv, FILE_HEADER_SIZE + 52)
    elif header_size == 40 and comp == Compression.BI_BITFIELDS:
        _need(mv, after_header + 12, "colour masks")
        red, green, blue = _MASKS3.unpack_from(mv, after_header)
        after_header += 12
    elif header_size == 40 and comp == Compression.BI_ALPHABITFIELDS:
        _need(mv, after_header + 16, "colour masks")
        red, green, blue, alpha = _MASKS4.unpack_from(mv, after_header)
        after_header += 16

    if header_size >= 108:
        cstype, raw_endpoints, gamma_r, gamma_g, gamma_b = _V4_TAIL.unpack_from(
            mv, FILE_HEADER_SIZE + 56
        )
        endpoints = bytes(raw_endpoints)
    if header_size >= 124:
        intent, pdata, psize, _reserved = _V5_TAIL.unpack_from(
            mv, FILE_HEADER_SIZE + 108
        )

    if bpp not in _VALID_BPP:
        raise InvalidBMPError(f"invalid bits per pixel: {bpp}")
    if width <= 0:
        raise InvalidBMPError(f"invalid width: {width}")
    if height == 0:
        raise InvalidBMPError("invalid height: 0")
    if offset < after_header:
        raise InvalidBMPError(
            f"pixel data offset {offset} points inside the headers (< {after_header})"
        )

    # Palette: 3-byte RGBTRIPLEs for the core header, 4-byte RGBQUADs otherwise.
    palette: tuple[tuple[int, int, int], ...] = ()
    count = used or (1 << bpp if bpp <= 8 else 0)
    if count:
        entry = 3 if header_size == CORE_HEADER_SIZE else 4
        available = (min(offset, len(mv)) - after_header) // entry
        if bpp <= 8 and available <= 0:
            raise TruncatedFileError("palette is missing")
        count = max(0, min(count, available, 1 << 16))
        raw = bytes(mv[after_header : after_header + count * entry])
        palette = tuple(zip(raw[2::entry], raw[1::entry], raw[0::entry], strict=True))

    return BMPHeader(
        signature=signature,
        file_size=file_size,
        reserved1=res1,
        reserved2=res2,
        pixel_offset=offset,
        header_size=header_size,
        width=width,
        height=height,
        planes=planes,
        bits_per_pixel=bpp,
        compression=comp,
        image_size=size,
        x_pixels_per_meter=xres,
        y_pixels_per_meter=yres,
        colors_used=used,
        colors_important=important,
        red_mask=red,
        green_mask=green,
        blue_mask=blue,
        alpha_mask=alpha,
        color_space_type=cstype,
        endpoints=endpoints,
        gamma_red=gamma_r,
        gamma_green=gamma_g,
        gamma_blue=gamma_b,
        intent=intent,
        profile_data=pdata,
        profile_size=psize,
        palette=palette,
    )
