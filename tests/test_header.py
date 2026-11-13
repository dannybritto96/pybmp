"""Unit tests for pybmp._header."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from helpers import build_bmp
from pybmp import (
    BMPHeader,
    Compression,
    HeaderNotSupported,
    InvalidBMPError,
    TruncatedFileError,
    parse_header,
)
from pybmp._header import row_stride


@pytest.mark.parametrize(
    ("bpp", "width", "expected"),
    [
        (1, 1, 4),
        (1, 33, 8),
        (4, 9, 8),
        (8, 5, 8),
        (16, 3, 8),
        (24, 1, 4),
        (24, 5, 16),
        (32, 3, 12),
        (2, 17, 8),
    ],
)
def test_row_stride(bpp: int, width: int, expected: int) -> None:
    assert row_stride(bpp, width) == expected


@pytest.mark.parametrize("header_size", [12, 16, 40, 52, 56, 64, 108, 124])
def test_every_header_version(header_size: int) -> None:
    data = build_bmp(
        header_size=header_size, width=3, height=2, bpp=24, pixel_data=bytes(24)
    )
    h = parse_header(data)
    assert isinstance(h, BMPHeader)
    assert (h.header_size, h.width, h.height, h.bits_per_pixel) == (
        header_size,
        3,
        2,
        24,
    )
    assert h.pixel_offset == 14 + header_size
    assert h.header_name
    assert h.compression_name == "BI_RGB"
    assert not h.top_down
    assert h.is_os2 == (header_size in (16, 64))


def test_v4_fields() -> None:
    data = build_bmp(
        header_size=108,
        width=1,
        height=1,
        bpp=32,
        compression=3,
        masks=(0xFF0000, 0xFF00, 0xFF, 0xFF000000),
        pixel_data=bytes(4),
    )
    h = parse_header(data)
    assert (h.red_mask, h.green_mask, h.blue_mask, h.alpha_mask) == (
        0xFF0000,
        0xFF00,
        0xFF,
        0xFF000000,
    )
    assert h.color_space_type == 0x73524742
    assert len(h.endpoints) == 36


def test_v5_fields() -> None:
    data = bytearray(
        build_bmp(header_size=124, width=1, height=1, bpp=24, pixel_data=bytes(4))
    )
    struct.pack_into("<III", data, 14 + 108, 4, 99, 7)
    h = parse_header(bytes(data))
    assert (h.intent, h.profile_data, h.profile_size) == (4, 99, 7)


def test_top_down_and_signed_height() -> None:
    h = parse_header(build_bmp(width=2, height=-3, bpp=24, pixel_data=bytes(24)))
    assert h.height == -3
    assert h.top_down


def test_masks_after_info_header() -> None:
    data = build_bmp(
        width=1,
        height=1,
        bpp=16,
        compression=3,
        masks=(0xF800, 0x07E0, 0x001F),
        pixel_data=bytes(4),
    )
    h = parse_header(data)
    assert (h.red_mask, h.green_mask, h.blue_mask, h.alpha_mask) == (
        0xF800,
        0x7E0,
        0x1F,
        0,
    )
    assert h.pixel_offset == 14 + 40 + 12


def test_alphabitfields_after_info_header() -> None:
    data = build_bmp(
        width=1,
        height=1,
        bpp=32,
        compression=6,
        masks=(0xFF0000, 0xFF00, 0xFF, 0xFF000000),
        pixel_data=bytes(4),
    )
    h = parse_header(data)
    assert h.alpha_mask == 0xFF000000
    assert h.compression == Compression.BI_ALPHABITFIELDS


def test_palette_core_and_info() -> None:
    pal = [(1, 2, 3), (4, 5, 6)]
    for hs in (12, 40):
        h = parse_header(
            build_bmp(
                header_size=hs,
                width=1,
                height=1,
                bpp=1,
                palette=pal,
                pixel_data=bytes(4),
            )
        )
        assert h.palette == tuple(pal)


def test_palette_defaults_to_two_pow_bpp_and_is_clamped() -> None:
    pal = [(i, i, i) for i in range(4)]
    h = parse_header(
        build_bmp(
            width=1, height=1, bpp=4, palette=pal, colors_used=0, pixel_data=bytes(4)
        )
    )
    assert len(h.palette) == 4  # only 4 entries fit before the pixel offset


def test_unknown_compression_name() -> None:
    h = parse_header(
        build_bmp(width=1, height=1, bpp=24, compression=99, pixel_data=bytes(4))
    )
    assert h.compression_name == "UNKNOWN(99)"


@pytest.mark.parametrize("cut", [0, 5, 14, 17, 30, 53])
def test_truncated_headers(cut: int) -> None:
    data = build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4))
    with pytest.raises(TruncatedFileError):
        parse_header(data[:cut])


def test_truncated_masks() -> None:
    data = build_bmp(
        width=1, height=1, bpp=16, compression=3, masks=(1, 2, 4), pixel_data=b""
    )
    with pytest.raises(TruncatedFileError):
        parse_header(data[: 14 + 40 + 6])
    data = build_bmp(
        width=1, height=1, bpp=32, compression=6, masks=(1, 2, 4, 8), pixel_data=b""
    )
    with pytest.raises(TruncatedFileError):
        parse_header(data[: 14 + 40 + 14])


def test_bad_signature() -> None:
    with pytest.raises(InvalidBMPError, match="signature"):
        parse_header(
            build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4), signature=b"XX")
        )


def test_os2_signature_accepted() -> None:
    h = parse_header(
        build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4), signature=b"BA")
    )
    assert h.signature == "BA"


def test_unknown_header_size() -> None:
    data = bytearray(build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4)))
    struct.pack_into("<I", data, 14, 77)
    with pytest.raises(HeaderNotSupported):
        parse_header(bytes(data))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"width": 1, "height": 1, "bpp": 3}, "bits per pixel"),
        ({"width": 0, "height": 1, "bpp": 24}, "width"),
        ({"width": -4, "height": 1, "bpp": 24}, "width"),
        ({"width": 1, "height": 0, "bpp": 24}, "height"),
    ],
)
def test_invalid_fields(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(InvalidBMPError, match=match):
        parse_header(build_bmp(pixel_data=bytes(4), **kwargs))


def test_offset_inside_headers() -> None:
    with pytest.raises(InvalidBMPError, match="offset"):
        parse_header(
            build_bmp(width=1, height=1, bpp=24, pixel_data=bytes(4), offset_adjust=-10)
        )


def test_missing_palette() -> None:
    data = build_bmp(width=1, height=1, bpp=8, pixel_data=bytes(4))
    with pytest.raises(TruncatedFileError, match="palette"):
        parse_header(data)
