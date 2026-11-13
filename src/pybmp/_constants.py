"""BMP format constants."""

from __future__ import annotations

from enum import IntEnum

__all__ = [
    "CORE_HEADER_SIZE",
    "FILE_HEADER_SIZE",
    "HEADER_NAMES",
    "INFO_HEADER_SIZE",
    "LCS_SRGB",
    "SIGNATURES",
    "V4_HEADER_SIZE",
    "V5_HEADER_SIZE",
    "Compression",
]

FILE_HEADER_SIZE = 14
CORE_HEADER_SIZE = 12
INFO_HEADER_SIZE = 40
V4_HEADER_SIZE = 108
V5_HEADER_SIZE = 124

#: Human readable names for every DIB header size pybmp understands.
HEADER_NAMES: dict[int, str] = {
    12: "BITMAPCOREHEADER",
    16: "OS22XBITMAPHEADER (short)",
    40: "BITMAPINFOHEADER",
    52: "BITMAPV2INFOHEADER",
    56: "BITMAPV3INFOHEADER",
    64: "OS22XBITMAPHEADER",
    108: "BITMAPV4HEADER",
    124: "BITMAPV5HEADER",
}

#: Valid two-byte signatures (``BM`` is the Windows bitmap; the rest are OS/2).
SIGNATURES = frozenset({"BM", "BA", "CI", "CP", "IC", "PT"})

#: ``LCS_sRGB`` colour-space tag stored in V4/V5 headers.
LCS_SRGB = 0x73524742


class Compression(IntEnum):
    """Values of the ``biCompression`` header field."""

    BI_RGB = 0
    BI_RLE8 = 1
    BI_RLE4 = 2
    BI_BITFIELDS = 3
    BI_JPEG = 4
    BI_PNG = 5
    BI_ALPHABITFIELDS = 6
    BI_CMYK = 11
    BI_CMYKRLE8 = 12
    BI_CMYKRLE4 = 13
